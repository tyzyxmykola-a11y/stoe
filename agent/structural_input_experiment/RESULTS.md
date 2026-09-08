# SToE Structural-Input Experiment v1 — Result

Status: **RUN ONCE — INCONCLUSIVE EXECUTION FAILURE**

No candidate was evaluated or activated. The experiment did not produce a valid ordinary-versus-structural comparison, so the zero-filled unevaluated candidate metrics in the machine report must not be interpreted as `0/12` performance or as a tie.

## Frozen identity

- Freeze commit: `6de3254c136f5a4385055bcb463cd111ca03504c`
- Model: local Ollama `qwen3-coder:latest`
- Model digest: `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca`
- Hidden cases: 12 independent instances (8 changed-constraint targets, 4 controls)
- Case SHA-256: `10c9e3685bc3634715d65418fb694203309698dfc5d9ec73b257aa9857e9186b`
- Frozen input-bundle SHA-256: `45a7b363bfbfc19038e66901ea101db93af20d7eb96c5a7740e3af9662d46c49`
- Raw result SHA-256 before this report: `68c2e5c2ec0de85e6930b099333362e4e0aa06c2ec88d9bc8af653a67f94410e`

## What happened

Only the proposal call occurred in each arm: 2 actual model calls of the preregistered maximum 4, with no retries.

| Condition | Proposal tokens (input/output/total) | Proposal outcome | Policy call | Hidden evaluation |
|---|---:|---|---|---|
| `ORDINARY_OBSERVABLE` | 2,473 / 762 / 3,235 | Rejected by grounding validator | Not run | Not run |
| `BOUNDED_TYPED_STOE` | 3,671 / 760 / 4,431 | Passed grounding validator | Blocked locally before Ollama | Not run |

The ordinary proposal named the active selector's `kind` check as the mechanism for one failed diagnostic. `item.kind` is an allowed public input and is present in the active source, but the frozen validator's narrow lexical allowlist omitted the word `kind`. It therefore rejected a substantively source-grounded statement as ungrounded.

The structural proposal passed that gate. Its policy-generation prompt was then estimated at 8,388 tokens including the fixed output and checkpoint reserves, exceeding the frozen 8,192-token context limit by 196. The budget manager stopped the call before it reached Ollama. This protected the context invariant, but it also shows that the preflight checked a representative prompt rather than the worst allowed proposal size.

The active legacy selector was evaluated after both generation attempts. It passed 3/12 overall: 0/8 changed-constraint targets and 3/4 controls. This confirms the hypothesized active limitation on the newly frozen cases, but it does not compare candidate improvements.

## Scientific decision

- Preregistered structural success criterion: **NOT EVALUABLE**.
- Evidence that typed SToE connections improve self-development: **NONE FROM THIS RUN**.
- Activation: **NO**.
- Rerun of v1: **NO**. The cases and both proposal responses have now been observed; changing the gate or token allocation and reusing these cases would no longer be confirmatory.

The run is informative as a failed experiment: representation-level gate wording and worst-case prompt feasibility were not adequately validated. It is not evidence for or against the structural hypothesis.

## Exact remaining research question

On a newly authored and frozen set of unseen changed-constraint cases, does a content-matched typed/directed relational overlay improve the generated inert selector policy over ordinary memory when (a) proposal grounding is validated structurally against the allowed input fields rather than by a lexical word list, and (b) both complete two-call pipelines are proven to fit the same context budget for every schema-valid proposal before any model call?

Any v2 must use new hidden cases, retain the v1 raw traces unchanged, preregister a worst-case budget proof, and still give SToE no favorable tie-break or post-result tuning.
