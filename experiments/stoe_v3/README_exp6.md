# Experiment 6 — Structure vs Priming for the K-topology + SToE Lift

Pre-registered next experiment for paper v4 §7.5. Distinguishes whether the v4
exploratory +8 pp K-topology + SToE result comes from the framework's *graph
structure* or from *concept names alone* (keyword-density priming).

This is a drop-in addition to `stoe_v3/`. After extraction it adds:

```
stoe_v3/
├── PREREG.md                                   # locked protocol — read first
├── README_exp6.md                              # this file
├── run_experiment_6.sh                         # main runner
├── seed/stoe_chimera_seed.json                 # pre-built chimera (verified)
├── seed/.chimera.sha256                        # canonical hash, runner verifies
├── scripts/build_chimera_seed.py               # how the chimera was built (reproducible)
├── scripts/analyze_experiment_6.py             # Wilson CIs, Fisher exact, verdict
└── tests/test_experiment_6.py                  # 21 tests — all must pass
```

It does NOT modify any existing v3 file. Every flag the runner uses
(`--seed-path`, `--ontology-manifest`, `--mention-edges`, `--include-seed-ontology`)
already exists in `harness/cli.py`.

## Quick start

1. **Extract into the v3 root.**
   ```bash
   cd /path/to/stoe_v3
   unzip experiment_6.zip            # adds the files above; overwrites nothing
   ```

2. **Verify the chimera builds reproducibly (optional but recommended).**
   ```bash
   python scripts/build_chimera_seed.py \
       --stoe  seed/stoe_seed.json \
       --music seed/music_theory_seed.json \
       --out   /tmp/rebuilt_chimera.json
   diff seed/stoe_chimera_seed.json /tmp/rebuilt_chimera.json
   # should be empty — chimera build is deterministic
   ```

3. **Run the 21 tests.** All must pass before running the experiment.
   ```bash
   python -m unittest tests.test_experiment_6 -v
   ```

4. **Launch Ollama with qwen2.5:32b.** The runner expects it at
   `http://localhost:11434` (override with `OLLAMA_URL`).

5. **Run the pre-registered comparison.**
   ```bash
   bash run_experiment_6.sh 2>&1 | tee runs/exp6.log
   ```
   Expected wall time: ~15–16 hours at ~50 s/call on the v4 hardware.

6. **Read the verdict.** The runner writes `runs/exp6_<ts>_verdict.json`
   automatically. The single line that matters is the `"verdict"` field:
   `strong_pass` | `falsification` | `inconclusive`.

## Pre-registration is the whole point

Read `PREREG.md` before changing any parameter. The runner refuses to run
if the chimera seed's SHA differs from `seed/.chimera.sha256` — that's the
guard against silent ontology drift mid-experiment.

The pre-registered thresholds (PREREG.md §5):

| Outcome | Criterion |
|---|---|
| `strong_pass` (H1: structural) | A − B ≥ +5 pp AND Fisher exact p < 0.05 |
| `falsification` (H0: priming only) | A − B ∈ [−2, +2] pp AND Newcombe 95% CI on diff contains 0 |
| `inconclusive` | anything else |

No multiple-comparison correction is applied because there is one primary test
on one primary outcome.

## Sanity check: the analyzer reproduces v4 paper §5.1

Before running anything new, confirm the analyzer reproduces the v4 published
Run E numbers:

```bash
python scripts/analyze_experiment_6.py \
    --condition-a runs/20260512_091444_topology.json \
    --condition-b runs/20260512_091444_similarity.json
```

Expected output (verifies the analyzer matches the paper):

```
condition_a: 76.67% Wilson CI [69.28, 82.72]
condition_b: 76.00% Wilson CI [68.57, 82.13]
difference:  +0.67 pp, Newcombe CI [−8.93, +10.25], Fisher p = 1.000
verdict:     falsification
```

If those numbers print, the analyzer is sound.

## What this experiment can and cannot answer

It can distinguish: structure-vs-priming for the v4 +8 pp lift, on
qwen2.5:32b, on these six puzzles.

It cannot distinguish: training-data exposure to the SToE vocabulary
(separate experiment with post-cutoff manifest required), and cannot speak
to the larger framework — see paper v4 §7.4.

## If you change anything

The PREREG.md protocol is locked. If you must deviate (different K, different
puzzles, different model), the paper must report the deviation explicitly
under a "Deviations from pre-registration" subsection (PREREG.md §7). Do not
edit thresholds after seeing the result. Do not stop early. Do not re-run
conditional on outcome.

The methodological discipline is the part that holds whether the result is
positive, null, or inconclusive.
