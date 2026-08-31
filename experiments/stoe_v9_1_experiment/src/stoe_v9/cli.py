from __future__ import annotations

import argparse
import json
from pathlib import Path

from .providers import DeterministicMockProvider, GenerationParams, OllamaClient, OllamaEmbedder
from .retrieval import DeterministicHashEmbedder
from .runner import ALL_CONDITIONS, ExperimentRunner, write_results
from .tasks import build_task_graph, load_tasks


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--tasks", required=True)
    run = commands.add_parser("run")
    run.add_argument("--tasks", required=True)
    run.add_argument("--provider", choices=["ollama", "mock"], default="mock")
    run.add_argument("--api-base", default="http://127.0.0.1:11434")
    run.add_argument("--model", default="qwen3.5:4b")
    run.add_argument("--model-digest")
    run.add_argument("--embedding-model", default="qwen3-embedding:0.6b")
    run.add_argument("--embedding-digest")
    run.add_argument("--output", required=True)
    run.add_argument("--allow-primary", action="store_true")
    run.add_argument("--no-counterfactuals", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    tasks = load_tasks(args.tasks)
    if args.command == "validate":
        for task in tasks:
            graph, state = build_task_graph(task)
            if len(graph.eligible_refs()) < 4:
                raise SystemExit(f"{task.id}: fewer than four eligible artifacts")
            if state.ref not in graph.nodes:
                raise SystemExit(f"{task.id}: missing observer state")
        print(json.dumps({"tasks": len(tasks), "valid": True}))
        return 0
    if "benchmarks" in Path(args.tasks).parts and not args.allow_primary:
        raise SystemExit("Primary benchmark execution is locked; pass --allow-primary only after a future freeze gate.")
    answers = {task.id: task.expected_answer for task in tasks}
    if args.provider == "ollama":
        provider = OllamaClient(args.api_base, args.model_digest)
        embedder = OllamaEmbedder(args.api_base, args.embedding_model, args.embedding_digest)
    else:
        provider = DeterministicMockProvider(answers)
        embedder = DeterministicHashEmbedder()
    runner = ExperimentRunner(
        provider=provider,
        params=GenerationParams(model=args.model),
        embedder=embedder,
    )
    result = runner.run(tasks, ALL_CONDITIONS, counterfactuals=not args.no_counterfactuals)
    write_results(result, args.output)
    print(json.dumps({"output": args.output, "rows": len(result["results"]), "status": result["status"]}))
    return 0
