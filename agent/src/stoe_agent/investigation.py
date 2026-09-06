from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .field_journal import RebuildJournal, SESSION_ID
from .selector_loader import Selector, validate_selection


@dataclass(frozen=True)
class DiagnosticCase:
    name: str
    observer: dict[str, Any]
    items: list[dict[str, Any]]
    max_items: int
    max_chars: int
    required_refs: tuple[str, ...]
    forbidden_refs: tuple[str, ...] = ()
    invalidated_failure_refs: tuple[str, ...] = ()


def public_diagnostics() -> tuple[DiagnosticCase, ...]:
    """Observable probes used to investigate v1, not to accept a successor."""
    return (
        DiagnosticCase(
            name="raised_storage_ceiling",
            observer={
                "goal": "Choose the research-agent architecture now that the storage ceiling changed",
                "active_constraints": ["preserve rejected reasoning", "keep active context bounded"],
                "changed_constraints": [
                    "storage ceiling increased from one gigabyte to one hundred gigabytes"
                ],
                "evidence": ["cold history can remain outside the active prompt"],
                "open_questions": ["Which formerly rejected design is newly feasible?"],
            },
            items=[
                {
                    "ref": "DIAG_STORAGE_FAILED",
                    "content": "Partitioned cold provenance retains rejected hypotheses outside active context.",
                    "origin": "failure_history",
                    "kind": "hypothesis",
                    "outcome": "rejected",
                    "failure_condition": "A one gigabyte storage ceiling made partitioned history infeasible.",
                    "created_order": 1,
                },
                {
                    "ref": "DIAG_STORAGE_DISTRACTOR",
                    "content": "Choose the current research-agent architecture by reviewing current architecture notes.",
                    "origin": "runtime_reasoning",
                    "kind": "plan",
                    "outcome": "untested",
                    "failure_condition": "",
                    "created_order": 3,
                },
                {
                    "ref": "DIAG_STORAGE_EVAL",
                    "content": "A compact success-only cache was fast but lost rejected-path provenance.",
                    "origin": "evaluation",
                    "kind": "evaluation",
                    "outcome": "supported",
                    "failure_condition": "",
                    "created_order": 2,
                },
            ],
            max_items=1,
            max_chars=240,
            required_refs=("DIAG_STORAGE_FAILED",),
            forbidden_refs=("DIAG_STORAGE_DISTRACTOR",),
            invalidated_failure_refs=("DIAG_STORAGE_FAILED",),
        ),
        DiagnosticCase(
            name="unchanged_offline_constraint",
            observer={
                "goal": "Choose a semantic evidence index for the research project",
                "active_constraints": ["network access remains unavailable"],
                "changed_constraints": [],
                "evidence": ["local embedding inference is installed"],
                "open_questions": ["Which currently feasible index should be used?"],
            },
            items=[
                {
                    "ref": "DIAG_OFFLINE_FAILED",
                    "content": "Use a semantic evidence index hosted by a remote vector service.",
                    "origin": "failure_history",
                    "kind": "hypothesis",
                    "outcome": "rejected",
                    "failure_condition": "Requires network access.",
                    "created_order": 4,
                },
                {
                    "ref": "DIAG_OFFLINE_LOCAL",
                    "content": "Build an on-device embedding index with the installed local model.",
                    "origin": "runtime_reasoning",
                    "kind": "hypothesis",
                    "outcome": "supported",
                    "failure_condition": "",
                    "created_order": 3,
                },
                {
                    "ref": "DIAG_OFFLINE_GENERIC",
                    "content": "Review the research project evidence before deciding.",
                    "origin": "runtime_reasoning",
                    "kind": "plan",
                    "outcome": "untested",
                    "failure_condition": "",
                    "created_order": 5,
                },
            ],
            max_items=1,
            max_chars=220,
            required_refs=("DIAG_OFFLINE_LOCAL",),
            forbidden_refs=("DIAG_OFFLINE_FAILED",),
        ),
        DiagnosticCase(
            name="measured_evidence",
            observer={
                "goal": "Decide which retrieval strategy has measured recovery evidence",
                "active_constraints": ["prefer observed matched-condition evidence over an untested proposal"],
                "changed_constraints": [],
                "evidence": ["evaluation results are available"],
                "open_questions": ["Which IP reports an observed comparison?"],
            },
            items=[
                {
                    "ref": "DIAG_EVIDENCE_EVAL",
                    "content": "Matched-condition evaluation measured recovery on six constraint-change probes.",
                    "origin": "evaluation",
                    "kind": "evaluation",
                    "outcome": "supported",
                    "failure_condition": "",
                    "created_order": 6,
                },
                {
                    "ref": "DIAG_EVIDENCE_IDEA",
                    "content": "A retrieval strategy might provide measured recovery evidence in future work.",
                    "origin": "runtime_reasoning",
                    "kind": "hypothesis",
                    "outcome": "untested",
                    "failure_condition": "",
                    "created_order": 7,
                },
                {
                    "ref": "DIAG_EVIDENCE_OLD",
                    "content": "An earlier design note discusses tokenization and caching.",
                    "origin": "runtime_reasoning",
                    "kind": "observation",
                    "outcome": "superseded",
                    "failure_condition": "",
                    "created_order": 2,
                },
            ],
            max_items=1,
            max_chars=220,
            required_refs=("DIAG_EVIDENCE_EVAL",),
        ),
    )


def evaluate_public_selector(selector: Selector) -> dict[str, Any]:
    """Run the disclosed diagnostic contract without writing to the field."""
    results: list[dict[str, Any]] = []
    for case in public_diagnostics():
        selected: list[str] = []
        deterministic = False
        error = ""
        try:
            first = validate_selection(
                selector(case.observer, case.items, case.max_items, case.max_chars),
                case.items,
                case.max_items,
                case.max_chars,
            )
            second = validate_selection(
                selector(case.observer, case.items, case.max_items, case.max_chars),
                case.items,
                case.max_items,
                case.max_chars,
            )
            selected = first
            deterministic = first == second
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        passed = (
            deterministic
            and set(case.required_refs).issubset(selected)
            and not set(case.forbidden_refs).intersection(selected)
        )
        results.append(
            {
                "case": case.name,
                "selected": selected,
                "required_refs": list(case.required_refs),
                "forbidden_refs": list(case.forbidden_refs),
                "deterministic": deterministic,
                "passed": passed,
                "error": error,
            }
        )
    return {
        "status": "completed",
        "failure_kind": "",
        "case_count": len(results),
        "pass_count": sum(1 for item in results if item["passed"]),
        "passed_cases": [item["case"] for item in results if item["passed"]],
        "results": results,
    }


def investigate_selector(
    *,
    public_evaluation: dict[str, Any],
    journal: RebuildJournal,
    cycle_id: str,
    component_ref: str,
) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    observed_failure_refs: list[str] = []
    public_results = {item["case"]: item for item in public_evaluation.get("results", [])}

    for case in public_diagnostics():
        item_ips: dict[str, dict[str, Any]] = {}
        failure_constraints: dict[str, str] = {}
        for item in case.items:
            ip = journal.add_ip(
                cycle_id=cycle_id,
                label=f"{case.name}_{item['ref']}",
                content=str(item["content"]),
                kind=str(item["kind"]),
                origin=str(item["origin"]),
                outcome=str(item["outcome"]),
                failure_condition=str(item["failure_condition"]),
                metadata={"diagnostic_case": case.name, "external_ref": item["ref"]},
            )
            item_ips[str(item["ref"])] = ip
            journal.relate(ip["ref"], component_ref, "available_to", "Diagnostic item available to selector")
            if item["failure_condition"]:
                constraint = journal.add_ip(
                    cycle_id=cycle_id,
                    label=f"{case.name}_{item['ref']}_constraint",
                    content=str(item["failure_condition"]),
                    kind="constraint",
                    outcome=(
                        "invalidated" if item["ref"] in case.invalidated_failure_refs else "active"
                    ),
                    metadata={"diagnostic_case": case.name, "for_failure_ref": item["ref"]},
                )
                failure_constraints[str(item["ref"])] = constraint["ref"]
                journal.relate(ip["ref"], constraint["ref"], "rejected_by", "Recorded rejection basis")

        state = journal.store.set_observer_state(
            goal=str(case.observer["goal"]),
            question="Which prior reasoning IP should enter the bounded research context?",
            active_constraints=list(case.observer["active_constraints"]),
            changed_constraints=list(case.observer["changed_constraints"]),
            evidence=list(case.observer["evidence"]),
            open_questions=list(case.observer["open_questions"]),
            invalidates_refs=[
                failure_constraints[ref]
                for ref in case.invalidated_failure_refs
                if ref in failure_constraints
            ],
            recent_refs=[ip["ref"] for ip in item_ips.values()],
            current_reasoning_ref=component_ref,
            session_id=SESSION_ID,
        )

        public_result = public_results.get(
            case.name,
            {
                "selected": [],
                "passed": False,
                "deterministic": False,
                "error": public_evaluation.get("error", "public diagnostic child returned no case result"),
            },
        )
        selected = list(public_result["selected"])
        passed = bool(public_result["passed"])
        result_ip = journal.add_ip(
            cycle_id=cycle_id,
            label=f"{case.name}_observed_result",
            content=f"Diagnostic {case.name}: selector returned {selected}; required {list(case.required_refs)}.",
            kind="result",
            outcome="supported" if passed else "failed",
            origin="evaluation",
            failure_condition=(
                "Observed selection violated the diagnostic relevance contract." if not passed else ""
            ),
            metadata={"diagnostic_case": case.name, "selected": selected, "passed": passed},
        )
        journal.relate(result_ip["ref"], component_ref, "generated_by", "Observed behavior of active selector")
        for external_ref in selected:
            journal.relate(result_ip["ref"], item_ips[external_ref]["ref"], "selected", "Selector chose this IP")

        missed = [ref for ref in case.required_refs if ref not in selected]
        if missed:
            failure_ip = journal.add_ip(
                cycle_id=cycle_id,
                label=f"{case.name}_missed_connection",
                content=(
                    f"In {case.name}, the selector missed required IPs {missed} and returned {selected}. "
                    "The exact implementation cause remains a hypothesis until related to source and traces."
                ),
                kind="observation",
                origin="failure_history",
                outcome="failed",
                failure_condition="The active selector did not satisfy the public diagnostic relevance contract.",
                metadata={"diagnostic_case": case.name, "missed": missed, "selected": selected},
            )
            observed_failure_refs.append(failure_ip["ref"])
            journal.relate(failure_ip["ref"], result_ip["ref"], "derived_from", "Failure is grounded in observed output")
            journal.relate(failure_ip["ref"], component_ref, "implicates", "Observed miss implicates active selector")
            for external_ref in missed:
                journal.relate(
                    failure_ip["ref"],
                    item_ips[external_ref]["ref"],
                    "missed_connection",
                    "Required item was available but absent from output",
                )

        navigation = journal.store.navigate(
            observer_state_ref=state["observer_state_ref"],
            limit=6,
            max_depth=4,
            include_failures=True,
            include_seed=True,
            per_item_chars=700,
            total_chars=3500,
            run_label="self_investigation_observer_aware",
        )
        trace = journal.store.get_retrieval_trace(run_id=navigation["run_id"], limit=100)
        external_by_internal = {ip["ref"]: external for external, ip in item_ips.items()}
        navigator_external = [
            external_by_internal[ref]
            for ref in navigation["selected_refs"]
            if ref in external_by_internal
        ]
        candidate_trace = []
        for candidate in trace["candidate_page"]:
            if candidate["candidate_ip"] in external_by_internal:
                candidate_trace.append(
                    {
                        "external_ref": external_by_internal[candidate["candidate_ip"]],
                        "selected": candidate["selected"],
                        "edge_types": candidate["edge_types"],
                        "edge_directions": candidate["edge_directions"],
                        "path": candidate["path"],
                        "scores": {
                            "structural": candidate["structural_score"],
                            "goal": candidate["goal_relevance_score"],
                            "state_change": candidate["state_change_score"],
                            "failure": candidate["failure_relevance_score"],
                            "final": candidate["final_score"],
                        },
                        "reason": candidate["reason"],
                    }
                )
        observations.append(
            {
                "case": case.name,
                "observer": case.observer,
                "available_refs": [item["ref"] for item in case.items],
                "required_refs": list(case.required_refs),
                "forbidden_refs": list(case.forbidden_refs),
                "selector_selected": selected,
                "selector_passed": passed,
                "missed_refs": missed,
                "navigator_selected_available_refs": navigator_external,
                "navigator_run_id": navigation["run_id"],
                "navigator_candidate_trace": candidate_trace,
            }
        )

    investigation_state = journal.store.set_observer_state(
        goal="Formulate a bounded improvement to the active research-context selector from observed behavior",
        question="What implementation hypothesis best explains and addresses the observed misses?",
        active_constraints=[
            "base claims on observed diagnostics and inspectable source",
            "preserve context budgets and deterministic output",
            "do not expose protected evaluation cases",
            "treat the change as an AI-generated research hypothesis",
        ],
        evidence=[
            f"{sum(1 for item in observations if item['selector_passed'])}/{len(observations)} public diagnostics passed",
            "typed navigator traces record available, selected, and missed connections",
        ],
        open_questions=[
            "Which source behavior explains each miss?",
            "Which observed pattern is general enough to justify a code change?",
            "Will held-out matched evaluation support the hypothesis?",
        ],
        recent_refs=observed_failure_refs,
        current_reasoning_ref=component_ref,
        session_id=SESSION_ID,
    )
    for failure_ref in observed_failure_refs:
        journal.relate(
            investigation_state["observer_state_ref"],
            failure_ref,
            "depends_on",
            "The successor decision depends on this observed diagnostic failure",
        )
    bounded = journal.store.navigate(
        observer_state_ref=investigation_state["observer_state_ref"],
        limit=8,
        max_depth=4,
        include_failures=True,
        include_seed=True,
        per_item_chars=900,
        total_chars=5000,
        run_label="self_investigation_synthesis",
    )
    return {
        "diagnostics": observations,
        "pass_count": sum(1 for item in observations if item["selector_passed"]),
        "case_count": len(observations),
        "observed_failure_refs": observed_failure_refs,
        "synthesis_observer_state_ref": investigation_state["observer_state_ref"],
        "synthesis_navigation_run_id": bounded["run_id"],
        "bounded_prior_context": [
            {
                "ref": item["ref"],
                "origin": item["origin"],
                "kind": item["kind"],
                "outcome": item["outcome"],
                "content": item["content"],
                "path": item["path"],
                "reason": item["reason"],
            }
            for item in bounded["selected_items"]
        ],
        "known_structure": (
            "The source, observer fields, available candidates, actual outputs, typed paths, and failure conditions are observed."
        ),
        "unknown_structure": (
            "The diagnostics do not establish which implementation change will generalize to protected cases; that remains testable."
        ),
        "execution": {
            "status": public_evaluation.get("status", "unknown"),
            "failure_kind": public_evaluation.get("failure_kind", ""),
            "error": public_evaluation.get("error", ""),
            "subprocess": True,
        },
    }
