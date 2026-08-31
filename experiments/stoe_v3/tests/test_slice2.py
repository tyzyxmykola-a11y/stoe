"""
Slice 2 self-test: verifies graph-aware operators.

Run from project root:
    python -m tests.test_slice2

Slice 2 checkpoint per PLAN.md:
    "operators sometimes can't fire and that's correct behavior."

This test exercises:
    Pre-LLM precondition checks (no LLM call when arity fails)
    Graph-state preconditions (Disruption needs failed/contradicts neighbors)
    Effects: each op produces the right edge types
    Graph-context consumption: SynergyOp prompt actually contains
        neighborhood lines (the v82 gap that v3 closes)
    Failure conservation: LLM errors become Ghost nodes, not silent drops
    Recursion dedup: near-duplicate output is refused, conserved as Ghost
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from core import (
    InformationField,
    MockLLM,
    OllamaError,
    ConnectionOp, SynergyOp, RecursionOp,
    DisruptionOp, RemovalOp, SummarizeOp,
    default_registry,
)


PASS = "[ok]"
FAIL = "[FAIL]"

results: list[tuple[bool, str]] = []

def check(cond: bool, label: str) -> None:
    results.append((bool(cond), label))
    print(f"  {PASS if cond else FAIL} {label}")

def section(title: str) -> None:
    print(f"\n=== {title} ===".encode("ascii", errors="replace").decode("ascii"))


def run_tests() -> int:
    workdir = tempfile.mkdtemp(prefix="stoev3_slice2_")
    try:
        storage = os.path.join(workdir, "field.json")
        f = InformationField(storage_path=storage)

        # Build a small starting graph
        a = f.add_point("the sun heats the earth")
        b = f.add_point("plants convert light to sugar")
        c = f.add_point("ecosystems depend on solar energy")
        f.connect(a, b, edge_type="connected_to", weight=0.7)
        f.connect(b, c, edge_type="connected_to", weight=0.9)

        # ---- 1. Arity precondition: no LLM call on bad arity ----
        section("1 - arity preconditions short-circuit before LLM")
        llm = MockLLM(responses=["should not be called"])
        op = ConnectionOp()
        r = op.fire(f, args=[a], llm=llm)        # arity 2, only 1 given
        check(not r.fired, "ConnectionOp refuses arity-1 call")
        check("expected 2" in r.reason, f"reason mentions arity (got: {r.reason!r})")
        check(len(llm.calls) == 0, "no LLM call made for refused operator")

        r = op.fire(f, args=[a, b, c], llm=llm)  # too many
        check(not r.fired, "ConnectionOp refuses arity-3 call")
        check(len(llm.calls) == 0, "still no LLM call after second refusal")

        # ---- 2. Existence precondition: missing node id ----
        section("2 - missing-node precondition")
        r = op.fire(f, args=[a, "nonexistent_id_xyz"], llm=llm)
        check(not r.fired, "operator refuses when one id is missing")
        check("not in field" in r.reason, f"reason mentions missing node (got {r.reason!r})")
        check(len(llm.calls) == 0, "still no LLM call")

        # ---- 3. ConnectionOp effect: produces node + 2 connected_to edges ----
        section("3 - ConnectionOp fires and produces correct edges")
        llm = MockLLM(responses=["solar energy drives the food chain"])
        n_before = len(f.nodes)
        e_before = len(f.edges)
        r = ConnectionOp().fire(f, args=[a, b], llm=llm, session_id="s1")
        check(r.fired, "ConnectionOp(a, b) fires")
        check(r.produced_node_id is not None, "produced a node")
        check(len(f.nodes) == n_before + 1, "exactly 1 new node")
        check(len(f.edges) == e_before + 2, "exactly 2 new edges")
        new_id = r.produced_node_id
        outgoing = [e for e in f.edges if e["source"] == new_id]
        edge_types = sorted(e["type"] for e in outgoing)
        check(edge_types == ["connected_to", "connected_to"],
              f"both new edges are connected_to (got {edge_types})")
        targets = sorted(e["target"] for e in outgoing)
        check(targets == sorted([a, b]), "edges point to the two input nodes")
        check(len(llm.calls) == 1, "exactly 1 LLM call for a successful fire")

        # ---- 4. SynergyOp prompt INCLUDES neighborhoods ----
        section("4 - SynergyOp prompt consumes graph context (v82 gap closed)")
        llm = MockLLM(responses=["photosynthesis as planetary metabolism"])
        r = SynergyOp().fire(f, args=[a, b], llm=llm, session_id="s1")
        check(r.fired, "SynergyOp fires on (a, b)")
        prompt = llm.last_call() or ""
        # b's neighborhood should mention c's content (b -> c)
        check("ecosystems depend" in prompt,
              "synergy prompt includes b's neighbour c's content")
        # The prompt should also contain edge type annotations from neighborhoods
        check("connected_to" in prompt,
              "synergy prompt includes edge type from neighborhood")
        synergy_edges = [e for e in f.edges if e["source"] == r.produced_node_id]
        check(all(e["type"] == "synergy_with" for e in synergy_edges),
              "synergy edges are typed synergy_with")

        # ---- 5. RecursionOp dedup: near-duplicate output is refused ----
        section("5 - RecursionOp dedup refuses near-duplicates, conserves as Ghost")
        seed = f.add_point("artificial intelligence is changing how we think")
        # First call produces something different — accepted
        llm = MockLLM(responses=[
            "AI restructures the very texture of cognitive labor across society",
        ])
        r = RecursionOp().fire(f, args=[seed], llm=llm, session_id="s1")
        check(r.fired, "first recursion fires (novel output)")
        first_evolution = r.produced_node_id

        # Second call produces an output near-identical to the input — refused
        llm2 = MockLLM(responses=[
            "artificial intelligence is changing how we think",  # exact match
        ])
        ghost_count_before = sum(1 for n in f.nodes.values() if n.get("category") == "Ghost")
        r2 = RecursionOp().fire(f, args=[seed], llm=llm2, session_id="s1")
        check(not r2.fired, "second recursion refuses near-duplicate output")
        check("near-duplicate" in r2.reason,
              f"reason cites near-duplicate (got {r2.reason!r})")
        check(r2.produced_node_id is not None,
              "refused output is conserved as Ghost (not silently dropped)")
        ghost_count_after = sum(1 for n in f.nodes.values() if n.get("category") == "Ghost")
        check(ghost_count_after == ghost_count_before + 1,
              "exactly one new Ghost node from the dedup refusal")
        # The Ghost should be reachable from `seed` via failed_from
        de = f.dead_end_query(seed)
        check(any(d["edge_type"] == "failed_from" for d in de),
              "dead_end_query on seed finds the failed_from edge")

        # Third call: an output similar to the FIRST evolution (already in chain) — refused
        llm3 = MockLLM(responses=[
            "AI restructures the very texture of cognitive labor across society",
        ])
        r3 = RecursionOp().fire(f, args=[seed], llm=llm3, session_id="s1")
        check(not r3.fired,
              "third recursion refuses output matching prior chain element")

        # ---- 6. DisruptionOp REQUIRES failed/contradicts neighbors ----
        section("6 - DisruptionOp graph-state precondition")
        clean_node = f.add_point("a fresh idea with no failure history")
        llm = MockLLM(responses=["should not be called"])
        r = DisruptionOp().fire(f, args=[clean_node], llm=llm, session_id="s1")
        check(not r.fired, "DisruptionOp refuses node with no failed/contradicts neighbours")
        check("nothing to disrupt against" in r.reason,
              f"reason explains why (got {r.reason!r})")
        check(len(llm.calls) == 0,
              "no LLM call when graph-state precondition fails")

        # Now `seed` has failed_from neighbours from the dedup test — disruption can fire
        llm = MockLLM(responses=["the assumption is that evolution must add words, not subtract them"])
        r = DisruptionOp().fire(f, args=[seed], llm=llm, session_id="s1")
        check(r.fired, "DisruptionOp fires once seed has failed neighbours")
        prompt = llm.last_call() or ""
        check("[failed_from]" in prompt,
              "DisruptionOp prompt includes the failed_from edge type")

        # ---- 7. RemovalOp: severs lowest-weight outgoing edge, no LLM call ----
        section("7 - RemovalOp severs without LLM call")
        edge_count_active_before = sum(1 for e in f.edges if not e.get("severed"))
        # Pick a node with multiple outgoing edges and known weights
        # `a` has an outgoing connected_to to `b` with weight 0.7
        # `b` has an outgoing to `c` with weight 0.9
        # Add another outgoing from `a` to make selection meaningful
        z = f.add_point("auxiliary endpoint")
        f.connect(a, z, edge_type="connected_to", weight=0.3)  # weakest
        llm = MockLLM(responses=["should not be called"])
        r = RemovalOp().fire(f, args=[a], llm=llm)
        check(r.fired, "RemovalOp fires on node with outgoing edges")
        check(r.severed_edge_id is not None, "severed an edge")
        check(len(llm.calls) == 0, "RemovalOp made no LLM call")
        severed = [e for e in f.edges if e.get("severed")]
        check(any(e["target"] == z for e in severed),
              "severed the weakest (a -> z, weight=0.3) edge")

        # No outgoing edges -> refuse
        isolated = f.add_point("isolated node")
        r = RemovalOp().fire(f, args=[isolated], llm=llm)
        check(not r.fired, "RemovalOp refuses node with no active outgoing edges")
        check("no active outgoing edges" in r.reason,
              f"reason explains absence (got {r.reason!r})")

        # ---- 8. SummarizeOp: variadic arity, ≥3 ----
        section("8 - SummarizeOp variadic precondition")
        llm = MockLLM(responses=["should not be called"])
        r = SummarizeOp().fire(f, args=[a, b], llm=llm, session_id="s1")
        check(not r.fired, "SummarizeOp refuses with 2 inputs")
        check(">= 3 args" in r.reason or ">=3" in r.reason or ">= 3" in r.reason,
              f"reason mentions min_arity=3 (got {r.reason!r})")
        check(len(llm.calls) == 0, "no LLM call on insufficient arity")

        llm = MockLLM(responses=["solar input drives both biology and ecology"])
        r = SummarizeOp().fire(f, args=[a, b, c], llm=llm, session_id="s1")
        check(r.fired, "SummarizeOp fires with 3 inputs")
        # Should produce 3 evaluates edges
        eval_edges = [e for e in f.edges
                      if e["source"] == r.produced_node_id and e["type"] == "evaluates"]
        check(len(eval_edges) == 3, f"3 evaluates edges produced (got {len(eval_edges)})")

        # ---- 9. LLM failure -> Ghost conservation ----
        section("9 - LLM transport failure becomes Ghost (no silent drop)")
        class FailingLLM:
            def call(self, prompt):
                raise OllamaError("simulated transport failure")
        ghost_before = sum(1 for n in f.nodes.values() if n.get("category") == "Ghost")
        r = ConnectionOp().fire(f, args=[a, b], llm=FailingLLM(), session_id="s1")
        check(not r.fired, "ConnectionOp does not fire on LLM transport error")
        check("transport failure" in r.reason or "LLM call failed" in r.reason,
              f"reason mentions failure (got {r.reason!r})")
        ghost_after = sum(1 for n in f.nodes.values() if n.get("category") == "Ghost")
        check(ghost_after > ghost_before,
              "LLM failure conserved as Ghost — nothing silently lost")

        # ---- 10. Registry contains all six operators ----
        section("10 - default_registry covers all six operators")
        reg = default_registry()
        for sym in ("+", "×", "↻", "!", "−", "∑"):
            check(sym in reg, f"registry contains {sym!r}")

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
