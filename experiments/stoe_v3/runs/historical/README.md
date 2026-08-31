# SToE v3 Benchmark Runs

This directory holds artifacts from every `python -m harness.cli` invocation.
Files are timestamped `YYYYMMDD_HHMMSS_*` so multiple runs don't collide.

## File types per run

| Filename pattern | What it is |
|---|---|
| `<ts>_topology.json` | Full per-attempt report, topology context mode. Includes every LLM response_tail, structural verdicts, failed_from-in-context counts, per-puzzle solve breakdown. |
| `<ts>_similarity.json` | Same shape, similarity context mode. |
| `<ts>_diff.json` | Aggregate comparison: delta solve rate, failed_from ratio, verdict (`strong_pass` / `weak_pass` / `falsification` / `undetermined`). |
| `<ts>_topology_field.json` | Field state snapshot (only if `--fresh-field` is NOT set). Includes seeded ontology + every node and edge produced during the run. |
| `<ts>_similarity_field.json` | Same for similarity mode. |
| `<ts>.stdout.log` | Raw stdout of the CLI run — header, per-mode summary lines, diff section. |

## Verdict thresholds (locked in PLAN.md slice 0)

| Verdict | Trigger |
|---|---|
| `strong_pass` | topology solve rate ≥ similarity + 15pp **AND** topology shows ≥3× more `failed_from` traversals (or similarity surfaces zero, qualitatively the strongest signal) |
| `weak_pass`   | topology solve rate > similarity, but failed_from advantage doesn't reach 3× |
| `falsification` | solve rates within 1pp of each other AND no measurable failed_from divergence |
| `undetermined` | similarity wins, or none of the above conditions hold |

## Existing runs in this directory

(Populated as runs accumulate. Each is shareable as-is — JSON + log only, no
binary blobs, no model weights, no opaque state.)

## Reading a run

```python
import json
rep = json.load(open("20260510_205519_topology.json", encoding="utf-8"))
print(rep["aggregate"])                # solve rate, attempts, failed_from
for run in rep["runs"]:
    for attempt in run["attempts"]:
        print(attempt["response_tail"])  # last 400 chars of LLM output
```

The diff file is the executive summary. Open it first.
