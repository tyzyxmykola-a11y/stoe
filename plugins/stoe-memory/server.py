from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from core import FieldStore


server = MCPServer(
    name="stoe_memory",
    title="SToE Persistent Reasoning Field",
    description=(
        "Local observer-aware memory for reasoning IPs, failures, evaluations, state changes, "
        "typed directed relations, bounded navigation traces, and counterfactual contexts."
    ),
    instructions=(
        "Use this field only for nonlinear work where preserved reasoning may matter later. "
        "Create a CurrentObserverStateIP before navigation. Do not expose the entire canonical seed."
    ),
    version="0.1.0",
)
store = FieldStore()
store.initialize()


@server.tool(name="stoe_field_status", title="Inspect SToE field", structured_output=True)
def stoe_field_status() -> dict[str, Any]:
    """Return local database, field counts, latest observer state, and canonical-seed identity."""
    return store.status()


@server.tool(name="stoe_add_ip", title="Add reasoning IP", structured_output=True)
def stoe_add_ip(
    content: str,
    kind: str,
    origin: str = "runtime_reasoning",
    outcome: str = "unknown",
    failure_condition: str = "",
    session_id: str = "default",
    visible: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a substantive reasoning artifact, including failed hypotheses and provenance."""
    return store.add_ip(
        content=content,
        kind=kind,
        origin=origin,
        outcome=outcome,
        failure_condition=failure_condition,
        session_id=session_id,
        visible=visible,
        metadata=metadata,
    )


@server.tool(name="stoe_add_relation", title="Add typed relation", structured_output=True)
def stoe_add_relation(
    source_ref: str,
    target_ref: str,
    relation: str,
    weight: float = 1.0,
    note: str = "",
) -> dict[str, Any]:
    """Connect two field IPs with an explicit directed relation and provenance note."""
    return store.add_relation(
        source_ref=source_ref,
        target_ref=target_ref,
        relation=relation,
        weight=weight,
        note=note,
    )


@server.tool(name="stoe_set_observer_state", title="Set observer state", structured_output=True)
def stoe_set_observer_state(
    goal: str,
    question: str = "",
    active_constraints: list[str] | None = None,
    changed_constraints: list[str] | None = None,
    evidence: list[str] | None = None,
    open_questions: list[str] | None = None,
    invalidates_refs: list[str] | None = None,
    recent_refs: list[str] | None = None,
    current_reasoning_ref: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Create a CurrentObserverStateIP in the field and connect explicit state changes and recent IPs."""
    return store.set_observer_state(
        goal=goal,
        question=question,
        active_constraints=active_constraints,
        changed_constraints=changed_constraints,
        evidence=evidence,
        open_questions=open_questions,
        invalidates_refs=invalidates_refs,
        recent_refs=recent_refs,
        current_reasoning_ref=current_reasoning_ref,
        session_id=session_id,
    )


@server.tool(name="stoe_record_evaluation", title="Record evaluation", structured_output=True)
def stoe_record_evaluation(
    evaluates_ref: str,
    content: str,
    outcome: str,
    session_id: str = "default",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist an EvaluationIP linked to the result or reasoning IP it evaluates."""
    return store.record_evaluation(
        evaluates_ref=evaluates_ref,
        content=content,
        outcome=outcome,
        session_id=session_id,
        metadata=metadata,
    )


@server.tool(name="stoe_navigate", title="Navigate reasoning field", structured_output=True)
def stoe_navigate(
    observer_state_ref: str,
    limit: int = 4,
    max_depth: int = 4,
    include_failures: bool = True,
    include_seed: bool = True,
    per_item_chars: int = 1500,
    total_chars: int = 5000,
) -> dict[str, Any]:
    """Select bounded model-visible IPs using normalized direction-aware observer-state topology."""
    return store.navigate(
        observer_state_ref=observer_state_ref,
        limit=limit,
        max_depth=max_depth,
        include_failures=include_failures,
        include_seed=include_seed,
        per_item_chars=per_item_chars,
        total_chars=total_chars,
    )


@server.tool(name="stoe_get_retrieval_trace", title="Read retrieval trace", structured_output=True)
def stoe_get_retrieval_trace(run_id: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    """Read a paginated candidate-level trace with paths, directions, components, and selection reasons."""
    return store.get_retrieval_trace(run_id=run_id, offset=offset, limit=limit)


@server.tool(name="stoe_prepare_counterfactual_contexts", title="Prepare counterfactual contexts", structured_output=True)
def stoe_prepare_counterfactual_contexts(
    observer_state_ref: str,
    focal_ip_ref: str,
    limit: int = 4,
    max_depth: int = 4,
    include_seed: bool = True,
) -> dict[str, Any]:
    """Retrieve paired WITH_IP and WITHOUT_IP contexts; final causal classification still requires replay."""
    return store.prepare_counterfactual_contexts(
        observer_state_ref=observer_state_ref,
        focal_ip_ref=focal_ip_ref,
        limit=limit,
        max_depth=max_depth,
        include_seed=include_seed,
    )


@server.tool(name="stoe_get_ip", title="Inspect reasoning IP", structured_output=True)
def stoe_get_ip(ref: str) -> dict[str, Any]:
    """Return one IP and its bounded incident-edge list."""
    return store.get_ip(ref)


@server.tool(name="stoe_list_recent", title="List recent reasoning IPs", structured_output=True)
def stoe_list_recent(session_id: str = "default", limit: int = 20) -> dict[str, Any]:
    """List recent IPs for one session without searching or dumping the complete field."""
    return store.list_recent(session_id=session_id, limit=limit)


if __name__ == "__main__":
    server.run(transport="stdio")
