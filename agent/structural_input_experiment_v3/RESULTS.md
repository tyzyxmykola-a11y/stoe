# SToE Structural-Input v3 Results

Status: **COMPLETED ONCE — NO ACTIVATION — DO NOT RERUN**

## Primary result

| System | Changed-constraint targets | Controls | Total |
|---|---:|---:|---:|
| Active legacy selector | 1/8 | 4/4 | 5/12 |
| Ordinary observable generation | 3/8 | 3/4 | 6/12 |
| Bounded typed SToE generation | 0/8 | 1/4 | 1/12 |

Preregistered primary comparison:
`BOUNDED_TYPED_STOE - ORDINARY_OBSERVABLE = -3/8` targeted cases.

The preregistered success criterion required at least `+2/8` with no control
loss. It was **not met**. Both candidates scored `0/3` on the disclosed public
diagnostics, failed the public and acceptance gates, and were ineligible for
activation. There was no winner and the active release was unchanged.

Raw result:
`results/20260908T053018Z_structural_v1.json`

Raw-result SHA-256:
`ff7de9b79d146c83d39c09445f974cfee76fce4f7f705b6347dc8c4f5bdaf7df`

Frozen benchmark SHA-256 before and after evaluation:
`f14d953c890e296c392918ce9ac6f821b8ce2020f853f7ea2e8aa9964bd18b65`

## Integrity and execution

- The response harness was frozen only after its third public-only revision
  completed `6/6` real-Qwen development pipelines without retry.
- The twelve v3 cases were authored and hash-locked after that freeze.
- The experiment used local Ollama `qwen3-coder:latest`, exact digest
  `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca`.
- Both arms used temperature `0`, top-p `0.9`, top-k `40`, context `8,192`,
  identical seeds, two calls, no retry, the same active source, public evidence,
  unstructured memory, policy language, scoring implementation, and gates.
- The structural arm alone received the preregistered bounded typed/directed
  overlay. No v3 identifier occurred in either model prompt.
- All four responses passed the exact proposal/policy schemas. The run took
  `48.75` seconds and made exactly four calls.
- Ordinary used 5,430 provider-counted tokens; structural used 7,106. The latter
  difference is the cost of the preregistered structural treatment, not an
  unreported budget change.

## What the generated policies actually did

The ordinary policy retained one useful unconditional mechanism: token
similarity from `observer_state.goal` to `item.content`. Its additional fixed
condition groups were generally impossible conjunctions, but the lexical rule
still selected the required item in three target cases and three controls.

The structural policy replaced that useful comparison with token similarity
from `item.outcome` to `observer_state.changed_constraints`. Those fields are
semantically mismatched (`rejected` versus a prose constraint change), so the
score was normally zero. It also populated all six condition tables inside each
conditional rule. The trusted interpreter correctly treats conditions within a
rule as conjunctions. Examples therefore required an item simultaneously to be
a hypothesis, not be rejected, occur under an exact public-case constraint,
contain the token `hypothesis`, and meet other predicates. No unseen item could
satisfy those public-specific conjunctions.

With every meaningful score at zero, deterministic tie-breaking selected the
newest fitting item. That was usually the generic distractor. The structural
policy passed only the budget control because greedy oversize skipping selected
the two smaller items independently of semantic score.

This is not a JSON failure. It is a valid but behaviorally degenerate policy
caused by the structural arm's model-generated mapping from evidence to
operations.

## Target-by-target comparison

Ordinary succeeded on:

- `digitized_register_reopens_linkage`
- `interface_consensus_reopens_federation`
- `reference_material_reopens_quantitation`

Typed structural succeeded on no changed-constraint target. It selected the
highest-created-order distractor in all eight targets.

The ordinary policy lost the chain-of-custody control and passed the allergy,
replication, and budget controls. The structural policy failed the two critical
controls plus the replication control; it passed only the budget control.

## Scientific interpretation

V3 is evidence **against the current structural-input generation pipeline**.
Adding the bounded typed overlay caused this fixed model and frozen generation
procedure to produce a substantially worse selector than ordinary observable
input. It supplies no evidence that SToE structure improves changed-constraint
reactivation.

The result does not falsify the full SToE ontology. It tests only whether this
particular typed overlay, serialized into a Qwen generation prompt and compiled
through this policy grammar, yields a better selector. It did not.

The two earlier holdouts still establish the legacy selector limitation:
baseline `0/8` targets with `3/4` controls in v1 and `0/8` with `4/4` controls in
v2. V3 independently found `1/8` and `4/4`. The weakness therefore remains
strongly supported; what failed is the proposed route to repairing it.

## Exact remaining research question

Why does the typed overlay lead Qwen to translate a structurally relevant
changed-constraint/failure relation into the mismatched operation
`item.outcome -> observer_state.changed_constraints` and overconstrained
public-specific conjunctions, and can an independently qualified representation
express the intended bounded comparison
`observer_state.changed_constraints -> item.failure_condition` without embedding
the desired answer, overfitting disclosed cases, or changing the paired
information and acceptance budgets?

Any future investigation must begin on exposed development cases and a newly
qualified instrument. V3 must not be tuned or rerun, and its cases must not be
reused as a holdout.
