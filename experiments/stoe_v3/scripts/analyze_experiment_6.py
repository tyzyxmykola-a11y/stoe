"""
analyze_experiment_6.py
=======================
Compute the pre-registered primary analysis (§5 of PREREG.md) on the two
BenchmarkReport JSONs produced by harness.cli for Conditions A and B.

- Wilson 95% CI for each condition's solve rate.
- Fisher's exact test (two-sided) on the 2x2 (solved, unsolved) x (A, B) table.
- Wilson 95% CI for the difference A - B (Newcombe's hybrid-score interval).
- Stamps the verdict per pre-registered thresholds:
      strong_pass    : A - B >= +5 pp AND Fisher p < 0.05
      falsification  : A - B in [-2, +2] pp AND Wilson CI on diff contains 0
      inconclusive   : anything else

Stdlib only (no scipy dependency; we implement Wilson and Fisher exact directly).

Usage:
    python analyze_experiment_6.py \\
        --condition-a runs/exp6_<ts>_A_topology.json \\
        --condition-b runs/exp6_<ts>_B_topology.json \\
        --out runs/exp6_<ts>_verdict.json
"""

from __future__ import annotations
import argparse, json, math, sys
from typing import Optional


# ---------- Stats primitives ----------

def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score 95% CI for a binomial proportion. z=1.96 for 95%."""
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    halfw = (z / denom) * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (max(0.0, centre - halfw), min(1.0, centre + halfw))


def newcombe_diff_ci(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    """Newcombe's hybrid-score 95% CI for the difference p1 - p2."""
    l1, u1 = wilson_ci(k1, n1)
    l2, u2 = wilson_ci(k2, n2)
    p1 = k1 / n1 if n1 else 0.0
    p2 = k2 / n2 if n2 else 0.0
    delta_lo = (p1 - p2) - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    delta_hi = (p1 - p2) + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (delta_lo, delta_hi)


def _log_choose(n: int, k: int) -> float:
    if k < 0 or k > n:
        return -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def _hypergeom_logpmf(k: int, K: int, N: int, n: int) -> float:
    """log P(X = k) where X ~ Hypergeom(N, K, n)."""
    return _log_choose(K, k) + _log_choose(N - K, n - k) - _log_choose(N, n)


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """
    Two-sided Fisher exact p-value on
        [[a, b],
         [c, d]]
    using the "p-value summation" definition: sum of probabilities for all
    tables (with the same marginals) at least as extreme as the observed one.
    """
    n1 = a + b          # row 1 total (e.g., condition A: solved + unsolved)
    n2 = c + d
    K  = a + c          # column 1 total (e.g., total solved)
    N  = n1 + n2

    if min(n1, n2, K, N - K) == 0:
        return 1.0

    obs_lp = _hypergeom_logpmf(a, K, N, n1)
    # Iterate over all feasible a' (number of "successes" in row 1)
    lo = max(0, K - n2)
    hi = min(n1, K)
    p_sum = 0.0
    for x in range(lo, hi + 1):
        lp = _hypergeom_logpmf(x, K, N, n1)
        # "at least as extreme" = lp <= obs_lp (plus a tiny epsilon for float noise)
        if lp <= obs_lp + 1e-12:
            p_sum += math.exp(lp)
    return min(1.0, p_sum)


# ---------- Report ingestion ----------

def load_report(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cond_stats(rep: dict) -> dict:
    """Compute (solved, total) for a BenchmarkReport JSON."""
    agg = rep.get("aggregate")
    if agg is None:
        # Some versions store aggregate flat at top level
        agg = rep
    solved = int(agg["solved_runs"])
    total = int(agg["total_runs"])
    failed_from = int(agg.get("total_failed_from_in_context", 0))
    return {"solved": solved, "total": total, "failed_from": failed_from,
            "solve_rate": solved / total if total else 0.0,
            "model": agg.get("model") or rep.get("model_label", "?"),
            "mode":  agg.get("mode")  or rep.get("mode", "?")}


# ---------- Pre-registered verdict ----------

def verdict(stats_a: dict, stats_b: dict) -> dict:
    a = stats_a["solved"]; b = stats_a["total"] - a
    c = stats_b["solved"]; d = stats_b["total"] - c
    p = fisher_exact_2x2(a, b, c, d)
    diff = stats_a["solve_rate"] - stats_b["solve_rate"]
    diff_pp = diff * 100
    diff_lo, diff_hi = newcombe_diff_ci(stats_a["solved"], stats_a["total"],
                                        stats_b["solved"], stats_b["total"])
    diff_lo_pp = diff_lo * 100
    diff_hi_pp = diff_hi * 100
    ci_a = tuple(x * 100 for x in wilson_ci(stats_a["solved"], stats_a["total"]))
    ci_b = tuple(x * 100 for x in wilson_ci(stats_b["solved"], stats_b["total"]))

    # Pre-registered §5 thresholds:
    if diff_pp >= 5.0 and p < 0.05:
        v = "strong_pass"
        rationale = "A - B >= +5 pp AND Fisher exact p < 0.05 (pre-registered)"
    elif -2.0 <= diff_pp <= 2.0 and diff_lo_pp <= 0.0 <= diff_hi_pp:
        v = "falsification"
        rationale = "A - B in [-2, +2] pp AND Newcombe 95% CI on diff contains 0"
    else:
        v = "inconclusive"
        rationale = "neither strong-pass nor falsification thresholds met"

    return {
        "condition_a": {
            "label": "A: native SToE seed",
            **stats_a,
            "solve_rate_pct": stats_a["solve_rate"] * 100,
            "wilson_95_ci_pct": [round(ci_a[0], 2), round(ci_a[1], 2)],
        },
        "condition_b": {
            "label": "B: chimera (SToE names, music graph)",
            **stats_b,
            "solve_rate_pct": stats_b["solve_rate"] * 100,
            "wilson_95_ci_pct": [round(ci_b[0], 2), round(ci_b[1], 2)],
        },
        "difference": {
            "a_minus_b_pp": round(diff_pp, 3),
            "newcombe_95_ci_pp": [round(diff_lo_pp, 2), round(diff_hi_pp, 2)],
            "fisher_exact_p_two_sided": round(p, 6),
        },
        "verdict": v,
        "rationale": rationale,
        "thresholds_from_prereg": {
            "strong_pass": "A - B >= +5 pp AND Fisher p < 0.05",
            "falsification": "A - B in [-2, +2] pp AND Newcombe 95% CI on diff contains 0",
            "all_other_outcomes": "inconclusive",
        },
    }


# ---------- main ----------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition-a", required=True,
                    help="Condition A BenchmarkReport JSON (native SToE seed)")
    ap.add_argument("--condition-b", required=True,
                    help="Condition B BenchmarkReport JSON (chimera seed)")
    ap.add_argument("--out", default=None, help="write verdict JSON here (else stdout)")
    args = ap.parse_args()

    a_stats = cond_stats(load_report(args.condition_a))
    b_stats = cond_stats(load_report(args.condition_b))
    v = verdict(a_stats, b_stats)

    # Cross-condition sanity: same total trial count, same model
    if a_stats["total"] != b_stats["total"]:
        v["sanity_warning"] = (f"trial counts differ: A={a_stats['total']}, "
                               f"B={b_stats['total']} (pre-reg expected equal n)")
    if a_stats["model"] != b_stats["model"]:
        v["sanity_warning_model"] = (f"models differ: A={a_stats['model']}, "
                                     f"B={b_stats['model']}")

    out_json = json.dumps(v, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out_json)
        print(f"VERDICT: {v['verdict']}  (A-B={v['difference']['a_minus_b_pp']:+.2f} pp, "
              f"Fisher p={v['difference']['fisher_exact_p_two_sided']:.4f})")
        print(f"  Condition A: {v['condition_a']['solve_rate_pct']:.2f}% "
              f"CI {v['condition_a']['wilson_95_ci_pct']}")
        print(f"  Condition B: {v['condition_b']['solve_rate_pct']:.2f}% "
              f"CI {v['condition_b']['wilson_95_ci_pct']}")
        print(f"  diff CI (Newcombe): {v['difference']['newcombe_95_ci_pp']} pp")
        print(f"  -> {args.out}")
    else:
        print(out_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
