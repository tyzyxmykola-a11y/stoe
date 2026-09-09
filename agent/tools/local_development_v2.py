from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.local_development_pipeline import DEFAULT_ACTION, conserve_failed_coder, run_coder, run_planner, run_reviewer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Trusted Local Development v2 stage runner")
    parser.add_argument("command", choices=["planner", "coder", "reviewer", "test-analyst", "conserve-failed-coder"])
    parser.add_argument("--observer-state")
    parser.add_argument("--action-id", default=DEFAULT_ACTION)
    parser.add_argument("--difficulty", choices=["low", "medium", "high"], default="medium")
    parser.add_argument("--planner-result")
    parser.add_argument("--coder-action")
    parser.add_argument("--correction-ref")
    parser.add_argument("--test-evidence")
    args = parser.parse_args()
    if args.command == "conserve-failed-coder":
        value = conserve_failed_coder(args.action_id)
    elif not args.observer_state:
        parser.error(f"{args.command} requires --observer-state")
    elif args.command == "planner":
        value = run_planner(args.observer_state, args.action_id, difficulty=args.difficulty)
    elif args.command == "coder":
        if not args.planner_result:
            parser.error("coder requires --planner-result")
        value = run_coder(args.observer_state, args.planner_result, args.action_id, correction_ref=args.correction_ref)
    else:
        if not args.planner_result or not args.coder_action:
            parser.error("reviewer requires --planner-result and --coder-action")
        value = run_reviewer(args.observer_state, args.planner_result, args.coder_action, args.action_id, test_evidence=args.test_evidence if args.command == "test-analyst" else None)
    print(json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True))
    return 0 if value.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
