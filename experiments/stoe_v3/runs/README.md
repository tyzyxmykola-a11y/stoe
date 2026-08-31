# v3 evidence archive: read this before the historical index

This package preserves 61 original JSON reports in `results.tar.gz`, including
pilots, exploratory comparisons, later runs, and 13 completed Experiment 6
condition reports. The later conditions each contain 300 recorded trials:
3,900 trials in total on the same six puzzles, not 3,900 independent tasks.

## Main Experiment 6 A/B comparison

Native SToE adjacency: **233/300 (77.67%)**. Rewired music adjacency with SToE
concept identities: **234/300 (78.00%)**. The archived analyzer reports A-B =
-0.333 percentage points, Fisher two-sided p = 1.0, and Newcombe 95% interval
[-6.97, +6.31] percentage points. This does not show a detected native-structure
advantage in that setup. The saved `falsification` label is the historical
protocol's decision rule, not proof of equivalence or of a priming-only mechanism.

## Later condition inventory

Condition descriptions below follow the original filenames. Most report headers
record model/mode and times but do not fully encode all launch flags. The A/B
runner is supplied; do not silently treat every later condition as part of the
same preregistered primary test. All these headers name `qwen2.5:32b`.

| Report | Solved / trials | Rate |
| --- | ---: | ---: |
| `exp6_20260514_190304_A_topology.json` | 233/300 | 77.67% |
| `exp6_20260514_190304_B_topology.json` | 234/300 | 78.00% |
| `exp6_20260515_095148_C_music_K_topology.json` | 237/300 | 79.00% |
| `exp6_20260515_172435_D_stoe_K_similarity.json` | 239/300 | 79.67% |
| `exp6_20260516_010243_E_floor_topology.json` | 243/300 | 81.00% |
| `exp6_20260516_070834_F_stoe_basic_topology.json` | 241/300 | 80.33% |
| `exp6_20260516_131002_H_chimera_K_similarity.json` | 238/300 | 79.33% |
| `exp6_20260516_201949_I_chimera_basic_topology.json` | 228/300 | 76.00% |
| `exp6_20260517_025008_G_stoe_basic_similarity.json` | 236/300 | 78.67% |
| `exp6_20260517_091300_K_music_K_similarity.json` | 227/300 | 75.67% |
| `exp6_20260517_165939_L_music_basic_topology.json` | 241/300 | 80.33% |
| `exp6_20260517_231636_M_music_basic_similarity.json` | 234/300 | 78.00% |
| `exp6_20260518_053720_J_chimera_basic_similarity.json` | 234/300 | 78.00% |

## How to interpret the older documents

The [historical index](historical/INDEX.md) describes earlier K=25 exploratory
cells. Its claims of strong support are not the summary of these later K=50
runs and should not be quoted as such. The protocol itself describes the earlier
+8 pp observation as exploratory, raw p approximately .099 and not robust to
multiple-comparison correction.

The [protocol](../PREREG_exp6.md) calls itself locked but leaves the lock date
blank. This archive cannot certify a pre-outcome timestamp. In addition,
`core/llm.py` does not send explicit decoder options or pin model digests,
although decoder settings appear in the protocol. Repeated `seed_idx` values
are trial labels, not configured model RNG seeds. Puzzles were calibrated on
the same model. Preserve these limitations when analyzing or citing the data.

The v9.1 experiment uses different tasks, a different model, stronger comparison
retrievers, and different exposure checks. Do not combine the result percentages
as though they measure one unchanged system.

## Restore

From `experiments/stoe_v3`:

```text
python scripts/restore_archived_results.py
```

This verifies the original size and SHA-256 of all 61 JSON reports using
`ARCHIVED_RESULTS.json` and restores their original filenames in this directory.
It refuses to overwrite changed results. Raw stdout/session logs and live field
snapshots are omitted. Restored report files are ignored by Git; the verified
archive remains the committed source of record.
