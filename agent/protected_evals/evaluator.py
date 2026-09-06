from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def load_selector(path: Path):
    spec = importlib.util.spec_from_file_location("candidate_under_evaluation", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    selector = getattr(module, "select_context", None)
    if not callable(selector):
        raise TypeError("select_context is missing")
    return selector


def validate_output(selected, items, max_items, max_chars):
    if not isinstance(selected, list) or not all(isinstance(ref, str) for ref in selected):
        raise TypeError("output must be list[str]")
    if len(selected) != len(set(selected)):
        raise ValueError("duplicate refs")
    if len(selected) > max_items:
        raise ValueError("max_items exceeded")
    by_ref = {item["ref"]: item for item in items}
    if any(ref not in by_ref for ref in selected):
        raise ValueError("unknown ref returned")
    if sum(len(str(by_ref[ref].get("content", ""))) for ref in selected) > max_chars:
        raise ValueError("max_chars exceeded")


def evaluate(source_path: Path, cases_path: Path) -> dict:
    selector = load_selector(source_path)
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        try:
            first = selector(case["observer"], case["items"], case["max_items"], case["max_chars"])
            second = selector(case["observer"], case["items"], case["max_items"], case["max_chars"])
            validate_output(first, case["items"], case["max_items"], case["max_chars"])
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
        "source": str(source_path),
        "pass_count": sum(1 for result in results if result["passed"]),
        "case_count": len(results),
        "critical_failures": [
            result["name"] for result in results if result["critical"] and not result["passed"]
        ],
        "passed_cases": [result["name"] for result in results if result["passed"]],
        "results": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--cases", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.source.resolve(), args.cases.resolve())
    except Exception as exc:
        report = {"fatal_error": f"{type(exc).__name__}: {exc}", "pass_count": 0, "case_count": 0}
    sys.stdout.write(json.dumps(report, sort_keys=True))
    return 0 if "fatal_error" not in report else 2


if __name__ == "__main__":
    raise SystemExit(main())
