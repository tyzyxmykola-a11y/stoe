from __future__ import annotations

import argparse
import json
from pathlib import Path

from .supervisor import RebuildSupervisor, SupervisorConfig


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _supervisor(args) -> RebuildSupervisor:
    config = SupervisorConfig.defaults(
        repo_root=_repo_root(),
        model=getattr(args, "model", "qwen3-coder:latest"),
        runtime_dir=getattr(args, "runtime_dir", None),
    )
    return RebuildSupervisor(config)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Supervised SToE research-agent rebuild lifecycle")
    parser.add_argument("--runtime-dir", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("inspect")
    cycle = subparsers.add_parser("cycle")
    cycle.add_argument("--model", default="qwen3-coder:latest")
    subparsers.add_parser("status")
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--version", required=True)
    subparsers.add_parser("failure-probe")
    args = parser.parse_args(argv)

    supervisor = _supervisor(args)
    if args.command == "inspect":
        result = supervisor.inspect()
    elif args.command == "cycle":
        result = supervisor.run_cycle()
    elif args.command == "status":
        result = {
            "active": supervisor.read_active_pointer(),
            "persistent_field": supervisor.journal.status(),
        }
    elif args.command == "rollback":
        result = supervisor.rollback(args.version)
    elif args.command == "failure-probe":
        result = supervisor.failure_probe()
    else:
        parser.error(f"unknown command: {args.command}")
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0
