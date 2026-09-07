from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .selector_loader import ARTIFACT_TYPES, load_selector_artifact, validate_selection


def evaluate(artifact: Path, artifact_type: str, cases_path: Path) -> dict:
    selector = load_selector_artifact(artifact, artifact_type)
    raw = cases_path.read_bytes()
    if len(raw) > 1_000_000:
        raise RuntimeError("protected case file exceeds trusted worker bound")
    cases = json.loads(raw.decode("utf-8"))
    if not isinstance(cases, list) or len(cases) > 512:
        raise RuntimeError("protected cases must be a bounded array")
    results = []
    for case in cases:
        try:
            first = validate_selection(
                selector(case["observer"], case["items"], case["max_items"], case["max_chars"]),
                case["items"],
                case["max_items"],
                case["max_chars"],
            )
            second = validate_selection(
                selector(case["observer"], case["items"], case["max_items"], case["max_chars"]),
                case["items"],
                case["max_items"],
                case["max_chars"],
            )
            deterministic = first == second
            required = set(case["required_refs"]).issubset(first)
            forbidden = bool(set(case.get("forbidden_refs", [])).intersection(first))
            passed = deterministic and required and not forbidden
            error = ""
        except Exception as exc:
            first = []
            deterministic = False
            required = False
            forbidden = False
            passed = False
            error = f"{type(exc).__name__}: {exc}"
        results.append(
            {
                "name": case["name"],
                "critical": bool(case.get("critical", False)),
                "passed": passed,
                "selected": first,
                "deterministic": deterministic,
                "required_present": required,
                "forbidden_present": forbidden,
                "error": error,
            }
        )
    return {
        "status": "completed",
        "artifact": str(artifact),
        "artifact_type": artifact_type,
        "pass_count": sum(1 for result in results if result["passed"]),
        "case_count": len(results),
        "critical_failures": [
            result["name"] for result in results if result["critical"] and not result["passed"]
        ],
        "passed_cases": [result["name"] for result in results if result["passed"]],
        "results": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--artifact-type", required=True, choices=sorted(ARTIFACT_TYPES))
    parser.add_argument("--cases", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.artifact.resolve(), args.artifact_type, args.cases.resolve())
    except Exception as exc:
        report = {
            "status": "rejected",
            "failure_kind": "worker_exception",
            "error": f"{type(exc).__name__}: {exc}",
            "pass_count": 0,
            "case_count": 0,
            "critical_failures": [],
            "passed_cases": [],
            "results": [],
        }
    sys.stdout.write(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
