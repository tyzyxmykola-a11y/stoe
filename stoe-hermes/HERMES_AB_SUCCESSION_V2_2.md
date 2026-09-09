# Hermes A/B Succession v2.2

Status: **VALIDATOR CORRECTED — EXACT V2.1 CANDIDATE QUALIFIED — INACTIVE PENDING AUTHOR APPROVAL**

Stable action: `self-code-cycle:hermes-ab-v2-2:parent-relative-validation`

## Conserved v2.1 failure

The v2.1 code-model call produced a complete inert candidate whose reconstructed
SHA-256 was
`fc16fd51028967cd9972332ec671f8a3bb0c72815343a495df502cafd5d052ff`.
It was rejected before application or execution because the protected validator
categorically rejected `ast.Raise`, although the exact `raise ValueError` guard
already existed in trusted parent
`b1d11d98c8797c11fcd5ff7f8e337764580ca8c4a6c9ca66a32c336158041155`.
That historical failure and its reports were not rewritten.

## Parent-relative correction

The v2.2 validator does not whitelist `Raise`. For every capability-forbidden
candidate AST node it computes a trusted structural fingerprint containing:

- the normalized editable-function signature;
- the normalized AST prefix through the top-level statement containing the node;
- the exact AST field/index path from the function body to the node; and
- the forbidden node type and complete subtree.

A candidate occurrence is grandfathered only when its fingerprint consumes one
matching parent occurrence. This multiset rule rejects added duplicates. The
prefix binds earlier state and the guard/control-flow region; the path binds the
occurrence's structural location. AST normalization tolerates formatting-only
parentheses but does not treat alternate expressions as equivalent.

The matched forbidden subtree includes its descendants. Capability checks are
skipped only inside that exact inherited subtree, which is necessary because the
trusted inherited `Raise` contains a `ValueError(...)` call that is otherwise
outside the candidate call allowlist. New or modified descendants change the
fingerprint and remain rejected.

The categorical v2.1 validator remains available under its original function
name for exact historical action replay. The corrected boundary is explicitly
versioned as `validate_candidate_source_v2_2` and is called only by the v2.2
validation wrapper. The v2.1 test artifact remains byte-identical to its recorded
manifest hash.

For the reproduced candidate the validator recorded one grandfathered node:

- type: `Raise`;
- parent occurrence: 1;
- candidate occurrence: 1;
- structural path: function `body[1]` → branch `body[0]`;
- comparison: `normalized_ast_prefix_and_structural_path`;
- fingerprint: `f559a161ab5b43ab39a7393fe7e4196d7cb069c7c843cf47aebc0b4ea95e074b`.

## Adversarial qualification

The focused v2.2 and conserved v2.1 tests passed 18/18 before candidate
execution. They demonstrate:

- unchanged inherited `Raise` accepted;
- formatting-only parentheses accepted after AST normalization;
- second/duplicate `Raise` rejected;
- exception type and message changes rejected;
- guard changes and semantically reordered comparison rejected;
- new prior state affecting the guard rejected;
- relocation, duplicated surrounding block, and equivalent new branch rejected;
- a different forbidden node type rejected;
- import and call-authority expansion rejected; and
- malformed patches, stale parent hashes, and protected/out-of-scope paths rejected.

The matching is intentionally conservative. A harmless edit before an inherited
forbidden construct may be rejected because it changes the normalized prefix.
That false-positive bias is preferable to silently granting candidate authority.

## Same-candidate reproduction and protected result

No model was called in v2.2. The exact parsed v2.1 inert proposal is preserved at
`evidence/v2_2/v2_1_candidate_patch.json`. Reconstructing it produced the same
candidate SHA-256, proving byte-identical reproduction rather than a tuned
successor.

Only after corrected static validation passed, the candidate ran in a separate
ignored evaluation package. The unchanged v2.1 withheld focused protocol passed
2/2: syntax was valid; one canonical payload was rendered once; both distinct
SToE connection/provenance records survived; legacy and explicit counters were
correct; input data was unchanged; and the output budget was respected.

Execution used the existing bounded process monitor with 20-second, 100,000-byte
output, 2 GB RAM, 12-process, and 250 MB disk-growth limits. Peak measured RAM
was below 20 MB and no limit fired. This process ran under the caller's Windows
identity and is **not** an OS security sandbox. Static capability validation is
the authority boundary for this pure formatter candidate.

The active `context_renderer.py` remained at the parent hash. The active release
pointer remained at SHA-256
`b6a1e4f89ea85a845eda7a8aa821135fa152cbbb126f3c294a6dc0a10e7c82c3`.
No source was copied into the active adapter and no pointer was switched.

## SToE continuity and regression

Observer state `STATE_9b67da81d2c7479d` and retrieval
`RETRIEVAL_c06df2a38cb44a31` recovered the v2.1 failure, diagnosis, evaluation,
correction authorization, and v2.2 succession state without loading the seed or
repository history. The field connects correction `IP_4afce2212e8c4bf3`,
validation `IP_f4d2f7b504cd433f`, exact candidate `IP_52b9f2678db549e0`, protected
evaluation `IP_48cf7c158ae24efd`, decision `IP_80337f0df2224e72`, and next action
`IP_8eed182da4384b73` to the conserved v2.1 failure.

Final observer state `STATE_eef3fe6eb8ce4e73` and fresh navigation
`RETRIEVAL_e5092f84df20472d` reconstructed the approval decision and exact next
action under a 3,000-character retrieval budget, with no seed injection.

Full deterministic regression passed:

- Hermes: 32/32;
- Agent, including Local Worker Delegation: 101/101;
- SToE Memory: 9/9;
- v9.1: 50/50; and
- v3: 21/21.

Canonical seed validation, release-hash verification, Python compilation, and
`git diff --check` also passed.

## Decision

The validator correction and exact candidate are technically qualified. This is
evidence for one bounded succession mechanism, not unrestricted recursive
self-improvement, OS isolation, general intelligence, or the full SToE ontology.

The candidate remains inactive. Mykola must explicitly authorize a separate
promotion action bound to candidate SHA-256
`fc16fd51028967cd9972332ec671f8a3bb0c72815343a495df502cafd5d052ff` and parent
SHA-256 `b1d11d98c8797c11fcd5ff7f8e337764580ca8c4a6c9ca66a32c336158041155`.
That action must create the approved release record, use the protected supervisor,
run health checks, and retain Hermes A as rollback target.
