"""
Context builders
================
Two strategies for building the field-context block injected into an LLM
prompt during a reasoning step. The whole point of v3 — and of paper 4
§3.2's load-bearing claim — is that these two strategies should produce
materially different prompts, and that the topology-aware strategy
should yield better outcomes on backtrack-required problems.

  TopologyContext   — walks edges from the current node (paper 4's spec).
  SimilarityContext — keyword-matches against node content (the v82 fallback).

Both strategies expose the same `build(field, current_node_id) -> str`
interface so the runner can swap them with a flag.
"""

from __future__ import annotations

from typing import Protocol

from core.field import InformationField


class ContextBuilder(Protocol):
    """A strategy that produces a text block summarizing relevant
    field state for inclusion in an LLM prompt."""

    name: str

    def build(self, field: InformationField, current_node_id: str) -> str:
        ...


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------

class TopologyContext:
    """
    Walk edges from the current node up to `depth` hops. Include
    `failed_from` and `contradicts` neighbours preferentially — those
    are the edges paper 4 §3.2 specifies as the structurally-adjacent
    points that similarity search misses.

    Restricted to current session (if known): we only surface nodes
    whose session_id matches the current node's. The seed ontology
    (loaded from stoe_seed.json with a different session_id) is field
    background, not session-state, and is excluded.
    """

    name = "topology"

    def __init__(self, depth: int = 2, max_items: int = 12, session_restricted: bool = True):
        self.depth = depth
        self.max_items = max_items
        self.session_restricted = session_restricted

    def build(self, field: InformationField, current_node_id: str) -> str:
        if current_node_id not in field.nodes:
            return ""

        current_session = field.nodes[current_node_id].get("session_id", "")

        sub = field.navigate_from(
            current_node_id, depth=self.depth, include_failed=True,
        )

        # Ordering priority: failed_from > contradicts > others (closer first).
        def edge_priority(edge_types: set) -> int:
            if "failed_from" in edge_types:
                return 0
            if "contradicts" in edge_types:
                return 1
            if "evaluates" in edge_types:
                return 2
            return 3

        items = []
        for nid, info in sub.items():
            if nid == current_node_id:
                continue
            # Session restriction: only surface nodes from the current session,
            # unless session_restricted=False (then include seed ontology too).
            if (self.session_restricted and current_session
                    and info["ip"].get("session_id", "") != current_session):
                continue
            edge_types = {e["type"] for e in info["edges"]}
            items.append((
                edge_priority(edge_types),
                info["depth"],
                edge_types,
                info["ip"],
            ))

        items.sort(key=lambda x: (x[0], x[1]))
        items = items[:self.max_items]

        if not items:
            return ""

        lines = ["FIELD CONTEXT (graph topology, depth=%d):" % self.depth]
        for _, depth, edge_types, ip in items:
            tag = ",".join(sorted(edge_types)) or "?"
            content = ip["content"]
            content = content[:200] + ("..." if len(content) > 200 else "")
            lines.append(f"  [d{depth}] [{tag}] {content}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Similarity (the v82 baseline being compared against)
# ---------------------------------------------------------------------------

class SimilarityContext:
    """
    Keyword-match the current node's content against the field. The v82
    retrieval pattern; v3 reproduces it as the comparison baseline.

    Restricted to current session (if known) so the comparison with
    TopologyContext is fair: both modes draw from the same retrieval
    pool (current-session reasoning history), differing only in their
    retrieval strategy (graph traversal vs keyword match). Background
    ontology nodes loaded from stoe_seed.json are excluded.
    """

    name = "similarity"

    def __init__(self, max_items: int = 12, session_restricted: bool = True):
        self.max_items = max_items
        self.session_restricted = session_restricted

    def build(self, field: InformationField, current_node_id: str) -> str:
        if current_node_id not in field.nodes:
            return ""

        current_session = field.nodes[current_node_id].get("session_id", "")

        query = field.nodes[current_node_id]["content"]
        hits = field.cold_start_lookup(query, limit=self.max_items * 4)
        # Exclude the current node. Optionally restrict to current session.
        filtered = []
        for h in hits:
            if h["id"] == current_node_id:
                continue
            if (self.session_restricted and current_session
                    and h.get("session_id", "") != current_session):
                continue
            filtered.append(h)
            if len(filtered) >= self.max_items:
                break

        if not filtered:
            return ""

        lines = ["FIELD CONTEXT (keyword similarity):"]
        for ip in filtered:
            content = ip["content"]
            content = content[:200] + ("..." if len(content) > 200 else "")
            lines.append(f"  [sim] {content}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def get_builder(mode: str, **kwargs) -> ContextBuilder:
    """
    mode: 'topology' | 'similarity'
    Extra kwargs forwarded to the builder constructor.
    """
    if mode == "topology":
        return TopologyContext(**kwargs)
    if mode == "similarity":
        return SimilarityContext(**kwargs)
    raise ValueError(f"unknown context mode: {mode!r}")
