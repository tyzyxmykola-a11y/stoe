from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any


SESSION_ID = "stoe-self-rebuild-v1"


def _load_field_store(repo_root: Path):
    core_path = repo_root / "plugins" / "stoe-memory" / "core.py"
    spec = importlib.util.spec_from_file_location("stoe_memory_core_for_agent", core_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load SToE memory core from {core_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.FieldStore


class RebuildJournal:
    def __init__(self, *, repo_root: Path, runtime_dir: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.runtime_dir = runtime_dir.resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        field_store = _load_field_store(self.repo_root)
        self.db_path = self.runtime_dir / "research_field.sqlite3"
        self.store = field_store(
            db_path=self.db_path,
            seed_path=self.repo_root / "plugins" / "stoe-memory" / "assets" / "stoe_seed.json",
        )
        self.store.initialize()

    @staticmethod
    def ref(cycle_id: str, label: str) -> str:
        safe = "".join(char if char.isalnum() else "_" for char in label).strip("_")
        return f"REBUILD_{cycle_id}_{safe}_{uuid.uuid4().hex[:6]}"

    def add_ip(
        self,
        *,
        cycle_id: str,
        label: str,
        content: str,
        kind: str,
        origin: str = "runtime_reasoning",
        outcome: str = "untested",
        failure_condition: str = "",
        metadata: dict[str, Any] | None = None,
        visible: bool = True,
    ) -> dict[str, Any]:
        merged = {"cycle_id": cycle_id, **(metadata or {})}
        return self.store.add_ip(
            ref=self.ref(cycle_id, label),
            content=content,
            kind=kind,
            origin=origin,
            outcome=outcome,
            failure_condition=failure_condition,
            session_id=SESSION_ID,
            metadata=merged,
            visible=visible,
        )

    def relate(self, source: str, target: str, relation: str, note: str) -> dict[str, Any]:
        return self.store.add_relation(
            source_ref=source,
            target_ref=target,
            relation=relation,
            note=note,
        )

    def observer_state(
        self,
        *,
        goal: str,
        evidence: list[str],
        recent_refs: list[str],
        current_reasoning_ref: str,
    ) -> dict[str, Any]:
        return self.store.set_observer_state(
            goal=goal,
            question="Should the proposed successor replace the active research-context selector?",
            active_constraints=[
                "protected evaluator and acceptance rule remain unchanged",
                "only the owned selector source may be generated",
                "activation must pass a fresh-process health check",
                "rollback must preserve research continuity",
            ],
            evidence=evidence,
            open_questions=["Will the candidate improve held-out observer-aware selection without regressions?"],
            recent_refs=recent_refs,
            current_reasoning_ref=current_reasoning_ref,
            session_id=SESSION_ID,
        )

    def record_evaluation(
        self,
        *,
        candidate_ref: str,
        content: str,
        outcome: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return self.store.record_evaluation(
            evaluates_ref=candidate_ref,
            content=content,
            outcome=outcome,
            session_id=SESSION_ID,
            metadata=metadata,
        )

    def snapshot(self, *, cycle_id: str) -> dict[str, str]:
        destination = self.runtime_dir / f"snapshot_{cycle_id}.sqlite3"
        with sqlite3.connect(self.db_path) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        return {"path": str(destination), "sha256": _sha256(destination)}

    def status(self) -> dict[str, Any]:
        status = self.store.status()
        status["recent"] = self.store.list_recent(session_id=SESSION_ID, limit=12)["items"]
        return status

    def find_cycle_nodes(self, cycle_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT ref, content, origin, kind, outcome, failure_condition, metadata_json "
                "FROM nodes WHERE metadata_json LIKE ? ORDER BY created_order ASC",
                (f"%{cycle_id}%",),
            ).fetchall()
        items = []
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            if metadata.get("cycle_id") != cycle_id:
                continue
            items.append(
                {
                    **{key: row[key] for key in row.keys() if key != "metadata_json"},
                    "metadata": metadata,
                }
            )
        return items

    def find_exact_content(self, content: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT ref, content, origin, kind, outcome, failure_condition, metadata_json "
                "FROM nodes WHERE session_id = ? AND content = ? ORDER BY created_order DESC LIMIT 1",
                (SESSION_ID, content),
            ).fetchone()
        if row is None:
            return None
        return {
            **{key: row[key] for key in row.keys() if key != "metadata_json"},
            "metadata": json.loads(row["metadata_json"]),
        }


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
