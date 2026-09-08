from __future__ import annotations

import argparse
import json
from pathlib import Path

from .supervisor import RebuildSupervisor, SupervisorConfig
from .structural_experiment import StructuralInputExperiment


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
    cycle.add_argument("--action-id", default=None)
    subparsers.add_parser("status")
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--version", required=True)
    subparsers.add_parser("failure-probe")
    checkpoint = subparsers.add_parser("checkpoint")
    checkpoint.add_argument("--reason", required=True)
    resume = subparsers.add_parser("resume")
    resume.add_argument("--max-tokens", type=int, default=1800)
    resume.add_argument("--known-hash", action="append", default=[], metavar="REF=SHA256")
    action = subparsers.add_parser("action")
    action.add_argument("--id", required=True)
    action.add_argument("--status", required=True, choices=["running", "completed", "uncertain", "failed"])
    action.add_argument("--description", default="")
    action.add_argument("--result-ref", action="append", default=[])
    question = subparsers.add_parser("record-next-question")
    question.add_argument("--report", required=True, type=Path)
    capability = subparsers.add_parser("record-capability-checkpoint")
    capability.add_argument("--report", required=True, type=Path)
    continuity = subparsers.add_parser("record-continuity-checkpoint")
    continuity.add_argument("--report", required=True, type=Path)
    state_update = subparsers.add_parser("state-update")
    state_update.add_argument("--current-task")
    state_update.add_argument("--next-step")
    artifact = subparsers.add_parser("artifact")
    artifact.add_argument("--ref", required=True)
    artifact.add_argument("--path", required=True, type=Path)
    artifact.add_argument("--summary", required=True)
    artifact.add_argument("--kind", required=True)
    artifact.add_argument("--provenance", required=True)
    artifact.add_argument("--source-ref", action="append", default=[])
    replay = subparsers.add_parser("replay")
    replay.add_argument("--source", required=True, type=Path)
    replay.add_argument("--output", type=Path, default=None)
    structural = subparsers.add_parser("structural-experiment")
    structural.add_argument("--spec", required=True, type=Path)
    structural.add_argument("--allow-generation", action="store_true")
    args = parser.parse_args(argv)

    supervisor = _supervisor(args)
    if args.command == "inspect":
        result = supervisor.inspect()
    elif args.command == "cycle":
        result = supervisor.run_cycle(action_id=args.action_id)
    elif args.command == "status":
        result = {
            "active": supervisor.read_active_pointer(),
            "persistent_field": supervisor.journal.status(),
        }
    elif args.command == "rollback":
        result = supervisor.rollback(args.version)
    elif args.command == "failure-probe":
        result = supervisor.failure_probe()
    elif args.command == "checkpoint":
        result = supervisor.checkpoint_research_state(args.reason)
    elif args.command == "resume":
        known_hashes = {}
        for item in args.known_hash:
            if "=" not in item:
                parser.error("--known-hash must be REF=SHA256")
            ref, digest = item.split("=", 1)
            known_hashes[ref] = digest
        result = supervisor.resume_research_context(max_tokens=args.max_tokens, known_hashes=known_hashes)
    elif args.command == "action":
        if args.status == "running":
            result = supervisor.research_state.begin_action(
                action_id=args.id,
                description=args.description or args.id,
            )
        else:
            result = supervisor.research_state.set_action_status(
                action_id=args.id,
                status=args.status,
                result_refs=args.result_ref,
            )
    elif args.command == "record-next-question":
        result = supervisor.record_next_research_question(args.report)
    elif args.command == "record-capability-checkpoint":
        result = supervisor.record_capability_boundary_checkpoint(args.report)
    elif args.command == "record-continuity-checkpoint":
        result = supervisor.record_continuity_reconciliation_checkpoint(args.report)
    elif args.command == "state-update":
        state = supervisor.research_state.load()
        if args.current_task is not None:
            state["current_task"] = args.current_task
        if args.next_step is not None:
            state["next_executable_step"] = args.next_step
        supervisor.research_state.save(state)
        result = {"updated": True, "current_task": state["current_task"], "next_executable_step": state["next_executable_step"]}
    elif args.command == "artifact":
        result = supervisor.research_state.register_artifact(
            ref=args.ref,
            path=args.path,
            summary=args.summary,
            kind=args.kind,
            provenance=args.provenance,
            source_refs=args.source_ref,
        )
    elif args.command == "replay":
        result = supervisor.replay_selector(args.source)
        if args.output is not None:
            RebuildSupervisor._atomic_write_json(args.output.resolve(), result)
            result["output_path"] = str(args.output.resolve())
    elif args.command == "structural-experiment":
        result = StructuralInputExperiment(supervisor, args.spec).run(
            allow_generation=args.allow_generation
        )
    else:
        parser.error(f"unknown command: {args.command}")
    # ASCII escaping keeps structured output printable on Windows hosts whose
    # inherited console encoding cannot represent model-generated Unicode.
    print(json.dumps(result, indent=2, ensure_ascii=True, sort_keys=True))
    return 0
