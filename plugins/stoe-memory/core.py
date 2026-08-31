from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import uuid
from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


CANONICAL_SEED_SHA256 = "b327db6dbce9981ed21561b9d1a857e2e3786f1391d41edc0381fead79e59868"
SEED_DOMAIN_REF = "STOE_Seed_IP"
ALLOWED_ORIGINS = {
    "canonical_seed",
    "runtime_reasoning",
    "failure_history",
    "evaluation",
    "state_change",
    "current_observer_state",
}
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
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
RELATION_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_db_path() -> Path:
    override = os.environ.get("STOE_MEMORY_DB")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "SToE" / "field.sqlite3"


def token_set(text: str) -> set[str]:
    return set(TOKEN_PATTERN.findall(text.lower()))


def token_relevance(left: str, right: str) -> float:
    a, b = token_set(left), token_set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def structural_score(path: list[dict[str, Any]]) -> float:
    if not path:
        return 0.0
    numerator = 0.0
    denominator = 0.0
    for index, step in enumerate(path):
        decay = PATH_DECAY**index
        strength = EDGE_STRENGTH.get(step["type"], 0.25)
        direction = DIRECTION_WEIGHT.get(step["type"], {}).get(step["direction"], 0.60)
        numerator += decay * strength * direction
        denominator += decay
    return (numerator / denominator) / (1.0 + EXTRA_HOP_PENALTY * (len(path) - 1))


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


@dataclass(slots=True)
class Node:
    ref: str
    content: str
    origin: str
    kind: str
    outcome: str
    visible: bool
    created_order: int
    session_id: str
    failure_condition: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class Edge:
    edge_id: str
    source: str
    target: str
    relation: str
    weight: float
    note: str


class FieldStore:
    def __init__(self, db_path: str | Path | None = None, seed_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.seed_path = Path(seed_path) if seed_path else Path(__file__).resolve().parent / "assets" / "stoe_seed.json"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> dict[str, Any]:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    ref TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    visible INTEGER NOT NULL,
                    created_order INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    failure_condition TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS edges (
                    edge_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL REFERENCES nodes(ref) ON DELETE CASCADE,
                    target TEXT NOT NULL REFERENCES nodes(ref) ON DELETE CASCADE,
                    relation TEXT NOT NULL,
                    weight REAL NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
                CREATE INDEX IF NOT EXISTS idx_nodes_session ON nodes(session_id, created_order);
                CREATE INDEX IF NOT EXISTS idx_nodes_origin ON nodes(origin);
                CREATE TABLE IF NOT EXISTS field_metadata (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS retrieval_runs (
                    run_id TEXT PRIMARY KEY,
                    observer_state_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                """
            )
            connection.execute("PRAGMA journal_mode = WAL")
            self._load_seed(connection)
        return self.status()

    def _read_seed(self) -> dict[str, Any]:
        raw_bytes = self.seed_path.read_bytes()
        actual = hashlib.sha256(raw_bytes).hexdigest()
        if actual != CANONICAL_SEED_SHA256:
            raise ValueError(
                f"canonical SToE seed hash mismatch: expected {CANONICAL_SEED_SHA256}, got {actual}"
            )
        raw = json.loads(raw_bytes.decode("utf-8"))
        if set(raw) != {"nodes", "edges"} or not isinstance(raw["nodes"], dict) or not isinstance(raw["edges"], list):
            raise ValueError("canonical seed must contain nodes and edges")
        for key, node in raw["nodes"].items():
            if key != node.get("id"):
                raise ValueError(f"seed node key/id mismatch: {key}")
        for edge in raw["edges"]:
            if edge.get("source") not in raw["nodes"] or edge.get("target") not in raw["nodes"]:
                raise ValueError(f"seed edge has missing endpoint: {edge.get('id')}")
        return raw

    def _load_seed(self, connection: sqlite3.Connection) -> None:
        raw = self._read_seed()
        existing = connection.execute(
            "SELECT value_json FROM field_metadata WHERE key = 'canonical_seed_sha256'"
        ).fetchone()
        if existing and json.loads(existing["value_json"]) != CANONICAL_SEED_SHA256:
            raise ValueError("database contains a different canonical seed")

        self._insert_node(
            connection,
            ref=SEED_DOMAIN_REF,
            content="Canonical SToE bootstrap information domain (folded)",
            origin="canonical_seed",
            kind="domain_root",
            outcome="unknown",
            visible=False,
            created_order=-1000,
            session_id="STOE_SEED",
            failure_condition="",
            metadata={"canonical_seed_sha256": CANONICAL_SEED_SHA256, "folded": True},
            ignore_existing=True,
        )
        for order, (canonical_id, node) in enumerate(sorted(raw["nodes"].items()), start=1):
            description = node.get("description") or node.get("metadata", {}).get("description", "")
            expression = node.get("expression") or node.get("metadata", {}).get("expr", "")
            content = (
                f"{node.get('name') or node.get('content', '')}. "
                f"Category: {node.get('category', '')}. "
                f"Description: {description}. Expression: {expression}"
            )
            self._insert_node(
                connection,
                ref=f"SEED_{canonical_id}",
                content=content,
                origin="canonical_seed",
                kind="stoe_core_ip",
                outcome="unknown",
                visible=True,
                created_order=-500 + order,
                session_id="STOE_SEED",
                failure_condition="",
                metadata={
                    "canonical_id": canonical_id,
                    "category": node.get("category", ""),
                    "description": description,
                    "expression": expression,
                    "canonical_node": node,
                },
                ignore_existing=True,
            )
        for edge in raw["edges"]:
            self._insert_edge(
                connection,
                edge_id=f"SEED_EDGE_{edge['id']}",
                source=f"SEED_{edge['source']}",
                target=f"SEED_{edge['target']}",
                relation=str(edge["type"]),
                weight=float(edge.get("weight", 1.0)),
                note=str(edge.get("note", "")),
                ignore_existing=True,
            )
        stoe_ids = [key for key, node in raw["nodes"].items() if node.get("name") == "Special Theory of Everything (SToE)"]
        if len(stoe_ids) != 1:
            raise ValueError("canonical seed does not contain exactly one SToE core node")
        self._insert_edge(
            connection,
            edge_id="SEED_DOMAIN_UNFOLDS",
            source=SEED_DOMAIN_REF,
            target=f"SEED_{stoe_ids[0]}",
            relation="unfolds_to",
            weight=1.0,
            note="Folded canonical seed domain unfolds to its SToE root",
            ignore_existing=True,
        )
        report = self.seed_report(raw)
        for key, value in {
            "canonical_seed_sha256": CANONICAL_SEED_SHA256,
            "canonical_seed_report": report,
            "canonical_seed_payload": raw,
            "schema_version": 1,
        }.items():
            connection.execute(
                "INSERT INTO field_metadata(key, value_json) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
                (key, json.dumps(value, ensure_ascii=False, sort_keys=True)),
            )

        seed_nodes = connection.execute("SELECT COUNT(*) AS n FROM nodes WHERE origin = 'canonical_seed'").fetchone()["n"]
        seed_edges = connection.execute("SELECT COUNT(*) AS n FROM edges WHERE edge_id LIKE 'SEED_EDGE_%'").fetchone()["n"]
        if seed_nodes != 37 or seed_edges != 113:
            raise ValueError(f"canonical seed database structure mismatch: nodes={seed_nodes}, edges={seed_edges}")

    @staticmethod
    def seed_report(raw: dict[str, Any]) -> dict[str, Any]:
        nodes = list(raw["nodes"].values())
        return {
            "core_ips": len(nodes),
            "typed_relations": len(raw["edges"]),
            "categories": dict(sorted(Counter(node.get("category", "") for node in nodes).items())),
            "expressions": sum(bool(node.get("expression") or node.get("metadata", {}).get("expr")) for node in nodes),
            "nonempty_descriptions": sum(
                bool(node.get("description") or node.get("metadata", {}).get("description")) for node in nodes
            ),
            "sha256": CANONICAL_SEED_SHA256,
        }

    @staticmethod
    def _insert_node(
        connection: sqlite3.Connection,
        *,
        ref: str,
        content: str,
        origin: str,
        kind: str,
        outcome: str,
        visible: bool,
        created_order: int,
        session_id: str,
        failure_condition: str,
        metadata: dict[str, Any],
        ignore_existing: bool = False,
    ) -> None:
        command = "INSERT OR IGNORE" if ignore_existing else "INSERT"
        connection.execute(
            f"{command} INTO nodes(ref, content, origin, kind, outcome, visible, created_order, created_at, "
            "session_id, failure_condition, metadata_json) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ref,
                content,
                origin,
                kind,
                outcome,
                int(visible),
                created_order,
                utc_now(),
                session_id,
                failure_condition,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            ),
        )

    @staticmethod
    def _insert_edge(
        connection: sqlite3.Connection,
        *,
        edge_id: str,
        source: str,
        target: str,
        relation: str,
        weight: float,
        note: str,
        ignore_existing: bool = False,
    ) -> None:
        command = "INSERT OR IGNORE" if ignore_existing else "INSERT"
        connection.execute(
            f"{command} INTO edges(edge_id, source, target, relation, weight, note, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (edge_id, source, target, relation, weight, note, utc_now()),
        )

    def _next_order(self, connection: sqlite3.Connection) -> int:
        return int(connection.execute("SELECT COALESCE(MAX(created_order), 0) + 1 AS n FROM nodes").fetchone()["n"])

    def add_ip(
        self,
        *,
        content: str,
        kind: str,
        origin: str = "runtime_reasoning",
        outcome: str = "unknown",
        failure_condition: str = "",
        session_id: str = "default",
        visible: bool = True,
        metadata: dict[str, Any] | None = None,
        ref: str | None = None,
    ) -> dict[str, Any]:
        if origin not in ALLOWED_ORIGINS or origin == "canonical_seed":
            raise ValueError(f"invalid runtime IP origin: {origin}")
        content = content.strip()
        if not content or len(content) > 20000:
            raise ValueError("content must contain 1..20000 characters")
        kind = kind.strip()
        if not kind or len(kind) > 80:
            raise ValueError("kind must contain 1..80 characters")
        ref = ref or f"IP_{uuid.uuid4().hex[:16]}"
        with self.connect() as connection:
            self._insert_node(
                connection,
                ref=ref,
                content=content,
                origin=origin,
                kind=kind,
                outcome=outcome.strip() or "unknown",
                visible=visible,
                created_order=self._next_order(connection),
                session_id=session_id.strip() or "default",
                failure_condition=failure_condition.strip(),
                metadata=metadata or {},
            )
        return self.get_ip(ref)

    def add_relation(
        self,
        *,
        source_ref: str,
        target_ref: str,
        relation: str,
        weight: float = 1.0,
        note: str = "",
    ) -> dict[str, Any]:
        if not RELATION_PATTERN.fullmatch(relation):
            raise ValueError("relation must be lower-case snake_case with at most 64 characters")
        if not 0.0 <= weight <= 2.0:
            raise ValueError("weight must be between 0 and 2")
        edge_id = f"EDGE_{uuid.uuid4().hex[:16]}"
        with self.connect() as connection:
            present = {
                row["ref"]
                for row in connection.execute("SELECT ref FROM nodes WHERE ref IN (?, ?)", (source_ref, target_ref))
            }
            missing = sorted({source_ref, target_ref} - present)
            if missing:
                raise KeyError(f"missing edge endpoints: {missing}")
            self._insert_edge(
                connection,
                edge_id=edge_id,
                source=source_ref,
                target=target_ref,
                relation=relation,
                weight=weight,
                note=note[:2000],
            )
        return {
            "edge_id": edge_id,
            "source": source_ref,
            "target": target_ref,
            "relation": relation,
            "weight": weight,
            "note": note[:2000],
        }

    def set_observer_state(
        self,
        *,
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
        active_constraints = active_constraints or []
        changed_constraints = changed_constraints or []
        evidence = evidence or []
        open_questions = open_questions or []
        invalidates_refs = invalidates_refs or []
        recent_refs = recent_refs or []
        if not goal.strip():
            raise ValueError("goal is required")
        state_ref = f"STATE_{uuid.uuid4().hex[:16]}"
        change_ref = f"CHANGE_{uuid.uuid4().hex[:16]}" if changed_constraints else None
        metadata = {
            "goal": goal,
            "question": question,
            "active_constraints": active_constraints,
            "changed_constraints": changed_constraints,
            "evidence": evidence,
            "open_questions": open_questions,
            "current_reasoning_ref": current_reasoning_ref,
            "recent_refs": recent_refs,
        }
        content = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        with self.connect() as connection:
            refs_to_check = set(invalidates_refs + recent_refs)
            if current_reasoning_ref:
                refs_to_check.add(current_reasoning_ref)
            if refs_to_check:
                placeholders = ",".join("?" for _ in refs_to_check)
                present = {
                    row["ref"]
                    for row in connection.execute(
                        f"SELECT ref FROM nodes WHERE ref IN ({placeholders})", tuple(sorted(refs_to_check))
                    )
                }
                missing = sorted(refs_to_check - present)
                if missing:
                    raise KeyError(f"observer state references missing IPs: {missing}")
            order = self._next_order(connection)
            self._insert_node(
                connection,
                ref=state_ref,
                content=content,
                origin="current_observer_state",
                kind="current_state",
                outcome="active",
                visible=False,
                created_order=order,
                session_id=session_id,
                failure_condition="",
                metadata=metadata,
            )
            if change_ref:
                self._insert_node(
                    connection,
                    ref=change_ref,
                    content="; ".join(changed_constraints),
                    origin="state_change",
                    kind="state_change",
                    outcome="active",
                    visible=True,
                    created_order=order + 1,
                    session_id=session_id,
                    failure_condition="",
                    metadata={"changed_constraints": changed_constraints},
                )
                self._insert_edge(
                    connection,
                    edge_id=f"EDGE_{uuid.uuid4().hex[:16]}",
                    source=state_ref,
                    target=change_ref,
                    relation="contains_change",
                    weight=1.0,
                    note="Current observer state contains this change",
                )
                for target in invalidates_refs:
                    self._insert_edge(
                        connection,
                        edge_id=f"EDGE_{uuid.uuid4().hex[:16]}",
                        source=change_ref,
                        target=target,
                        relation="invalidates",
                        weight=1.0,
                        note="Changed condition invalidates the recorded constraint",
                    )
            for recent_ref in recent_refs:
                self._insert_edge(
                    connection,
                    edge_id=f"EDGE_{uuid.uuid4().hex[:16]}",
                    source=state_ref,
                    target=recent_ref,
                    relation="contains",
                    weight=1.0,
                    note="Recent evidence or evaluation in the current state",
                )
            if current_reasoning_ref:
                self._insert_edge(
                    connection,
                    edge_id=f"EDGE_{uuid.uuid4().hex[:16]}",
                    source=state_ref,
                    target=current_reasoning_ref,
                    relation="evolved_from",
                    weight=1.0,
                    note="Current state evolved from this reasoning position",
                )
        return {"observer_state_ref": state_ref, "state_change_ref": change_ref, "metadata": metadata}

    def record_evaluation(
        self,
        *,
        evaluates_ref: str,
        content: str,
        outcome: str,
        session_id: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        evaluation = self.add_ip(
            content=content,
            kind="evaluation",
            origin="evaluation",
            outcome=outcome,
            session_id=session_id,
            metadata=metadata,
        )
        edge = self.add_relation(
            source_ref=evaluation["ref"],
            target_ref=evaluates_ref,
            relation="evaluates",
            note="Evaluation of an observed reasoning result",
        )
        return {"evaluation": evaluation, "relation": edge}

    def get_ip(self, ref: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM nodes WHERE ref = ?", (ref,)).fetchone()
            if not row:
                raise KeyError(ref)
            edges = connection.execute(
                "SELECT edge_id, source, target, relation, weight, note FROM edges "
                "WHERE source = ? OR target = ? ORDER BY created_at, edge_id LIMIT 200",
                (ref, ref),
            ).fetchall()
        return {**self._node_dict(self._row_to_node(row)), "edges": [dict(edge) for edge in edges]}

    def list_recent(self, *, session_id: str = "default", limit: int = 20) -> dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM nodes WHERE session_id = ? ORDER BY created_order DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return {"session_id": session_id, "items": [self._node_dict(self._row_to_node(row)) for row in rows]}

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> Node:
        return Node(
            ref=row["ref"],
            content=row["content"],
            origin=row["origin"],
            kind=row["kind"],
            outcome=row["outcome"],
            visible=bool(row["visible"]),
            created_order=int(row["created_order"]),
            session_id=row["session_id"],
            failure_condition=row["failure_condition"],
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _node_dict(node: Node, *, content: str | None = None) -> dict[str, Any]:
        return {
            "ref": node.ref,
            "content": node.content if content is None else content,
            "origin": node.origin,
            "kind": node.kind,
            "outcome": node.outcome,
            "visible": node.visible,
            "created_order": node.created_order,
            "session_id": node.session_id,
            "failure_condition": node.failure_condition,
            "metadata": node.metadata,
        }

    def status(self) -> dict[str, Any]:
        with self.connect() as connection:
            counts = {
                row["origin"]: row["n"]
                for row in connection.execute("SELECT origin, COUNT(*) AS n FROM nodes GROUP BY origin")
            }
            edge_count = connection.execute("SELECT COUNT(*) AS n FROM edges").fetchone()["n"]
            retrieval_count = connection.execute("SELECT COUNT(*) AS n FROM retrieval_runs").fetchone()["n"]
            last_state = connection.execute(
                "SELECT ref, session_id, created_at FROM nodes WHERE kind = 'current_state' "
                "ORDER BY created_order DESC LIMIT 1"
            ).fetchone()
            report_row = connection.execute(
                "SELECT value_json FROM field_metadata WHERE key = 'canonical_seed_report'"
            ).fetchone()
        return {
            "database": str(self.db_path),
            "schema_version": 1,
            "node_count": sum(counts.values()),
            "nodes_by_origin": counts,
            "edge_count": edge_count,
            "retrieval_run_count": retrieval_count,
            "last_observer_state": dict(last_state) if last_state else None,
            "canonical_seed": json.loads(report_row["value_json"]) if report_row else None,
            "fold_unfold_lossless": self.verify_seed_roundtrip(),
            "privacy": "local_only",
        }

    def verify_seed_roundtrip(self) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM field_metadata WHERE key = 'canonical_seed_payload'"
            ).fetchone()
        return bool(row) and json.loads(row["value_json"]) == self._read_seed()

    def _load_graph(
        self, *, excluded_refs: set[str] | None = None, include_seed: bool = True
    ) -> tuple[dict[str, Node], list[Edge]]:
        excluded_refs = excluded_refs or set()
        with self.connect() as connection:
            node_rows = connection.execute("SELECT * FROM nodes ORDER BY ref").fetchall()
            edge_rows = connection.execute(
                "SELECT edge_id, source, target, relation, weight, note FROM edges ORDER BY relation, edge_id"
            ).fetchall()
        nodes = {}
        for row in node_rows:
            node = self._row_to_node(row)
            if node.ref in excluded_refs:
                continue
            if not include_seed and node.origin == "canonical_seed":
                continue
            nodes[node.ref] = node
        edges = [
            Edge(
                edge_id=row["edge_id"],
                source=row["source"],
                target=row["target"],
                relation=row["relation"],
                weight=float(row["weight"]),
                note=row["note"],
            )
            for row in edge_rows
            if row["source"] in nodes and row["target"] in nodes
        ]
        return nodes, edges

    @staticmethod
    def _adjacency(nodes: dict[str, Node], edges: list[Edge]) -> dict[str, list[tuple[str, Edge, str]]]:
        adjacent: dict[str, list[tuple[str, Edge, str]]] = {ref: [] for ref in nodes}
        for edge in edges:
            adjacent[edge.source].append((edge.target, edge, "outgoing"))
            adjacent[edge.target].append((edge.source, edge, "incoming"))
        for ref in adjacent:
            adjacent[ref].sort(key=lambda item: (item[1].relation, item[2], item[0], item[1].edge_id))
        return adjacent

    @staticmethod
    def _reachable_paths(
        start: str,
        nodes: dict[str, Node],
        edges: list[Edge],
        *,
        max_depth: int,
        candidate_limit: int = 500,
        path_limit_per_candidate: int = 8,
        expansion_limit: int = 20000,
    ) -> tuple[dict[str, list[list[dict[str, Any]]]], bool]:
        if start not in nodes:
            raise KeyError(start)
        adjacent = FieldStore._adjacency(nodes, edges)
        found: dict[str, list[list[dict[str, Any]]]] = {}
        queue = deque([(start, [], frozenset({start}))])
        expansions = 0
        truncated = False
        while queue:
            current, path, visited = queue.popleft()
            if len(path) >= max_depth:
                continue
            for other, edge, direction in adjacent[current]:
                expansions += 1
                if expansions > expansion_limit:
                    truncated = True
                    queue.clear()
                    break
                if other in visited:
                    continue
                if other not in found and len(found) >= candidate_limit:
                    truncated = True
                    continue
                step = {
                    "from": current,
                    "to": other,
                    "edge_id": edge.edge_id,
                    "type": edge.relation,
                    "direction": direction,
                    "semantic": reverse_semantic(edge.relation, direction),
                    "weight": edge.weight,
                }
                new_path = path + [step]
                paths = found.setdefault(other, [])
                paths.append(new_path)
                paths.sort(
                    key=lambda item: (
                        -structural_score(item),
                        len(item),
                        tuple((part["to"], part["type"], part["direction"]) for part in item),
                    )
                )
                if len(paths) > path_limit_per_candidate:
                    dropped = paths.pop()
                    if dropped is new_path:
                        continue
                queue.append((other, new_path, visited | {other}))
        return found, truncated

    @staticmethod
    def _has_change_chain(path: list[dict[str, Any]]) -> bool:
        invalidation_positions = [
            index
            for index, step in enumerate(path)
            if step["type"] == "invalidates" and step["direction"] == "outgoing"
        ]
        rejection_positions = [
            index
            for index, step in enumerate(path)
            if step["type"] == "rejected_by" and step["direction"] == "incoming"
        ]
        return any(left < right for left in invalidation_positions for right in rejection_positions)

    @staticmethod
    def _serialize_selected(
        selected: list[dict[str, Any]], nodes: dict[str, Node], *, per_item_chars: int, total_chars: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        remaining = total_chars
        visible: list[dict[str, Any]] = []
        truncations: list[str] = []
        for trace in selected:
            node = nodes[trace["candidate_ip"]]
            allowed = max(0, min(per_item_chars, remaining))
            original = node.content
            if len(original) > allowed:
                content = original[: max(0, allowed - 1)] + ("…" if allowed else "")
                truncations.append(node.ref)
            else:
                content = original
            if not content:
                break
            item = FieldStore._node_dict(node, content=content)
            item.update(
                {
                    "score": trace["final_score"],
                    "path": trace["path"],
                    "reason": trace["reason"],
                }
            )
            visible.append(item)
            remaining -= len(content)
            if remaining <= 0:
                break
        return visible, {
            "selected_count": len(selected),
            "visible_count": len(visible),
            "per_item_char_cap": per_item_chars,
            "total_char_cap": total_chars,
            "actual_content_chars": sum(len(item["content"]) for item in visible),
            "truncated_refs": truncations,
            "selection_serialization_match": [item["ref"] for item in visible]
            == [item["candidate_ip"] for item in selected[: len(visible)]],
        }

    def navigate(
        self,
        *,
        observer_state_ref: str,
        limit: int = 4,
        max_depth: int = 4,
        include_failures: bool = True,
        include_seed: bool = True,
        per_item_chars: int = 1500,
        total_chars: int = 5000,
        excluded_refs: set[str] | None = None,
        run_label: str = "observer_aware_topology",
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 12))
        max_depth = max(1, min(int(max_depth), 6))
        per_item_chars = max(100, min(int(per_item_chars), 5000))
        total_chars = max(500, min(int(total_chars), 20000))
        nodes, edges = self._load_graph(excluded_refs=excluded_refs, include_seed=include_seed)
        if observer_state_ref not in nodes:
            raise KeyError(observer_state_ref)
        state = nodes[observer_state_ref]
        if state.kind != "current_state":
            raise ValueError(f"{observer_state_ref} is not a CurrentObserverStateIP")
        paths, candidate_region_truncated = self._reachable_paths(
            observer_state_ref, nodes, edges, max_depth=max_depth
        )
        state_metadata = state.metadata
        observer_text = "\n".join(
            [
                str(state_metadata.get("question", "")),
                str(state_metadata.get("goal", "")),
                *[str(item) for item in state_metadata.get("active_constraints", [])],
                *[str(item) for item in state_metadata.get("changed_constraints", [])],
                *[str(item) for item in state_metadata.get("evidence", [])],
                *[str(item) for item in state_metadata.get("open_questions", [])],
            ]
        )
        provisional: list[dict[str, Any]] = []
        failed_outcomes = {"failure", "failed", "rejected"}
        for ref in sorted(paths):
            candidate_paths = paths[ref]
            best_path = sorted(
                candidate_paths,
                key=lambda path: (
                    -structural_score(path),
                    len(path),
                    tuple((step["to"], step["type"], step["direction"]) for step in path),
                ),
            )[0]
            node = nodes[ref]
            structural = structural_score(best_path)
            change_chain = self._has_change_chain(best_path)
            direct_change = any(
                step["type"] in {"contains_change", "invalidates"} and step["direction"] == "outgoing"
                for step in best_path
            )
            state_change_score = 1.0 if change_chain else 0.55 if direct_change else 0.0
            provenance = 1.0 if change_chain else 0.5 if any(
                step["type"] in {"invalidates", "evaluates", "depends_on"} for step in best_path
            ) else 0.0
            is_failure = node.outcome.lower() in failed_outcomes or node.origin == "failure_history"
            failure_relevance = 1.0 if change_chain and is_failure else 0.0
            goal = token_relevance(observer_text, node.content)
            distance = max(0, len(best_path) - 1) / max_depth
            stale = 1.0 if (
                best_path
                and best_path[0]["type"] == "evolved_from"
                and best_path[0]["direction"] == "outgoing"
                and is_failure
                and not change_chain
            ) else 0.0
            eligible = (
                node.visible
                and node.kind not in {"current_state", "domain_root", "bookkeeping"}
                and (include_failures or not is_failure)
            )
            provisional.append(
                {
                    "current_state_ip": observer_state_ref,
                    "candidate_ip": ref,
                    "origin": node.origin,
                    "outcome": node.outcome,
                    "path": best_path,
                    "edge_directions": [step["direction"] for step in best_path],
                    "edge_types": [step["type"] for step in best_path],
                    "structural_score": structural,
                    "goal_relevance_score": goal,
                    "state_change_score": state_change_score,
                    "provenance_relevance_score": provenance,
                    "failure_relevance_score": failure_relevance,
                    "distance_penalty": distance,
                    "redundancy_penalty": 0.0,
                    "stale_locality_penalty": stale,
                    "final_score": 0.0,
                    "eligible": eligible,
                    "selected": False,
                    "canonical_tie_key": ref,
                    "reason": "",
                }
            )

        selected: list[dict[str, Any]] = []
        remaining = [trace for trace in provisional if trace["eligible"]]
        while remaining and len(selected) < limit:
            for trace in remaining:
                node = nodes[trace["candidate_ip"]]
                redundancy = max(
                    (
                        token_relevance(node.content, nodes[item["candidate_ip"]].content)
                        for item in selected
                    ),
                    default=0.0,
                )
                trace["redundancy_penalty"] = redundancy
                trace["final_score"] = (
                    0.25 * trace["structural_score"]
                    + 0.15 * trace["goal_relevance_score"]
                    + 0.30 * trace["state_change_score"]
                    + 0.10 * trace["provenance_relevance_score"]
                    + 0.10 * trace["failure_relevance_score"]
                    - 0.05 * trace["distance_penalty"]
                    - 0.10 * trace["redundancy_penalty"]
                    - 0.15 * trace["stale_locality_penalty"]
                )
                trace["reason"] = (
                    "observer-aware: "
                    f"structural={trace['structural_score']:.4f}; "
                    f"goal={trace['goal_relevance_score']:.4f}; "
                    f"change={trace['state_change_score']:.4f}; "
                    f"provenance={trace['provenance_relevance_score']:.4f}; "
                    f"failure={trace['failure_relevance_score']:.4f}; "
                    f"distance={trace['distance_penalty']:.4f}; "
                    f"redundancy={trace['redundancy_penalty']:.4f}; "
                    f"stale={trace['stale_locality_penalty']:.4f}; "
                    f"final={trace['final_score']:.4f}"
                )
            chosen = sorted(remaining, key=lambda item: (-item["final_score"], item["candidate_ip"]))[0]
            chosen["selected"] = True
            selected.append(chosen)
            remaining.remove(chosen)

        for trace in provisional:
            if not trace["reason"]:
                trace["reason"] = "reachable but filtered before model-visible top-k"
        visible_items, serialization = self._serialize_selected(
            selected, nodes, per_item_chars=per_item_chars, total_chars=total_chars
        )
        run_id = f"RETRIEVAL_{uuid.uuid4().hex[:16]}"
        config = {
            "method": run_label,
            "limit": limit,
            "max_depth": max_depth,
            "include_failures": include_failures,
            "include_seed": include_seed,
            "per_item_chars": per_item_chars,
            "total_chars": total_chars,
            "excluded_refs": sorted(excluded_refs or set()),
        }
        stored_result = {
            "selected_refs": [trace["candidate_ip"] for trace in selected],
            "selected_items": visible_items,
            "serialization": serialization,
            "candidate_region_truncated": candidate_region_truncated,
            "candidate_count": len(provisional),
            "candidates": provisional,
        }
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO retrieval_runs(run_id, observer_state_ref, created_at, config_json, result_json) "
                "VALUES(?, ?, ?, ?, ?)",
                (
                    run_id,
                    observer_state_ref,
                    utc_now(),
                    json.dumps(config, ensure_ascii=False, sort_keys=True),
                    json.dumps(stored_result, ensure_ascii=False, sort_keys=True),
                ),
            )
        return {
            "run_id": run_id,
            "method": run_label,
            "observer_state_ref": observer_state_ref,
            "selected_refs": stored_result["selected_refs"],
            "selected_items": visible_items,
            "serialization": serialization,
            "candidate_count": len(provisional),
            "candidate_region_truncated": candidate_region_truncated,
            "trace_tool": "stoe_get_retrieval_trace",
        }

    def get_retrieval_trace(self, *, run_id: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 100))
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM retrieval_runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        result = json.loads(row["result_json"])
        candidates = result.pop("candidates")
        return {
            "run_id": run_id,
            "observer_state_ref": row["observer_state_ref"],
            "created_at": row["created_at"],
            "config": json.loads(row["config_json"]),
            **result,
            "candidate_page": candidates[offset : offset + limit],
            "candidate_offset": offset,
            "candidate_page_size": min(limit, max(0, len(candidates) - offset)),
            "candidate_total": len(candidates),
        }

    def prepare_counterfactual_contexts(
        self,
        *,
        observer_state_ref: str,
        focal_ip_ref: str,
        limit: int = 4,
        max_depth: int = 4,
        include_seed: bool = True,
    ) -> dict[str, Any]:
        if focal_ip_ref == observer_state_ref:
            raise ValueError("cannot remove the current observer state")
        self.get_ip(focal_ip_ref)
        with_ip = self.navigate(
            observer_state_ref=observer_state_ref,
            limit=limit,
            max_depth=max_depth,
            include_seed=include_seed,
            run_label="counterfactual_with_ip",
        )
        without_ip = self.navigate(
            observer_state_ref=observer_state_ref,
            limit=limit,
            max_depth=max_depth,
            include_seed=include_seed,
            excluded_refs={focal_ip_ref},
            run_label="counterfactual_without_ip",
        )
        focal_selected = focal_ip_ref in with_ip["selected_refs"]
        if not focal_selected:
            retrieval_effect = "FOCAL_NOT_SELECTED"
        elif with_ip["selected_refs"] == without_ip["selected_refs"]:
            retrieval_effect = "NO_CONTEXT_CHANGE"
        else:
            retrieval_effect = "RETRIEVAL_CONTEXT_CHANGED"
        return {
            "focal_ip_ref": focal_ip_ref,
            "with_ip": with_ip,
            "without_ip": without_ip,
            "retrieval_effect": retrieval_effect,
            "causal_status": "REPLAY_REQUIRED",
            "instruction": (
                "Replay the same final model decision once with each selected_items context. "
                "Only the paired model outcomes can classify necessity or contribution."
            ),
        }
