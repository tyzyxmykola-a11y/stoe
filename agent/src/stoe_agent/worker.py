from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import sys
from pathlib import Path

from .selector_loader import infer_artifact_type, load_selector_artifact, sha256_file, validate_selection
from .public_worker import BoundedTextSink


def run_health_check(*, active_pointer: Path, field_db: Path) -> dict:
    pointer = json.loads(active_pointer.read_text(encoding="utf-8"))
    source_path = Path(pointer["source_path"]).resolve()
    if sha256_file(source_path) != pointer["sha256"]:
        raise RuntimeError("active source hash does not match activation pointer")
    observer = {
        "goal": "Retrieve the measured evaluation for fresh-process continuation",
        "active_constraints": ["bounded context"],
        "changed_constraints": [],
        "evidence": ["evaluation is available"],
        "open_questions": [],
        "__activation_probe__": True,
    }
    items = [
        {
            "ref": "HEALTH_EVAL",
            "content": "The measured evaluation recorded a successful fresh-process continuation.",
            "origin": "evaluation",
            "kind": "evaluation",
            "outcome": "supported",
            "failure_condition": "",
            "created_order": 2,
        },
        {
            "ref": "HEALTH_NOTE",
            "content": "A generic planning note remains available.",
            "origin": "runtime_reasoning",
            "kind": "plan",
            "outcome": "untested",
            "failure_condition": "",
            "created_order": 1,
        },
    ]
    captured_stdout = BoundedTextSink()
    captured_stderr = BoundedTextSink()
    with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
        artifact_type = str(pointer.get("artifact_type") or infer_artifact_type(source_path))
        selector = load_selector_artifact(source_path, artifact_type)
        selected = validate_selection(selector(observer, items, 1, 180), items, 1, 180)
    if not selected:
        raise RuntimeError("active selector returned no context during health check")

    with sqlite3.connect(field_db) as connection:
        node_count = int(connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0])
        latest = connection.execute(
            "SELECT ref, kind, outcome FROM nodes ORDER BY created_order DESC LIMIT 1"
        ).fetchone()
        seed_row = connection.execute(
            "SELECT value_json FROM field_metadata WHERE key='canonical_seed_sha256'"
        ).fetchone()
    if not seed_row:
        raise RuntimeError("persistent field does not contain canonical seed identity")
    return {
        "healthy": True,
        "active_version": pointer["version"],
        "active_sha256": pointer["sha256"],
        "active_artifact_type": artifact_type,
        "selected": selected,
        "persistent_node_count": node_count,
        "latest_persistent_ip": list(latest) if latest else None,
        "canonical_seed_sha256": json.loads(seed_row[0]),
        "candidate_stdout": captured_stdout.result(),
        "candidate_stderr": captured_stderr.result(),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-pointer", required=True, type=Path)
    parser.add_argument("--field-db", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_health_check(
            active_pointer=args.active_pointer.resolve(),
            field_db=args.field_db.resolve(),
        )
    except Exception as exc:
        sys.stdout.write(json.dumps({"healthy": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
