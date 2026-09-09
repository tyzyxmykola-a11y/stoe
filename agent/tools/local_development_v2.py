from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.local_development_pipeline import DEFAULT_ACTION, run_coder, run_planner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Trusted Local Development v2 stage runner")
    parser.add_argument("command", choices=["planner", "coder"])
    parser.add_argument("--observer-state", required=True)
    parser.add_argument("--action-id", default=DEFAULT_ACTION)
    parser.add_argument("--difficulty", choices=["low", "medium", "high"], default="medium")
    parser.add_argument("--planner-result")
    args = parser.parse_args()
    if args.command == "planner":
        value = run_planner(args.observer_state, args.action_id, difficulty=args.difficulty)
    else:
        if not args.planner_result:
            parser.error("coder requires --planner-result")
        value = run_coder(args.observer_state, args.planner_result, args.action_id)
    print(json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True))
    return 0 if value.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
