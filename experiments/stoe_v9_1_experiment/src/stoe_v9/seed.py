from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from .graph import InformationGraph
from .models import InformationPoint


CANONICAL_SEED_SHA256 = "b327db6dbce9981ed21561b9d1a857e2e3786f1391d41edc0381fead79e59868"
SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "stoe_seed.json"
SEED_DOMAIN_REF = "STOE_Seed_IP"
CHIMERA_TARGET_OFFSET = 7
SeedMode = Literal["native", "absent", "chimera"]


def canonical_ref(canonical_id: str) -> str:
    return f"SEED_{canonical_id}"


def load_canonical_seed(path: str | Path = SEED_PATH) -> dict[str, Any]:
    source = Path(path)
    payload = source.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != CANONICAL_SEED_SHA256:
        raise ValueError(f"canonical SToE seed hash mismatch: expected {CANONICAL_SEED_SHA256}, got {actual}")
    raw = json.loads(payload.decode("utf-8"))
    validate_seed_structure(raw)
    return raw


def validate_seed_structure(raw: dict[str, Any]) -> None:
    if set(raw) != {"nodes", "edges"}:
        raise ValueError("canonical seed must contain exactly nodes and edges")
    nodes = raw["nodes"]
    if not isinstance(nodes, dict) or not isinstance(raw["edges"], list):
        raise ValueError("invalid canonical seed containers")
    for key, node in nodes.items():
        if key != node.get("id"):
            raise ValueError(f"seed node key/id mismatch: {key}")
    for edge in raw["edges"]:
        if edge.get("source") not in nodes or edge.get("target") not in nodes:
            raise ValueError(f"seed edge has missing endpoint: {edge.get('id')}")


def seed_report(raw: dict[str, Any]) -> dict[str, Any]:
    nodes = list(raw["nodes"].values())
    return {
        "core_ips": len(nodes),
        "typed_relations": len(raw["edges"]),
        "categories": dict(sorted(Counter(node.get("category", "") for node in nodes).items())),
        "relation_types": dict(sorted(Counter(edge.get("type", "") for edge in raw["edges"]).items())),
        "expressions": sum(bool(node.get("expression") or node.get("metadata", {}).get("expr")) for node in nodes),
        "nonempty_descriptions": sum(bool(node.get("description") or node.get("metadata", {}).get("description")) for node in nodes),
        "sha256": CANONICAL_SEED_SHA256,
    }


def fold_seed(raw: dict[str, Any]) -> InformationPoint:
    validate_seed_structure(raw)
    return InformationPoint(
        ref=SEED_DOMAIN_REF,
        content="Canonical SToE bootstrap information domain (folded)",
        kind="seed_domain",
        outcome="unknown",
        visible=False,
        created_order=-1000,
        metadata={
            "origin": "canonical_seed",
            "canonical_seed_sha256": CANONICAL_SEED_SHA256,
            "folded_seed": copy.deepcopy(raw),
        },
    )


def unfold_seed(domain_ip: InformationPoint) -> dict[str, Any]:
    if domain_ip.ref != SEED_DOMAIN_REF or domain_ip.kind != "seed_domain":
        raise ValueError("not a folded SToE seed domain IP")
    raw = copy.deepcopy(domain_ip.metadata["folded_seed"])
    validate_seed_structure(raw)
    return raw


def _node_text(node: dict[str, Any]) -> str:
    description = node.get("description") or node.get("metadata", {}).get("description", "")
    expression = node.get("expression") or node.get("metadata", {}).get("expr", "")
    return (
        f"{node.get('name') or node.get('content', '')}. "
        f"Category: {node.get('category', '')}. "
        f"Description: {description}. Expression: {expression}"
    )


def _chimera_edges(raw: dict[str, Any]) -> list[dict[str, Any]]:
    ordered = sorted(raw["nodes"])
    index = {ref: position for position, ref in enumerate(ordered)}
    output = []
    for edge in raw["edges"]:
        changed = copy.deepcopy(edge)
        target_position = (index[edge["target"]] + CHIMERA_TARGET_OFFSET) % len(ordered)
        target = ordered[target_position]
        if target == edge["source"]:
            target = ordered[(target_position + 1) % len(ordered)]
        changed["target"] = target
        output.append(changed)
    return output


def load_seed_into_graph(graph: InformationGraph, *, mode: SeedMode = "native") -> None:
    graph.field_metadata["seed_mode"] = mode
    graph.field_metadata["canonical_seed_sha256"] = CANONICAL_SEED_SHA256
    if mode == "absent":
        return
    raw = load_canonical_seed()
    graph.add_node(fold_seed(raw))
    for canonical_id, node in raw["nodes"].items():
        graph.add_node(InformationPoint(
            ref=canonical_ref(canonical_id),
            content=_node_text(node),
            kind="stoe_core_ip",
            outcome="unknown",
            visible=True,
            created_order=-500,
            metadata={
                "origin": "canonical_seed",
                "canonical_id": canonical_id,
                "category": node.get("category", ""),
                "description": node.get("description") or node.get("metadata", {}).get("description", ""),
                "expression": node.get("expression") or node.get("metadata", {}).get("expr", ""),
                "canonical_node": copy.deepcopy(node),
                "relation_context": "stoe_core",
            },
        ))
    edges = raw["edges"] if mode == "native" else _chimera_edges(raw)
    for edge in edges:
        graph.add_edge(canonical_ref(edge["source"]), canonical_ref(edge["target"]), edge["type"])
    stoe_id = seed_id_by_name(raw, "Special Theory of Everything (SToE)")
    graph.add_edge(SEED_DOMAIN_REF, canonical_ref(stoe_id), "unfolds_to")
    graph.field_metadata["seed_report"] = seed_report(raw)


def seed_id_by_name(raw: dict[str, Any], name: str) -> str:
    matches = [node_id for node_id, node in raw["nodes"].items() if node.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"canonical seed name lookup failed: {name}")
    return matches[0]


def add_runtime_seed_bridges(graph: InformationGraph, *, mode: SeedMode) -> None:
    if mode == "absent":
        return
    raw = load_canonical_seed()
    names = {
        "IP_00001": ("Observer (O)", "instantiates"),
        "IP_00002": ("Law of Conservation", "instantiates"),
        "IP_00004": ("Operator − (Removal)", "applies_core"),
        "IP_00006": ("Information Function", "instantiates"),
    }
    for runtime_ref, (name, relation) in names.items():
        graph.add_edge(runtime_ref, canonical_ref(seed_id_by_name(raw, name)), relation)
    graph.add_edge("IP_00000", SEED_DOMAIN_REF, "shares_field_with")


def seed_relation_counts(graph: InformationGraph) -> Counter[str]:
    return Counter(
        edge.relation for edge in graph.edges
        if edge.source.startswith("SEED_") and edge.target.startswith("SEED_")
    )
