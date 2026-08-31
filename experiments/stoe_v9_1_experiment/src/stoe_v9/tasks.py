from __future__ import annotations

import json
from pathlib import Path

from .graph import InformationGraph
from .models import InformationPoint, ObserverState, TaskDefinition
from .seed import SeedMode, add_runtime_seed_bridges, load_seed_into_graph


def load_tasks(path: str | Path) -> list[TaskDefinition]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tasks = []
    for raw in data["tasks"]:
        tasks.append(TaskDefinition(**raw))
    if len({task.id for task in tasks}) != len(tasks):
        raise ValueError("duplicate task IDs")
    return tasks


def build_task_graph(task: TaskDefinition, *, seed_mode: SeedMode = "native") -> tuple[InformationGraph, ObserverState]:
    graph = InformationGraph()
    graph.add_node(InformationPoint(
        "IP_00000", f"Task domain for {task.id}", "domain_root", visible=False,
        metadata={"canonical_order": 0, "origin": "runtime_reasoning"},
    ))
    recent_evidence = [task.state_change["content"], task.evaluation["content"]]
    state_content = (
        f"GOAL: {task.goal}\nQUESTION: {task.question}\n"
        f"ACTIVE_CONSTRAINTS: {'; '.join(task.active_constraints)}\n"
        f"CHANGED_CONSTRAINTS: {'; '.join(task.changed_constraints)}\n"
        f"CURRENT_REASONING_REF: IP_00005\n"
        f"RECENT_EVIDENCE: {'; '.join(recent_evidence)}"
    )
    graph.add_node(InformationPoint(
        "IP_00001", state_content, "current_state", visible=False, created_order=100,
        metadata={"canonical_order": 1, "origin": "current_observer_state"},
    ))
    graph.add_node(_node("IP_00002", task.focal, "failed_candidate", 2, "rejected_by", "failure_history"))
    graph.add_node(_node("IP_00003", task.constraint, "constraint", 3, "depends_on", "runtime_reasoning"))
    graph.add_node(_node("IP_00004", task.state_change, "state_change", 4, "invalidates", "state_change"))
    recent_origin = "failure_history" if task.recent.get("outcome") == "failure" else "runtime_reasoning"
    graph.add_node(_node("IP_00005", task.recent, "recent_reasoning", 50, "evolved_from", recent_origin))
    graph.add_node(_node("IP_00006", task.evaluation, "evaluation", 60, "evaluates", "evaluation"))
    for index, item in enumerate(task.distractors, start=7):
        origin = "failure_history" if item.get("outcome") == "failure" else "runtime_reasoning"
        graph.add_node(_node(f"IP_{index:05d}", item, "memory_artifact", 10 + index, item.get("relation", "connected_to"), origin))

    no_useful_provenance = bool(task.metadata.get("no_useful_provenance"))
    if no_useful_provenance:
        graph.add_edge("IP_00001", "IP_00004", "contains")
        graph.add_edge("IP_00004", "IP_00003", "connected_to")
    else:
        graph.add_edge("IP_00001", "IP_00004", "contains_change")
        graph.add_edge("IP_00004", "IP_00003", "invalidates")
    graph.add_edge("IP_00002", "IP_00003", "rejected_by")
    graph.add_edge("IP_00001", "IP_00005", "evolved_from")
    graph.add_edge("IP_00006", "IP_00005", "evaluates")
    graph.add_edge("IP_00001", "IP_00006", "contains")
    for index, _ in enumerate(task.distractors, start=7):
        ref = f"IP_{index:05d}"
        graph.add_edge(ref, "IP_00003", graph.nodes[ref].metadata["relation_context"])
    graph.add_edge("IP_00000", "IP_00001", "session_of")

    if no_useful_provenance:
        graph.edges = [
            edge for edge in graph.edges
            if not (edge.source == "IP_00002" and edge.target == "IP_00003")
        ]
        graph.add_edge("IP_00002", "IP_00000", "session_of")
    load_seed_into_graph(graph, mode=seed_mode)
    add_runtime_seed_bridges(graph, mode=seed_mode)
    target = task.metadata.get("correct_source", "focal")
    task.topology_target_ref = {
        "focal": "IP_00002", "recent": "IP_00005", "evaluation": "IP_00006"
    }.get(target, "IP_00002")
    state = ObserverState(
        ref="IP_00001",
        current_question=task.question,
        current_goal=task.goal,
        active_constraints=list(task.active_constraints),
        changed_constraints=list(task.changed_constraints),
        current_reasoning_ref="IP_00005",
        recent_evidence=recent_evidence,
        traversal_history=["IP_00005", "IP_00006"],
    )
    return graph, state


def _node(ref: str, raw: dict, kind: str, created_order: int, relation: str, origin: str) -> InformationPoint:
    return InformationPoint(
        ref=ref,
        content=str(raw["content"]),
        kind=kind,
        outcome=str(raw.get("outcome", "unknown")),
        visible=bool(raw.get("visible", True)),
        created_order=created_order,
        metadata={
            "canonical_order": int(ref.split("_")[-1]),
            "relation_context": relation,
            "origin": origin,
        },
    )
