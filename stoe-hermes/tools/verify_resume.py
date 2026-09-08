from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugins" / "stoe-memory"))
sys.path.insert(0, str(ROOT / "agent" / "src"))

from core import FieldStore
from stoe_agent.token_budget import TokenEstimator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=ROOT / "stoe-hermes" / "HERMES_AB_RESUME.json")
    parser.add_argument("--db", type=Path)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    tokens = TokenEstimator().estimate(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    if tokens > snapshot["budget"]["limit_tokens"]:
        raise RuntimeError("resume snapshot exceeds budget")
    store = FieldStore(args.db or Path(snapshot["canonical_field"]))
    refs = {
        "observer": snapshot["observer_state_ref"],
        "active": snapshot["active_release"]["state_ref"],
        "failure": snapshot["candidate"]["failure_ref"],
        "decision": snapshot["decision_ref"],
        "next_action": snapshot["next_action_ref"],
    }
    resolved = {name: store.get_ip(ref) for name, ref in refs.items()}
    print(json.dumps({
        "passed": True,
        "resume_tokens": tokens,
        "reserve_tokens": snapshot["budget"]["limit_tokens"] - tokens,
        "active_release": snapshot["active_release"]["release_id"],
        "candidate_status": snapshot["candidate"]["status"],
        "rollback_target": snapshot["active_release"]["rollback_target"],
        "next_action": resolved["next_action"]["content"],
        "resolved_refs": refs,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
