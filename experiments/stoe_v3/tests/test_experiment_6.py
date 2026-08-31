"""
Tests for experiment 6 artifacts. Run with:

    python -m unittest tests.test_experiment_6 -v

Three concerns:
  (A) the chimera seed has the structural properties PREREG.md §3 requires
  (B) the analyzer's stats primitives are correct against known values
  (C) the analyzer's pre-registered verdict logic stamps correctly on
      synthetic A/B reports
"""

from __future__ import annotations
import json, math, os, sys, unittest
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import analyze_experiment_6 as A


SEED_DIR = os.path.join(ROOT, "seed")
STOE = os.path.join(SEED_DIR, "stoe_seed_reference.json")  # symlink at package time
CHIM = os.path.join(SEED_DIR, "stoe_chimera_seed.json")
MUSIC = os.path.join(SEED_DIR, "music_theory_seed_reference.json")


def _load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


@unittest.skipUnless(os.path.exists(CHIM), "chimera not built")
class ChimeraStructure(unittest.TestCase):
    """PREREG.md §3 requires: chimera preserves SToE node identity,
    music edge-type histogram, and adjacency differs from SToE."""

    @classmethod
    def setUpClass(cls):
        cls.chimera = _load(CHIM)
        cls.stoe = _load(STOE) if os.path.exists(STOE) else None
        cls.music = _load(MUSIC) if os.path.exists(MUSIC) else None

    def test_node_count(self):
        self.assertEqual(len(self.chimera["nodes"]), 36)

    def test_edge_count(self):
        self.assertEqual(len(self.chimera["edges"]), 113)

    def test_node_identity_preserved(self):
        if self.stoe is None:
            self.skipTest("stoe reference seed not bundled in this artifact")
        self.assertEqual(set(self.chimera["nodes"].keys()),
                         set(self.stoe["nodes"].keys()))
        for nid, n in self.chimera["nodes"].items():
            self.assertEqual(n["name"], self.stoe["nodes"][nid]["name"])
            self.assertEqual(n["category"], self.stoe["nodes"][nid]["category"])

    def test_edge_type_distribution(self):
        if self.music is None:
            self.skipTest("music reference seed not bundled")
        cc = Counter(e["type"] for e in self.chimera["edges"])
        cm = Counter(e["type"] for e in self.music["edges"])
        self.assertEqual(cc, cm)

    def test_adjacency_differs_from_stoe(self):
        if self.stoe is None:
            self.skipTest("stoe reference seed not bundled")
        def adj(edges):
            return frozenset(
                (frozenset((e["source"], e["target"])), e["type"]) for e in edges
            )
        overlap = adj(self.chimera["edges"]) & adj(self.stoe["edges"])
        n = len(self.chimera["edges"])
        # PREREG §3: must be much less than full identity. Threshold ≤ 25%.
        self.assertLessEqual(len(overlap), int(0.25 * n),
            f"adjacency overlap with SToE is {len(overlap)}/{n}; chimera is not "
            f"structurally distinct as required by PREREG §3.")

    def test_all_chimera_edges_reference_valid_nodes(self):
        nids = set(self.chimera["nodes"].keys())
        for e in self.chimera["edges"]:
            self.assertIn(e["source"], nids)
            self.assertIn(e["target"], nids)

    def test_chimera_metadata_flag(self):
        for n in self.chimera["nodes"].values():
            self.assertTrue(n.get("metadata", {}).get("chimera", False),
                            f"chimera flag missing on node {n['id']}")


class WilsonCI(unittest.TestCase):
    """Wilson 95% CI against known reference values."""

    def test_centre_of_50pct(self):
        lo, hi = A.wilson_ci(50, 100)
        # known: Wilson 50/100 95% CI ≈ [40.4%, 59.6%]
        self.assertAlmostEqual(lo, 0.4038, places=3)
        self.assertAlmostEqual(hi, 0.5962, places=3)

    def test_boundary_zero(self):
        lo, hi = A.wilson_ci(0, 20)
        self.assertAlmostEqual(lo, 0.0, places=6)
        self.assertGreater(hi, 0.0)
        self.assertLess(hi, 0.20)

    def test_n_300_at_82pct(self):
        # n=300, 246 solved (82.0%)
        lo, hi = A.wilson_ci(246, 300)
        # Wilson reference (computed independently): ≈ [77.2%, 86.0%]
        self.assertAlmostEqual(lo, 0.772, places=2)
        self.assertAlmostEqual(hi, 0.860, places=2)


class FisherExact(unittest.TestCase):
    """Fisher's exact test against known reference values."""

    def test_identical_proportions(self):
        # 75/100 vs 75/100 → p = 1.0
        p = A.fisher_exact_2x2(75, 25, 75, 25)
        self.assertAlmostEqual(p, 1.0, places=4)

    def test_classic_example(self):
        # Fisher's tea-tasting toy table [[3,1],[1,3]] → two-sided p = 0.4857
        p = A.fisher_exact_2x2(3, 1, 1, 3)
        self.assertAlmostEqual(p, 0.4857, places=3)

    def test_paper_v4_run_e(self):
        # paper v4 Run E: topology 115/150 vs similarity 114/150 → p = 1.000
        p = A.fisher_exact_2x2(115, 35, 114, 36)
        self.assertGreater(p, 0.9)

    def test_significant_difference(self):
        # 90/100 vs 60/100 → strongly significant
        p = A.fisher_exact_2x2(90, 10, 60, 40)
        self.assertLess(p, 0.001)


class VerdictLogic(unittest.TestCase):
    """Pre-registered §5 verdict thresholds: strong_pass / falsification / inconclusive."""

    def _stats(self, solved, total, label="x"):
        return {"solved": solved, "total": total, "failed_from": 0,
                "solve_rate": solved / total, "model": "test", "mode": "topology"}

    def test_strong_pass(self):
        # A = 240/300 (80.0%), B = 210/300 (70.0%); diff = +10 pp, Fisher p ~ 0.005
        v = A.verdict(self._stats(240, 300), self._stats(210, 300))
        self.assertEqual(v["verdict"], "strong_pass")

    def test_falsification(self):
        # A = 224/300, B = 223/300 — diff +0.33 pp, p ~ 1.0
        v = A.verdict(self._stats(224, 300), self._stats(223, 300))
        self.assertEqual(v["verdict"], "falsification")

    def test_inconclusive_small_diff_no_sig(self):
        # A = 228/300, B = 217/300 — diff +3.7 pp, not significant
        v = A.verdict(self._stats(228, 300), self._stats(217, 300))
        self.assertEqual(v["verdict"], "inconclusive")

    def test_inconclusive_large_diff_no_sig(self):
        # A = 47/60, B = 43/60 — diff +6.67 pp but n too small for sig
        v = A.verdict(self._stats(47, 60), self._stats(43, 60))
        self.assertEqual(v["verdict"], "inconclusive")

    def test_strong_pass_borderline(self):
        # A = 232/300 (77.3%), B = 218/300 (72.7%); diff = +4.67 pp
        # Below the +5 pp threshold → inconclusive even if Fisher is borderline
        v = A.verdict(self._stats(232, 300), self._stats(218, 300))
        # +4.67 pp doesn't reach +5 pp threshold
        self.assertNotEqual(v["verdict"], "strong_pass")


class NewcombeCI(unittest.TestCase):
    """Newcombe difference CI sanity."""

    def test_zero_difference_contains_zero(self):
        lo, hi = A.newcombe_diff_ci(75, 100, 75, 100)
        self.assertLessEqual(lo, 0.0)
        self.assertGreaterEqual(hi, 0.0)

    def test_significant_difference_excludes_zero(self):
        # 90/100 vs 60/100 → diff CI should exclude 0
        lo, hi = A.newcombe_diff_ci(90, 100, 60, 100)
        self.assertGreater(lo, 0.0)


if __name__ == "__main__":
    unittest.main()
