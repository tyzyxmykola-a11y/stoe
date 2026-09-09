from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.function_candidate import reconstruct_module, target_function  # noqa: E402
from stoe_agent.self_code_cycle_v2 import validate_candidate_source  # noqa: E402


TARGET = ROOT / "agent" / "src" / "stoe_agent" / "development_report.py"
FUNCTION = "render_retrieved_context"


def _load_validated(candidate_path: Path):
    parent = TARGET.read_text(encoding="utf-8")
    candidate = candidate_path.read_text(encoding="utf-8")
    validate_candidate_source(parent, candidate)
    parent_node, parent_function = target_function(parent, FUNCTION)
    candidate_node, candidate_function = target_function(candidate, FUNCTION)
    if parent_node.name != candidate_node.name:
        raise RuntimeError("candidate function identity mismatch")
    artifact = {
        "format": "stoe.function_replacement",
        "path": "agent/src/stoe_agent/development_report.py",
        "function": FUNCTION,
        "parent_function_sha256": __import__("hashlib").sha256(parent_function.encode("utf-8")).hexdigest(),
        "replacement_source": candidate_function,
    }
    if reconstruct_module(parent, artifact, expected_path=artifact["path"], expected_function=FUNCTION) != candidate:
        raise RuntimeError("candidate is not an exact function-only reconstruction")
    spec = importlib.util.spec_from_file_location("stoe_validated_development_report_candidate", candidate_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load validated candidate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render_retrieved_context


def evaluate(candidate_path: Path) -> dict:
    render = _load_validated(candidate_path)
    shared = "a" * 64
    duplicate = [
        {"ref": "A", "origin": "evaluation", "kind": "report", "outcome": "failed", "path": "A->X", "content": "same evidence", "payload_sha256": shared},
        {"ref": "B", "origin": "failure_history", "kind": "correction", "outcome": "corrected", "path": "B->Y", "content": "same evidence", "payload_sha256": shared},
    ]
    before = copy.deepcopy(duplicate)
    observed = render(duplicate, 4000)
    checks = {
        "canonical_content_once": observed.count("same evidence") == 1,
        "all_refs_preserved": observed.count("A") >= 1 and observed.count("B") >= 1,
        "all_paths_preserved": "A->X" in observed and "B->Y" in observed,
        "canonical_count": "canonical_payload_count=1" in observed,
        "collapsed_count": "collapsed_duplicate_count=1" in observed,
        "input_immutable": duplicate == before,
    }
    unhashed = [
        {"ref": "U1", "origin": "x", "kind": "x", "outcome": "x", "path": "P1", "content": "unhashed same"},
        {"ref": "U2", "origin": "x", "kind": "x", "outcome": "x", "path": "P2", "content": "unhashed same"},
    ]
    unhashed_observed = render(unhashed, 4000)
    checks["unhashed_remain_distinct"] = unhashed_observed.count("unhashed same") == 2
    checks["budget_bound"] = len(render(duplicate, 80)) <= 80
    try:
        render(duplicate, -1)
    except ValueError:
        checks["negative_rejected"] = True
    else:
        checks["negative_rejected"] = False
    return {"passed": all(checks.values()), "checks": checks, "observed": observed[:1000], "unhashed_observed": unhashed_observed[:1000]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.candidate.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
