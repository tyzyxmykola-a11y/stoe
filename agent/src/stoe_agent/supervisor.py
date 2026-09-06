from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .field_journal import RebuildJournal, SESSION_ID
from .investigation import investigate_selector
from .ollama import OllamaClient
from .selector_loader import load_selector, sha256_file
from .static_gate import validate_candidate_source


PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "hypothesis": {"type": "string"},
        "observed_evidence": {"type": "array", "items": {"type": "string"}},
        "diagnostic_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "case": {"type": "string"},
                    "observed_selection": {"type": "array", "items": {"type": "string"}},
                    "missed_required": {"type": "array", "items": {"type": "string"}},
                    "source_mechanism": {"type": "string"},
                    "relation_to_hypothesis": {"type": "string"},
                },
                "required": [
                    "case",
                    "observed_selection",
                    "missed_required",
                    "source_mechanism",
                    "relation_to_hypothesis",
                ],
                "additionalProperties": False,
            },
        },
        "source_diagnosis": {"type": "string"},
        "proposed_change": {"type": "string"},
        "expected_benefit": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "hypothesis",
        "observed_evidence",
        "diagnostic_findings",
        "source_diagnosis",
        "proposed_change",
        "expected_benefit",
        "risks",
    ],
    "additionalProperties": False,
}

SOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {"type": "string"},
        "implementation_note": {"type": "string"},
    },
    "required": ["source", "implementation_note"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class SupervisorConfig:
    repo_root: Path
    runtime_dir: Path
    component_dir: Path
    protected_eval_dir: Path
    report_dir: Path
    accepted_version_dir: Path | None = None
    rejected_candidate_dir: Path | None = None
    model: str = "qwen3-coder:latest"
    ollama_endpoint: str = "http://127.0.0.1:11434"
    evaluation_timeout_seconds: int = 25
    activation_timeout_seconds: int = 20

    @classmethod
    def defaults(
        cls,
        *,
        repo_root: Path,
        model: str = "qwen3-coder:latest",
        runtime_dir: Path | None = None,
    ) -> "SupervisorConfig":
        agent_root = repo_root / "agent"
        return cls(
            repo_root=repo_root.resolve(),
            runtime_dir=(runtime_dir or agent_root / "runtime").resolve(),
            component_dir=(agent_root / "owned_components" / "context_selector").resolve(),
            protected_eval_dir=(agent_root / "protected_evals").resolve(),
            report_dir=(agent_root / "rebuild_reports").resolve(),
            accepted_version_dir=None,
            rejected_candidate_dir=(agent_root / "rejected_candidates").resolve(),
            model=model,
        )


class RebuildSupervisor:
    def __init__(self, config: SupervisorConfig, *, model_client: Any | None = None) -> None:
        self.config = config
        self.config.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.config.report_dir.mkdir(parents=True, exist_ok=True)
        self.journal = RebuildJournal(repo_root=config.repo_root, runtime_dir=config.runtime_dir)
        self.model_client = model_client or OllamaClient(
            endpoint=config.ollama_endpoint,
            model=config.model,
        )
        self.active_pointer = self.config.runtime_dir / "active_component.json"
        self._ensure_active_pointer()

    @property
    def baseline_path(self) -> Path:
        return self.config.component_dir / "versions" / "v1.py"

    def _ensure_active_pointer(self) -> dict[str, Any]:
        if self.active_pointer.exists():
            return self.read_active_pointer()
        pointer = {
            "version": "v1",
            "source_path": str(self.baseline_path.resolve()),
            "sha256": sha256_file(self.baseline_path),
            "activated_at": datetime.now(timezone.utc).isoformat(),
            "previous_version": None,
        }
        self._atomic_write_json(self.active_pointer, pointer)
        return pointer

    def read_active_pointer(self) -> dict[str, Any]:
        pointer = json.loads(self.active_pointer.read_text(encoding="utf-8"))
        if sha256_file(pointer["source_path"]) != pointer["sha256"]:
            raise RuntimeError("active pointer source hash mismatch")
        return pointer

    def protected_hashes(self) -> dict[str, str]:
        return {
            name: sha256_file(self.config.protected_eval_dir / name)
            for name in ("evaluator.py", "cases.json")
        }

    def inspect(self) -> dict[str, Any]:
        pointer = self.read_active_pointer()
        component_map = json.loads(
            (self.config.component_dir / "component.json").read_text(encoding="utf-8")
        )
        return {
            "active": pointer,
            "component": component_map,
            "protected_hashes": self.protected_hashes(),
            "persistent_field": self.journal.status(),
            "scope": {
                "agent_owned": [component_map["editable_scope"]],
                "trusted_supervisor": [
                    "agent/src/stoe_agent/supervisor.py",
                    "agent/src/stoe_agent/static_gate.py",
                    "agent/protected_evals",
                ],
                "external_dependencies": ["Python runtime", "local Ollama service"],
                "underlying_model": "External model weights are selected but not modified by this cycle.",
            },
        }

    def run_cycle(self) -> dict[str, Any]:
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        cycle_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
        try:
            return self._run_cycle(cycle_id=cycle_id, started=started, started_at=started_at)
        except Exception as exc:
            failure = self.journal.add_ip(
                cycle_id=cycle_id,
                label="cycle_execution_failure",
                content=f"Rebuild cycle stopped safely after {type(exc).__name__}: {exc}",
                kind="result",
                origin="failure_history",
                outcome="failed",
                failure_condition="The rebuild infrastructure or configured local provider raised an exception.",
                metadata={"exception_type": type(exc).__name__, "exception": str(exc)},
            )
            report = {
                "cycle_id": cycle_id,
                "started_at": started_at,
                "decision": "ERROR_REJECT",
                "decision_reason": f"{type(exc).__name__}: {exc}",
                "activated": False,
                "active_after": self.read_active_pointer(),
                "protected_hashes": self.protected_hashes(),
                "failure_field_ref": failure["ref"],
                "traceback": traceback.format_exc(),
            }
            return self._finish_report(report, cycle_id, started)

    def _run_cycle(
        self,
        *,
        cycle_id: str,
        started: float,
        started_at: str,
    ) -> dict[str, Any]:
        pointer_before = self.read_active_pointer()
        active_path = Path(pointer_before["source_path"])
        active_source = active_path.read_text(encoding="utf-8")
        protected_before = self.protected_hashes()
        identity = self.model_client.identity()

        author_definition = self.journal.add_ip(
            cycle_id=cycle_id,
            label="author_definition",
            content=(
                "Author definition: self-rebuilding means inspecting the working implementation, proposing and "
                "building an isolated code successor, evaluating it, then activating or rejecting it with continuity and rollback."
            ),
            kind="definition",
            outcome="active",
            metadata={"provenance_type": "author_definition", "author": "Mykola Voronin"},
        )
        architecture = self.journal.add_ip(
            cycle_id=cycle_id,
            label="active_architecture",
            content=(
                "Active architecture: protected rebuild supervisor + SToE persistent field + local Ollama generator + "
                "versioned research-context selector + protected subprocess evaluation and activation health check."
            ),
            kind="architecture",
            outcome="active",
            metadata={"source_hash": pointer_before["sha256"], "provenance_type": "observed_implementation"},
        )
        component = self.journal.add_ip(
            cycle_id=cycle_id,
            label="active_component",
            content=(
                f"Active research-context selector {pointer_before['version']} at {active_path}; "
                "selects bounded prior IP refs for an observer state."
            ),
            kind="component",
            outcome="active",
            metadata={
                "version": pointer_before["version"],
                "source_path": str(active_path),
                "source_hash": pointer_before["sha256"],
                "provenance_type": "observed_implementation",
            },
        )
        self.journal.relate(architecture["ref"], component["ref"], "contains_component", "Architecture contains active selector")
        self.journal.relate(architecture["ref"], author_definition["ref"], "constrained_by", "Architecture implements author control definition")
        self.journal.relate(
            architecture["ref"],
            "SEED_8901dee66818444c",
            "applies_core",
            "Operational mapping to the canonical Persistent Reasoning Graph IP; not evidence for broader ontology claims",
        )
        self.journal.relate(
            architecture["ref"],
            "SEED_f56596242b9c4438",
            "applies_core",
            "The implementation reifies its own modules and revisions as inspectable IPs",
        )
        self.journal.relate(
            component["ref"],
            "SEED_3300f93f95154bdf",
            "instantiates",
            "The selector operationally maps observer state and candidate IPs to a bounded selected set",
        )

        selector = load_selector(active_path)
        investigation = investigate_selector(
            selector=selector,
            journal=self.journal,
            cycle_id=cycle_id,
            component_ref=component["ref"],
        )
        investigation_ip = self.journal.add_ip(
            cycle_id=cycle_id,
            label="investigation_summary",
            content=(
                f"Observed investigation: active selector passed {investigation['pass_count']}/"
                f"{investigation['case_count']} public diagnostic cases."
            ),
            kind="observation",
            origin="evaluation",
            outcome=(
                "supported" if investigation["pass_count"] == investigation["case_count"] else "failed"
            ),
            failure_condition=(
                "One or more public diagnostic selection contracts were violated."
                if investigation["pass_count"] < investigation["case_count"]
                else ""
            ),
            metadata={
                "provenance_type": "observed_behavior",
                "diagnostic_pass_count": investigation["pass_count"],
                "diagnostic_case_count": investigation["case_count"],
                "synthesis_navigation_run_id": investigation["synthesis_navigation_run_id"],
            },
        )
        self.journal.relate(investigation_ip["ref"], component["ref"], "evaluates", "Public behavioral investigation of active selector")

        proposal_prompt = self._proposal_prompt(active_source, investigation)
        proposal, proposal_trace = self.model_client.generate_json(
            system=(
                "You are the bounded research component of an SToE-guided self-developing agent. "
                "Infer only from supplied source, observed behavior, and bounded field retrieval. "
                "Treat changes as falsifiable engineering hypotheses, not proof of SToE."
            ),
            prompt=proposal_prompt,
            schema=PROPOSAL_SCHEMA,
            max_output_tokens=1400,
            seed=1701,
        )
        self._validate_proposal(proposal, investigation)
        proposal_ip = self.journal.add_ip(
            cycle_id=cycle_id,
            label="candidate_hypothesis",
            content=str(proposal["hypothesis"]),
            kind="hypothesis",
            outcome="untested",
            metadata={
                "provenance_type": "ai_generated_hypothesis",
                "model": asdict(identity),
                "proposal": proposal,
                "synthesis_navigation_run_id": investigation["synthesis_navigation_run_id"],
            },
        )
        self.journal.relate(proposal_ip["ref"], investigation_ip["ref"], "derived_from", "Hypothesis formulated after SToE investigation")
        self.journal.relate(proposal_ip["ref"], component["ref"], "proposes_successor_to", "Hypothesis targets active component")

        generation_prompt = self._generation_prompt(active_source, investigation, proposal)
        attempts: list[dict[str, Any]] = []
        accepted_source: str | None = None
        accepted_note = ""
        repair_errors: list[str] = []
        for attempt_index in range(2):
            prompt = generation_prompt
            if repair_errors:
                prompt += (
                    "\n\nThe first source failed only the static safety/interface gate. Repair these errors "
                    "without changing the hypothesis and without seeing evaluation outcomes:\n- "
                    + "\n- ".join(repair_errors)
                )
            generated, trace = self.model_client.generate_json(
                system=(
                    "Generate one deterministic, side-effect-free Python component. Return JSON only. "
                    "Do not access files, network, processes, environment, or protected evaluation."
                ),
                prompt=prompt,
                schema=SOURCE_SCHEMA,
                max_output_tokens=3200,
                seed=2701 + attempt_index,
            )
            source = self._clean_source(str(generated.get("source", "")))
            gate = validate_candidate_source(source)
            attempt_path = self.config.runtime_dir / f"candidate_{cycle_id}_attempt_{attempt_index + 1}.py"
            attempt_path.write_text(source, encoding="utf-8", newline="\n")
            attempt = {
                "attempt": attempt_index + 1,
                "source_path": str(attempt_path),
                "source_sha256": sha256_file(attempt_path),
                "implementation_note": generated.get("implementation_note", ""),
                "static_gate_passed": gate.passed,
                "static_gate_errors": list(gate.errors),
                "model_trace": trace,
            }
            attempts.append(attempt)
            if gate.passed:
                accepted_source = source
                accepted_note = str(generated.get("implementation_note", ""))
                break
            repair_errors = list(gate.errors)
            failed_attempt_ip = self.journal.add_ip(
                cycle_id=cycle_id,
                label=f"static_gate_failure_{attempt_index + 1}",
                content=f"Generated source failed static gate: {list(gate.errors)}",
                kind="implementation",
                origin="failure_history",
                outcome="rejected",
                failure_condition="Protected static safety/interface gate rejected the generated source.",
                metadata={"source_sha256": attempt["source_sha256"], "attempt": attempt_index + 1},
            )
            self.journal.relate(failed_attempt_ip["ref"], proposal_ip["ref"], "implements", "Rejected generation attempt")

        if self.protected_hashes() != protected_before:
            raise RuntimeError("protected evaluation files changed during generation")

        report: dict[str, Any] = {
            "cycle_id": cycle_id,
            "started_at": started_at,
            "infrastructure": self.inspect()["scope"],
            "active_before": pointer_before,
            "model": asdict(identity),
            "protected_hashes": protected_before,
            "investigation": investigation,
            "proposal": proposal,
            "proposal_trace": proposal_trace,
            "generation_attempts": attempts,
            "acceptance_rule": (
                "candidate pass_count > active pass_count; every active-passing case remains passing; "
                "no critical failure; protected hashes unchanged; activation health check succeeds"
            ),
        }

        if accepted_source is None:
            archived_attempts = [self._archive_rejected(Path(item["source_path"]), cycle_id, suffix=f"attempt_{item['attempt']}") for item in attempts]
            report.update(
                {
                    "decision": "REJECT",
                    "decision_reason": "No generated source passed the protected static gate.",
                    "activated": False,
                    "archived_rejected_candidates": archived_attempts,
                }
            )
            return self._finish_report(report, cycle_id, started)

        candidate_runtime_path = Path(attempts[-1]["source_path"])
        candidate_ip = self.journal.add_ip(
            cycle_id=cycle_id,
            label="candidate_implementation",
            content=f"Generated selector candidate {sha256_file(candidate_runtime_path)}: {accepted_note}",
            kind="implementation",
            outcome="untested",
            metadata={
                "provenance_type": "ai_generated_source",
                "source_sha256": sha256_file(candidate_runtime_path),
                "runtime_path": str(candidate_runtime_path),
            },
        )
        self.journal.relate(candidate_ip["ref"], proposal_ip["ref"], "implements", "Candidate implements preregistered hypothesis")

        baseline_eval = self._evaluate(active_path)
        candidate_eval = self._evaluate(candidate_runtime_path)
        protected_after = self.protected_hashes()
        if protected_after != protected_before:
            raise RuntimeError("protected evaluation files changed during evaluation")
        acceptance = self._acceptance_decision(baseline_eval, candidate_eval)
        evaluation = self.journal.record_evaluation(
            candidate_ref=candidate_ip["ref"],
            content=(
                f"Protected matched evaluation: active {baseline_eval['pass_count']}/{baseline_eval['case_count']}; "
                f"candidate {candidate_eval['pass_count']}/{candidate_eval['case_count']}; "
                f"decision {acceptance['decision']}."
            ),
            outcome="supported" if acceptance["decision"] == "ACCEPT" else "rejected",
            metadata={
                "baseline": baseline_eval,
                "candidate": candidate_eval,
                "acceptance": acceptance,
                "protected_hashes": protected_after,
            },
        )
        report.update(
            {
                "candidate": {
                    "runtime_path": str(candidate_runtime_path),
                    "sha256": sha256_file(candidate_runtime_path),
                    "implementation_note": accepted_note,
                    "field_ref": candidate_ip["ref"],
                },
                "evaluation": {"active": baseline_eval, "candidate": candidate_eval},
                "acceptance": acceptance,
                "evaluation_field_ref": evaluation["evaluation"]["ref"],
            }
        )
        if acceptance["decision"] != "ACCEPT":
            archived = self._archive_rejected(candidate_runtime_path, cycle_id)
            report.update(
                {
                    "decision": "REJECT",
                    "decision_reason": acceptance["reason"],
                    "activated": False,
                    "archived_rejected_candidate": archived,
                }
            )
            return self._finish_report(report, cycle_id, started)

        version_name = f"generated_{cycle_id}"
        version_dir = self.config.accepted_version_dir or (self.config.component_dir / "versions")
        version_dir.mkdir(parents=True, exist_ok=True)
        version_path = version_dir / f"{version_name}.py"
        shutil.copy2(candidate_runtime_path, version_path)
        activation = self._activate(
            version=version_name,
            source_path=version_path,
            cycle_id=cycle_id,
            candidate_ref=candidate_ip["ref"],
        )
        if activation["activated"]:
            report.update(
                {
                    "decision": "ACCEPT",
                    "decision_reason": acceptance["reason"],
                    "activated": True,
                    "activation": activation,
                    "active_after": self.read_active_pointer(),
                }
            )
        else:
            report.update(
                {
                    "decision": "REJECT_AFTER_ACTIVATION_FAILURE",
                    "decision_reason": activation["error"],
                    "activated": False,
                    "activation": activation,
                    "active_after": self.read_active_pointer(),
                }
            )
        return self._finish_report(report, cycle_id, started)

    def _proposal_prompt(self, source: str, investigation: dict[str, Any]) -> str:
        evidence = {
            "diagnostics": self._compact_diagnostics(investigation),
            "bounded_prior_context": investigation["bounded_prior_context"],
            "known_structure": investigation["known_structure"],
            "unknown_structure": investigation["unknown_structure"],
        }
        return (
            "Inspect the active selector and the agent's completed SToE investigation below. Formulate one bounded "
            "implementation hypothesis. diagnostic_findings MUST contain one entry for every failed public diagnostic, "
            "with its exact observed selections and missed required refs. Each source_mechanism must name a field or "
            "operation visible in ACTIVE SOURCE. Reject abstract ontology language that is not tied to an observed "
            "selection decision. Do not assume observer-aware scoring is better merely because it is SToE-derived. "
            "Do not request evaluator changes; the supervisor's acceptance and rollback rules are fixed.\n\n"
            "ACTIVE SOURCE:\n" + source + "\n\nINVESTIGATION:\n" + json.dumps(evidence, indent=2, ensure_ascii=False)
        )

    def _generation_prompt(
        self,
        source: str,
        investigation: dict[str, Any],
        proposal: dict[str, Any],
    ) -> str:
        public_contract = {
            "signature": "select_context(observer_state, items, max_items, max_chars) -> list[str]",
            "item_fields": [
                "ref",
                "content",
                "origin",
                "kind",
                "outcome",
                "failure_condition",
                "created_order",
            ],
            "observer_fields": [
                "goal",
                "active_constraints",
                "changed_constraints",
                "evidence",
                "open_questions",
            ],
            "invariants": [
                "deterministic",
                "return only unique available refs",
                "respect max_items and sum of selected content lengths <= max_chars",
                "side-effect free",
                "stdlib imports limited to re, math, collections, typing",
                "do not reward every failure; relate failure conditions to active or changed constraints",
                "do not assume origin alone proves relevance",
            ],
        }
        return (
            "Implement the preregistered proposal as a complete Python source file. Generalize from the investigation; "
            "do not encode diagnostic ref names or case-specific phrases. The protected acceptance cases are unavailable.\n\n"
            f"PUBLIC CONTRACT:\n{json.dumps(public_contract, indent=2)}\n\n"
            f"PROPOSAL:\n{json.dumps(proposal, indent=2, ensure_ascii=False)}\n\n"
            f"OBSERVED DIAGNOSTIC SUMMARY:\n{json.dumps(self._compact_diagnostics(investigation), indent=2, ensure_ascii=False)}\n\n"
            f"ACTIVE SOURCE:\n{source}"
        )

    @staticmethod
    def _validate_proposal(proposal: dict[str, Any], investigation: dict[str, Any]) -> None:
        required = set(PROPOSAL_SCHEMA["required"])
        if set(proposal) != required:
            raise RuntimeError(f"proposal schema mismatch: expected {sorted(required)}, got {sorted(proposal)}")
        for key in required - {"observed_evidence", "risks", "diagnostic_findings"}:
            if not isinstance(proposal[key], str) or not proposal[key].strip():
                raise RuntimeError(f"proposal field is empty: {key}")
        for key in ("observed_evidence", "risks"):
            if not isinstance(proposal[key], list) or not proposal[key] or not all(
                isinstance(item, str) and item.strip() for item in proposal[key]
            ):
                raise RuntimeError(f"proposal list field is empty or invalid: {key}")
        if not isinstance(proposal["diagnostic_findings"], list) or not proposal["diagnostic_findings"] or not all(
            isinstance(item, dict) for item in proposal["diagnostic_findings"]
        ):
            raise RuntimeError("proposal diagnostic_findings field is empty or invalid")
        failed = {item["case"]: item for item in investigation["diagnostics"] if not item["selector_passed"]}
        findings = {item.get("case"): item for item in proposal["diagnostic_findings"] if isinstance(item, dict)}
        missing_cases = sorted(set(failed) - set(findings))
        if missing_cases:
            raise RuntimeError(f"proposal omits failed diagnostic cases: {missing_cases}")
        source_terms = {
            "goal",
            "query",
            "active_constraints",
            "changed_constraints",
            "evidence",
            "open_questions",
            "failure_condition",
            "outcome",
            "origin",
            "created_order",
            "overlap",
        }
        for case_name, observed in failed.items():
            finding = findings[case_name]
            if list(finding.get("observed_selection", [])) != list(observed["selector_selected"]):
                raise RuntimeError(f"proposal misstates observed selection for {case_name}")
            if list(finding.get("missed_required", [])) != list(observed["missed_refs"]):
                raise RuntimeError(f"proposal misstates missed refs for {case_name}")
            mechanism = str(finding.get("source_mechanism", "")).lower()
            if not any(term in mechanism for term in source_terms):
                raise RuntimeError(f"proposal source mechanism is not tied to active code fields for {case_name}")

    @staticmethod
    def _compact_diagnostics(investigation: dict[str, Any]) -> list[dict[str, Any]]:
        compact = []
        for item in investigation["diagnostics"]:
            relevant_trace = [
                {
                    "external_ref": trace["external_ref"],
                    "selected": trace["selected"],
                    "edge_types": trace["edge_types"],
                    "edge_directions": trace["edge_directions"],
                    "scores": trace["scores"],
                }
                for trace in item["navigator_candidate_trace"]
                if trace["external_ref"] in set(item["required_refs"] + item["selector_selected"])
            ]
            compact.append(
                {
                    "case": item["case"],
                    "observer": item["observer"],
                    "available_refs": item["available_refs"],
                    "required_refs": item["required_refs"],
                    "forbidden_refs": item["forbidden_refs"],
                    "selector_selected": item["selector_selected"],
                    "selector_passed": item["selector_passed"],
                    "missed_refs": item["missed_refs"],
                    "navigator_selected_available_refs": item["navigator_selected_available_refs"],
                    "navigator_relevant_trace": relevant_trace,
                }
            )
        return compact

    def _archive_rejected(self, source_path: Path, cycle_id: str, *, suffix: str = "candidate") -> str:
        archive_dir = self.config.rejected_candidate_dir
        if archive_dir is None:
            return str(source_path)
        archive_dir.mkdir(parents=True, exist_ok=True)
        destination = archive_dir / f"{cycle_id}_{suffix}.py"
        shutil.copy2(source_path, destination)
        return str(destination)

    @staticmethod
    def _clean_source(source: str) -> str:
        cleaned = source.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines.pop()
            cleaned = "\n".join(lines)
        return cleaned.rstrip() + "\n"

    def _evaluate(self, source_path: Path) -> dict[str, Any]:
        command = [
            sys.executable,
            str(self.config.protected_eval_dir / "evaluator.py"),
            "--source",
            str(source_path),
            "--cases",
            str(self.config.protected_eval_dir / "cases.json"),
        ]
        completed = subprocess.run(
            command,
            cwd=self.config.protected_eval_dir,
            capture_output=True,
            text=True,
            timeout=self.config.evaluation_timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"protected evaluator failed with code {completed.returncode}: {completed.stdout} {completed.stderr}"
            )
        return json.loads(completed.stdout)

    @staticmethod
    def _acceptance_decision(active: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        active_passes = set(active.get("passed_cases", []))
        candidate_passes = set(candidate.get("passed_cases", []))
        regressions = sorted(active_passes - candidate_passes)
        critical = list(candidate.get("critical_failures", []))
        improved = int(candidate.get("pass_count", 0)) > int(active.get("pass_count", 0))
        accepted = improved and not regressions and not critical
        reasons = []
        if not improved:
            reasons.append("candidate did not strictly improve protected pass count")
        if regressions:
            reasons.append(f"candidate regressed active-passing cases: {regressions}")
        if critical:
            reasons.append(f"candidate failed critical cases: {critical}")
        if accepted:
            reasons.append("strict improvement with no regression or critical failure")
        return {
            "decision": "ACCEPT" if accepted else "REJECT",
            "reason": "; ".join(reasons),
            "active_pass_count": active.get("pass_count"),
            "candidate_pass_count": candidate.get("pass_count"),
            "regressions": regressions,
            "critical_failures": critical,
        }

    def _activate(
        self,
        *,
        version: str,
        source_path: Path,
        cycle_id: str,
        candidate_ref: str,
    ) -> dict[str, Any]:
        old_pointer = self.read_active_pointer()
        snapshot = self.journal.snapshot(cycle_id=cycle_id)
        new_pointer = {
            "version": version,
            "source_path": str(source_path.resolve()),
            "sha256": sha256_file(source_path),
            "activated_at": datetime.now(timezone.utc).isoformat(),
            "previous_version": old_pointer["version"],
        }
        self._atomic_write_json(self.active_pointer, new_pointer)
        health = self._fresh_process_health()
        if not health["healthy"]:
            self._atomic_write_json(self.active_pointer, old_pointer)
            rollback_health = self._fresh_process_health()
            failure_ip = self.journal.add_ip(
                cycle_id=cycle_id,
                label="activation_failure",
                content=f"Activation of {version} failed and pointer rolled back: {health['error']}",
                kind="state_change",
                origin="failure_history",
                outcome="failed",
                failure_condition="Fresh-process successor health check failed.",
                metadata={
                    "attempted_version": version,
                    "restored_version": old_pointer["version"],
                    "rollback_health": rollback_health,
                    "snapshot": snapshot,
                },
            )
            self.journal.relate(failure_ip["ref"], candidate_ref, "rejected_by", "Activation gate rejected successor")
            return {
                "activated": False,
                "error": health["error"],
                "health": health,
                "rollback_health": rollback_health,
                "snapshot": snapshot,
                "restored_pointer": old_pointer,
            }

        activation_ip = self.journal.add_ip(
            cycle_id=cycle_id,
            label="successor_activation",
            content=f"Activated {version} after protected evaluation and fresh-process continuation check.",
            kind="state_change",
            origin="state_change",
            outcome="active",
            metadata={"old_pointer": old_pointer, "new_pointer": new_pointer, "health": health, "snapshot": snapshot},
        )
        self.journal.relate(activation_ip["ref"], candidate_ref, "activates", "Controlled successor activation")
        return {"activated": True, "health": health, "snapshot": snapshot, "old_pointer": old_pointer}

    def _fresh_process_health(self) -> dict[str, Any]:
        env = dict(os.environ)
        source_root = str((self.config.repo_root / "agent" / "src").resolve())
        env["PYTHONPATH"] = source_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "stoe_agent.worker",
                "--active-pointer",
                str(self.active_pointer),
                "--field-db",
                str(self.journal.db_path),
            ],
            cwd=self.config.repo_root / "agent",
            env=env,
            capture_output=True,
            text=True,
            timeout=self.config.activation_timeout_seconds,
            check=False,
        )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError:
            result = {"healthy": False, "error": completed.stderr or completed.stdout or "no health output"}
        if completed.returncode != 0:
            result["healthy"] = False
            result.setdefault("error", f"health process exited {completed.returncode}")
        return result

    def rollback(self, version: str) -> dict[str, Any]:
        source_path = self.config.component_dir / "versions" / f"{version}.py"
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        cycle_id = "rollback_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        prior = self.read_active_pointer()
        self._atomic_write_json(
            self.active_pointer,
            {
                "version": version,
                "source_path": str(source_path.resolve()),
                "sha256": sha256_file(source_path),
                "activated_at": datetime.now(timezone.utc).isoformat(),
                "previous_version": prior["version"],
            },
        )
        health = self._fresh_process_health()
        if not health["healthy"]:
            self._atomic_write_json(self.active_pointer, prior)
            raise RuntimeError(f"rollback target failed health check: {health}")
        change = self.journal.add_ip(
            cycle_id=cycle_id,
            label="manual_rollback",
            content=f"Controlled rollback from {prior['version']} to {version}.",
            kind="state_change",
            origin="state_change",
            outcome="active",
            metadata={"prior": prior, "current": self.read_active_pointer(), "health": health},
        )
        return {"rolled_back": True, "field_ref": change["ref"], "active": self.read_active_pointer(), "health": health}

    def failure_probe(self) -> dict[str, Any]:
        """Exercise activation rollback in isolated state without touching the live pointer."""
        probe_parent = self.config.repo_root / "agent"
        root = probe_parent / f"runtime_failure_probe_{uuid.uuid4().hex}"
        root.mkdir()
        try:
            config = SupervisorConfig(
                repo_root=self.config.repo_root,
                runtime_dir=root,
                component_dir=self.config.component_dir,
                protected_eval_dir=self.config.protected_eval_dir,
                report_dir=root,
                accepted_version_dir=root,
                rejected_candidate_dir=root,
                model=self.config.model,
            )
            isolated = RebuildSupervisor(config, model_client=self.model_client)
            failing = root / "deliberately_failed.py"
            failing.write_text(
                "def select_context(observer_state, items, max_items, max_chars):\n"
                "    if observer_state.get('__activation_probe__'):\n"
                "        raise RuntimeError('deliberate activation failure')\n"
                "    return []\n",
                encoding="utf-8",
            )
            result = isolated._activate(
                version="deliberately_failed",
                source_path=failing,
                cycle_id="deliberate_failure_probe",
                candidate_ref=isolated.journal.add_ip(
                    cycle_id="deliberate_failure_probe",
                    label="candidate",
                    content="Deliberately failing candidate used only to verify recovery.",
                    kind="implementation",
                    outcome="untested",
                )["ref"],
            )
            result["probe_passed"] = (
                not result["activated"]
                and result["rollback_health"]["healthy"]
                and isolated.read_active_pointer()["version"] == "v1"
            )
            return result
        finally:
            if root.resolve().parent != probe_parent.resolve():
                raise RuntimeError("refusing to remove failure probe outside isolated parent")
            shutil.rmtree(root, ignore_errors=True)

    def _finish_report(self, report: dict[str, Any], cycle_id: str, started: float) -> dict[str, Any]:
        report["duration_seconds"] = round(time.perf_counter() - started, 3)
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        report["persistent_field_status"] = self.journal.status()
        report_path = self.config.report_dir / f"{cycle_id}.json"
        self._atomic_write_json(report_path, report)
        report["report_path"] = str(report_path)
        return report

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
