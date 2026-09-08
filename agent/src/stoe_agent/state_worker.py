from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .research_state import ResearchStateStore


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--checkpoint-dir", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--bootstrap", type=Path, default=None)
    parser.add_argument("--max-tokens", type=int, default=1800)
    args = parser.parse_args(argv)
    try:
        store = ResearchStateStore(
            runtime_dir=args.runtime_dir,
            checkpoint_dir=args.checkpoint_dir,
            bootstrap_path=args.bootstrap,
            project_root=args.project_root,
        )
        result = store.build_resume_context(max_tokens=args.max_tokens)
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 2
    sys.stdout.write(json.dumps({"ok": True, **result}, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
