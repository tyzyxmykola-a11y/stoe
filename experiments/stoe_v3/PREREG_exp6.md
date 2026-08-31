# Pre-registration: Experiment 6 — Structural vs Priming Decomposition of the K-topology + SToE Lift

**Status:** LOCKED. This document is fixed before any data is collected for experiment 6. Any deviation from the protocol below in the eventual paper must be explicitly noted as a deviation, with rationale and timestamp.

**Lock date:** (fill in at the moment of `git tag prereg-exp6`)

**Author:** Mykola Voronin

**Predecessor:** paper_draft_v4.docx §7.5 ("Pre-registered next experiment").

---

## 1. Motivation in one paragraph

Paper v4 reports an exploratory +8.0 pp lift on the K-topology + SToE cell (Run E, 82.67% vs the 74.67% K-off counterpart, Fisher's exact p ≈ 0.099 raw; not robust to Holm–Bonferroni). A structurally-matched music-theory control showed no lift. Two readings of that pattern survive the v4 analysis. (a) STRUCTURAL — the lift depends on the framework's graph structure, not just on SToE concept names being task-adjacent vocabulary. (b) PRIMING / KEYWORD-DENSITY — the lift is task-relevant priming from the SToE names in the manifest, and any reasonable wiring over the same names would produce it. Experiment 6 distinguishes them.

## 2. Hypotheses

- **H1 (structural):** K-topology with the native SToE graph (Condition A) outperforms K-topology with SToE concept names re-wired onto the music-seed's graph structure (Condition B).
- **H0 (priming-only):** Condition A and Condition B are indistinguishable. The +8 pp v4 lift is keyword-density priming from the SToE concept names, not graph structure.

Both conditions hold constant: model, decoder configuration, puzzles, K mechanism, manifest contents (SToE concept names + categories), seed loader path semantics. Only the *adjacency pattern* of the underlying ontology changes.

## 3. Conditions

| | Condition A (native) | Condition B (chimera) |
|---|---|---|
| Seed file | `seed/stoe_seed.json` | `seed/stoe_chimera_seed.json` |
| Concept names visible in manifest | SToE | SToE (identical) |
| Categories per concept | SToE | SToE (identical) |
| Graph adjacency pattern | SToE | music-seed adjacency, rebound to SToE concept ids |
| Edge-type histogram | SToE native | music-matched (also identical to SToE in this dataset) |
| Retrieval mode | topology | topology |
| K mechanism (manifest + mention edges) | on | on |
| Decoder | qwen2.5:32b, T=0.7, top_p=0.9 | identical |
| Max attempts per trial | 3 | 3 |

The chimera seed is built deterministically by `scripts/build_chimera_seed.py` from the two existing seed files. The chimera is verified at build time to preserve node identity, edge count, edge-type distribution, and category distribution, while differing in adjacency from the native SToE seed (≤25% adjacency overlap — observed 4.4% at build time).

## 4. Sample size

K = 50 seeds per condition. 6 puzzles. n = 300 trials per condition. Total trials across the two conditions: 600. Approximate LLM call budget assuming the v4 attempts-per-trial mean ≈ 1.85: ~1,110 LLM calls. At ~50 s per call this is ~15.5 wall hours.

Power justification: under the H0 model assuming both conditions converge on the K-off baseline (~75%), an A−B difference of +5 pp at n=300 each corresponds to a Fisher exact two-sided p ≈ 0.20 — too underpowered for our threshold. A +8 pp difference at n=300 each yields Fisher exact p ≈ 0.035 (two-sided). Our strong-pass threshold (§5) is +5 pp because it must distinguish *direction* under H1 from null under H0; we accept that this trades type-II risk for completion within a 15-hour wall-time budget. If the v4 +8 pp effect is real and structural, this design has ~78% power to detect it at α = 0.05 two-sided.

If wall time permits, the protocol may be doubled to K = 100 (n = 600/cond, ~31 hours, power ~96% for the +8 pp effect). The decision to double is locked at the moment the first run finishes — not based on its outcome, but based on whether the wall time was acceptable. This decision rule prevents outcome-conditioned optional stopping.

## 5. Pre-registered analysis

**Primary outcome:** solve rate per condition over n = 300 trials.

**Primary test:** Fisher's exact test (two-sided) on the 2×2 table of (solved, unsolved) × (Condition A, Condition B). Wilson 95% CIs for each condition.

**Strong pass (H1 supported):** A − B ≥ +5 pp AND Fisher exact p < 0.05 (uncorrected).

**Falsification (H0 supported):** A − B ∈ [−2 pp, +2 pp] AND the Wilson 95% CI on A − B contains zero.

**Inconclusive:** anything else (e.g., A − B = +3 pp with overlapping CIs, or |A − B| > +5 pp without exact-test significance). An inconclusive result is reported as inconclusive; we do not move the threshold.

**No multiple comparisons** are conducted in this experiment. The pre-registered analysis is a single primary Fisher test on a single primary outcome.

**Secondary outcome (descriptive only, not gated):** per-attempt count of failed_from edges visible in topology context blocks, by condition. We expect both conditions to surface comparable counts (~200/run); a large divergence would indicate a confound in the chimera build worth investigating.

## 6. Stopping rules

- The run completes when all 6 × 50 × 2 = 600 trials have either been graded or hit max attempts.
- No early stopping. If wall time forces termination, the partial result is reported as partial and not analyzed against the pre-registered thresholds.
- No re-run conditional on outcome. If the run completes but the result is inconclusive (per §5), the inconclusive verdict stands and goes into the paper.

## 7. Deviation disclosure

Any deviation from this protocol — change in K, change in puzzles, change in model, change in thresholds, change in test — must appear in the eventual paper under a "Deviations from pre-registration" subsection with the deviation, the reason, and the timestamp.

## 8. What this experiment does and does not show

**Does:** distinguishes whether the v4 K-topology + SToE lift comes from SToE *graph structure* or from SToE *concept names alone* — under the specific conditions of qwen2.5:32b on the six-puzzle benchmark.

**Does not:** rule out training-data exposure (the SToE concept vocabulary may be more present in qwen2.5's training corpus than a post-cutoff vocabulary would be) or selective-calibration confounds (the six "goldilocks" puzzles were selected on the same model). Those are separate experiments — see paper v4 §7.2 — and remain open.

## 9. Materials provenance

- Native seed: `seed/stoe_seed.json` (36 nodes, 113 edges, SToE adjacency). Unchanged from v3.
- Chimera seed: `seed/stoe_chimera_seed.json` (36 nodes, 113 edges, music adjacency, SToE concept identities). Built by `scripts/build_chimera_seed.py`. Build is deterministic; SHA-256 of the chimera file is recorded in `seed/.chimera.sha256` at build time and verified by the runner before each condition.
- Puzzles: `benchmark/puzzles.json` six-puzzle "goldilocks" subset {LG-003, LG-004, LG-005, LG-006, LG-009, CSP-002}. Unchanged from v3.
- Grader: `benchmark/grader.py`. Unchanged from v3. Deterministic, no LLM.

## 10. Commands run (to be filled in at execution time)

```bash
# from stoe_v3/ project root
bash run_experiment_6.sh 2>&1 | tee runs/exp6.log
python scripts/analyze_experiment_6.py \
    --condition-a runs/exp6_A_topology.json \
    --condition-b runs/exp6_B_topology.json \
    > runs/exp6_verdict.json
```
