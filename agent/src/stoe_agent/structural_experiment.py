from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .investigation import investigate_selector, public_diagnostics
from .selection_policy import validate_policy
from .selector_loader import sha256_file


STRUCTURAL_CONTEXT_CHAR_CAP = 5000
PROPOSAL_SEED = 3701
POLICY_SEED = 4701
PROPOSAL_MAX_TOKENS = 2400
POLICY_MAX_TOKENS = 3200
CONDITIONS = ("ORDINARY_OBSERVABLE", "BOUNDED_TYPED_STOE")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def assert_no_hidden_identifiers(
    conditions: dict[str, dict[str, Any]], cases: list[dict[str, Any]]
) -> None:
    hidden_markers = [case["name"] for case in cases] + [
        item["ref"] for case in cases for item in case["items"]
    ]
    for condition in conditions.values():
        for trace_name in ("proposal_trace", "generation_trace"):
            trace = condition.get(trace_name, {})
            request = trace.get("request", {}) if isinstance(trace, dict) else {}
            sent = str(request.get("system", "")) + str(request.get("prompt", ""))
            leaked = next((marker for marker in hidden_markers if marker in sent), None)
            if leaked is not None:
                raise RuntimeError(
                    f"frozen-case identifier leaked into a model prompt: {leaked}"
                )


def select_unique_winner(conditions: dict[str, dict[str, Any]]) -> tuple[list[str], str | None]:
    eligible = [
        name
        for name, result in conditions.items()
        if result["public_gate"].get("decision") == "PROCEED"
        and result["acceptance"].get("decision") == "ACCEPT"
    ]
    if not eligible:
        return eligible, None
    ordered = sorted(
        eligible,
        key=lambda name: (
            -conditions[name]["metrics"]["targeted_pass_count"],
            -conditions[name]["metrics"]["total_pass_count"],
            name,
        ),
    )
    if len(ordered) > 1 and (
        conditions[ordered[0]]["metrics"]["targeted_pass_count"],
        conditions[ordered[0]]["metrics"]["total_pass_count"],
    ) == (
        conditions[ordered[1]]["metrics"]["targeted_pass_count"],
        conditions[ordered[1]]["metrics"]["total_pass_count"],
    ):
        return eligible, None
    return eligible, ordered[0]


def validate_unseen_cases(cases: Any) -> dict[str, Any]:
    if not isinstance(cases, list) or len(cases) != 12:
        raise RuntimeError("frozen structural-input benchmark must contain exactly 12 cases")
    names: set[str] = set()
    refs: set[str] = set()
    families: set[str] = set()
    targeted = 0
    controls = 0
    for case in cases:
        if not isinstance(case, dict):
            raise RuntimeError("every frozen case must be an object")
        name = str(case.get("name", ""))
        family = str(case.get("family", ""))
        if not name or name in names or not family or family in families:
            raise RuntimeError("case names and families must be nonempty and unique")
        names.add(name)
        families.add(family)
        if case.get("targeted_changed_constraint") is True:
            targeted += 1
            if not case.get("observer", {}).get("changed_constraints"):
                raise RuntimeError(f"targeted case has no changed constraint: {name}")
        else:
            controls += 1
            if case.get("observer", {}).get("changed_constraints"):
                raise RuntimeError(f"control unexpectedly changes a constraint: {name}")
        items = case.get("items")
        if not isinstance(items, list) or len(items) < 2:
            raise RuntimeError(f"case has too few items: {name}")
        item_refs = {str(item.get("ref", "")) for item in items}
        if "" in item_refs or len(item_refs) != len(items) or refs.intersection(item_refs):
            raise RuntimeError(f"case item refs are empty or duplicated: {name}")
        refs.update(item_refs)
        required = set(case.get("required_refs", []))
        forbidden = set(case.get("forbidden_refs", []))
        if not required or not required.issubset(item_refs) or not forbidden.issubset(item_refs):
            raise RuntimeError(f"invalid required/forbidden refs: {name}")
        if required.intersection(forbidden):
            raise RuntimeError(f"required and forbidden refs overlap: {name}")
        max_items = int(case.get("max_items", 0))
        max_chars = int(case.get("max_chars", 0))
        if max_items < len(required) or max_items > len(items) or max_chars <= 0:
            raise RuntimeError(f"invalid selection budget: {name}")
        by_ref = {item["ref"]: item for item in items}
        if sum(len(str(by_ref[ref].get("content", ""))) for ref in required) > max_chars:
            raise RuntimeError(f"required answer cannot fit case budget: {name}")
    if targeted != 8 or controls != 4:
        raise RuntimeError("benchmark must contain eight targets and four controls")
    return {
        "case_count": len(cases),
        "targeted_count": targeted,
        "control_count": controls,
        "family_count": len(families),
        "independent_case_count": len(cases),
    }


def observable_diagnostics(investigation: dict[str, Any]) -> list[dict[str, Any]]:
    definitions = {case.name: case for case in public_diagnostics()}
    visible: list[dict[str, Any]] = []
    for item in investigation["diagnostics"]:
        case = definitions[item["case"]]
        visible.append(
            {
                "case": item["case"],
                "observer": item["observer"],
                "available_items": deepcopy(case.items),
                "selector_selected": item["selector_selected"],
                "selector_passed": item["selector_passed"],
                "required_refs": item["required_refs"],
                "forbidden_refs": item["forbidden_refs"],
                "missed_refs": item["missed_refs"],
            }
        )
    return visible


def bounded_field_contexts(
    investigation: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return content-matched ordinary memory and its typed relational overlay."""
    memory_candidates: list[dict[str, Any]] = []
    relation_candidates: list[dict[str, Any]] = []
    for diagnostic in investigation["diagnostics"]:
        relevant = set(diagnostic["required_refs"] + diagnostic["selector_selected"])
        for trace in diagnostic["navigator_candidate_trace"]:
            if trace["external_ref"] not in relevant:
                continue
            record_id = f"diagnostic:{diagnostic['case']}:{trace['external_ref']}"
            memory_candidates.append(
                {
                    "record_id": record_id,
                    "source": "public_diagnostic_item",
                    "case": diagnostic["case"],
                    "external_ref": trace["external_ref"],
                }
            )
            relation_candidates.append(
                {
                    "record_type": "diagnostic_typed_path",
                    "record_id": record_id,
                    "selected_by_navigator": trace["selected"],
                    "path": [
                        {
                            "relation": step["type"],
                            "direction": step["direction"],
                            "from": step["from"],
                            "to": step["to"],
                        }
                        for step in trace["path"]
                    ],
                    "scores": trace["scores"],
                }
            )
    for item in investigation["bounded_prior_context"]:
        record_id = f"field:{item['ref']}"
        memory_candidates.append(
            {
                "record_id": record_id,
                "source": "bounded_field_retrieval",
                "ref": item["ref"],
                "origin": item["origin"],
                "kind": item["kind"],
                "outcome": item["outcome"],
                "content": str(item["content"])[:360],
            }
        )
        relation_candidates.append(
            {
                "record_type": "field_typed_path",
                "record_id": record_id,
                "path": [
                    {
                        "relation": step["type"],
                        "direction": step["direction"],
                        "from": step["from"],
                        "to": step["to"],
                    }
                    for step in item["path"]
                ],
            }
        )
    memory: dict[str, Any] = {
        "format": "stoe.unstructured_memory",
        "version": 1,
        "content_matching": "identical serialized object in both paired conditions",
        "budget": {
            "max_records": 14,
            "max_serialized_characters": STRUCTURAL_CONTEXT_CHAR_CAP,
        },
        "records": [],
    }
    overlay: dict[str, Any] = {
        "format": "stoe.typed_relational_overlay",
        "version": 1,
        "content_contract": "adds relations only; node content is supplied in the common memory object",
        "source_run_ids": [
            *[item["navigator_run_id"] for item in investigation["diagnostics"]],
            investigation["synthesis_navigation_run_id"],
        ],
        "records": [],
    }
    omitted = 0
    for memory_candidate, relation_candidate in zip(memory_candidates, relation_candidates):
        trial_memory = deepcopy(memory)
        trial_overlay = deepcopy(overlay)
        trial_memory["records"].append(memory_candidate)
        trial_overlay["records"].append(relation_candidate)
        combined_size = len(_canonical_bytes(trial_memory)) + len(_canonical_bytes(trial_overlay))
        if len(trial_memory["records"]) > 14 or combined_size > STRUCTURAL_CONTEXT_CHAR_CAP - 240:
            omitted += 1
            continue
        memory, overlay = trial_memory, trial_overlay
    serialization = {
        "candidate_record_count": len(memory_candidates),
        "visible_record_count": len(memory["records"]),
        "omitted_for_budget": omitted,
    }
    memory["serialization"] = deepcopy(serialization)
    overlay["serialization"] = deepcopy(serialization)
    combined_size = len(_canonical_bytes(memory)) + len(_canonical_bytes(overlay))
    memory["serialization"]["combined_serialized_characters"] = combined_size
    overlay["serialization"]["combined_serialized_characters"] = combined_size
    combined_size = len(_canonical_bytes(memory)) + len(_canonical_bytes(overlay))
    if combined_size > STRUCTURAL_CONTEXT_CHAR_CAP:
        raise RuntimeError("bounded paired field contexts exceeded preregistered character cap")
    if [item["record_id"] for item in memory["records"]] != [
        item["record_id"] for item in overlay["records"]
    ]:
        raise RuntimeError("typed overlay and ordinary memory do not expose identical record IDs")
    return memory, overlay


class StructuralInputExperiment:
    def __init__(self, supervisor: Any, spec_path: Path) -> None:
        self.supervisor = supervisor
        self.spec_path = spec_path.resolve()
        self.root = self.spec_path.parent
        self.spec = json.loads(self.spec_path.read_text(encoding="utf-8"))
        self.cases_path = (self.root / self.spec["benchmark"]["file"]).resolve()
        self.manifest_path = (self.root / self.spec["freeze_manifest"]).resolve()

    def preflight(self, *, require_clean: bool = True) -> dict[str, Any]:
        if self.spec.get("status") != "FROZEN_NOT_RUN":
            raise RuntimeError("experiment specification is not marked FROZEN_NOT_RUN")
        cases = json.loads(self.cases_path.read_text(encoding="utf-8"))
        structure = validate_unseen_cases(cases)
        if self.spec.get("condition_order") != list(CONDITIONS):
            raise RuntimeError("condition order differs from the frozen paired design")
        generation = self.spec.get("generation", {})
        expected_generation = {
            "calls_per_condition": 2,
            "total_call_budget": 4,
            "retry_count": 0,
            "proposal_seed": PROPOSAL_SEED,
            "policy_seed": POLICY_SEED,
            "proposal_max_output_tokens": PROPOSAL_MAX_TOKENS,
            "policy_max_output_tokens": POLICY_MAX_TOKENS,
            "context_limit_tokens": 8192,
        }
        if any(generation.get(key) != value for key, value in expected_generation.items()):
            raise RuntimeError("runner constants differ from frozen generation settings")
        if getattr(self.supervisor.model_client, "context_limit_tokens", 8192) != 8192:
            raise RuntimeError("model client context limit differs from frozen specification")
        actual_case_hash = sha256_file(self.cases_path)
        if actual_case_hash != self.spec["benchmark"]["sha256"]:
            raise RuntimeError("frozen unseen-case SHA-256 mismatch")
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        for relative, expected in manifest["critical_file_sha256"].items():
            path = (self.supervisor.config.repo_root / relative).resolve()
            if sha256_file(path) != expected:
                raise RuntimeError(f"frozen critical-file SHA-256 mismatch: {relative}")
        identity = self.supervisor.model_client.identity()
        expected_model = self.spec["model"]
        if identity.name != expected_model["name"] or identity.digest != expected_model["digest"]:
            raise RuntimeError("local Ollama model or digest differs from frozen specification")
        pointer = self.supervisor.read_active_pointer()
        expected_active = self.spec["active_baseline"]
        if (
            pointer["sha256"] != expected_active["sha256"]
            or pointer["version"] != expected_active["version"]
            or pointer.get("artifact_type", "legacy_python") != expected_active["artifact_type"]
        ):
            raise RuntimeError("active selector differs from frozen baseline")
        commit = subprocess.run(
            ["git", "-C", str(self.supervisor.config.repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        if require_clean:
            dirty = subprocess.run(
                ["git", "-C", str(self.supervisor.config.repo_root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
            if dirty:
                raise RuntimeError("frozen experiment requires a clean worktree")
        return {
            "verified": True,
            "git_commit": commit,
            "model": asdict(identity),
            "active_baseline": pointer,
            "benchmark": {"path": str(self.cases_path), "sha256": actual_case_hash, **structure},
            "freeze_manifest_sha256": sha256_file(self.manifest_path),
        }

    def _generate_condition(
        self,
        *,
        condition: str,
        active_source: str,
        investigation: dict[str, Any],
        observable: list[dict[str, Any]],
        unstructured_memory: dict[str, Any],
        structural: dict[str, Any] | None,
        cycle_id: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"condition": condition, "status": "generation_started"}
        proposal_system = (
            "You are the bounded research component of an SToE-guided self-developing agent. "
            "Infer only from supplied source and evidence. Treat changes as falsifiable engineering hypotheses, not proof of SToE."
        )
        proposal_prompt = self.supervisor._proposal_prompt(
            active_source,
            investigation,
            observable_diagnostics=observable,
            unstructured_memory=unstructured_memory,
            structural_context=structural,
        )
        try:
            proposal, proposal_trace = self.supervisor.model_client.generate_json(
                system=proposal_system,
                prompt=proposal_prompt,
                schema=self.supervisor.proposal_schema,
                max_output_tokens=PROPOSAL_MAX_TOKENS,
                seed=PROPOSAL_SEED,
                context_sections={
                    "task_context": active_source,
                    "retrieved_material": json.dumps(
                        {"unstructured_memory": unstructured_memory, "typed_overlay": structural},
                        sort_keys=True,
                    ),
                    "tool_results": json.dumps(observable, sort_keys=True),
                },
            )
            result.update({"proposal": proposal, "proposal_trace": proposal_trace})
            self.supervisor._validate_proposal(proposal, investigation)
        except Exception as exc:
            result.update(
                {
                    "status": "proposal_failed",
                    "failure_stage": "proposal",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return result
        generation_system = (
            "Generate one deterministic declarative selection policy as JSON data. Return JSON only. "
            "Do not emit Python, expressions, templates, executable strings, paths, or external resource names."
        )
        generation_prompt = self.supervisor._generation_prompt(
            active_source,
            investigation,
            proposal,
            observable_diagnostics=observable,
            unstructured_memory=unstructured_memory,
            structural_context=structural,
        )
        try:
            generated, generation_trace = self.supervisor.model_client.generate_json(
                system=generation_system,
                prompt=generation_prompt,
                schema=self.supervisor.candidate_policy_schema,
                max_output_tokens=POLICY_MAX_TOKENS,
                seed=POLICY_SEED,
                context_sections={
                    "task_context": active_source + json.dumps(proposal, sort_keys=True),
                    "retrieved_material": json.dumps(
                        {"unstructured_memory": unstructured_memory, "typed_overlay": structural},
                        sort_keys=True,
                    ),
                    "tool_results": json.dumps(observable, sort_keys=True),
                },
            )
            result["generation_trace"] = generation_trace
        except Exception as exc:
            result.update(
                {
                    "status": "policy_generation_failed",
                    "failure_stage": "policy_generation",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return result
        policy = generated.get("policy")
        gate = validate_policy(policy)
        path = self.supervisor.config.runtime_dir / f"candidate_{cycle_id}_{condition.lower()}.policy.json"
        self.supervisor._atomic_write_json(
            path, policy if isinstance(policy, dict) else {"invalid_policy_value": repr(policy)[:1000]}
        )
        result.update({
            "status": "generated",
            "implementation_note": generated.get("implementation_note", ""),
            "policy": policy,
            "policy_path": str(path),
            "policy_sha256": sha256_file(path),
            "policy_validation": {
                "passed": gate.passed,
                "errors": list(gate.errors),
                "estimated_operations": gate.estimated_operations,
            },
        })
        return result

    @staticmethod
    def _case_metrics(evaluation: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
        by_name = {item["name"]: item for item in evaluation.get("results", [])}
        target_names = [case["name"] for case in cases if case["targeted_changed_constraint"]]
        control_names = [case["name"] for case in cases if not case["targeted_changed_constraint"]]
        passed = set(evaluation.get("passed_cases", []))
        return {
            "targeted_pass_count": len(passed.intersection(target_names)),
            "targeted_case_count": len(target_names),
            "control_pass_count": len(passed.intersection(control_names)),
            "control_case_count": len(control_names),
            "total_pass_count": evaluation.get("pass_count", 0),
            "case_count": evaluation.get("case_count", 0),
            "by_family": {
                case["family"]: bool(by_name.get(case["name"], {}).get("passed", False))
                for case in cases
            },
        }

    def run(self, *, allow_generation: bool) -> dict[str, Any]:
        if not allow_generation:
            raise RuntimeError("local model generation requires explicit --allow-generation")
        preflight = self.preflight(require_clean=True)
        action_id = self.spec["action_id"]
        started_action = self.supervisor.research_state.begin_action(
            action_id=action_id,
            description="One frozen paired ordinary-versus-bounded-typed-structure development cycle.",
        )
        if not started_action.get("started"):
            return {
                "decision": "SKIP_COMPLETED_ACTION"
                if started_action.get("duplicate_completed")
                else "RECONCILIATION_REQUIRED",
                "action_id": action_id,
                "model_calls": 0,
            }
        pre_checkpoint = self.supervisor.research_state.checkpoint(
            reason=f"Before frozen paired model action {action_id}"
        )
        started = time.perf_counter()
        cycle_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_structural_v1"
        active_path = Path(preflight["active_baseline"]["source_path"])
        active_source = active_path.read_text(encoding="utf-8")
        active_public = self.supervisor._evaluate_public(active_path)
        component = self.supervisor.journal.add_ip(
            cycle_id=cycle_id,
            label="paired_experiment_active_component",
            content=f"Frozen paired experiment targets active selector {preflight['active_baseline']['version']}.",
            kind="component",
            outcome="active",
            metadata={"source_sha256": preflight["active_baseline"]["sha256"]},
        )
        investigation = investigate_selector(
            public_evaluation=active_public,
            journal=self.supervisor.journal,
            cycle_id=cycle_id,
            component_ref=component["ref"],
        )
        observable = observable_diagnostics(investigation)
        unstructured_memory, structural = bounded_field_contexts(investigation)
        unstructured_hash = _sha256_json(unstructured_memory)
        structural_hash = _sha256_json(structural)
        structural_ip = self.supervisor.journal.add_ip(
            cycle_id=cycle_id,
            label="frozen_bounded_typed_structural_context",
            content=(
                f"Bounded typed structural treatment {structural_hash} contains "
                f"{len(structural['records'])} records under {STRUCTURAL_CONTEXT_CHAR_CAP} characters."
            ),
            kind="retrieval_context",
            origin="runtime_reasoning",
            outcome="untested",
            metadata={"sha256": structural_hash, "context": structural},
        )
        conditions: dict[str, dict[str, Any]] = {}
        for condition in self.spec["condition_order"]:
            treatment = structural if condition == "BOUNDED_TYPED_STOE" else None
            conditions[condition] = self._generate_condition(
                condition=condition,
                active_source=active_source,
                investigation=investigation,
                observable=observable,
                unstructured_memory=unstructured_memory,
                structural=treatment,
                cycle_id=cycle_id,
            )

        if sha256_file(self.cases_path) != self.spec["benchmark"]["sha256"]:
            raise RuntimeError("frozen cases changed before evaluation")
        cases = json.loads(self.cases_path.read_text(encoding="utf-8"))
        assert_no_hidden_identifiers(conditions, cases)

        active_eval = self.supervisor._evaluate_cases(active_path, self.cases_path)
        active_metrics = self._case_metrics(active_eval, cases)
        for condition, result in conditions.items():
            if result.get("status") != "generated" or not result["policy_validation"]["passed"]:
                result["public_evaluation"] = {"status": "not_run", "pass_count": 0, "case_count": 3}
                result["frozen_evaluation"] = {"status": "not_run", "pass_count": 0, "case_count": 12, "results": []}
                result["metrics"] = self._case_metrics(result["frozen_evaluation"], cases)
                result["public_gate"] = {"decision": "REJECT", "reason": "generation or policy validation failed"}
                result["acceptance"] = {"decision": "REJECT", "reason": "generation or policy validation failed"}
                continue
            policy_path = Path(result["policy_path"])
            result["public_evaluation"] = self.supervisor._evaluate_public(
                policy_path, artifact_type="declarative_policy"
            )
            result["frozen_evaluation"] = self.supervisor._evaluate_cases(
                policy_path, self.cases_path, artifact_type="declarative_policy"
            )
            result["metrics"] = self._case_metrics(result["frozen_evaluation"], cases)
            result["public_gate"] = self.supervisor._public_behavioral_improvement_decision(
                investigation, result["public_evaluation"]
            )
            result["acceptance"] = self.supervisor._acceptance_decision(
                active_eval, result["frozen_evaluation"]
            )

        ordinary = conditions["ORDINARY_OBSERVABLE"]["metrics"]
        stoe = conditions["BOUNDED_TYPED_STOE"]["metrics"]
        primary_difference = stoe["targeted_pass_count"] - ordinary["targeted_pass_count"]
        success_criterion = (
            primary_difference >= self.spec["analysis"]["minimum_targeted_advantage_cases"]
            and stoe["control_pass_count"] >= ordinary["control_pass_count"]
        )
        eligible, winner = select_unique_winner(conditions)

        activation = None
        if winner is not None:
            source = Path(conditions[winner]["policy_path"])
            version = f"generated_{cycle_id}_{winner.lower()}"
            destination = self.supervisor.config.component_dir / "versions" / f"{version}.policy.json"
            shutil.copy2(source, destination)
            candidate_ip = self.supervisor.journal.add_ip(
                cycle_id=cycle_id,
                label=f"{winner.lower()}_candidate",
                content=f"Paired condition {winner} generated inert policy {sha256_file(destination)}.",
                kind="implementation",
                outcome="supported",
                metadata={"condition": winner, "source_sha256": sha256_file(destination)},
            )
            if winner == "BOUNDED_TYPED_STOE":
                self.supervisor.journal.relate(
                    candidate_ip["ref"], structural_ip["ref"], "generated_with", "Condition received bounded typed structural evidence"
                )
            activation = self.supervisor._activate(
                version=version,
                source_path=destination,
                cycle_id=cycle_id,
                candidate_ref=candidate_ip["ref"],
                artifact_type="declarative_policy",
            )

        report = {
            "experiment_id": self.spec["experiment_id"],
            "classification": "single_frozen_paired_pipeline_intervention_on_unseen_cases",
            "action_id": action_id,
            "cycle_id": cycle_id,
            "preflight": preflight,
            "pre_action_checkpoint": pre_checkpoint,
            "model_call_budget": {"per_condition": 2, "total": 4, "retries": 0},
            "independent_variable": self.spec["independent_variable"],
            "observable_context_sha256": _sha256_json(observable),
            "unstructured_memory": unstructured_memory,
            "unstructured_memory_sha256": unstructured_hash,
            "structural_context": structural,
            "structural_context_sha256": structural_hash,
            "conditions": conditions,
            "active_frozen_evaluation": active_eval,
            "active_metrics": active_metrics,
            "primary": {
                "ordinary_targeted_pass_count": ordinary["targeted_pass_count"],
                "stoe_targeted_pass_count": stoe["targeted_pass_count"],
                "absolute_difference_cases": primary_difference,
                "minimum_advantage_cases": self.spec["analysis"]["minimum_targeted_advantage_cases"],
                "success_criterion_met": success_criterion,
                "interpretation": "paired pipeline intervention; not proof of universal SToE superiority",
            },
            "eligible_conditions": eligible,
            "winner": winner,
            "activation": activation,
            "activated": bool(activation and activation.get("activated")),
            "decision": (
                f"ACTIVATE_{winner}" if activation and activation.get("activated") else "NO_ACTIVATION"
            ),
            "elapsed_seconds": time.perf_counter() - started,
            "model_calls": sum(
                int("proposal_trace" in result) + int("generation_trace" in result)
                for result in conditions.values()
            ),
            "frozen_case_hash_after": sha256_file(self.cases_path),
        }
        results_dir = self.root / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        report_path = results_dir / f"{cycle_id}.json"
        self.supervisor._atomic_write_json(report_path, report)
        self._record_state_and_artifacts(report, report_path, structural_ip)
        return report

    def _record_state_and_artifacts(
        self, report: dict[str, Any], report_path: Path, structural_ip: dict[str, Any]
    ) -> None:
        action_id = report["action_id"]
        for condition, result in report["conditions"].items():
            if result.get("status") != "generated":
                continue
            evaluation_ip = self.supervisor.journal.record_evaluation(
                candidate_ref=structural_ip["ref"],
                content=(
                    f"Frozen paired condition {condition}: targeted "
                    f"{result['metrics']['targeted_pass_count']}/{result['metrics']['targeted_case_count']}, "
                    f"controls {result['metrics']['control_pass_count']}/{result['metrics']['control_case_count']}."
                ),
                outcome="supported" if result["acceptance"].get("decision") == "ACCEPT" else "rejected",
                metadata={"condition": condition, "metrics": result["metrics"]},
            )
            if condition == "BOUNDED_TYPED_STOE":
                self.supervisor.journal.relate(
                    evaluation_ip["evaluation"]["ref"],
                    structural_ip["ref"],
                    "evaluates_use_of",
                    "Evaluation follows the structural-context intervention",
                )
        state = self.supervisor.research_state.load()
        state["current_task"] = "Frozen paired structural-input experiment completed."
        state["next_executable_step"] = (
            "Review the frozen paired result and its complete prompts before deciding whether replication or a revised hypothesis is justified."
        )
        self.supervisor.research_state.save(state)
        self.supervisor.research_state.set_action_status(
            action_id=action_id,
            status="completed",
            result_refs=[report_path.relative_to(self.supervisor.config.repo_root).as_posix()],
        )
        report["continuity_checkpoint"] = self.supervisor.checkpoint_research_state(
            f"After frozen paired structural-input experiment {action_id}"
        )
        self.supervisor._atomic_write_json(report_path, report)
        self.supervisor.research_state.register_artifact(
            ref="structural_input_experiment_v1_results",
            path=report_path,
            summary="Complete paired ordinary-versus-bounded-typed-structure prompts, traces, policies, unseen-case evaluations, and activation decision.",
            kind="experiment_result",
            provenance="frozen_paired_local_ollama_experiment",
            source_refs=["continuity_reconciliation_report"],
        )
        self.supervisor.research_state.checkpoint(
            reason="Registered immutable structural-input experiment result artifact"
        )
