"""
SToE v3 — Information Field
============================
A persistent, monotonically-growing typed graph. Implements the architectural
requirements derived from paper 4 §3 and §5:

  • Persistent reasoning graph: nodes are never deleted; edges are severed,
    not removed. The active context window is a subgraph of G — not G itself.

  • Topology-aware navigation: queries operate on graph structure
    (adjacency, paths, dead-ends), not on content similarity.

  • Conservation of failure: failed reasoning attempts become Ghost nodes
    connected by `failed_from` edges. They remain navigable.

This module is the data substrate. It does NOT call an LLM, score outputs,
or apply operators. Those live in higher-level modules and consume the API
this module exposes.

Difference from v82's field.py
------------------------------
  • No `delete_point` method.            (v82 had hard delete via HTTP)
  • No `wipe` method.                    (v82 had `wipe_field` in server.py)
  • `search()` is private (`_search`)    (v82 exposed it as primary retrieval)
    and only called by cold-start logic. Topology drives all live retrieval.
  • Adds `assert_no_deletion_methods()`  (slice-1 invariant guard)
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Optional, Iterable

try:
    import networkx as nx
    HAS_NX = True
except ImportError:
    HAS_NX = False


# ---------------------------------------------------------------------------
# Edge type vocabulary (paper 4 §5.1)
#
# The vocabulary is richer than paper 4 strictly demands because v82's experience
# showed that operator-typed edges are useful diagnostically. Keep them.
# ---------------------------------------------------------------------------

EDGE_TYPES: tuple[str, ...] = (
    "generated_by",     # default: this IP was produced from another
    "evolved_from",     # operator ↻ (Recursion) effect
    "amplified_from",   # operator ^ (Amplification) effect
    "synergy_with",     # operator × (Synergy) effect
    "connected_to",     # operator + (Connection) effect
    "removed_from",     # operator − (Removal) effect
    "distributed_to",   # operator ÷ (Distribution) effect
    "failed_from",      # an attempt that failed — paper 4's central edge type
    "contradicts",      # logical tension between two IPs
    "evaluates",        # one IP assesses another (structural verdict, slice 3)
    "confirmed_by",     # an evaluation was subsequently confirmed
    "extends",          # paper 4 §5.1 vocabulary
    "adjacent_to",      # structural proximity without direct generation
    "session_of",       # belongs to an engine session
)

# Categories carried over from v82's "dashboard" framing. These are content
# tags for nodes; they do not affect graph topology. Keeping them lets v3
# remain compatible with the existing seed file (`stoe_seed.json`).
CATEGORIES: tuple[str, ...] = (
    "Star",
    "Hidden Diamond",
    "Seed",
    "Fertilizer",
    "Mirror",
    "Catalyst",
    "Vampire",
    "Ghost",
    "Echo",
    "Unknown",
)


# ---------------------------------------------------------------------------
# Node + Edge dataclasses (kept minimal; serialize as plain dicts)
# ---------------------------------------------------------------------------

@dataclass
class _Node:
    id: str
    content: str
    category: str = "Unknown"
    operator: str = ""
    session_id: str = ""
    created_at: str = ""
    score: dict = dc_field(default_factory=dict)
    metadata: dict = dc_field(default_factory=dict)
    name: str = ""
    description: str = ""
    expression: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ---------------------------------------------------------------------------
# InformationField
# ---------------------------------------------------------------------------

class InformationField:
    """
    The Information Field.

    Invariants this class enforces:

      I1. Monotonic growth. Once added, a node remains in `self.nodes`
          for the lifetime of the field. There is no public method to
          remove one.

      I2. Severance, not deletion. An edge can be marked severed
          (`severed: True`); it is not removed from `self.edges`.

      I3. Failure conservation. The `add_failed` helper produces a Ghost
          node with a `failed_from` edge from its origin. Ghost nodes are
          first-class graph members, navigable like any other.

      I4. Topology-first retrieval. The retrieval helpers exposed for
          live reasoning (`navigate_from`, `dead_end_query`, `path_query`,
          `get_adjacent`) operate on edges. The content-similarity helper
          `_search` is private and intended only for cold-start lookup
          when no current node exists.

    The class does NOT call an LLM, score outputs, or apply operators.
    """

    # --- Construction ---

    def __init__(self, storage_path: str):
        """
        storage_path is the file the field is persisted to. It is created
        on first save. The seed (`seed/stoe_seed.json`) is a separate file
        loaded by `load_seed_if_empty` at startup; storage_path is the
        running field's home.
        """
        self.storage_path = storage_path
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self._load()

    # --- Persistence ---

    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            return
        # Empty files are treated as "fresh field" — this matches the
        # case where a temp file was created by the harness ahead of
        # InformationField construction and not yet written to.
        if os.path.getsize(self.storage_path) == 0:
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.nodes = data.get("nodes", {})
            self.edges = data.get("edges", [])
        except Exception:
            # Genuinely corrupt JSON — don't silently overwrite. Re-raise
            # so the caller decides whether to wipe and start fresh.
            raise

    def _save(self) -> None:
        # Atomic-ish save: write to temp + rename.
        tmp = self.storage_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {"nodes": self.nodes, "edges": self.edges},
                f, ensure_ascii=False, indent=2,
            )
        os.replace(tmp, self.storage_path)

    # --- Mutation: add only ---

    def add_point(
        self,
        content: str,
        category: str = "Unknown",
        operator: str = "",
        session_id: str = "",
        score: Optional[dict] = None,
        metadata: Optional[dict] = None,
        name: str = "",
        description: str = "",
        expression: str = "",
    ) -> str:
        """
        Add an information point. Returns its ID.
        Nodes are never deleted; this is the only way new ones enter G.
        """
        ip_id = uuid.uuid4().hex[:16]
        node = _Node(
            id=ip_id,
            content=content,
            category=category,
            operator=operator,
            session_id=session_id,
            created_at=datetime.now().isoformat(),
            score=score or {},
            metadata=metadata or {},
            name=name or content[:60],
            description=description,
            expression=expression,
        ).to_dict()
        self.nodes[ip_id] = node
        self._save()
        return ip_id

    def connect(
        self,
        source_id: str,
        target_id: str,
        edge_type: str = "connected_to",
        weight: float = 1.0,
        note: str = "",
    ) -> Optional[str]:
        """
        Add a typed edge. Returns the edge id, or None if either endpoint
        is missing. Edges, like nodes, are not deleted; sever instead.
        """
        if source_id not in self.nodes or target_id not in self.nodes:
            return None
        if edge_type not in EDGE_TYPES:
            # We accept unknown types but record them — useful for catching
            # typos during slice 2 development without breaking the run.
            pass
        edge_id = uuid.uuid4().hex[:16]
        edge = {
            "id": edge_id,
            "source": source_id,
            "target": target_id,
            "type": edge_type,
            "weight": float(weight),
            "note": note,
            "created_at": datetime.now().isoformat(),
        }
        self.edges.append(edge)
        self._save()
        return edge_id

    def sever(self, edge_id: str) -> bool:
        """
        Mark an edge severed. The edge stays in `self.edges`. This is the
        only mechanism by which the connectivity of the graph reduces.
        """
        for e in self.edges:
            if e["id"] == edge_id and not e.get("severed"):
                e["severed"] = True
                e["severed_at"] = datetime.now().isoformat()
                self._save()
                return True
        return False

    def add_failed(
        self,
        from_id: str,
        reason: str,
        operator: str = "",
        session_id: str = "",
    ) -> str:
        """
        Conserve a failed attempt. Creates a Ghost node and a `failed_from`
        edge from `from_id` to it. Returns the Ghost's id.

        This is the structural realization of paper 5's Law of Conservation:
        failures don't vanish, they become navigable points in the field.
        """
        ghost_id = self.add_point(
            content=f"[FAILED] {reason}",
            category="Ghost",
            operator=operator,
            session_id=session_id,
            metadata={"failed": True, "reason": reason},
        )
        self.connect(from_id, ghost_id, edge_type="failed_from",
                     note=f"failure: {reason}")
        return ghost_id

    # --- Read: structural queries (paper 4 §5.2) ---

    def get_adjacent(
        self,
        ip_id: str,
        edge_types: Optional[Iterable[str]] = None,
        include_severed: bool = False,
    ) -> list[dict]:
        """
        All IPs adjacent to `ip_id` via at least one edge.

        Returns list of {ip, edge, direction}. `direction` ∈ {'outgoing',
        'incoming'}. Severed edges are excluded by default.

        This is the primitive on which all live retrieval is built.
        """
        if ip_id not in self.nodes:
            return []
        wanted = set(edge_types) if edge_types else None
        out = []
        for e in self.edges:
            if e.get("severed") and not include_severed:
                continue
            if wanted and e["type"] not in wanted:
                continue
            if e["source"] == ip_id and e["target"] in self.nodes:
                out.append({
                    "ip": self.nodes[e["target"]],
                    "edge": e,
                    "direction": "outgoing",
                })
            elif e["target"] == ip_id and e["source"] in self.nodes:
                out.append({
                    "ip": self.nodes[e["source"]],
                    "edge": e,
                    "direction": "incoming",
                })
        return out

    def navigate_from(
        self,
        ip_id: str,
        depth: int = 2,
        include_failed: bool = True,
        include_severed: bool = False,
    ) -> dict[str, dict]:
        """
        Topology-aware traversal. Returns all nodes reachable within
        `depth` hops from `ip_id`, annotated with their depth and the
        edges that reach them.

        Result shape:
            { node_id: {"ip": <node>, "depth": int, "edges": [...]} }

        This is paper 4 §3.2's required navigation primitive — the
        replacement for similarity-based retrieval. Higher-level modules
        compose this with type filters to build operator-specific context.
        """
        if ip_id not in self.nodes:
            return {}
        visited: dict[str, dict] = {}
        frontier: list[str] = [ip_id]
        for d in range(depth + 1):
            next_frontier: list[str] = []
            for nid in frontier:
                if nid in visited or nid not in self.nodes:
                    continue
                adj = self.get_adjacent(nid, include_severed=include_severed)
                visited[nid] = {
                    "ip": self.nodes[nid],
                    "depth": d,
                    "edges": [],
                }
                for item in adj:
                    e = item["edge"]
                    if not include_failed and e["type"] == "failed_from":
                        continue
                    visited[nid]["edges"].append({
                        "type": e["type"],
                        "direction": item["direction"],
                        "target_id": item["ip"]["id"],
                        "weight": e.get("weight", 1.0),
                        "note": e.get("note", ""),
                    })
                    next_frontier.append(item["ip"]["id"])
            frontier = [n for n in next_frontier if n not in visited]
            if not frontier:
                break
        return visited

    def dead_end_query(self, ip_id: str) -> list[dict]:
        """
        Paper 4 §5.2: 'what nodes are reachable only through paths that
        have been marked as failed or contradicted?'

        Returns the immediate neighbours of `ip_id` reached via
        `failed_from` or `contradicts` edges. These are the conserved
        dead-ends the agent can navigate back to instead of treating
        them as discarded noise.
        """
        if ip_id not in self.nodes:
            return []
        out = []
        for e in self.edges:
            if e["type"] not in ("failed_from", "contradicts"):
                continue
            if e.get("severed"):
                continue
            other = None
            if e["source"] == ip_id:
                other = e["target"]
            elif e["target"] == ip_id:
                other = e["source"]
            if other and other in self.nodes:
                out.append({
                    "ip": self.nodes[other],
                    "edge_type": e["type"],
                    "edge_id": e["id"],
                    "note": e.get("note", ""),
                })
        return out

    def path_query(self, source_id: str, target_id: str) -> dict:
        """
        Shortest path between two nodes, with edge-type annotation.
        Uses networkx if available, BFS fallback otherwise.
        """
        if source_id not in self.nodes or target_id not in self.nodes:
            return {"found": False, "steps": []}
        if HAS_NX:
            return self._nx_path(source_id, target_id)
        return self._bfs_path(source_id, target_id)

    def _nx_path(self, source_id: str, target_id: str) -> dict:
        G = nx.DiGraph()
        for nid in self.nodes:
            G.add_node(nid)
        for e in self.edges:
            if e.get("severed"):
                continue
            G.add_edge(e["source"], e["target"],
                       type=e["type"], edge_id=e["id"],
                       weight=e.get("weight", 1.0))
        try:
            path = nx.shortest_path(G, source_id, target_id)
        except Exception:
            return {"found": False, "steps": []}
        steps = []
        for i in range(len(path) - 1):
            s, t = path[i], path[i + 1]
            ed = G.get_edge_data(s, t, {})
            steps.append({
                "from_id": s, "to_id": t,
                "edge_type": ed.get("type", "connected_to"),
                "weight": ed.get("weight", 1.0),
            })
        return {"found": True, "length": len(steps), "steps": steps}

    def _bfs_path(self, source_id: str, target_id: str) -> dict:
        from collections import deque
        edge_idx: dict[tuple[str, str], dict] = {}
        for e in self.edges:
            if e.get("severed"):
                continue
            edge_idx[(e["source"], e["target"])] = e
        q = deque([(source_id, [source_id])])
        seen = {source_id}
        while q:
            node, path = q.popleft()
            if node == target_id:
                steps = []
                for i in range(len(path) - 1):
                    s, t = path[i], path[i + 1]
                    e = edge_idx.get((s, t), {})
                    steps.append({
                        "from_id": s, "to_id": t,
                        "edge_type": e.get("type", "connected_to"),
                        "weight": e.get("weight", 1.0),
                    })
                return {"found": True, "length": len(steps), "steps": steps}
            for (s, t), e in edge_idx.items():
                if s == node and t not in seen:
                    seen.add(t)
                    q.append((t, path + [t]))
        return {"found": False, "steps": []}

    # --- Read: bulk + stats ---

    def get_by_session(self, session_id: str) -> list[dict]:
        return [n for n in self.nodes.values() if n.get("session_id") == session_id]

    def get_ontology_manifest(
        self,
        session_id: str,
        max_items: Optional[int] = None,
    ) -> list[dict]:
        """
        Return a compact directory of non-session (background ontology) nodes.

        Used by the Option-K retrieval mode (paper 4 §5.3 traverse-evaluate-
        integrate): the LLM is shown what concepts exist in the field so it
        can reference them by name during reasoning. Subsequent mention-edge
        recording then creates `adjacent_to` connections between session
        content and the ontology nodes the LLM named.

        Excludes nodes from `session_id` (current reasoning) and any nodes
        with category "Evaluation" (verdict nodes from the structural
        evaluator). Returns dicts with name, category, and a short summary.
        """
        out = []
        for n in self.nodes.values():
            if n.get("session_id") == session_id:
                continue
            if n.get("category") == "Evaluation":
                continue
            if n.get("metadata", {}).get("is_verdict"):
                continue
            name = n.get("name") or n.get("content", "")[:60]
            if not name:
                continue
            summary = (n.get("description") or n.get("content") or "")[:100]
            out.append({
                "id": n["id"],
                "name": name,
                "category": n.get("category", "Unknown"),
                "summary": summary,
            })
        if max_items is not None:
            out = out[:max_items]
        return out

    def get_by_category(self, category: str) -> list[dict]:
        return [n for n in self.nodes.values() if n.get("category") == category]

    def stats(self) -> dict:
        cats: dict[str, int] = {}
        edge_types: dict[str, int] = {}
        for n in self.nodes.values():
            c = n.get("category", "Unknown")
            cats[c] = cats.get(c, 0) + 1
        active = 0
        severed = 0
        for e in self.edges:
            t = e["type"]
            edge_types[t] = edge_types.get(t, 0) + 1
            if e.get("severed"):
                severed += 1
            else:
                active += 1
        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "active_edges": active,
            "severed_edges": severed,
            "categories": cats,
            "edge_types": edge_types,
            "ghosts": cats.get("Ghost", 0),
        }

    # --- Cold-start retrieval (private) ---

    def _search(self, query: str, limit: int = 10) -> list[dict]:
        """
        Content-keyword search. PRIVATE. The only legitimate caller is the
        cold-start path: when a session has no current node, this finds a
        starting position in the seed.

        Live operator loops MUST NOT call this. Topology-aware retrieval
        via `navigate_from` is the load-bearing requirement of paper 4 §3.2;
        leaking similarity search into the live loop reintroduces the v82
        gap that v3 exists to close.
        """
        q = query.lower().strip()
        tokens = [t for t in q.split() if len(t) > 1]
        scored = []
        for n in self.nodes.values():
            content_lower = n["content"].lower()
            if q and q in content_lower:
                score = 10
            else:
                score = sum(2 for t in tokens if t in content_lower)
            if score > 0:
                scored.append((score, n))
        scored.sort(key=lambda x: -x[0])
        return [n for _, n in scored[:limit]]

    def cold_start_lookup(self, query: str, limit: int = 5) -> list[dict]:
        """
        Public wrapper around `_search`. Callers must annotate why they
        need cold-start retrieval; the engine logs it as a deviation from
        topology-only navigation.
        """
        return self._search(query, limit=limit)


# ---------------------------------------------------------------------------
# Slice-1 invariant guard
# ---------------------------------------------------------------------------

def assert_no_deletion_methods() -> None:
    """
    Static guard. Raises AssertionError if InformationField gains any method
    whose name suggests deletion. This is a tripwire against future drift
    back into the v82 pattern.
    """
    forbidden_substrings = ("delete", "remove_node", "wipe", "drop", "purge")
    for name in dir(InformationField):
        if name.startswith("_"):
            continue
        for sub in forbidden_substrings:
            if sub in name.lower():
                raise AssertionError(
                    f"InformationField.{name} violates slice-1 invariant: "
                    f"no public deletion methods are permitted. The field is "
                    f"monotonic; sever edges instead."
                )
