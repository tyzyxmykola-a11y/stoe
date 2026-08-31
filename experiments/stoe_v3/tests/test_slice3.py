"""
Slice 3 self-test: structural evaluator.

Run from project root:
    python -m tests.test_slice3

Slice 3 checkpoint per PLAN.md:
    "evaluator picks differently from LLM scoring on this run."

This test exercises:
    Each metric independently (novelty, coherence, bridging, attractor)
    Verdict is added to field as a node + evaluates edge
    Verdict node carries structured metadata (machine-readable)
    Verdict survives field round-trip (persistence)
    LLM-saturated scoring vs structural ranking — divergence demonstrated
    Severed edges are excluded from all metrics
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from core import (
    InformationField,
    StructuralEvaluator,
    Verdict,
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
    workdir = tempfile.mkdtemp(prefix="stoev3_slice3_")
    try:
        storage = os.path.join(workdir, "field.json")
        f = InformationField(storage_path=storage)
        ev = StructuralEvaluator(attractor_seed_depth=2)

        # Build a graph: seed S, A1/A2 inside S's depth-2 nbhd, B1/B2 outside.
        S = f.add_point("solar energy drives planetary biology and weather",
                        category="Seed", session_id="sess1")
        A1 = f.add_point("photosynthesis is the conversion of light to sugar",
                         category="Seed", session_id="sess1")
        A2 = f.add_point("plants are autotrophs",
                         category="Seed", session_id="sess1")
        f.connect(S, A1, edge_type="connected_to")
        f.connect(A1, A2, edge_type="connected_to")
        # depth-2 of S = {S, A1, A2}

        # Two "far" nodes, NOT connected to S
        B1 = f.add_point("Roman senate vote tallies in 49 BCE",
                         category="Seed", session_id="sess1")
        B2 = f.add_point("medieval guild apprenticeships in Bruges",
                         category="Seed", session_id="sess1")
        # Not connected to anything yet — they sit alone in the field.

        # ---- 1. Novelty: candidate connecting only inside seed nbhd is novelty 0 ----
        section("1 - novelty metric")
        # Cand_low connects to A1 only (A1 is inside seed nbhd)
        cand_low = f.add_point("photosynthesis happens in chloroplasts",
                               category="Evolution", session_id="sess1")
        f.connect(cand_low, A1, edge_type="evolved_from")
        v_low = ev.evaluate(f, cand_low, seed_id=S, session_id="sess1",
                            write_verdict=False)
        check(v_low.novelty == 0,
              f"novelty=0 when only edge points inside seed nbhd (got {v_low.novelty})")

        # Cand_high connects to B1 (outside nbhd)
        cand_high = f.add_point("a hypothesis bridging biology and ancient politics",
                                category="Evolution", session_id="sess1")
        f.connect(cand_high, A1, edge_type="connected_to")  # one inside
        f.connect(cand_high, B1, edge_type="connected_to")  # one outside
        f.connect(cand_high, B2, edge_type="connected_to")  # one outside
        v_high = ev.evaluate(f, cand_high, seed_id=S, session_id="sess1",
                             write_verdict=False)
        check(v_high.novelty == 2,
              f"novelty=2 (B1, B2 are outside nbhd) — got {v_high.novelty}")

        # ---- 2. Coherence penalty ----
        section("2 - coherence_penalty metric")
        # Add a contradicts edge — coherence_penalty should rise
        f.connect(cand_high, A2, edge_type="contradicts",
                  note="cand_high disagrees with A2")
        v_h2 = ev.evaluate(f, cand_high, seed_id=S, session_id="sess1",
                           write_verdict=False)
        check(v_h2.coherence_penalty == 1,
              f"coherence_penalty=1 after one contradicts edge (got {v_h2.coherence_penalty})")

        # Severed contradicts edges should not count
        # Find that edge and sever it
        contradicts_edge = next(
            e for e in f.edges
            if e["type"] == "contradicts"
            and e["source"] == cand_high
            and e["target"] == A2
        )
        f.sever(contradicts_edge["id"])
        v_h3 = ev.evaluate(f, cand_high, seed_id=S, session_id="sess1",
                           write_verdict=False)
        check(v_h3.coherence_penalty == 0,
              "severed contradicts edge no longer counts")

        # ---- 3. Bridging ----
        section("3 - bridging metric")
        # B1 and B2 are still in different components (each isolated, no
        # connection to the seed cluster). Removing cand_high from the
        # graph: B1 and B2 are isolated from each other → cand_high
        # bridges between them (and also bridges B-component to S-component).
        v_h_bridge = ev.evaluate(f, cand_high, seed_id=S, session_id="sess1",
                                  write_verdict=False)
        check(v_h_bridge.bridging is True,
              "cand_high bridges previously-disconnected B1 and B2")

        # cand_low only connects to A1 — single neighbour, can't bridge
        v_low_bridge = ev.evaluate(f, cand_low, seed_id=S, session_id="sess1",
                                    write_verdict=False)
        check(v_low_bridge.bridging is False,
              "cand_low has only one neighbour — bridging=False")

        # ---- 4. Attractor distance ----
        section("4 - attractor_distance metric")
        # cand_low's content uses session vocab: "photosynthesis", "chloroplasts"
        # Session contains: "photosynthesis", "plants", "autotrophs", etc.
        v_low_d = ev.evaluate(f, cand_low, seed_id=S, session_id="sess1",
                              write_verdict=False)
        # cand_high's content is more divergent ("hypothesis", "ancient",
        # "politics", "bridging") so distance should be higher
        v_high_d = ev.evaluate(f, cand_high, seed_id=S, session_id="sess1",
                               write_verdict=False)
        check(v_high_d.attractor_distance > v_low_d.attractor_distance,
              f"high-novelty cand has greater attractor_distance "
              f"({v_high_d.attractor_distance:.2f} > {v_low_d.attractor_distance:.2f})")
        check(0.0 <= v_low_d.attractor_distance <= 1.0,
              f"attractor_distance is in [0,1] (got {v_low_d.attractor_distance})")

        # ---- 5. Verdict is added as a node + evaluates edge ----
        section("5 - verdict written to field")
        before_nodes = len(f.nodes)
        before_edges = len(f.edges)
        v_written = ev.evaluate(f, cand_low, seed_id=S, session_id="sess1",
                                write_verdict=True)
        check(v_written.verdict_node_id is not None, "verdict_node_id set")
        check(v_written.verdict_edge_id is not None, "verdict_edge_id set")
        check(len(f.nodes) == before_nodes + 1, "exactly one new node added")
        check(len(f.edges) == before_edges + 1, "exactly one new edge added")
        verdict_node = f.nodes[v_written.verdict_node_id]
        check(verdict_node["category"] == "Evaluation",
              "verdict node category=Evaluation")
        check(verdict_node["metadata"].get("is_verdict") is True,
              "verdict metadata.is_verdict=True")
        check(verdict_node["metadata"].get("evaluates") == cand_low,
              "verdict metadata.evaluates points to candidate")
        check("novelty" in verdict_node["metadata"],
              "verdict metadata carries machine-readable structural facts")
        edge_to_cand = next(
            e for e in f.edges if e["id"] == v_written.verdict_edge_id
        )
        check(edge_to_cand["type"] == "evaluates",
              "verdict edge type=evaluates")
        check(edge_to_cand["target"] == cand_low,
              "verdict edge target=candidate")

        # ---- 6. Persistence: verdict survives field reload ----
        section("6 - verdict persists across field reload")
        verdict_id = v_written.verdict_node_id
        del f
        f2 = InformationField(storage_path=storage)
        check(verdict_id in f2.nodes, "verdict node persists")
        check(f2.nodes[verdict_id]["metadata"].get("is_verdict") is True,
              "verdict metadata persists with is_verdict flag")

        # ---- 7. Composite score: structural ranking ≠ saturated LLM ranking ----
        section("7 - structural ranking diverges from LLM-saturated scoring")
        # Simulate v82's score_step: returns 8/9/8 for everything
        def saturated_llm_score(node_id):
            return 25  # equivalent to 8+9+8 — same for every node

        # Compute structural verdicts for both candidates
        v_a = ev.evaluate(f2, cand_low, seed_id=S, session_id="sess1",
                          write_verdict=False)
        v_b = ev.evaluate(f2, cand_high, seed_id=S, session_id="sess1",
                          write_verdict=False)

        # LLM scores: tied. Structural composite scores: different.
        llm_low = saturated_llm_score(cand_low)
        llm_high = saturated_llm_score(cand_high)
        check(llm_low == llm_high,
              f"LLM saturated scoring is tied: both {llm_low}")
        check(v_a.composite_score() != v_b.composite_score(),
              f"structural scores DIFFER: low={v_a.composite_score():.2f}, "
              f"high={v_b.composite_score():.2f}")

        # The structural ranker picks the high-novelty/bridging candidate
        ranked = StructuralEvaluator.rank([v_a, v_b])
        check(ranked[0].node_id == cand_high,
              f"structural rank picks cand_high (novelty + bridging) "
              f"over cand_low which would tie under LLM scoring")

        # ---- 8. Empty session: attractor_distance defaults to 1.0 ----
        section("8 - edge case: empty session centroid -> attractor_distance=1.0")
        f3 = InformationField(storage_path=os.path.join(workdir, "f3.json"))
        seed3 = f3.add_point("isolated seed", session_id="solo")
        v_solo = ev.evaluate(f3, seed3, seed_id=seed3, session_id="solo",
                             write_verdict=False)
        check(v_solo.attractor_distance == 1.0,
              "single-node session has attractor_distance=1.0 (no centroid to be pulled toward)")

        # ---- 9. Bad inputs raise ValueError ----
        section("9 - missing node_id or seed_id raises")
        f4 = InformationField(storage_path=os.path.join(workdir, "f4.json"))
        n4 = f4.add_point("a node")
        try:
            ev.evaluate(f4, "fake_id", seed_id=n4, session_id="x",
                        write_verdict=False)
            check(False, "should have raised on missing node_id")
        except ValueError as e:
            check("node_id" in str(e), f"ValueError mentions node_id ({e})")

        try:
            ev.evaluate(f4, n4, seed_id="fake_seed", session_id="x",
                        write_verdict=False)
            check(False, "should have raised on missing seed_id")
        except ValueError as e:
            check("seed_id" in str(e), f"ValueError mentions seed_id ({e})")

        # ---- 10. No LLM is ever instantiated ----
        section("10 - evaluator does not import or call any LLM")
        import core.evaluator as ev_mod
        src = open(ev_mod.__file__, encoding="utf-8").read()
        check("LLMClient" not in src,
              "evaluator.py does not reference LLMClient")
        check("ollama" not in src.lower() and "openai" not in src.lower(),
              "evaluator.py does not reference any LLM backend")

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
