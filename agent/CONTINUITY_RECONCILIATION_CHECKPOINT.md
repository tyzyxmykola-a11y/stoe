# Continuity reconciliation checkpoint v1

Stable action: `checkpoint:continuity-reconciliation-v1`

Status: implementation checkpoint; no provider/model generation and no new
scientific experiment.

## Observed failure

The prior loader returned `runtime/research_state.json` as soon as that ignored
file existed. It did not compare the runtime state with the tracked
`research_checkpoints/LATEST.json` checkpoint or `research_state/bootstrap.json`.
After a repository update, a valid but older runtime could therefore suppress a
newer tracked research question. The active component pointer had the same shape:
an existing runtime pointer bypassed `active_release.json` reconciliation.

This corrects the continuity claim without changing historical reports, scores,
protected cases, thresholds, or evidence classifications. Storage had preserved
the old state; it had not preserved which state was the connected successor.

## Repair

Research-state checkpoints now have a hash-verified lineage manifest. Each entry
binds an immutable checkpoint-file hash and logical state fingerprint to its
declared parent, complete ancestor set, stream, and branch. Runtime and bootstrap
states have fingerprint-bound lineage records. Resume considers runtime, latest
checkpoint, and bootstrap together:

- a runtime fingerprint found in tracked checkpoint ancestry is fast-forwarded;
- a runtime descendant whose sidecar proves the tracked state is an ancestor is
  preserved byte-for-byte;
- equal states converge on the tracked representation;
- unrelated streams, sibling states, lineage/hash mismatches, and cross-branch
  histories fail with `ContinuityDivergenceError` instead of guessing.

The active selector uses the same rule. `active_release.json` and the ignored
runtime pointer carry content-addressed release lineage. A stale `v1` pointer
fast-forwards, a proven successor is preserved, and an unrelated release fails
explicitly. Existing legacy release ancestry is migrated only through the known
`v1 -> generated_20260906T125305Z_92e7e913` chain.

## Context folding

The complete research state and artifacts remain externally recoverable by path,
SHA-256, and source reference. Resume now keeps the current question, failure and
correction evidence, recent decisions, all completed action IDs, active version,
and next executable step while folding older definitions and decisions into
counts and references. The 1,800-token resume projection targets 80% occupancy.
The measured fresh-process result is recorded after final verification below.

## Verification

Deterministic tests cover stale runtime, provably ahead runtime, divergent
histories, clean checkout, cross-branch state, stale active pointer, ahead active
pointer, and divergent active release. Checkpoint hashes, parent lists, and
fingerprints are independently recomputed when the manifest is loaded.

Verification completed:

- agent suite: 38/38 passed;
- v9.1 suite: 50/50 passed;
- v3 suite: 21/21 passed;
- memory-plugin suite: 9/9 passed (the stdio integration test required the
  already-authorized local subprocess boundary); no dependency-blocked tests;
- immutable accepted-selector replay: public 1/3, protected 3/5, with zero
  critical failures—this is a compatibility replay, not a new blind result;
- fresh-process resume: 1,424 estimated tokens of 1,800, leaving 376 tokens of
  reserve before this checkpoint's additional state is folded;
- `git diff --check`: passed before commit.

Historical SHA-256 values remained unchanged:

- accepted report: `a008eba9e581ccb1850f509c1a535c26b7b6c361c3174a0936fb18dd473677b1`;
- accepted selector: `d37f48335f87c4c4370ea78d7719cf3a79aa26ef41b0911c81f448f7828d2cb1`;
- protected cases: `76512fc8fda0c0ae31e47c9ba0d8fb6e2555c27f531b0700221673b506444138`;
- historical evaluator: `6be6246238aedb0c37a72be6e2623772ba6ff1b67415fa46ab3ab4272e3fec06`.

## Scientific boundary and remaining question

This is infrastructure evidence, not evidence that SToE improves task
performance. It establishes deterministic succession and fail-closed continuity.
It does not answer the pending scientific question:

> Why did changed-constraint invalidation fail to materialize, and can a bounded
> structural input improve it on newly frozen cases without expanding candidate
> authority?

That experiment remains not run.
