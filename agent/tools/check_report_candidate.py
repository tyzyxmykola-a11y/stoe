from __future__ import annotations

import copy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.development_report import render_retrieved_context  # noqa: E402


def main() -> int:
    items = [
        {"ref": "A", "origin": "evaluation", "kind": "result", "outcome": "supported", "path": ["state", "evaluates", "A"], "content": "canonical payload", "sha256": "1" * 64},
        {"ref": "B", "origin": "failure_history", "kind": "result", "outcome": "failed", "path": ["state", "invalidates", "B"], "content": "canonical payload", "sha256": "1" * 64},
        {"ref": "C", "origin": "runtime_reasoning", "kind": "note", "outcome": "active", "path": ["state", "contains", "C"], "content": "unhashed duplicate"},
        {"ref": "D", "origin": "runtime_reasoning", "kind": "note", "outcome": "active", "path": ["state", "contains", "D"], "content": "unhashed duplicate"},
    ]
    before = copy.deepcopy(items)
    rendered = render_retrieved_context(items, 4000)
    assert items == before, "candidate mutated input"
    assert rendered.startswith("[dedup] collapsed_payload_copies=1")
    assert rendered.count("canonical payload") == 1
    for ref in ("A", "B", "C", "D"):
        assert ref in rendered, f"connection {ref} was lost"
    assert rendered.count("unhashed duplicate") == 2
    assert len(render_retrieved_context(items, 180)) <= 180
    try:
        render_retrieved_context(items, -1)
    except ValueError:
        pass
    else:
        raise AssertionError("negative budget did not fail")
    print("focused candidate contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
