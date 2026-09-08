from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.self_code_cycle_v2 import SelfCodeCycleV2  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run supervised self-code-modification cycle v2")
    parser.add_argument("--allow-generation", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = SelfCodeCycleV2(repo_root=ROOT).run(allow_generation=args.allow_generation)
    rendered = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        args.output.resolve().write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
