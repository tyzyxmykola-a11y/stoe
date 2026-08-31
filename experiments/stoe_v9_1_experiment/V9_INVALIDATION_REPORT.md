# V9 Primary Invalidation Report

## Scientific status

The completed `stoe_v9_experiment` remains immutable historical evidence. Its primary score, traces, counterfactuals, reports, benchmark, canonical seed, source, and manifests are not overwritten or retroactively rescored.

**V9 scientific status: `V9_PRIMARY_INVALID_CONTEXT_BUDGET`.**

This status invalidates the old v9 primary as a test of its claimed equal four-artifact model exposure. It does not delete the observations or imply what a corrected run will show.

## Defect

V9 selected up to four eligible artifacts and recorded `realized_artifact_count` from that selection. Its serializer then appended complete artifact lines until the next line would exceed the total 5000-character memory budget:

```python
candidate = "\n".join(lines + [line])
if len(candidate) > max_chars:
    break
lines.append(line)
```

The `break` made selection count and exposure count non-equivalent. When one selected artifact was oversized, v9 discarded that artifact and every selected artifact after it. Thus a row could record four selected nodes while Gemma actually received fewer than four `[MEMORY_REF ...]` blocks.

This violated the intended invariant:

```text
selected_artifact_count == 4
    implies
model_visible_artifact_count == 4
```

and could create unequal exposure across conditions depending on artifact length and order. Large canonical seed nodes make this defect especially consequential, but seed content and seed size are not the bug. The bug is list-ending serialization.

## Corrective scope

V9.1 is a **CORRECTIVE REPLICATION**, not an independent confirmation and not a new architecture version. It reuses the known benchmark only to measure the same frozen architecture after repairing the measuring instrument.

The intended v9→v9.1 scientific difference is limited to:

1. deterministic post-selection, per-artifact bounded serialization under the unchanged 5000-character total budget;
2. truthful selected-versus-model-visible exposure accounting;
3. a fatal exact-final-context assertion before every memory-bearing model call;
4. tests, audits, dry-run records, and trace fields needed to verify those properties.

Navigator selection, weights, graph construction, seed/chimera topology, benchmark, answers, conditions, prompts except strictly necessary memory block formatting, model settings, retry policy, statistics, success criteria, and counterfactual definitions remain frozen.

## Historical result handling

The known v9 results—including observer-aware 13/18 overall and 9/9 targeted—remain the original, invalid-context-budget observations. V9.1 results will be reported separately and will not be presented as corrected historical v9 scores. Because v9 results and benchmark answers have already been inspected, a later new holdout benchmark is required for independent confirmation regardless of the v9.1 outcome.
