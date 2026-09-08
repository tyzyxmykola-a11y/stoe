from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

from stoe_agent.self_code_cycle import SelfCodeModificationCycle  # noqa: E402
from stoe_agent.supervisor import RebuildSupervisor, SupervisorConfig  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one supervised source-candidate cycle")
    parser.add_argument("--objective", required=True)
    parser.add_argument("--allow-generation", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    supervisor = RebuildSupervisor(
        SupervisorConfig.defaults(repo_root=REPO_ROOT, model="gemma4:26b")
    )
    result = SelfCodeModificationCycle(supervisor).run(
        args.objective, allow_generation=args.allow_generation
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        args.output.resolve().write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
