from __future__ import annotations

import copy
import random
from collections import deque

from .models import Edge, InformationPoint


class InformationGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, InformationPoint] = {}
        self.edges: list[Edge] = []
        self.field_metadata: dict[str, object] = {}

    def add_node(self, node: InformationPoint) -> None:
        if node.ref in self.nodes:
            raise ValueError(f"duplicate IP ref: {node.ref}")
        self.nodes[node.ref] = node

    def add_edge(self, source: str, target: str, relation: str) -> None:
        if source not in self.nodes or target not in self.nodes:
            raise KeyError((source, target))
        self.edges.append(Edge(source, target, relation))

    def adjacent(self, ref: str) -> list[tuple[str, Edge, str]]:
        output: list[tuple[str, Edge, str]] = []
        for edge in self.edges:
            if edge.source == ref:
                output.append((edge.target, edge, "outgoing"))
            elif edge.target == ref:
                output.append((edge.source, edge, "incoming"))
        return output

    def eligible_refs(self, *, include_failures: bool = True) -> list[str]:
        return [
            ref for ref, node in self.nodes.items()
            if node.visible and node.kind not in {"current_state", "domain_root", "bookkeeping"}
            and (include_failures or node.outcome != "failure")
        ]

    def clone(self) -> "InformationGraph":
        return copy.deepcopy(self)

    def without_node(self, ref: str) -> "InformationGraph":
        graph = self.clone()
        graph.nodes.pop(ref, None)
        graph.edges = [edge for edge in graph.edges if ref not in {edge.source, edge.target}]
        return graph

    def without_relation(self, relation: str) -> "InformationGraph":
        graph = self.clone()
        graph.edges = [edge for edge in graph.edges if edge.relation != relation]
        return graph

    def randomized_transition_endpoints(self, seed: int) -> "InformationGraph":
        graph = self.clone()
        mutable = [
            index for index, edge in enumerate(graph.edges)
            if edge.relation not in {"session_of", "contains"}
        ]
        targets = [graph.edges[index].target for index in mutable]
        random.Random(seed).shuffle(targets)
        for index, new_target in zip(mutable, targets):
            old = graph.edges[index]
            if old.source == new_target:
                candidates = [ref for ref in graph.nodes if ref != old.source]
                new_target = candidates[seed % len(candidates)]
            graph.edges[index] = Edge(old.source, new_target, old.relation)
        return graph

    def reachable_paths(self, start: str, max_depth: int = 4) -> dict[str, list[list[dict]]]:
        if start not in self.nodes:
            raise KeyError(start)
        found: dict[str, list[list[dict]]] = {}
        queue = deque([(start, [], {start})])
        while queue:
            current, path, visited = queue.popleft()
            if len(path) >= max_depth:
                continue
            adjacent = sorted(
                self.adjacent(current),
                key=lambda item: (item[1].relation, item[2], item[0]),
            )
            for other, edge, direction in adjacent:
                if other in visited:
                    continue
                step = {
                    "from": current,
                    "to": other,
                    "type": edge.relation,
                    "direction": direction,
                    "semantic": reverse_semantic(edge.relation, direction),
                }
                new_path = path + [step]
                found.setdefault(other, []).append(new_path)
                queue.append((other, new_path, visited | {other}))
        return found


def reverse_semantic(relation: str, direction: str) -> str:
    if direction == "outgoing":
        return relation
    meanings = {
        "rejected_by": "find_hypotheses_rejected_because_of",
        "invalidates": "find_evidence_that_invalidates",
        "evaluates": "find_evaluation_of",
        "contains_change": "find_observer_state_containing_change",
        "evolved_from": "find_later_state_evolved_from",
        "generated_by": "find_generators_of",
        "instantiates": "find_runtime_instances_of_core",
        "applies_core": "find_runtime_applications_of_core",
        "unfolds_to": "find_folded_seed_domain",
        "shares_field_with": "find_other_domain_in_same_field",
    }
    return meanings.get(relation, f"reverse_{relation}")
