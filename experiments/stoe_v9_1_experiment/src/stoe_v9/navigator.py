from __future__ import annotations

import math
import re
from dataclasses import asdict

from .graph import InformationGraph
from .models import CandidateTrace, ObserverState, RetrievalResult


EDGE_STRENGTH = {
    "contains_change": 0.95,
    "invalidates": 1.00,
    "rejected_by": 0.92,
    "evaluates": 0.82,
    "evolved_from": 0.88,
    "contradicts": 0.90,
    "depends_on": 0.78,
    "connected_to": 0.55,
    "contains": 0.35,
    "session_of": 0.25,
    "generated_by": 0.75,
    "synergy_with": 0.75,
    "instantiates": 0.70,
    "applies_core": 0.70,
    "unfolds_to": 0.30,
    "shares_field_with": 0.20,
}

DIRECTION_WEIGHT = {
    "contains_change": {"outgoing": 1.0, "incoming": 0.45},
    "invalidates": {"outgoing": 1.0, "incoming": 0.65},
    "rejected_by": {"outgoing": 0.45, "incoming": 1.0},
    "evaluates": {"outgoing": 1.0, "incoming": 0.75},
    # CurrentState --evolved_from--> PriorReasoning: outgoing traversal follows
    # the recorded local branch; reverse traversal asks for a later state.
    "evolved_from": {"outgoing": 1.0, "incoming": 0.65},
    "contradicts": {"outgoing": 1.0, "incoming": 1.0},
    "depends_on": {"outgoing": 1.0, "incoming": 0.70},
    "connected_to": {"outgoing": 0.70, "incoming": 0.70},
    "generated_by": {"outgoing": 1.0, "incoming": 0.65},
    "synergy_with": {"outgoing": 0.90, "incoming": 0.90},
    "instantiates": {"outgoing": 1.0, "incoming": 0.55},
    "applies_core": {"outgoing": 1.0, "incoming": 0.55},
    "unfolds_to": {"outgoing": 1.0, "incoming": 0.50},
    "shares_field_with": {"outgoing": 0.50, "incoming": 0.50},
}

PATH_DECAY = 0.65
EXTRA_HOP_PENALTY = 0.18
_TOKENS = re.compile(r"[a-z0-9]+")


def token_set(text: str) -> set[str]:
    return set(_TOKENS.findall(text.lower()))


def token_relevance(left: str, right: str) -> float:
    a, b = token_set(left), token_set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def direction_weight(relation: str, direction: str) -> float:
    return DIRECTION_WEIGHT.get(relation, {}).get(direction, 0.60)


def structural_score(path: list[dict]) -> float:
    if not path:
        return 0.0
    numerator = 0.0
    denominator = 0.0
    for index, step in enumerate(path):
        decay = PATH_DECAY ** index
        numerator += decay * EDGE_STRENGTH.get(step["type"], 0.25) * direction_weight(
            step["type"], step["direction"]
        )
        denominator += decay
    normalized = numerator / denominator
    return normalized / (1.0 + EXTRA_HOP_PENALTY * (len(path) - 1))


def best_structural_path(paths: list[list[dict]]) -> tuple[list[dict], float]:
    ranked = sorted(
        ((path, structural_score(path)) for path in paths),
        key=lambda item: (-item[1], len(item[0]), tuple(step["to"] for step in item[0])),
    )
    return ranked[0]


class QueryBlindNavigator:
    def __init__(self, graph: InformationGraph):
        self.graph = graph

    def select(self, state: ObserverState, *, limit: int, include_failures: bool = True) -> RetrievalResult:
        paths = self.graph.reachable_paths(state.ref, max_depth=4)
        eligible = set(self.graph.eligible_refs(include_failures=include_failures))
        traces: list[CandidateTrace] = []
        for ref in sorted(paths):
            path, score = best_structural_path(paths[ref])
            node = self.graph.nodes[ref]
            is_eligible = ref in eligible
            # Preserve the v8 control's query-blind current-branch locality bias.
            # This is a fixed, non-semantic term: it depends only on the observer's
            # recorded current reasoning position, never on task text or outcome.
            locality_bonus = 0.50 if ref == state.current_reasoning_ref else 0.0
            final_score = score + locality_bonus
            traces.append(CandidateTrace(
                current_state_ip=state.ref,
                candidate_ip=ref,
                path=path,
                edge_directions=[step["direction"] for step in path],
                edge_types=[step["type"] for step in path],
                structural_score=score,
                goal_relevance_score=0.0,
                state_change_score=0.0,
                provenance_relevance_score=0.0,
                failure_relevance_score=0.0,
                distance_penalty=max(0, len(path) - 1) / 4,
                redundancy_penalty=0.0,
                stale_locality_penalty=0.0,
                final_score=final_score,
                eligible=is_eligible,
                selected=False,
                reason=(
                    f"query-blind structural locality; depth={len(path)} "
                    f"structural={score:.6f}; current_branch_bonus={locality_bonus:.2f}; "
                    f"final={final_score:.6f}"
                ),
                canonical_tie_key=ref,
                origin=str(node.metadata.get("origin", "runtime_reasoning")),
            ))
        ranked = sorted(
            (trace for trace in traces if trace.eligible),
            key=lambda trace: (-trace.final_score, trace.candidate_ip),
        )
        chosen = ranked[:limit]
        for trace in chosen:
            trace.selected = True
        return RetrievalResult(
            refs=[trace.candidate_ip for trace in chosen],
            method="query_blind_topology",
            scores=[trace.final_score for trace in chosen],
            traces=traces,
            realized_artifact_count=len(chosen),
        )


class ObserverAwareNavigator:
    def __init__(self, graph: InformationGraph):
        self.graph = graph

    def select(
        self,
        state: ObserverState,
        *,
        limit: int,
        include_failures: bool = True,
        use_state_change: bool = True,
        use_query_relevance: bool = True,
    ) -> RetrievalResult:
        paths = self.graph.reachable_paths(state.ref, max_depth=4)
        eligible = set(self.graph.eligible_refs(include_failures=include_failures))
        provisional: list[CandidateTrace] = []
        observer_text = state.relevance_text()
        for ref in sorted(paths):
            path, structural = best_structural_path(paths[ref])
            node = self.graph.nodes[ref]
            edge_types = [step["type"] for step in path]
            change_chain = "invalidates" in edge_types and "rejected_by" in edge_types
            direct_change = "contains_change" in edge_types or "invalidates" in edge_types
            state_change = (1.0 if change_chain else 0.55 if direct_change else 0.0) if use_state_change else 0.0
            provenance = 1.0 if change_chain else 0.5 if any(
                item in edge_types for item in ("invalidates", "evaluates", "depends_on")
            ) else 0.0
            failure = 1.0 if use_state_change and change_chain and node.outcome == "failure" else 0.0
            goal = token_relevance(observer_text, node.content) if use_query_relevance else 0.0
            distance = max(0, len(path) - 1) / 4
            stale = 1.0 if (
                path and path[0]["type"] == "evolved_from"
                and not change_chain and node.outcome == "failure"
            ) else 0.0
            provisional.append(CandidateTrace(
                current_state_ip=state.ref,
                candidate_ip=ref,
                path=path,
                edge_directions=[step["direction"] for step in path],
                edge_types=edge_types,
                structural_score=structural,
                goal_relevance_score=goal,
                state_change_score=state_change,
                provenance_relevance_score=provenance,
                failure_relevance_score=failure,
                distance_penalty=distance,
                redundancy_penalty=0.0,
                stale_locality_penalty=stale,
                final_score=0.0,
                eligible=ref in eligible,
                selected=False,
                reason="",
                canonical_tie_key=ref,
                origin=str(node.metadata.get("origin", "runtime_reasoning")),
            ))

        selected: list[CandidateTrace] = []
        remaining = [trace for trace in provisional if trace.eligible]
        while remaining and len(selected) < limit:
            for trace in remaining:
                node = self.graph.nodes[trace.candidate_ip]
                redundancy = max(
                    (token_relevance(node.content, self.graph.nodes[item.candidate_ip].content) for item in selected),
                    default=0.0,
                )
                trace.redundancy_penalty = redundancy
                trace.final_score = (
                    0.25 * trace.structural_score
                    + 0.15 * trace.goal_relevance_score
                    + 0.30 * trace.state_change_score
                    + 0.10 * trace.provenance_relevance_score
                    + 0.10 * trace.failure_relevance_score
                    - 0.05 * trace.distance_penalty
                    - 0.10 * trace.redundancy_penalty
                    - 0.15 * trace.stale_locality_penalty
                )
                trace.reason = (
                    f"observer-aware: structural={trace.structural_score:.4f}; "
                    f"goal={trace.goal_relevance_score:.4f}; change={trace.state_change_score:.4f}; "
                    f"provenance={trace.provenance_relevance_score:.4f}; failure={trace.failure_relevance_score:.4f}; "
                    f"distance={trace.distance_penalty:.4f}; redundancy={trace.redundancy_penalty:.4f}; "
                    f"stale={trace.stale_locality_penalty:.4f}; final={trace.final_score:.4f}"
                )
            next_trace = sorted(remaining, key=lambda item: (-item.final_score, item.candidate_ip))[0]
            next_trace.selected = True
            selected.append(next_trace)
            remaining.remove(next_trace)

        for trace in provisional:
            if not trace.eligible and not trace.reason:
                trace.reason = "structurally reachable but filtered before top-k as non-model-visible"
        return RetrievalResult(
            refs=[trace.candidate_ip for trace in selected],
            method="observer_aware_topology",
            scores=[trace.final_score for trace in selected],
            traces=provisional,
            realized_artifact_count=len(selected),
        )


def trace_to_dict(trace: CandidateTrace) -> dict:
    return asdict(trace)
