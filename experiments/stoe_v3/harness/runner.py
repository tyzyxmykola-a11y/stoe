"""
Benchmark runner
================
Runs the puzzle benchmark (`benchmark/puzzles.json`) against a model.
Each puzzle is attempted up to `max_attempts` times with failure
conservation: if attempt K is graded wrong, a `failed_from` edge is
added so attempt K+1 can navigate to the conserved failure (in topology
mode).

This is the slice-4 vessel. It is what makes the difference between
topology and similarity context retrieval *measurable* on a problem
class where backtracking is genuinely required.

Output is a structured `BenchmarkReport` (also serializable to JSON)
that records, per puzzle and per seed:
  • whether the puzzle was solved
  • number of attempts before solving (or max_attempts if unsolved)
  • number of `failed_from` edges traversed in the context block
  • the final answer text
  • the structural verdict on the final node

Aggregation is done at report time, not during the run, so a partial run
(e.g. one mode finished, the other crashed) still has analyzable data.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field as dc_field, asdict
from typing import Optional

from core.field import InformationField
from core.seed_loader import load_seed_if_empty
from core.llm import LLMClient
from core.evaluator import StructuralEvaluator, Verdict

from .context import ContextBuilder, get_builder


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AttemptRecord:
    attempt_idx: int
    final_answer_extracted: Optional[str]   # what the grader saw
    correct: bool
    grader_reason: str
    response_chars: int
    failed_from_neighbors_in_context: int
    structural_verdict: Optional[dict] = None
    response_tail: Optional[str] = None     # last 400 chars of LLM output (diagnostic)
    mention_edges_created: int = 0          # Option K: ontology concepts the LLM referenced


@dataclass
class PuzzleRunRecord:
    """One run = one (puzzle, seed_idx) pair across attempts."""
    puzzle_id: str
    seed_idx: int
    attempts: list[AttemptRecord] = dc_field(default_factory=list)
    solved: bool = False
    attempts_to_solve: Optional[int] = None  # None if unsolved
    duration_s: float = 0.0


@dataclass
class BenchmarkReport:
    mode: str                         # "topology" | "similarity"
    model_label: str                  # informational
    runs: list[PuzzleRunRecord] = dc_field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    # Aggregate computed at report time
    def aggregate(self) -> dict:
        total = len(self.runs)
        solved = sum(1 for r in self.runs if r.solved)
        # group by puzzle
        per_puzzle: dict[str, list[PuzzleRunRecord]] = {}
        for r in self.runs:
            per_puzzle.setdefault(r.puzzle_id, []).append(r)
        per_puzzle_solve = {
            pid: sum(1 for r in runs_ if r.solved)
            for pid, runs_ in per_puzzle.items()
        }
        avg_attempts_when_solved = (
            sum(r.attempts_to_solve for r in self.runs if r.solved) / solved
            if solved else None
        )
        total_attempts = sum(len(r.attempts) for r in self.runs)
        total_failed_from_in_ctx = sum(
            a.failed_from_neighbors_in_context
            for r in self.runs for a in r.attempts
        )
        return {
            "mode": self.mode,
            "model": self.model_label,
            "total_runs": total,
            "solved_runs": solved,
            "solve_rate": (solved / total) if total else 0.0,
            "per_puzzle_solve": per_puzzle_solve,
            "avg_attempts_when_solved": avg_attempts_when_solved,
            "total_attempts_made": total_attempts,
            "total_failed_from_in_context": total_failed_from_in_ctx,
        }

    def to_json(self) -> str:
        return json.dumps({
            "header": {
                "mode": self.mode,
                "model": self.model_label,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            },
            "aggregate": self.aggregate(),
            "runs": [
                {**asdict(r),
                 "attempts": [asdict(a) for a in r.attempts]}
                for r in self.runs
            ],
        }, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class BenchmarkRunner:
    """
    Drives the benchmark on one mode (topology or similarity) with one
    LLM client. Use two instances (one per mode) for the comparison.

    The field is shared across all puzzles in a single run by default —
    this is paper 4's intended setting (large solution space, conserved
    state). Pass `fresh_field_per_puzzle=True` to reset the field
    between puzzles for a tighter ablation.
    """

    def __init__(
        self,
        mode: str,
        llm: LLMClient,
        grader_module,
        seed_loader_path: Optional[str] = None,
        max_attempts: int = 3,
        context_kwargs: Optional[dict] = None,
        model_label: str = "unknown",
        fresh_field_per_puzzle: bool = False,
        evaluate_attempts: bool = True,
        include_ontology_manifest: bool = False,
        mention_edges: bool = False,
    ):
        self.mode = mode
        self.llm = llm
        self.grader = grader_module
        self.seed_loader_path = seed_loader_path
        self.max_attempts = max_attempts
        self.context_builder: ContextBuilder = get_builder(
            mode, **(context_kwargs or {})
        )
        self.model_label = model_label
        self.fresh_field_per_puzzle = fresh_field_per_puzzle
        self.evaluate_attempts = evaluate_attempts
        self.evaluator = StructuralEvaluator()
        # Option K: ontology manifest in prompt + mention-edge recording
        self.include_ontology_manifest = include_ontology_manifest
        self.mention_edges = mention_edges

    # ---- core ----

    def run_puzzle(
        self,
        puzzle: dict,
        field: InformationField,
        seed_idx: int,
    ) -> PuzzleRunRecord:
        record = PuzzleRunRecord(
            puzzle_id=puzzle["id"],
            seed_idx=seed_idx,
        )
        t0 = time.time()
        session_id = f"{puzzle['id']}_seed{seed_idx}_{self.mode}"

        # Add the puzzle statement as a Seed node.
        seed_node = field.add_point(
            content=f"PUZZLE [{puzzle['id']}]: {puzzle['statement']}",
            category="Seed",
            session_id=session_id,
            metadata={"puzzle_id": puzzle["id"], "seed_idx": seed_idx},
        )
        current_node = seed_node

        # Option K: prepare the ontology manifest once per puzzle (it doesn't
        # change between attempts of the same session).
        manifest = None
        if self.include_ontology_manifest:
            manifest = field.get_ontology_manifest(session_id=session_id,
                                                   max_items=40)

        for attempt_idx in range(self.max_attempts):
            ctx_block = self.context_builder.build(field, current_node)

            # Count failed_from neighbours actually visible in the context
            # (this is the diagnostic that distinguishes the modes).
            failed_in_ctx = ctx_block.count("failed_from")

            prompt = self._build_prompt(puzzle, ctx_block, manifest=manifest)

            try:
                response = self.llm.call(prompt)
                response_text = (response or "").strip()
            except Exception as e:
                # LLM transport failure — conserve as Ghost, count as
                # a failed attempt that doesn't get re-tried (harness
                # treats transport failures as fatal for that attempt
                # so test runs aren't masked by network noise).
                ghost = field.add_failed(
                    from_id=current_node,
                    reason=f"LLM transport failure: {type(e).__name__}: {e}",
                    operator="@runner",
                    session_id=session_id,
                )
                record.attempts.append(AttemptRecord(
                    attempt_idx=attempt_idx,
                    final_answer_extracted=None,
                    correct=False,
                    grader_reason=f"transport_error: {e}",
                    response_chars=0,
                    failed_from_neighbors_in_context=failed_in_ctx,
                ))
                current_node = ghost
                continue

            # Add the attempt as a node.
            attempt_node = field.add_point(
                content=response_text,
                category="Attempt",
                operator="@runner",
                session_id=session_id,
                metadata={
                    "puzzle_id": puzzle["id"],
                    "attempt_idx": attempt_idx,
                    "mode": self.mode,
                },
            )
            field.connect(attempt_node, current_node, edge_type="generated_by",
                          note=f"attempt {attempt_idx}")

            # Option K: record mention edges. The LLM (observer) named these
            # concepts in its response; the field records the naming as
            # adjacent_to edges. Subsequent topology traversal can navigate
            # them. Law of Connection compliant: an observer caused each edge.
            mentions_recorded = 0
            if self.mention_edges and manifest:
                mentions_recorded = self._record_mention_edges(
                    field, attempt_node, response_text, manifest
                )

            # Grade.
            verdict = self.grader.grade(puzzle, response_text)

            # Optional: structural verdict on the attempt node itself.
            structural = None
            if self.evaluate_attempts:
                v = self.evaluator.evaluate(
                    field, attempt_node, seed_id=seed_node,
                    session_id=session_id, write_verdict=True,
                )
                structural = {
                    "novelty": v.novelty,
                    "coherence_penalty": v.coherence_penalty,
                    "bridging": v.bridging,
                    "attractor_distance": v.attractor_distance,
                    "composite_score": v.composite_score(),
                }

            record.attempts.append(AttemptRecord(
                attempt_idx=attempt_idx,
                final_answer_extracted=str(verdict.extracted) if verdict.extracted is not None else None,
                correct=verdict.correct,
                grader_reason=verdict.reason,
                response_chars=len(response_text),
                failed_from_neighbors_in_context=failed_in_ctx,
                structural_verdict=structural,
                response_tail=response_text[-400:] if response_text else None,
                mention_edges_created=mentions_recorded,
            ))

            if verdict.correct:
                record.solved = True
                record.attempts_to_solve = attempt_idx + 1
                break

            # Conserve the failure so the next attempt's topology context
            # can navigate to it.
            field.add_failed(
                from_id=attempt_node,
                reason=f"grader rejected: {verdict.reason}",
                operator="@runner",
                session_id=session_id,
            )
            # The next iteration's `current_node` is the failed attempt;
            # this means depth-1 navigation from current_node finds the
            # ghost via failed_from — which is exactly what topology
            # context will surface, and similarity context will miss.
            current_node = attempt_node

        record.duration_s = time.time() - t0
        return record

    # ---- Option K: mention-edge recording ----

    @staticmethod
    def _normalize_for_match(name: str) -> str:
        """Strip parentheticals and lowercase for substring matching."""
        import re
        n = re.sub(r"\s*\([^)]*\)", "", name).strip().lower()
        return n

    @staticmethod
    def _record_mention_edges(
        field: InformationField,
        attempt_node_id: str,
        response_text: str,
        manifest: list[dict],
    ) -> int:
        """
        Scan response_text for mentions of ontology node names from `manifest`.
        For each match, create an `adjacent_to` edge from the attempt node
        to the matched ontology node.

        Law of Connection compliance: the LLM (observer) named the concept;
        the field records the naming as a navigable edge. Subsequent topology
        traversal at later attempts surfaces these edges.

        Returns count of edges created.
        """
        if not response_text or not manifest:
            return 0
        response_lower = response_text.lower()
        created = 0
        for m in manifest:
            name = m.get("name", "")
            if not name:
                continue
            needle = BenchmarkRunner._normalize_for_match(name)
            if len(needle) < 3:
                continue
            count = response_lower.count(needle)
            if count == 0:
                continue
            field.connect(
                attempt_node_id, m["id"],
                edge_type="adjacent_to",
                weight=float(count),
                note=f"observer-mentioned {count}x: {name}",
            )
            created += 1
        return created

    # ---- prompt assembly ----

    @staticmethod
    def _build_prompt(
        puzzle: dict,
        ctx_block: str,
        manifest: Optional[list[dict]] = None,
    ) -> str:
        head = (
            "You are solving a puzzle. Reason briefly step by step (5 lines or fewer).\n"
            "Then on a NEW LINE output ONLY:\n"
            "  FINAL_ANSWER: <answer>\n"
            "Use the EXACT answer format specified. Do not add commentary after FINAL_ANSWER.\n"
            "If you cannot determine the answer, still output FINAL_ANSWER: unknown\n\n"
        )
        # Ontology manifest (Option K): make the field's existing concepts
        # discoverable to the LLM, so it can reference them by name. Any
        # such reference becomes an `adjacent_to` edge after the response
        # (see _record_mention_edges).
        if manifest:
            head += (
                "AVAILABLE FIELD CONCEPTS (you may reference these by name "
                "in your reasoning):\n"
            )
            for m in manifest:
                head += f"  • {m['name']} ({m['category']})\n"
            head += "\n"
        if ctx_block:
            head += ctx_block + "\n\n"
        head += f"PUZZLE [{puzzle['id']}]:\n{puzzle['statement']}\n\n"
        if puzzle.get("answer_format"):
            head += f"ANSWER FORMAT: {puzzle['answer_format']}\n\n"
        # Show a tiny example of the expected format shape if available
        if puzzle.get("expected_answer"):
            ex_shape = puzzle["expected_answer"]
            # don't reveal the answer; just show the shape via the first item
            if "|" in ex_shape:
                first = ex_shape.split("|")[0].strip()
                # Replace each token with placeholders to obscure content
                ex = "EXAMPLE FORMAT (not the answer): " + first
                head += ex + " | ...\n\n"
            elif "=" in ex_shape:
                first = ex_shape.split(",")[0].strip()
                head += f"EXAMPLE FORMAT (not the answer): {first.split('=')[0]}=<digit>, ...\n\n"
        head += "Reason briefly, then output FINAL_ANSWER on its own line."
        return head

    # ---- benchmark driver ----

    def run_benchmark(
        self,
        puzzles: list[dict],
        seeds_per_puzzle: int = 5,
        field_storage: Optional[str] = None,
    ) -> BenchmarkReport:
        report = BenchmarkReport(
            mode=self.mode,
            model_label=self.model_label,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        # Field needs a real, writable path. On Windows `os.devnull == 'nul'`
        # which `os.replace` cannot use as a destination, so fall back to a
        # tempfile if the caller didn't specify one.
        if field_storage is None:
            import tempfile
            tf = tempfile.NamedTemporaryFile(
                delete=False, suffix=".json", prefix="stoev3_field_"
            )
            tf.close()
            field_storage = tf.name

        if not self.fresh_field_per_puzzle:
            field = InformationField(storage_path=field_storage)
            load_seed_if_empty(field, seed_path=self.seed_loader_path)

        for puzzle in puzzles:
            for seed_idx in range(seeds_per_puzzle):
                if self.fresh_field_per_puzzle:
                    # Use a per-run temp file so puzzles don't collide
                    import tempfile
                    tf = tempfile.NamedTemporaryFile(
                        delete=False, suffix=".json", prefix="stoev3_field_"
                    )
                    tf.close()
                    field = InformationField(storage_path=tf.name)
                    load_seed_if_empty(field, seed_path=self.seed_loader_path)
                rec = self.run_puzzle(puzzle, field, seed_idx)
                report.runs.append(rec)

        report.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        return report
