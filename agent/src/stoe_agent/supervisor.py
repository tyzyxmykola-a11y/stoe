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

from .continuity import ContinuityDivergenceError, Lineage, advance_lineage, compare_lineage
from .field_journal import RebuildJournal, SESSION_ID
from .investigation import public_diagnostics, investigate_selector
from .ollama import OllamaClient
from .research_state import ResearchStateStore
from .selection_policy import POLICY_FORMAT, POLICY_VERSION, validate_policy
from .selector_loader import infer_artifact_type, sha256_file


PUBLIC_INPUT_FIELDS = (
    "observer_state.goal",
    "observer_state.active_constraints",
    "observer_state.changed_constraints",
    "observer_state.evidence",
    "observer_state.open_questions",
    "item.ref",
    "item.content",
    "item.origin",
    "item.kind",
    "item.outcome",
    "item.failure_condition",
    "item.created_order",
    "max_items",
    "max_chars",
)


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
        "implementation_inputs": {
            "type": "array",
            "items": {"type": "string", "enum": list(PUBLIC_INPUT_FIELDS)},
        },
        "input_feasibility": {"type": "string"},
        "expected_benefit": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "hypothesis",
        "observed_evidence",
        "diagnostic_findings",
        "source_diagnosis",
        "proposed_change",
        "implementation_inputs",
        "input_feasibility",
        "expected_benefit",
        "risks",
    ],
    "additionalProperties": False,
}

CANDIDATE_POLICY_SCHEMA = {
    "type": "object",
    "properties": {
        "policy": {"type": "object"},
        "implementation_note": {"type": "string"},
    },
    "required": ["policy", "implementation_note"],
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
    public_evaluation_timeout_seconds: float = 5.0
    persist_active_manifest: bool = True
    research_checkpoint_dir: Path | None = None
    research_bootstrap_path: Path | None = None
    continuity_branch: str | None = None

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
            research_checkpoint_dir=(agent_root / "research_checkpoints").resolve(),
            research_bootstrap_path=(agent_root / "research_state" / "bootstrap.json").resolve(),
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
        self.continuity_branch = self.config.continuity_branch or self._detect_git_branch()
        self.active_pointer = self.config.runtime_dir / "active_component.json"
        self._ensure_active_pointer()
        self.research_state = ResearchStateStore(
            runtime_dir=self.config.runtime_dir,
            checkpoint_dir=(self.config.research_checkpoint_dir or self.config.runtime_dir / "research_checkpoints"),
            bootstrap_path=self.config.research_bootstrap_path,
            project_root=self.config.repo_root,
            branch_id=self.continuity_branch,
        )

    @property
    def baseline_path(self) -> Path:
        return self.config.component_dir / "versions" / "v1.py"

    @property
    def active_release_manifest(self) -> Path:
        return self.config.component_dir / "active_release.json"

    def _ensure_active_pointer(self) -> dict[str, Any]:
        runtime = self._read_pointer_file(self.active_pointer) if self.active_pointer.exists() else None
        tracked = None
        if self.config.persist_active_manifest and self.active_release_manifest.exists():
            tracked = self._pointer_from_release_manifest()
        if runtime is not None and tracked is not None:
            runtime_lineage = self._release_lineage(runtime, tracked=tracked)
            tracked_lineage = self._release_lineage(tracked)
            try:
                relation = compare_lineage(runtime_lineage, tracked_lineage)
            except ContinuityDivergenceError as exc:
                raise ContinuityDivergenceError(
                    f"cannot reconcile runtime active pointer with active_release.json: {exc}"
                ) from exc
            if relation == "behind":
                self._atomic_write_json(self.active_pointer, tracked)
                return tracked
            if relation == "equal" and runtime.get("_lineage") is None:
                self._atomic_write_json(self.active_pointer, tracked)
                return tracked
            return runtime
        if runtime is not None:
            return runtime
        if tracked is not None:
            self._atomic_write_json(self.active_pointer, tracked)
            return tracked
        pointer = {
            "version": "v1",
            "source_path": str(self.baseline_path.resolve()),
            "sha256": sha256_file(self.baseline_path),
            "artifact_type": "legacy_python",
            "activated_at": datetime.now(timezone.utc).isoformat(),
            "previous_version": None,
        }
        pointer["_lineage"] = self._new_release_lineage(pointer).to_json(
            identity_field="release_id"
        )
        self._atomic_write_json(self.active_pointer, pointer)
        return pointer

    def _persist_active_release(self, pointer: dict[str, Any]) -> None:
        if not self.config.persist_active_manifest:
            return
        source_path = Path(pointer["source_path"]).resolve()
        versions_dir = (self.config.component_dir / "versions").resolve()
        if source_path.parent != versions_dir:
            raise RuntimeError("active release source must be in the versioned component directory")
        self._atomic_write_json(
            self.active_release_manifest,
            {
                "version": pointer["version"],
                "source_file": source_path.name,
                "sha256": pointer["sha256"],
                "artifact_type": pointer.get("artifact_type") or infer_artifact_type(source_path),
                "activated_at": pointer["activated_at"],
                "previous_version": pointer.get("previous_version"),
                "_lineage": pointer["_lineage"],
            },
        )

    def read_active_pointer(self) -> dict[str, Any]:
        pointer = self._read_pointer_file(self.active_pointer)
        return pointer

    def _read_pointer_file(self, path: Path) -> dict[str, Any]:
        pointer = json.loads(path.read_text(encoding="utf-8"))
        if sha256_file(pointer["source_path"]) != pointer["sha256"]:
            raise RuntimeError("active pointer source hash mismatch")
        pointer.setdefault("artifact_type", infer_artifact_type(pointer["source_path"]))
        return pointer

    def _pointer_from_release_manifest(self) -> dict[str, Any]:
        release = json.loads(self.active_release_manifest.read_text(encoding="utf-8"))
        source_path = self.config.component_dir / "versions" / str(release["source_file"])
        pointer = {
            "version": str(release["version"]),
            "source_path": str(source_path.resolve()),
            "sha256": str(release["sha256"]),
            "artifact_type": str(release.get("artifact_type") or infer_artifact_type(source_path)),
            "activated_at": str(release["activated_at"]),
            "previous_version": release.get("previous_version"),
        }
        if release.get("_lineage") is not None:
            pointer["_lineage"] = release["_lineage"]
        if not source_path.exists() or sha256_file(source_path) != pointer["sha256"]:
            raise RuntimeError("tracked active release source hash mismatch")
        if pointer.get("_lineage") is None:
            pointer["_lineage"] = self._legacy_release_lineage(pointer).to_json(
                identity_field="release_id"
            )
        return pointer

    @staticmethod
    def _release_id(pointer: dict[str, Any]) -> str:
        encoded = json.dumps(
            {
                "artifact_type": pointer.get("artifact_type"),
                "sha256": pointer["sha256"],
                "version": pointer["version"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _new_release_lineage(self, pointer: dict[str, Any]) -> Lineage:
        return Lineage(
            kind="active_release",
            stream_id="context-selector-release:v1",
            branch_id=self.continuity_branch,
            identity=self._release_id(pointer),
            parent_identity=None,
            ancestor_identities=(),
        )

    def _legacy_release_lineage(self, pointer: dict[str, Any]) -> Lineage:
        current = self._new_release_lineage(pointer)
        if pointer["version"] == "v1":
            return current
        if pointer.get("previous_version") != "v1":
            raise ContinuityDivergenceError(
                f"legacy active release {pointer['version']!r} has no provable ancestry"
            )
        baseline = {
            "version": "v1",
            "sha256": sha256_file(self.baseline_path),
            "artifact_type": "legacy_python",
        }
        return Lineage(
            kind=current.kind,
            stream_id=current.stream_id,
            branch_id=current.branch_id,
            identity=current.identity,
            parent_identity=self._release_id(baseline),
            ancestor_identities=(self._release_id(baseline),),
        )

    def _release_lineage(
        self, pointer: dict[str, Any], *, tracked: dict[str, Any] | None = None
    ) -> Lineage:
        value = pointer.get("_lineage")
        artifact_fingerprint = self._release_id(pointer)
        if value is None:
            if pointer["version"] == "v1":
                return self._legacy_release_lineage(pointer)
            if tracked is not None:
                tracked_lineage = self._release_lineage(tracked)
                tracked_fingerprint = tracked.get("_lineage", {}).get(
                    "artifact_fingerprint", self._release_id(tracked)
                )
                if artifact_fingerprint == tracked_fingerprint:
                    return tracked_lineage
                if artifact_fingerprint in tracked_lineage.ancestor_identities:
                    return Lineage(
                        kind=tracked_lineage.kind,
                        stream_id=tracked_lineage.stream_id,
                        branch_id=tracked_lineage.branch_id,
                        identity=artifact_fingerprint,
                        parent_identity=None,
                        ancestor_identities=(),
                    )
            raise ContinuityDivergenceError(
                f"unanchored active release {pointer['version']!r} has no ancestry proof"
            )
        identity = str(value.get("release_id"))
        if value.get("artifact_fingerprint", artifact_fingerprint) != artifact_fingerprint:
            raise ContinuityDivergenceError("active release lineage fingerprint mismatch")
        if "artifact_fingerprint" not in value and identity != artifact_fingerprint:
            raise ContinuityDivergenceError("legacy active release id is not content-addressed")
        if not identity:
            raise ContinuityDivergenceError("active release lineage has no release id")
        return Lineage(
            kind=str(value.get("kind")),
            stream_id=str(value.get("stream_id")),
            branch_id=str(value.get("branch_id")),
            identity=identity,
            parent_identity=value.get("parent_release_id"),
            ancestor_identities=tuple(value.get("ancestor_release_ids", [])),
        )

    def _successor_pointer(
        self, *, pointer: dict[str, Any], predecessor: dict[str, Any]
    ) -> dict[str, Any]:
        predecessor_lineage = self._release_lineage(predecessor)
        artifact_fingerprint = self._release_id(pointer)
        event_id = hashlib.sha256(
            json.dumps(
                {
                    "activated_at": pointer["activated_at"],
                    "artifact_fingerprint": artifact_fingerprint,
                    "parent_release_id": predecessor_lineage.identity,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        lineage = advance_lineage(predecessor_lineage, event_id)
        pointer["_lineage"] = lineage.to_json(identity_field="release_id")
        pointer["_lineage"]["artifact_fingerprint"] = artifact_fingerprint
        return pointer

    def _detect_git_branch(self) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.config.repo_root), "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            branch = result.stdout.strip()
            return branch or "detached"
        except (OSError, subprocess.SubprocessError):
            return "unscoped"

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
                    "agent/src/stoe_agent/selection_policy.py",
                    "agent/src/stoe_agent/selector_loader.py",
                    "agent/src/stoe_agent/public_worker.py",
                    "agent/src/stoe_agent/protected_worker.py",
                    "agent/protected_evals",
                ],
                "external_dependencies": ["Python runtime", "local Ollama service"],
                "underlying_model": "External model weights are selected but not modified by this cycle.",
            },
        }

    def checkpoint_research_state(self, reason: str) -> dict[str, Any]:
        state = self.research_state.load()
        pointer = self.read_active_pointer()
        state["versions"]["active"] = {
            "version": pointer["version"],
            "sha256": pointer["sha256"],
            "source_path": Path(pointer["source_path"]).resolve().relative_to(self.config.repo_root).as_posix(),
        }
        self.research_state.save(state)
        return self.research_state.checkpoint(reason=reason)

    def resume_research_context(
        self, *, max_tokens: int, known_hashes: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return self.research_state.build_resume_context(
            max_tokens=max_tokens,
            known_hashes=known_hashes,
        )

    def replay_selector(self, source_path: Path) -> dict[str, Any]:
        source_path = source_path.resolve()
        try:
            recorded_source_path = source_path.relative_to(self.config.repo_root).as_posix()
        except ValueError:
            recorded_source_path = str(source_path)
        protected_before = self.protected_hashes()
        public = self._evaluate_public(source_path)
        protected = self._evaluate(source_path)
        if "source" in protected:
            protected["source"] = recorded_source_path
        if "artifact" in protected:
            protected["artifact"] = recorded_source_path
        protected_after = self.protected_hashes()
        if protected_before != protected_after:
            raise RuntimeError("protected evaluation files changed during replay")
        return {
            "classification": "replay_on_previously_used_public_and_protected_cases_not_a_new_blind_experiment",
            "source_path": recorded_source_path,
            "source_sha256": sha256_file(source_path),
            "artifact_type": infer_artifact_type(source_path),
            "protected_hashes": protected_before,
            "public": public,
            "protected": protected,
            "replayed_at": datetime.now(timezone.utc).isoformat(),
        }

    def record_next_research_question(self, report_path: Path) -> dict[str, Any]:
        report_path = report_path.resolve()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("decision") != "ACCEPT" or not report.get("activated"):
            raise RuntimeError("next-question linkage requires an accepted, activated cycle report")
        cycle_id = str(report["cycle_id"])
        nodes = self.journal.find_cycle_nodes(cycle_id)
        correction_text = (
            "Evidence correction: the historical candidate_public_feasibility label records only an observed "
            "public behavioral improvement. It does not establish that the model's proposed invalidation mechanism "
            "caused the improvement; the accepted source used outcome/kind heuristics and changed-constraint "
            "reactivation remained unsuccessful."
        )
        correction = self.journal.find_exact_content(correction_text)
        if correction is None:
            correction = self.journal.add_ip(
                cycle_id="post_acceptance_correction",
                label="public_evidence_label_correction",
                content=correction_text,
                kind="correction",
                origin="runtime_reasoning",
                outcome="supported",
                metadata={
                    "addresses_cycle": cycle_id,
                    "source_report": str(report_path),
                    "source_report_sha256": sha256_file(report_path),
                },
            )
            for node in nodes:
                if (
                    "candidate_implementation" in node["ref"]
                    or "candidate_public_" in node["ref"]
                    or node["ref"] == report.get("evaluation_field_ref")
                ):
                    self.journal.relate(correction["ref"], node["ref"], "corrects_interpretation_of", "Post-acceptance evidence-label correction")

        question_text = (
            "Why did the proposed invalidation mechanism fail to materialize, and what evidence or interface "
            "change would let the agent investigate that discrepancy using SToE?"
        )
        question = self.journal.find_exact_content(question_text)
        if question is None:
            question = self.journal.add_ip(
                cycle_id="post_acceptance_question",
                label="next_research_question",
                content=question_text,
                kind="question",
                origin="runtime_reasoning",
                outcome="untested",
                metadata={
                    "source_cycle": cycle_id,
                    "source_report": str(report_path),
                    "research_status": "pending_next_cycle",
                },
            )
            for node in nodes:
                relation = None
                if "candidate_hypothesis" in node["ref"]:
                    relation = "questions_proposal"
                elif "candidate_implementation" in node["ref"]:
                    relation = "questions_implementation"
                elif "candidate_public_" in node["ref"] or node["ref"] == report.get("evaluation_field_ref"):
                    relation = "constrained_by_evidence"
                elif "successor_activation" in node["ref"]:
                    relation = "follows_activation"
                if relation:
                    self.journal.relate(question["ref"], node["ref"], relation, "Next research question linked to accepted-cycle evidence")
                if node["origin"] == "failure_history":
                    self.journal.relate(question["ref"], node["ref"], "motivated_by_failure", "Observed failure remains unresolved")
            self.journal.relate(question["ref"], correction["ref"], "constrained_by_correction", "Question preserves corrected evidence interpretation")
        return {
            "question_ref": question["ref"],
            "correction_ref": correction["ref"],
            "question": question_text,
            "source_cycle": cycle_id,
            "linked_cycle_node_count": len(nodes),
        }

    def record_capability_boundary_checkpoint(self, report_path: Path) -> dict[str, Any]:
        action_id = "checkpoint:candidate-capability-boundary-v1"
        question_text = (
            "Why did changed-constraint invalidation fail to materialize, and can a bounded structural input improve "
            "it on newly frozen cases without expanding candidate authority?"
        )
        report_path = report_path.resolve()
        if not report_path.is_file():
            raise FileNotFoundError(report_path)
        state = self.research_state.load()
        action = next((item for item in state["actions"] if item["action_id"] == action_id), None)
        if action is None:
            self.research_state.begin_action(
                action_id=action_id,
                description="Replace executable future selector candidates with bounded inert declarative policies.",
            )
        elif action["status"] == "completed":
            expected_questions = [
                {
                    "claim_type": "question",
                    "question": question_text,
                    "source_refs": ["candidate_capability_boundary_report"],
                }
            ]
            if state["unresolved_questions"] != expected_questions:
                state["unresolved_questions"] = expected_questions
                self.research_state.save(state)
                self.checkpoint_research_state("Compact superseded question after capability-boundary checkpoint")
            return {"decision": "SKIP_COMPLETED_ACTION", "action": action, "model_calls": 0}
        elif action["status"] not in {"running", "uncertain"}:
            self.research_state.begin_action(
                action_id=action_id,
                description="Replace executable future selector candidates with bounded inert declarative policies.",
            )

        cycle_id = "candidate_capability_boundary_v1"
        definitions = [
            (
                "intended_authority_boundary",
                "Intended boundary: generated selector candidates may receive only observer_state, items, max_items, and max_chars, with no ambient evaluator or host authority.",
                "constraint",
                "superseded",
                "The prior Python-source implementation did not enforce this intended boundary.",
            ),
            (
                "bypass_reproduction",
                "Observed bypass: __builtins__['open'] passed the former validate_candidate_source AST gate, so executing that candidate could use the evaluator child's filesystem authority and read cases.json from its working directory.",
                "observation",
                "failed",
                "Executable candidate Python inherited the child process's filesystem, environment, process, network, and memory authority.",
            ),
            (
                "affected_evaluation_claim",
                "Evidence correction: timeout containment and rollback were real, but the claim that generated Python had no filesystem or evaluator authority was not enforced; historical behavioral scores remain unchanged.",
                "correction",
                "supported",
                "",
            ),
            (
                "repair_decision",
                "Repair decision: future generated selectors are inert stoe.selection_policy version 1 JSON interpreted only by trusted bounded operations; arbitrary Python is never a candidate artifact.",
                "decision",
                "supported",
                "",
            ),
            (
                "repair_implementation",
                "Implementation: trusted policy validation and interpretation, fixed field projection, immutable hash-allowlisted legacy adapter, and separate time-bounded public/protected workers.",
                "implementation",
                "supported",
                "",
            ),
            (
                "adversarial_tests",
                "Adversarial evaluation: Python attacks were rejected before import, policy strings invoked no patched authority APIs, malformed and over-complex policies failed closed, and runtime/output/allocation bounds were enforced.",
                "evaluation",
                "supported",
                "",
            ),
            (
                "remaining_limitations",
                "Remaining limitation: the policy interpreter and supervisor are trusted Python with host authority; the narrow inert grammar removes candidate code execution but is not a general OS sandbox, and its scientific usefulness remains untested on new frozen cases.",
                "constraint",
                "active",
                "",
            ),
        ]
        nodes: dict[str, dict[str, Any]] = {}
        for label, content, kind, outcome, failure_condition in definitions:
            node = self.journal.find_exact_content(content)
            if node is None:
                node = self.journal.add_ip(
                    cycle_id=cycle_id,
                    label=label,
                    content=content,
                    kind=kind,
                    origin="failure_history" if label == "bypass_reproduction" else (
                        "evaluation" if label == "adversarial_tests" else (
                            "state_change" if label == "repair_decision" else "runtime_reasoning"
                        )
                    ),
                    outcome=outcome,
                    failure_condition=failure_condition,
                    metadata={
                        "action_id": action_id,
                        "report": report_path.relative_to(self.config.repo_root).as_posix(),
                        "report_sha256": sha256_file(report_path),
                        "provider_generation_calls": 0,
                    },
                )
            nodes[label] = node

        relation_plan = [
            ("bypass_reproduction", "intended_authority_boundary", "contradicts"),
            ("affected_evaluation_claim", "intended_authority_boundary", "corrects_interpretation_of"),
            ("repair_decision", "bypass_reproduction", "responds_to"),
            ("repair_implementation", "repair_decision", "implements"),
            ("adversarial_tests", "repair_implementation", "evaluates"),
            ("remaining_limitations", "repair_implementation", "constrains"),
        ]
        for source, target, relation in relation_plan:
            self.journal.relate(nodes[source]["ref"], nodes[target]["ref"], relation, "Capability-boundary checkpoint trace")

        question = self.journal.find_exact_content(question_text)
        if question is None:
            question = self.journal.add_ip(
                cycle_id=cycle_id,
                label="remaining_research_question",
                content=question_text,
                kind="question",
                origin="runtime_reasoning",
                outcome="untested",
                metadata={"action_id": action_id, "research_status": "pending_next_scientific_cycle"},
            )
            self.journal.relate(question["ref"], nodes["bypass_reproduction"]["ref"], "constrained_by_safety_finding", "Next research question preserves the repaired authority boundary")
            self.journal.relate(question["ref"], nodes["adversarial_tests"]["ref"], "follows_evaluation", "Infrastructure checkpoint precedes new scientific evaluation")
            self.journal.relate(question["ref"], nodes["remaining_limitations"]["ref"], "constrained_by", "New cases and narrow policy grammar remain required")

        artifact_specs = [
            (
                "candidate_capability_boundary_report",
                report_path,
                "Capability-boundary correction, implementation, verification, and limitations.",
                "checkpoint_report",
            ),
            (
                "selection_policy_format_v1",
                self.config.repo_root / "agent" / "SELECTION_POLICY_FORMAT.md",
                "Versioned inert policy grammar and resource bounds.",
                "specification",
            ),
            (
                "capability_boundary_adversarial_tests",
                self.config.repo_root / "agent" / "tests" / "test_capability_boundary.py",
                "Adversarial tests demonstrating non-execution and bounded policy interpretation.",
                "test_source",
            ),
            (
                "capability_boundary_accepted_replay",
                self.config.repo_root / "agent" / "evaluation_replays" / "20260907_capability_checkpoint_accepted_replay.json",
                "Compatibility replay of the immutable accepted legacy selector on previously observed cases.",
                "evaluation_replay",
            ),
        ]
        for ref, path, summary, kind in artifact_specs:
            self.research_state.register_artifact(
                ref=ref,
                path=path,
                summary=summary,
                kind=kind,
                provenance="verified_capability_boundary_checkpoint",
                source_refs=["accepted_cycle_json"],
            )

        state = self.research_state.load()
        state["current_task"] = "Candidate capability-boundary checkpoint completed without provider generation."
        state["active_hypothesis"] = {
            "claim_type": "hypothesis",
            "claim": question_text,
            "source_refs": ["candidate_capability_boundary_report", "accepted_cycle_json"],
        }
        additions = {
            "evidence": [
                {
                    "claim_type": "fact",
                    "kind": "failure",
                    "stance": "failure",
                    "claim": definitions[1][1],
                    "source_refs": ["candidate_capability_boundary_report"],
                },
                {
                    "claim_type": "fact",
                    "kind": "evaluation",
                    "stance": "supports",
                    "claim": definitions[5][1],
                    "source_refs": ["capability_boundary_adversarial_tests"],
                },
            ],
            "corrections": [
                {
                    "claim_type": "correction",
                    "claim": definitions[2][1],
                    "source_refs": ["candidate_capability_boundary_report", "accepted_cycle_json"],
                }
            ],
            "decisions": [
                {
                    "decision": definitions[3][1],
                    "reason": "The former AST blacklist admitted executable authority; an inert grammar removes candidate-supplied execution.",
                    "source_refs": ["selection_policy_format_v1", "candidate_capability_boundary_report"],
                }
            ],
        }
        for key, entries in additions.items():
            for entry in entries:
                identity = entry.get("claim") or entry.get("decision") or entry.get("question")
                if not any((item.get("claim") or item.get("decision") or item.get("question")) == identity for item in state[key]):
                    state[key].append(entry)
        state["unresolved_questions"] = [
            {
                "claim_type": "question",
                "question": question_text,
                "source_refs": ["candidate_capability_boundary_report"],
            }
        ]
        state["next_executable_step"] = (
            "Freeze new cases before outcomes, then test whether a bounded structural input improves changed-constraint "
            "invalidation through the declarative policy interface; do not repeat prior model actions or treat infrastructure tests as scientific evidence."
        )
        self.research_state.save(state)
        self.research_state.set_action_status(
            action_id=action_id,
            status="completed",
            result_refs=[ref for ref, _path, _summary, _kind in artifact_specs],
        )
        checkpoint = self.checkpoint_research_state(
            "Completed candidate capability-boundary v1 repair without provider generation"
        )
        return {
            "decision": "COMPLETED",
            "action_id": action_id,
            "model_calls": 0,
            "field_refs": {key: value["ref"] for key, value in nodes.items()} | {"remaining_question": question["ref"]},
            "question": question_text,
            "checkpoint": checkpoint,
        }

    def record_continuity_reconciliation_checkpoint(self, report_path: Path) -> dict[str, Any]:
        action_id = "checkpoint:continuity-reconciliation-v1"
        question_text = (
            "Why did changed-constraint invalidation fail to materialize, and can a bounded structural input improve "
            "it on newly frozen cases without expanding candidate authority?"
        )
        report_path = report_path.resolve()
        if not report_path.is_file():
            raise FileNotFoundError(report_path)
        state = self.research_state.load()
        existing = next((item for item in state["actions"] if item["action_id"] == action_id), None)
        if existing and existing["status"] == "completed":
            return {"decision": "SKIP_COMPLETED_ACTION", "action": existing, "model_calls": 0}
        if existing is None:
            self.research_state.begin_action(
                action_id=action_id,
                description="Reconcile runtime, tracked checkpoint/bootstrap, and active release by verified succession.",
            )

        cycle_id = "continuity_reconciliation_v1"
        definitions = [
            (
                "intended_state_succession",
                "Intended continuity boundary: resume must select the provable descendant across runtime, tracked checkpoint, and bootstrap rather than prefer a storage location.",
                "constraint",
                "supported",
                "runtime_reasoning",
            ),
            (
                "stale_runtime_precedence_failure",
                "Observed continuity failure: an ignored but stale runtime research_state.json was returned before the newer tracked checkpoint and restored an obsolete research question.",
                "observation",
                "failed",
                "failure_history",
            ),
            (
                "continuity_claim_correction",
                "Continuity correction: storage alone did not conserve the current connected succession of states; the former resume claim omitted reconciliation across persisted copies.",
                "correction",
                "supported",
                "runtime_reasoning",
            ),
            (
                "lineage_repair_decision",
                "Repair decision: compare content fingerprints and verified ancestry, fast-forward stale runtime, preserve only provably ahead runtime, and fail closed on divergent or cross-branch histories.",
                "decision",
                "supported",
                "state_change",
            ),
            (
                "lineage_repair_implementation",
                "Implementation: hash-anchored checkpoint lineage plus fingerprint-bound runtime/bootstrap and active-release ancestry now governs both research state and active component reconciliation.",
                "implementation",
                "supported",
                "state_change",
            ),
            (
                "lineage_adversarial_tests",
                "Evaluation: deterministic tests cover stale, ahead, divergent, clean-checkout, and cross-branch research states plus stale, ahead, and divergent active pointers.",
                "evaluation",
                "supported",
                "evaluation",
            ),
            (
                "continuity_remaining_limit",
                "Remaining limitation: local lineage metadata protects against accidental stale or divergent continuity, not a malicious host able to rewrite the repository and runtime together.",
                "constraint",
                "active",
                "runtime_reasoning",
            ),
        ]
        nodes: dict[str, dict[str, Any]] = {}
        for label, content, kind, outcome, origin in definitions:
            node = self.journal.find_exact_content(content)
            if node is None:
                node = self.journal.add_ip(
                    cycle_id=cycle_id,
                    label=label,
                    content=content,
                    kind=kind,
                    origin=origin,
                    outcome=outcome,
                    failure_condition=(
                        "Runtime file precedence ignored the tracked successor."
                        if label == "stale_runtime_precedence_failure"
                        else ""
                    ),
                    metadata={
                        "action_id": action_id,
                        "report": report_path.relative_to(self.config.repo_root).as_posix(),
                        "report_sha256": sha256_file(report_path),
                        "provider_generation_calls": 0,
                    },
                )
            nodes[label] = node
        for source, target, relation in [
            ("stale_runtime_precedence_failure", "intended_state_succession", "contradicts"),
            ("continuity_claim_correction", "stale_runtime_precedence_failure", "conserves_interpretation_of"),
            ("lineage_repair_decision", "stale_runtime_precedence_failure", "responds_to"),
            ("lineage_repair_implementation", "lineage_repair_decision", "implements"),
            ("lineage_adversarial_tests", "lineage_repair_implementation", "evaluates"),
            ("continuity_remaining_limit", "lineage_repair_implementation", "constrains"),
        ]:
            self.journal.relate(nodes[source]["ref"], nodes[target]["ref"], relation, "Continuity reconciliation trace")

        report_artifact = self.research_state.register_artifact(
            ref="continuity_reconciliation_report",
            path=report_path,
            summary="Observed stale-state precedence, lineage repair, verification, and remaining boundary.",
            kind="checkpoint_report",
            provenance="verified_continuity_reconciliation_checkpoint",
            source_refs=["candidate_capability_boundary_report"],
        )
        state = self.research_state.load()
        state["current_task"] = "Continuity reconciliation checkpoint completed without provider generation."
        failure_claim = definitions[1][1]
        correction_claim = definitions[2][1]
        decision_claim = definitions[3][1]
        if not any(item.get("claim") == failure_claim for item in state["evidence"]):
            state["evidence"].append(
                {
                    "claim_type": "fact",
                    "kind": "failure",
                    "stance": "failure",
                    "claim": failure_claim,
                    "source_refs": ["continuity_reconciliation_report"],
                }
            )
        if not any(item.get("claim") == correction_claim for item in state["corrections"]):
            state["corrections"].append(
                {
                    "claim_type": "correction",
                    "claim": correction_claim,
                    "source_refs": ["continuity_reconciliation_report"],
                }
            )
        if not any(item.get("decision") == decision_claim for item in state["decisions"]):
            state["decisions"].append(
                {
                    "decision": decision_claim,
                    "reason": "File timestamps or location cannot establish descent; bound ancestry can.",
                    "source_refs": ["continuity_reconciliation_report"],
                }
            )
        state["active_hypothesis"] = {
            "claim_type": "hypothesis",
            "claim": question_text,
            "source_refs": ["continuity_reconciliation_report", "candidate_capability_boundary_report"],
        }
        state["unresolved_questions"] = [
            {
                "claim_type": "question",
                "question": question_text,
                "source_refs": ["continuity_reconciliation_report"],
            }
        ]
        state["next_executable_step"] = (
            "Freeze new cases before outcomes, then investigate whether bounded structural input improves changed-constraint invalidation; "
            "do not run generation until this continuity checkpoint is independently reviewed."
        )
        self.research_state.save(state)
        self.research_state.set_action_status(
            action_id=action_id,
            status="completed",
            result_refs=[report_artifact["ref"]],
        )
        checkpoint = self.checkpoint_research_state(
            "Completed continuity reconciliation v1 without provider generation"
        )
        return {
            "decision": "COMPLETED",
            "action_id": action_id,
            "model_calls": 0,
            "field_refs": {key: value["ref"] for key, value in nodes.items()},
            "question": question_text,
            "checkpoint": checkpoint,
        }

    def run_cycle(self, *, action_id: str | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        cycle_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
        action_id = action_id or f"model-cycle:{cycle_id}"
        action = self.research_state.begin_action(
            action_id=action_id,
            description="Bounded SToE-guided proposal, implementation, evaluation, and activation cycle.",
        )
        if not action.get("started"):
            return {
                "decision": "SKIP_COMPLETED_ACTION" if action.get("duplicate_completed") else "RECONCILIATION_REQUIRED",
                "activated": False,
                "action_id": action_id,
                "action": action["action"],
                "reason": (
                    "The stable action id is already completed; no model call was repeated."
                    if action.get("duplicate_completed")
                    else "The action is running or uncertain and must be reconciled before retry."
                ),
            }
        pre_checkpoint = self.research_state.checkpoint(
            reason=f"Before model action {action_id}; reserve continuity if the process is interrupted"
        )
        try:
            return self._run_cycle(
                cycle_id=cycle_id,
                started=started,
                started_at=started_at,
                action_id=action_id,
                pre_checkpoint=pre_checkpoint,
            )
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
                "action_id": action_id,
                "pre_action_checkpoint": pre_checkpoint,
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
        action_id: str,
        pre_checkpoint: dict[str, Any],
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

        active_public = self._evaluate_public(active_path)
        investigation = investigate_selector(
            public_evaluation=active_public,
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
            max_output_tokens=2400,
            seed=1701,
            context_sections={
                "task_context": active_source,
                "retrieved_material": json.dumps(
                    investigation["bounded_prior_context"], ensure_ascii=False, sort_keys=True
                ),
                "tool_results": json.dumps(
                    self._compact_diagnostics(investigation), ensure_ascii=False, sort_keys=True
                ),
            },
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
        accepted_policy: dict[str, Any] | None = None
        accepted_note = ""
        repair_errors: list[str] = []
        for attempt_index in range(2):
            prompt = generation_prompt
            if repair_errors:
                prompt += (
                    "\n\nThe first policy failed only the declarative schema/complexity gate. Repair these errors "
                    "without changing the hypothesis and without seeing evaluation outcomes:\n- "
                    + "\n- ".join(repair_errors)
                )
            generated, trace = self.model_client.generate_json(
                system=(
                    "Generate one deterministic declarative selection policy as JSON data. Return JSON only. "
                    "Do not emit Python, expressions, templates, executable strings, paths, or external resource names."
                ),
                prompt=prompt,
                schema=CANDIDATE_POLICY_SCHEMA,
                max_output_tokens=3200,
                seed=2701 + attempt_index,
                context_sections={
                    "task_context": active_source + json.dumps(proposal, ensure_ascii=False, sort_keys=True),
                    "retrieved_material": "",
                    "tool_results": json.dumps(
                        self._compact_diagnostics(investigation), ensure_ascii=False, sort_keys=True
                    ),
                },
            )
            policy = generated.get("policy")
            gate = validate_policy(policy)
            attempt_path = self.config.runtime_dir / f"candidate_{cycle_id}_attempt_{attempt_index + 1}.policy.json"
            if isinstance(policy, dict):
                self._atomic_write_json(attempt_path, policy)
            else:
                self._atomic_write_json(attempt_path, {"invalid_policy_value": repr(policy)[:1000]})
            attempt = {
                "attempt": attempt_index + 1,
                "source_path": str(attempt_path),
                "source_sha256": sha256_file(attempt_path),
                "implementation_note": generated.get("implementation_note", ""),
                "artifact_type": "declarative_policy",
                "policy_validation_passed": gate.passed,
                "policy_validation_errors": list(gate.errors),
                "estimated_policy_operations_at_max_items": gate.estimated_operations,
                "model_trace": trace,
            }
            attempts.append(attempt)
            if gate.passed:
                accepted_policy = policy
                accepted_note = str(generated.get("implementation_note", ""))
                break
            repair_errors = list(gate.errors)
            failed_attempt_ip = self.journal.add_ip(
                cycle_id=cycle_id,
                label=f"policy_gate_failure_{attempt_index + 1}",
                content=f"Generated declarative policy failed schema/complexity gate: {list(gate.errors)}",
                kind="implementation",
                origin="failure_history",
                outcome="rejected",
                failure_condition="Trusted declarative policy validator rejected malformed, unavailable, or over-complex data.",
                metadata={"source_sha256": attempt["source_sha256"], "attempt": attempt_index + 1},
            )
            self.journal.relate(failed_attempt_ip["ref"], proposal_ip["ref"], "implements", "Rejected generation attempt")

        if self.protected_hashes() != protected_before:
            raise RuntimeError("protected evaluation files changed during generation")

        report: dict[str, Any] = {
            "cycle_id": cycle_id,
            "action_id": action_id,
            "pre_action_checkpoint": pre_checkpoint,
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

        if accepted_policy is None:
            archived_attempts = [self._archive_rejected(Path(item["source_path"]), cycle_id, suffix=f"attempt_{item['attempt']}") for item in attempts]
            report.update(
                {
                    "decision": "REJECT",
                    "decision_reason": "No generated declarative policy passed the trusted schema/complexity gate.",
                    "activated": False,
                    "archived_rejected_candidates": archived_attempts,
                }
            )
            return self._finish_report(report, cycle_id, started)

        candidate_runtime_path = Path(attempts[-1]["source_path"])
        candidate_ip = self.journal.add_ip(
            cycle_id=cycle_id,
            label="candidate_implementation",
            content=f"Generated inert selection-policy candidate {sha256_file(candidate_runtime_path)}: {accepted_note}",
            kind="implementation",
            outcome="untested",
            metadata={
                "provenance_type": "ai_generated_inert_policy",
                "artifact_type": "declarative_policy",
                "source_sha256": sha256_file(candidate_runtime_path),
                "runtime_path": str(candidate_runtime_path),
            },
        )
        self.journal.relate(candidate_ip["ref"], proposal_ip["ref"], "implements", "Candidate implements preregistered hypothesis")

        candidate_public = self._evaluate_public(candidate_runtime_path, artifact_type="declarative_policy")
        public_behavioral = self._public_behavioral_improvement_decision(investigation, candidate_public)
        report.update(
            {
                "candidate": {
                    "runtime_path": str(candidate_runtime_path),
                    "sha256": sha256_file(candidate_runtime_path),
                    "artifact_type": "declarative_policy",
                    "implementation_note": accepted_note,
                    "field_ref": candidate_ip["ref"],
                },
                "public_behavioral_improvement": public_behavioral,
            }
        )
        public_evaluation_ip = self.journal.add_ip(
            cycle_id=cycle_id,
            label="candidate_public_behavioral_improvement",
            content=(
                f"Disclosed behavioral improvement check: active {investigation['pass_count']}/{investigation['case_count']}; "
                f"candidate {candidate_public['pass_count']}/{candidate_public['case_count']}; "
                f"decision {public_behavioral['decision']}."
            ),
            kind="evaluation",
            origin="evaluation",
            outcome="supported" if public_behavioral["decision"] == "PROCEED" else "rejected",
            failure_condition=(
                "The generated implementation did not demonstrate its proposed mechanism on disclosed diagnostics."
                if public_behavioral["decision"] != "PROCEED"
                else ""
            ),
            metadata={
                "public_behavioral_improvement": public_behavioral,
                "causal_interpretation": "No mechanism-level causal claim; the check observes outputs only.",
            },
        )
        self.journal.relate(public_evaluation_ip["ref"], candidate_ip["ref"], "evaluates", "Disclosed behavioral improvement check")
        if public_behavioral["decision"] != "PROCEED":
            archived = self._archive_rejected(candidate_runtime_path, cycle_id)
            report.update(
                {
                    "decision": "REJECT_PUBLIC_MECHANISM",
                    "decision_reason": public_behavioral["reason"],
                    "activated": False,
                    "archived_rejected_candidate": archived,
                }
            )
            return self._finish_report(report, cycle_id, started)

        baseline_eval = self._evaluate(active_path)
        candidate_eval = self._evaluate(candidate_runtime_path, artifact_type="declarative_policy")
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
        version_path = version_dir / f"{version_name}.policy.json"
        shutil.copy2(candidate_runtime_path, version_path)
        activation = self._activate(
            version=version_name,
            source_path=version_path,
            cycle_id=cycle_id,
            candidate_ref=candidate_ip["ref"],
            artifact_type="declarative_policy",
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
            "concise implementation hypothesis. Keep every prose field to one or two sentences. diagnostic_findings "
            "MUST contain one entry for every failed public diagnostic, "
            "with its exact observed selections and missed required refs. Each source_mechanism must name a field or "
            "operation visible in ACTIVE SOURCE. Reject abstract ontology language that is not tied to an observed "
            "selection decision. Do not assume observer-aware scoring is better merely because it is SToE-derived. "
            "List every runtime value required by the proposed implementation in implementation_inputs, using only "
            "the exact PUBLIC INPUT FIELDS below. Navigator edge types, paths, relation labels, and scores are "
            "investigation evidence only: select_context does not receive them. Do not disguise an unavailable "
            "structural signal as failure_condition or another public field. "
            "Do not request evaluator changes; the supervisor's acceptance and rollback rules are fixed.\n\n"
            "PUBLIC INPUT FIELDS:\n" + json.dumps(PUBLIC_INPUT_FIELDS, indent=2) + "\n\n"
            "ACTIVE SOURCE:\n" + source + "\n\nINVESTIGATION:\n" + json.dumps(evidence, indent=2, ensure_ascii=False)
        )

    def _generation_prompt(
        self,
        source: str,
        investigation: dict[str, Any],
        proposal: dict[str, Any],
    ) -> str:
        public_contract = {
            "representation": "inert JSON data interpreted by trusted stoe_agent.selection_policy code",
            "format": POLICY_FORMAT,
            "version": POLICY_VERSION,
            "required_policy_fields": ["format", "version", "filters", "score_rules", "sort", "budget"],
            "rule_shapes": {
                "token_similarity": ["op", "left_fields", "right_field", "weight"],
                "constant_if": ["op", "conditions", "weight"],
                "conditional_similarity": [
                    "op",
                    "conditions",
                    "left_fields",
                    "right_field",
                    "weight",
                    "bias",
                ],
                "condition": ["field", "op", "value_or_values"],
            },
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
                "no Python, imports, expressions, templates, callbacks, paths, or resource names",
                "score_rules use only token_similarity, constant_if, or conditional_similarity",
                "conditions use only eq, not_eq, in, not_in, contains_token, or nonempty",
                "filters may only exclude_if",
                "sort is fixed to score descending, created_order descending, ref ascending",
                "budget strategy is greedy_skip_oversize",
                "do not reward every failure; relate failure conditions to active or changed constraints",
                "do not assume origin alone proves relevance",
                "navigator paths, edge types, relation labels, and scores are not selector inputs",
                "failure_condition is natural-language rejection-basis text, never an edge-label container",
            ],
        }
        return (
            "Implement the preregistered proposal as one inert declarative selection-policy JSON object. Generalize from "
            "the investigation; do not encode diagnostic ref names or case-specific phrases. The protected acceptance "
            "cases are unavailable. Do not emit executable text or name external resources.\n\n"
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
        for key in required - {"observed_evidence", "risks", "diagnostic_findings", "implementation_inputs"}:
            if not isinstance(proposal[key], str) or not proposal[key].strip():
                raise RuntimeError(f"proposal field is empty: {key}")
        for key in ("observed_evidence", "risks"):
            if not isinstance(proposal[key], list) or not proposal[key] or not all(
                isinstance(item, str) and item.strip() for item in proposal[key]
            ):
                raise RuntimeError(f"proposal list field is empty or invalid: {key}")
        implementation_inputs = proposal["implementation_inputs"]
        if not isinstance(implementation_inputs, list) or not implementation_inputs or not all(
            isinstance(item, str) and item in PUBLIC_INPUT_FIELDS for item in implementation_inputs
        ):
            raise RuntimeError("proposal implementation_inputs contains unavailable selector inputs")
        if len(implementation_inputs) != len(set(implementation_inputs)):
            raise RuntimeError("proposal implementation_inputs contains duplicates")
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
    def _public_behavioral_improvement_decision(
        investigation: dict[str, Any], candidate_public: dict[str, Any]
    ) -> dict[str, Any]:
        active_passed = {
            item["case"] for item in investigation["diagnostics"] if item["selector_passed"]
        }
        candidate_passed = set(candidate_public["passed_cases"])
        regressions = sorted(active_passed - candidate_passed)
        execution_completed = candidate_public.get("status") == "completed"
        improved = execution_completed and candidate_public["pass_count"] > investigation["pass_count"]
        proceed = improved and not regressions
        reason_parts = []
        if not execution_completed:
            reason_parts.append(
                "candidate public diagnostic subprocess failed: "
                f"{candidate_public.get('failure_kind', 'unknown')}: {candidate_public.get('error', '')}"
            )
        if not improved:
            reason_parts.append("candidate did not improve the disclosed diagnostic pass count")
        if regressions:
            reason_parts.append(f"candidate regressed disclosed cases: {regressions}")
        if proceed:
            reason_parts.append(
                "candidate showed disclosed behavioral improvement; this does not establish the proposed mechanism; protected evaluation remains decisive"
            )
        return {
            "decision": "PROCEED" if proceed else "REJECT",
            "reason": "; ".join(reason_parts),
            "active_pass_count": investigation["pass_count"],
            "candidate_pass_count": candidate_public["pass_count"],
            "regressions": regressions,
            "candidate_results": candidate_public["results"],
            "execution": {
                "status": candidate_public.get("status"),
                "failure_kind": candidate_public.get("failure_kind", ""),
                "error": candidate_public.get("error", ""),
            },
            "role": "disclosed behavioral improvement check only; never sufficient for activation or a causal mechanism claim",
        }

    def _evaluate_public(
        self, source_path: Path, *, artifact_type: str | None = None
    ) -> dict[str, Any]:
        artifact_type = artifact_type or infer_artifact_type(source_path)
        env = dict(os.environ)
        source_root = str((self.config.repo_root / "agent" / "src").resolve())
        env["PYTHONPATH"] = source_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        command = [
            sys.executable,
            "-m",
            "stoe_agent.public_worker",
            "--artifact",
            str(source_path),
            "--artifact-type",
            artifact_type,
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.config.repo_root / "agent",
                env=env,
                capture_output=True,
                text=True,
                timeout=self.config.public_evaluation_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return self._public_execution_rejection(
                "timeout", f"public diagnostic child exceeded {self.config.public_evaluation_timeout_seconds}s", exc
            )
        except OSError as exc:
            return self._public_execution_rejection("launch_error", f"{type(exc).__name__}: {exc}")
        if completed.returncode != 0 and not completed.stdout.strip():
            return self._public_execution_rejection(
                "crash",
                completed.stderr or f"public diagnostic child exited {completed.returncode}",
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        try:
            result = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            return self._public_execution_rejection(
                "malformed_output",
                f"{type(exc).__name__}: {exc}",
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        if completed.returncode != 0 or result.get("status") != "completed":
            return self._public_execution_rejection(
                "crash" if completed.returncode != 0 else str(result.get("failure_kind", "worker_rejection")),
                str(result.get("error") or completed.stderr or f"child exited {completed.returncode}"),
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        expected_cases = {case.name for case in public_diagnostics()}
        results = result.get("results")
        if not isinstance(results, list) or {item.get("case") for item in results if isinstance(item, dict)} != expected_cases:
            return self._public_execution_rejection("malformed_output", "child result did not contain every public diagnostic")
        result["subprocess_returncode"] = completed.returncode
        return result

    @staticmethod
    def _public_execution_rejection(
        failure_kind: str,
        error: str,
        exc: Exception | None = None,
        *,
        stdout: str = "",
        stderr: str = "",
    ) -> dict[str, Any]:
        results = [
            {
                "case": case.name,
                "selected": [],
                "required_refs": list(case.required_refs),
                "forbidden_refs": list(case.forbidden_refs),
                "deterministic": False,
                "passed": False,
                "error": error,
            }
            for case in public_diagnostics()
        ]
        return {
            "status": "rejected",
            "failure_kind": failure_kind,
            "error": error,
            "exception_type": type(exc).__name__ if exc is not None else "",
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
            "output_truncated": len(stdout) > 4000 or len(stderr) > 4000,
            "case_count": len(results),
            "pass_count": 0,
            "passed_cases": [],
            "results": results,
        }

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
        extension = "".join(source_path.suffixes) or ".artifact"
        destination = archive_dir / f"{cycle_id}_{suffix}{extension}"
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

    def _evaluate(
        self, source_path: Path, *, artifact_type: str | None = None
    ) -> dict[str, Any]:
        artifact_type = artifact_type or infer_artifact_type(source_path)
        env = dict(os.environ)
        source_root = str((self.config.repo_root / "agent" / "src").resolve())
        env["PYTHONPATH"] = source_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        command = [
            sys.executable,
            "-m",
            "stoe_agent.protected_worker",
            "--artifact",
            str(source_path),
            "--artifact-type",
            artifact_type,
            "--cases",
            str(self.config.protected_eval_dir / "cases.json"),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.config.repo_root / "agent",
                env=env,
                capture_output=True,
                text=True,
                timeout=self.config.evaluation_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return self._protected_execution_rejection(
                "timeout", f"protected evaluation exceeded {self.config.evaluation_timeout_seconds}s", exc
            )
        except OSError as exc:
            return self._protected_execution_rejection("launch_error", f"{type(exc).__name__}: {exc}")
        try:
            result = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            return self._protected_execution_rejection(
                "malformed_output", f"{type(exc).__name__}: {exc}", stdout=completed.stdout, stderr=completed.stderr
            )
        if completed.returncode != 0 or result.get("status") != "completed":
            return self._protected_execution_rejection(
                "crash" if completed.returncode != 0 else str(result.get("failure_kind", "worker_rejection")),
                str(result.get("error") or completed.stderr or f"child exited {completed.returncode}"),
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        result["subprocess_returncode"] = completed.returncode
        return result

    @staticmethod
    def _protected_execution_rejection(
        failure_kind: str,
        error: str,
        exc: Exception | None = None,
        *,
        stdout: str = "",
        stderr: str = "",
    ) -> dict[str, Any]:
        return {
            "status": "rejected",
            "failure_kind": failure_kind,
            "error": error,
            "exception_type": type(exc).__name__ if exc is not None else "",
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
            "output_truncated": len(stdout) > 4000 or len(stderr) > 4000,
            "pass_count": 0,
            "case_count": 0,
            "critical_failures": [],
            "passed_cases": [],
            "results": [],
        }

    @staticmethod
    def _acceptance_decision(active: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        active_passes = set(active.get("passed_cases", []))
        candidate_passes = set(candidate.get("passed_cases", []))
        regressions = sorted(active_passes - candidate_passes)
        critical = list(candidate.get("critical_failures", []))
        execution_completed = active.get("status", "completed") == "completed" and candidate.get("status") == "completed"
        improved = execution_completed and int(candidate.get("pass_count", 0)) > int(active.get("pass_count", 0))
        accepted = execution_completed and improved and not regressions and not critical
        reasons = []
        if not execution_completed:
            reasons.append("active or candidate protected evaluation did not complete")
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
            "execution_completed": execution_completed,
        }

    def _activate(
        self,
        *,
        version: str,
        source_path: Path,
        cycle_id: str,
        candidate_ref: str,
        artifact_type: str | None = None,
    ) -> dict[str, Any]:
        old_pointer = self.read_active_pointer()
        snapshot = self.journal.snapshot(cycle_id=cycle_id)
        artifact_type = artifact_type or infer_artifact_type(source_path)
        new_pointer = {
            "version": version,
            "source_path": str(source_path.resolve()),
            "sha256": sha256_file(source_path),
            "artifact_type": artifact_type,
            "activated_at": datetime.now(timezone.utc).isoformat(),
            "previous_version": old_pointer["version"],
        }
        new_pointer = self._successor_pointer(pointer=new_pointer, predecessor=old_pointer)
        attempt_ip = self.journal.add_ip(
            cycle_id=cycle_id,
            label="activation_attempt",
            content=f"Attempt activation of {version} from {old_pointer['version']}.",
            kind="state_change",
            origin="state_change",
            outcome="untested",
            metadata={"old_pointer": old_pointer, "attempted_pointer": new_pointer, "snapshot": snapshot},
        )
        self.journal.relate(attempt_ip["ref"], candidate_ref, "attempts_activation", "Controlled activation attempt")
        try:
            self._atomic_write_json(self.active_pointer, new_pointer)
        except Exception as exc:
            return self._record_activation_recovery(
                cycle_id=cycle_id,
                candidate_ref=candidate_ref,
                attempt_ref=attempt_ip["ref"],
                version=version,
                old_pointer=old_pointer,
                snapshot=snapshot,
                health={
                    "healthy": False,
                    "failure_kind": "pointer_write_error",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        health = self._safe_fresh_process_health()
        if not health["healthy"]:
            return self._record_activation_recovery(
                cycle_id=cycle_id,
                candidate_ref=candidate_ref,
                attempt_ref=attempt_ip["ref"],
                version=version,
                old_pointer=old_pointer,
                snapshot=snapshot,
                health=health,
            )

        try:
            self._persist_active_release(new_pointer)
        except Exception as exc:
            return self._record_activation_recovery(
                cycle_id=cycle_id,
                candidate_ref=candidate_ref,
                attempt_ref=attempt_ip["ref"],
                version=version,
                old_pointer=old_pointer,
                snapshot=snapshot,
                health={
                    "healthy": False,
                    "failure_kind": "release_manifest_error",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )

        activation_ip = self.journal.add_ip(
            cycle_id=cycle_id,
            label="successor_activation",
            content=f"Activated {version} after protected evaluation and fresh-process continuation check.",
            kind="state_change",
            origin="state_change",
            outcome="active",
            metadata={"old_pointer": old_pointer, "new_pointer": new_pointer, "health": health, "snapshot": snapshot},
        )
        self.journal.relate(activation_ip["ref"], attempt_ip["ref"], "completes", "Activation attempt completed successfully")
        self.journal.relate(activation_ip["ref"], candidate_ref, "activates", "Controlled successor activation")
        return {
            "activated": True,
            "health": health,
            "snapshot": snapshot,
            "old_pointer": old_pointer,
            "field_refs": {"attempt": attempt_ip["ref"], "activation": activation_ip["ref"]},
        }

    def _record_activation_recovery(
        self,
        *,
        cycle_id: str,
        candidate_ref: str,
        attempt_ref: str,
        version: str,
        old_pointer: dict[str, Any],
        snapshot: dict[str, Any],
        health: dict[str, Any],
    ) -> dict[str, Any]:
        failure_ip = self.journal.add_ip(
            cycle_id=cycle_id,
            label="activation_failure",
            content=f"Activation of {version} failed: {health.get('error', 'unknown health failure')}",
            kind="result",
            origin="failure_history",
            outcome="failed",
            failure_condition="Fresh-process activation or persistent release update did not complete successfully.",
            metadata={"attempted_version": version, "health": health, "snapshot": snapshot},
        )
        self.journal.relate(failure_ip["ref"], attempt_ref, "evaluates", "Failure observed during activation attempt")
        self.journal.relate(failure_ip["ref"], candidate_ref, "rejected_by", "Activation gate rejected successor")

        restoration_succeeded = False
        restoration_error = ""
        try:
            self._atomic_write_json(self.active_pointer, old_pointer)
            restoration_succeeded = True
        except Exception as exc:
            restoration_error = f"{type(exc).__name__}: {exc}"
        restoration_ip = self.journal.add_ip(
            cycle_id=cycle_id,
            label="activation_pointer_restoration",
            content=(
                f"Restored active pointer to {old_pointer['version']}."
                if restoration_succeeded
                else f"FAILED to restore active pointer to {old_pointer['version']}: {restoration_error}"
            ),
            kind="state_change",
            origin="state_change" if restoration_succeeded else "failure_history",
            outcome="supported" if restoration_succeeded else "failed",
            failure_condition="" if restoration_succeeded else "Writing the previous active pointer failed.",
            metadata={
                "restored_version": old_pointer["version"],
                "restoration_succeeded": restoration_succeeded,
                "restoration_error": restoration_error,
            },
        )
        self.journal.relate(restoration_ip["ref"], failure_ip["ref"], "responds_to", "Restoration follows activation failure")

        recovery_health = (
            self._safe_fresh_process_health()
            if restoration_succeeded
            else {
                "healthy": False,
                "failure_kind": "restoration_failed",
                "error": restoration_error,
            }
        )
        recovered = restoration_succeeded and bool(recovery_health.get("healthy"))
        recovery_ip = self.journal.add_ip(
            cycle_id=cycle_id,
            label="activation_recovery_evaluation",
            content=(
                f"Fresh-process recovery of {old_pointer['version']} succeeded."
                if recovered
                else f"Fresh-process recovery of {old_pointer['version']} FAILED: {recovery_health.get('error', '')}"
            ),
            kind="evaluation",
            origin="evaluation",
            outcome="supported" if recovered else "failed",
            failure_condition="" if recovered else "Previous-version recovery could not be verified in a fresh process.",
            metadata={"recovery_health": recovery_health, "restoration_succeeded": restoration_succeeded},
        )
        self.journal.relate(recovery_ip["ref"], restoration_ip["ref"], "evaluates", "Fresh-process verification of restored version")
        error = str(health.get("error", "activation failed"))
        if not recovered:
            error += f"; RECOVERY FAILED: {recovery_health.get('error', restoration_error)}"
        return {
            "activated": False,
            "error": error,
            "health": health,
            "rollback_health": recovery_health,
            "recovery_health": recovery_health,
            "restoration_succeeded": restoration_succeeded,
            "recovery_succeeded": recovered,
            "snapshot": snapshot,
            "restored_pointer": old_pointer if restoration_succeeded else None,
            "field_refs": {
                "attempt": attempt_ref,
                "failure": failure_ip["ref"],
                "restoration": restoration_ip["ref"],
                "recovery_evaluation": recovery_ip["ref"],
            },
        }

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

    def _safe_fresh_process_health(self) -> dict[str, Any]:
        try:
            result = self._fresh_process_health()
            if not result.get("healthy"):
                result.setdefault("failure_kind", "worker_unhealthy")
                result.setdefault("error", "fresh-process worker reported unhealthy")
            return result
        except subprocess.TimeoutExpired as exc:
            return {
                "healthy": False,
                "failure_kind": "timeout",
                "error": f"TimeoutExpired: fresh-process health exceeded {self.config.activation_timeout_seconds}s",
                "exception": str(exc),
            }
        except OSError as exc:
            return {
                "healthy": False,
                "failure_kind": "launch_error",
                "error": f"{type(exc).__name__}: {exc}",
            }
        except Exception as exc:
            return {
                "healthy": False,
                "failure_kind": "health_exception",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def rollback(self, version: str) -> dict[str, Any]:
        versions_dir = self.config.component_dir / "versions"
        candidates = [versions_dir / f"{version}.policy.json", versions_dir / f"{version}.py"]
        source_path = next((path for path in candidates if path.exists()), None)
        if source_path is None:
            raise FileNotFoundError(candidates[0])
        artifact_type = infer_artifact_type(source_path)
        cycle_id = "rollback_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        prior = self.read_active_pointer()
        next_pointer = self._successor_pointer(
            pointer={
                "version": version,
                "source_path": str(source_path.resolve()),
                "sha256": sha256_file(source_path),
                "artifact_type": artifact_type,
                "activated_at": datetime.now(timezone.utc).isoformat(),
                "previous_version": prior["version"],
            },
            predecessor=prior,
        )
        self._atomic_write_json(self.active_pointer, next_pointer)
        health = self._safe_fresh_process_health()
        if not health["healthy"]:
            self._atomic_write_json(self.active_pointer, prior)
            raise RuntimeError(f"rollback target failed health check: {health}")
        try:
            self._persist_active_release(self.read_active_pointer())
        except Exception:
            self._atomic_write_json(self.active_pointer, prior)
            raise
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
                persist_active_manifest=False,
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
        report["report_path"] = str(report_path)
        action_id = report.get("action_id")
        if action_id:
            try:
                self._record_cycle_token_measurements(report)
                status = "failed" if report.get("decision") == "ERROR_REJECT" else "completed"
                self.research_state.set_action_status(
                    action_id=str(action_id),
                    status=status,
                    result_refs=[str(report_path)],
                )
                report["continuity_checkpoint"] = self.research_state.checkpoint(
                    reason=f"After model action {action_id}: {report.get('decision', 'unknown')}"
                )
            except Exception as exc:
                report["continuity_checkpoint_error"] = f"{type(exc).__name__}: {exc}"
        self._atomic_write_json(report_path, report)
        return report

    def _record_cycle_token_measurements(self, report: dict[str, Any]) -> None:
        traces: list[tuple[str, dict[str, Any]]] = []
        if isinstance(report.get("proposal_trace"), dict):
            traces.append(("proposal", report["proposal_trace"]))
        for attempt in report.get("generation_attempts", []):
            if isinstance(attempt.get("model_trace"), dict):
                traces.append((f"generation_attempt_{attempt.get('attempt')}", attempt["model_trace"]))
        if not traces:
            return
        state = self.research_state.load()
        measurements = state.setdefault("measurements", {})
        usage_rows = measurements.setdefault("provider_usage", [])
        budget_rows = measurements.setdefault("budgets", [])
        truncation_rows = measurements.setdefault("truncations", [])
        action_id = str(report.get("action_id", ""))
        for call_label, trace in traces:
            call_id = f"{action_id}:{call_label}"
            usage = trace.get("provider_token_usage")
            if isinstance(usage, dict) and not any(row.get("call_id") == call_id for row in usage_rows):
                usage_rows.append({"call_id": call_id, **usage})
            budget = trace.get("token_budget")
            if isinstance(budget, dict) and not any(row.get("call_id") == call_id for row in budget_rows):
                budget_rows.append({"call_id": call_id, **budget})
                for event in budget.get("truncation_events", []):
                    truncation_rows.append({"call_id": call_id, **event})
        self.research_state.save(state)

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
