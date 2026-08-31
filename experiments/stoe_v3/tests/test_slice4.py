"""
Slice 4 self-test: comparison harness.

Run from project root:
    python -m tests.test_slice4

Slice 4 checkpoint per PLAN.md:
    "topology run vs similarity run produce measurably different
     subgraphs on benchmark X."

This test demonstrates the divergence on a synthetic puzzle that's
constructed to require a failure record to be visible on the second
attempt. With a deterministic MockLLM that uses [failed_from] context
when present, the topology run solves and the similarity run does not.

Coverage:
    Context builder selection
    TopologyContext renders failed_from neighbours with edge-type tags
    SimilarityContext does not use graph topology (verified textually)
    Runner per-attempt records + failed_from-in-context counter
    Topology mode solves backtrack puzzle / similarity mode does not
    Aggregate metrics + diff verdict
    Report JSON round-trip
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from core import InformationField, MockLLM
from harness import (
    BenchmarkRunner, BenchmarkReport,
    TopologyContext, SimilarityContext, get_builder,
)
from harness.cli import diff_reports
from benchmark import grader as grader_mod


PASS = "[ok]"
FAIL = "[FAIL]"

results: list[tuple[bool, str]] = []

def check(cond: bool, label: str) -> None:
    results.append((bool(cond), label))
    print(f"  {PASS if cond else FAIL} {label}")

def section(title: str) -> None:
    print(f"\n=== {title} ===".encode("ascii", errors="replace").decode("ascii"))


# ---------------------------------------------------------------------------
# Synthetic puzzle: deliberately constructed to require backtracking.
#
# The MockLLM below returns "FINAL_ANSWER: 42" by default (wrong).
# It returns "FINAL_ANSWER: 7" (correct) only when the prompt contains
# the substring "[failed_from]" — i.e., only when the topology context
# has surfaced the prior failure.
# ---------------------------------------------------------------------------

SYNTHETIC_PUZZLE = {
    "id": "TEST-001",
    "category": "csp_word",
    "statement": (
        "A toy puzzle for the slice-4 harness test. The correct numeric "
        "answer is 7. If you have seen a record of a previous failed "
        "attempt at this puzzle, output 7. Otherwise, output 42."
    ),
    "answer_format": "single_value",
    "expected_answer": "7",
}


def smart_mock_llm() -> MockLLM:
    """
    Returns 'FINAL_ANSWER: 7' iff the prompt contains '[failed_from]'.
    Otherwise returns 'FINAL_ANSWER: 42'.

    This emulates an LLM that productively uses the failure context
    when it's surfaced. The slice-4 claim is that topology surfaces
    that context and similarity does not.
    """
    def respond(prompt: str) -> str:
        if "[failed_from]" in prompt:
            return "Reasoning: the field shows a prior failure.\nFINAL_ANSWER: 7"
        return "Reasoning: trying the obvious value.\nFINAL_ANSWER: 42"
    return MockLLM(responses=respond)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def run_tests() -> int:
    workdir = tempfile.mkdtemp(prefix="stoev3_slice4_")
    try:
        storage = os.path.join(workdir, "field.json")

        # ---- 1. Builder selection ----
        section("1 - context builder selection")
        check(get_builder("topology").name == "topology",
              "get_builder('topology') returns TopologyContext")
        check(get_builder("similarity").name == "similarity",
              "get_builder('similarity') returns SimilarityContext")
        try:
            get_builder("nonsense")
            check(False, "should have raised on unknown mode")
        except ValueError:
            check(True, "unknown mode raises ValueError")

        # ---- 2. TopologyContext renders failed_from with [failed_from] tag ----
        section("2 - TopologyContext surfaces failed_from edges with edge-type tag")
        f = InformationField(storage_path=storage)
        a = f.add_point("anchor node", session_id="s")
        b = f.add_point("a related node", session_id="s")
        f.connect(a, b, edge_type="connected_to")
        ghost = f.add_failed(a, "first try went wrong", session_id="s")

        topo = TopologyContext(depth=2, max_items=10)
        ctx = topo.build(f, a)
        check("[failed_from]" in ctx,
              "TopologyContext output contains [failed_from] edge tag")
        check("first try went wrong" in ctx,
              "ghost's failure-reason content is rendered in topology context")
        check("[connected_to]" in ctx,
              "non-failure edge types still rendered")

        # ---- 3. SimilarityContext does not surface failed_from tag ----
        section("3 - SimilarityContext does NOT use graph topology")
        sim = SimilarityContext(max_items=10)
        ctx = sim.build(f, a)
        check("[failed_from]" not in ctx,
              "SimilarityContext output does NOT contain [failed_from] tag")
        check("[sim]" in ctx,
              "SimilarityContext output uses similarity tag instead")

        # ---- 4. BenchmarkRunner topology mode: solves the synthetic puzzle ----
        section("4 - topology mode solves the backtrack puzzle")
        mock = smart_mock_llm()
        runner_t = BenchmarkRunner(
            mode="topology", llm=mock, grader_module=grader_mod,
            max_attempts=3, model_label="mock-smart",
            fresh_field_per_puzzle=True,
            seed_loader_path=None,  # don't load the real seed for tests
        )
        rep_t = runner_t.run_benchmark(
            [SYNTHETIC_PUZZLE], seeds_per_puzzle=2,
            field_storage=os.path.join(workdir, "field_t.json"),
        )
        agg_t = rep_t.aggregate()
        check(agg_t["solve_rate"] == 1.0,
              f"topology solve rate = 100% (got {agg_t['solve_rate']:.0%})")
        check(agg_t["solved_runs"] == 2,
              f"both seeds solved (got {agg_t['solved_runs']}/2)")
        # Should have taken ≥2 attempts (first attempt is always wrong)
        any_run = rep_t.runs[0]
        check(any_run.attempts_to_solve == 2,
              f"solved on attempt 2 after attempt 1 was conserved (got {any_run.attempts_to_solve})")
        # The second attempt's context must show a failed_from neighbour
        check(any_run.attempts[1].failed_from_neighbors_in_context >= 1,
              f"attempt 2 saw the failed_from edge in its context "
              f"(got {any_run.attempts[1].failed_from_neighbors_in_context})")

        # ---- 5. BenchmarkRunner similarity mode: does NOT solve ----
        section("5 - similarity mode does NOT solve the backtrack puzzle")
        mock = smart_mock_llm()
        runner_s = BenchmarkRunner(
            mode="similarity", llm=mock, grader_module=grader_mod,
            max_attempts=3, model_label="mock-smart",
            fresh_field_per_puzzle=True,
            seed_loader_path=None,
        )
        rep_s = runner_s.run_benchmark(
            [SYNTHETIC_PUZZLE], seeds_per_puzzle=2,
            field_storage=os.path.join(workdir, "field_s.json"),
        )
        agg_s = rep_s.aggregate()
        check(agg_s["solve_rate"] == 0.0,
              f"similarity solve rate = 0% (got {agg_s['solve_rate']:.0%})")
        # Every attempt failed because the context never surfaced [failed_from]
        first_run = rep_s.runs[0]
        check(all(a.failed_from_neighbors_in_context == 0
                  for a in first_run.attempts),
              "no attempt in similarity mode saw a failed_from edge in its context")
        check(len(first_run.attempts) == 3,
              "similarity mode used the full max_attempts budget without solving")

        # ---- 6. Diff verdict: strong_pass on this synthetic case ----
        section("6 - diff_reports verdict")
        diff = diff_reports(rep_t, rep_s)
        check(diff["delta_solve_rate_pp"] == 100.0,
              f"delta solve rate = +100pp (got {diff['delta_solve_rate_pp']})")
        check(diff["verdict"] == "strong_pass",
              f"verdict is 'strong_pass' (got {diff['verdict']!r})")
        # ratio failed_from: topology has >0, similarity has 0 -> ratio is None
        check(diff["ratio_failed_from"] is None,
              "ratio_failed_from is None when similarity has zero (would be inf)")

        # Same-data diff -> falsification (zero delta, ratio ~1)
        diff_self = diff_reports(rep_t, rep_t)
        check(diff_self["delta_solve_rate_pp"] == 0.0,
              "self-diff delta is 0pp")
        check(diff_self["verdict"] == "falsification",
              "self-diff verdict is 'falsification' (no measurable difference)")

        # ---- 7. Report JSON round-trip ----
        section("7 - report serializes to valid JSON")
        js = rep_t.to_json()
        parsed = json.loads(js)
        check("header" in parsed and "aggregate" in parsed and "runs" in parsed,
              "JSON has header / aggregate / runs sections")
        check(parsed["header"]["mode"] == "topology",
              "JSON header records the mode")
        check(parsed["aggregate"]["solve_rate"] == 1.0,
              "JSON aggregate solve rate matches in-memory aggregate")
        check(len(parsed["runs"]) == 2,
              "JSON runs section has both seeds")

        # ---- 8. Structural verdict piggybacks per attempt ----
        section("8 - structural verdict attached to each attempt")
        for run in rep_t.runs:
            for att in run.attempts:
                check(att.structural_verdict is not None,
                      f"attempt {att.attempt_idx} carries a structural verdict")
                check("composite_score" in att.structural_verdict,
                      "verdict includes composite_score")
                # Only check first attempt of first run to avoid spam
                break
            break

        # ---- 9. LLM transport failure conserved as Ghost ----
        section("9 - LLM transport failure conserved, run continues")
        from core.llm import OllamaError

        class ExplodingLLM:
            def __init__(self):
                self.calls = 0
            def call(self, prompt):
                self.calls += 1
                if self.calls == 1:
                    raise OllamaError("simulated failure")
                # Recovers on second call, gives correct answer
                return "FINAL_ANSWER: 7"

        runner_e = BenchmarkRunner(
            mode="topology", llm=ExplodingLLM(), grader_module=grader_mod,
            max_attempts=3, model_label="exploding",
            fresh_field_per_puzzle=True, seed_loader_path=None,
            evaluate_attempts=False,  # skip evaluator on transport failures
        )
        rep_e = runner_e.run_benchmark(
            [SYNTHETIC_PUZZLE], seeds_per_puzzle=1,
            field_storage=os.path.join(workdir, "field_e.json"),
        )
        run_e = rep_e.runs[0]
        check(run_e.solved is True,
              "run recovers from transport failure on first attempt")
        # First attempt was the transport failure
        check("transport_error" in run_e.attempts[0].grader_reason,
              "first attempt recorded as transport_error")
        # Second attempt produced the correct answer
        check(run_e.attempts[1].correct,
              "second attempt produced correct answer")

        # ---- 10. failed_from-in-context counter integrity ----
        section("10 - failed_from-in-context counter behaves correctly")
        # In topology mode, the first attempt has zero (no failure exists yet).
        first_attempt_t = rep_t.runs[0].attempts[0]
        check(first_attempt_t.failed_from_neighbors_in_context == 0,
              f"first attempt sees zero failed_from in context "
              f"(got {first_attempt_t.failed_from_neighbors_in_context})")
        # Second attempt sees ≥1 (the just-conserved failure of attempt 1).
        second_attempt_t = rep_t.runs[0].attempts[1]
        check(second_attempt_t.failed_from_neighbors_in_context >= 1,
              f"second attempt sees ≥1 failed_from in context "
              f"(got {second_attempt_t.failed_from_neighbors_in_context})")

        # ---- summary ----
        section("Summary")
        passed = sum(1 for ok, _ in results if ok)
        total = len(results)
        print(f"  {passed}/{total} checks passed")
        return 0 if passed == total else 1

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(run_tests())
