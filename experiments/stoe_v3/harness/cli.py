"""
Benchmark CLI
=============
Run the puzzle benchmark in one or both modes against a real LLM.

Usage:
    python -m harness.cli --mode topology
    python -m harness.cli --mode similarity
    python -m harness.cli --mode both --puzzles LG-001 LG-002 --seeds 3

By default uses the local Ollama at http://localhost:11434 with model llama3.
Override with --ollama-url and --model.

The output JSON reports are written to `runs/<timestamp>_<mode>.json`.
For --mode both, also writes `runs/<timestamp>_diff.json` containing the
side-by-side comparison required by paper 4 §6.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional

# Make the parent package importable
sys.path.insert(0, os.path.normpath(os.path.dirname(os.path.dirname(__file__))))

from core.llm import OllamaClient
from harness.runner import BenchmarkRunner, BenchmarkReport
from benchmark import grader as grader_mod  # noqa - importable as a package

PROJECT_ROOT = os.path.normpath(os.path.dirname(os.path.dirname(__file__)))
PUZZLES_PATH = os.path.join(PROJECT_ROOT, "benchmark", "puzzles.json")
SEED_PATH    = os.path.join(PROJECT_ROOT, "seed", "stoe_seed.json")
RUNS_DIR     = os.path.join(PROJECT_ROOT, "runs")


def load_puzzles(filter_ids: Optional[list[str]] = None) -> list[dict]:
    with open(PUZZLES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    pz = data["puzzles"]
    if filter_ids:
        wanted = set(filter_ids)
        pz = [p for p in pz if p["id"] in wanted]
    return pz


def run_one_mode(
    mode: str,
    puzzles: list[dict],
    seeds: int,
    ollama_url: str,
    model: str,
    max_attempts: int,
    fresh_per_puzzle: bool,
    field_storage: str,
    include_seed_ontology: bool = False,
    seed_path: Optional[str] = None,
    include_ontology_manifest: bool = False,
    mention_edges: bool = False,
) -> BenchmarkReport:
    llm = OllamaClient(base_url=ollama_url, model=model)
    runner = BenchmarkRunner(
        mode=mode,
        llm=llm,
        grader_module=grader_mod,
        seed_loader_path=seed_path or SEED_PATH,
        max_attempts=max_attempts,
        model_label=model,
        fresh_field_per_puzzle=fresh_per_puzzle,
        context_kwargs={"session_restricted": not include_seed_ontology},
        include_ontology_manifest=include_ontology_manifest,
        mention_edges=mention_edges,
    )
    return runner.run_benchmark(
        puzzles, seeds_per_puzzle=seeds,
        field_storage=field_storage,
    )


def diff_reports(t: BenchmarkReport, s: BenchmarkReport) -> dict:
    """
    Side-by-side comparison for paper 4 §6 / PLAN.md scoring protocol.

    Returns a dict with:
        topology_solve_rate
        similarity_solve_rate
        delta_solve_rate (topology − similarity, in pp)
        topology_failed_from_in_ctx
        similarity_failed_from_in_ctx
        ratio_failed_from        (topology / similarity, or None)
        verdict                   (strong_pass | weak_pass | falsification | undetermined)
    """
    ta = t.aggregate()
    sa = s.aggregate()
    dr = (ta["solve_rate"] - sa["solve_rate"]) * 100  # in pp

    t_ff = ta["total_failed_from_in_context"]
    s_ff = sa["total_failed_from_in_context"]
    ratio = (t_ff / s_ff) if s_ff > 0 else None

    # Apply the locked thresholds from PLAN.md slice 0.
    #
    # Strong pass requires both:
    #   (a) topology solve rate >= similarity + 15pp
    #   (b) topology shows >= 3x more failed_from traversal — OR similarity
    #       surfaces zero and topology surfaces some (qualitatively the
    #       strongest signal; the ratio is mathematically infinite).
    has_failed_from_advantage = (
        (ratio is not None and ratio >= 3.0)
        or (t_ff > 0 and s_ff == 0)
    )
    has_no_failed_from_diff = (
        (t_ff == 0 and s_ff == 0)
        or (ratio is not None and 0.9 <= ratio <= 1.1)
    )

    if dr >= 15 and has_failed_from_advantage:
        verdict = "strong_pass"
    elif abs(dr) < 1.0 and has_no_failed_from_diff:
        verdict = "falsification"
    elif dr > 0:
        verdict = "weak_pass"
    else:
        verdict = "undetermined"

    return {
        "topology": ta,
        "similarity": sa,
        "delta_solve_rate_pp": dr,
        "ratio_failed_from": ratio,
        "verdict": verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="SToE v3 benchmark — topology vs similarity context retrieval",
    )
    ap.add_argument("--mode", choices=("topology", "similarity", "both"),
                    default="both",
                    help="which retrieval mode to run (default: both)")
    ap.add_argument("--puzzles", nargs="*",
                    help="puzzle IDs to run (default: all)")
    ap.add_argument("--seeds", type=int, default=5,
                    help="seeds per puzzle (default: 5)")
    ap.add_argument("--max-attempts", type=int, default=3,
                    help="max attempts per puzzle (default: 3)")
    ap.add_argument("--fresh-field", action="store_true",
                    help="reset field between puzzles (default: shared field)")
    ap.add_argument("--include-seed-ontology", action="store_true",
                    help="let both context builders surface seed-ontology nodes "
                         "(cross-session). Default: both modes session-restricted.")
    ap.add_argument("--seed-path", default=None,
                    help="path to the seed ontology JSON. Default: seed/stoe_seed.json. "
                         "Use seed/music_theory_seed.json for the non-SToE control.")
    ap.add_argument("--ontology-manifest", action="store_true",
                    help="Option K: include a compact directory of field "
                         "ontology concepts in each LLM prompt. The LLM may "
                         "reference these by name during reasoning.")
    ap.add_argument("--mention-edges", action="store_true",
                    help="Option K: after each LLM response, scan for "
                         "mentions of ontology node names and create "
                         "`adjacent_to` edges. Implements paper 4 §5.3's "
                         "integration step.")
    ap.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    ap.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "llama3"))
    ap.add_argument("--out-dir", default=RUNS_DIR)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # Tee stdout to a per-run log file so the summary lines are preserved
    # alongside the JSON reports (useful for sharing).
    stdout_log_path = os.path.join(args.out_dir, f"{timestamp}.stdout.log")
    stdout_log = open(stdout_log_path, "w", encoding="utf-8")

    class _Tee:
        def __init__(self, *streams):
            self.streams = streams
        def write(self, s):
            for st in self.streams:
                try:
                    st.write(s); st.flush()
                except (ValueError, OSError):
                    pass  # closed stream (atexit cleanup race); drop
        def flush(self):
            for st in self.streams:
                try:
                    st.flush()
                except (ValueError, OSError):
                    pass
    sys.stdout = _Tee(sys.__stdout__, stdout_log)

    puzzles = load_puzzles(args.puzzles)
    if not puzzles:
        print("no puzzles to run", file=sys.stderr)
        return 2

    print(f"running {len(puzzles)} puzzles x {args.seeds} seeds "
          f"x mode={args.mode} via Ollama {args.model} @ {args.ollama_url}")
    print(f"  puzzles: {[p['id'] for p in puzzles]}")
    print(f"  max_attempts={args.max_attempts}  fresh_field={args.fresh_field}")

    reports: dict[str, BenchmarkReport] = {}
    modes_to_run = ("topology", "similarity") if args.mode == "both" else (args.mode,)
    for m in modes_to_run:
        print(f"\n=== mode: {m} ===")
        # The field is per-mode ephemeral storage; persist it under runs/
        # so we can inspect it post-hoc but it won't collide between modes.
        field_storage_path = os.path.join(args.out_dir, f"{timestamp}_{m}_field.json")
        rep = run_one_mode(
            mode=m, puzzles=puzzles, seeds=args.seeds,
            ollama_url=args.ollama_url, model=args.model,
            max_attempts=args.max_attempts,
            fresh_per_puzzle=args.fresh_field,
            field_storage=field_storage_path,
            include_seed_ontology=args.include_seed_ontology,
            seed_path=args.seed_path,
            include_ontology_manifest=args.ontology_manifest,
            mention_edges=args.mention_edges,
        )
        reports[m] = rep
        path = os.path.join(args.out_dir, f"{timestamp}_{m}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(rep.to_json())
        agg = rep.aggregate()
        print(f"  solve rate: {agg['solve_rate']:.2%} "
              f"({agg['solved_runs']}/{agg['total_runs']})")
        print(f"  failed_from in context (cumulative): {agg['total_failed_from_in_context']}")
        print(f"  -> {path}")

    if args.mode == "both":
        diff = diff_reports(reports["topology"], reports["similarity"])
        diff_path = os.path.join(args.out_dir, f"{timestamp}_diff.json")
        with open(diff_path, "w", encoding="utf-8") as f:
            json.dump(diff, f, indent=2, ensure_ascii=False)
        print("\n=== diff ===")
        print(f"  topology  solve_rate: {diff['topology']['solve_rate']:.2%}")
        print(f"  similarity solve_rate: {diff['similarity']['solve_rate']:.2%}")
        print(f"  delta (pp): {diff['delta_solve_rate_pp']:+.1f}")
        print(f"  failed_from ratio (T/S): {diff['ratio_failed_from']}")
        print(f"  VERDICT: {diff['verdict']}")
        print(f"  -> {diff_path}")
    print(f"\nstdout transcript saved -> {stdout_log_path}")
    stdout_log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
