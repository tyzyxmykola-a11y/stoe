from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

from stoe_agent.self_code_cycle import SelfCodeModificationCycle  # noqa: E402
from stoe_agent.supervisor import RebuildSupervisor, SupervisorConfig  # noqa: E402


ERROR = "Ollama returned malformed JSON: Unterminated string starting at line 4 column 14 (char 340)"


def main() -> int:
    supervisor = RebuildSupervisor(
        SupervisorConfig.defaults(repo_root=REPO_ROOT, model="gemma4:26b")
    )
    result = SelfCodeModificationCycle(supervisor).conserve_generation_failure(ERROR)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
