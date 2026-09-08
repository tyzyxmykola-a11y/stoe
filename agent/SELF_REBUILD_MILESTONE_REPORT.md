# SToE research-agent self-rebuild milestone

Status: **FUNCTIONING SUPERVISED LIFECYCLE; PARTIAL SUCCESSOR ADOPTED IN A LATER BOUNDED CYCLE**

Date: 2026-09-06

Branch: `feature/self-rebuild-cycle-v1`

## Continuation after the initial negative milestone

The initial checkpoint below correctly recorded that no successor had been
adopted. Its final rejected candidate revealed a feasibility mismatch: the model
proposed graph-edge weighting even though `select_context` receives no graph
edges. The supervisor was then changed to require an explicit list of public
runtime inputs and to reject candidates that do not improve the disclosed
diagnostics before protected evaluation. Protected cases, evaluator, thresholds,
and the active `v1` source were unchanged.

One—not an indefinite sequence—new local-Ollama cycle then ran. The generated
candidate improved disclosed diagnostics from 0/3 to 1/3 and protected cases from
1/5 to 3/5. It newly passed the critical privacy case and the measured-evaluation
case, preserved the critical budget case, introduced no regression, and passed a
fresh-process activation check. It was therefore adopted under the fixed rule as
`generated_20260906T125305Z_92e7e913`.

The improvement is partial and mechanistically narrower than the proposal. The
source boosts `supported` outcomes and evaluation kinds; it still misses the two
protected cases that require reactivating a rejected hypothesis after a constraint
change. Its public “raised storage ceiling” case also remains failed. The result
supports one supervised agent-owned software improvement in this adaptive
development setting. It is not independent experimental evidence for topology,
the canonical ontology, self-modifying model weights, AGI, or unrestricted
self-rebuilding.

The checked-in `active_release.json` and source hash allow a new process or clean
checkout to reconstruct the adopted version without conversation history. The
full continuation record is in
`rebuild_reports/20260906T125305Z_92e7e913.json` and its concise Markdown report.

## 1. Infrastructure built to enable the capability

The agent now owns a replaceable research-context selector while a separate
trusted supervisor owns proposal validation, protected evaluation, activation,
rollback, and integrity checks. A local Ollama model may return only a structured
research proposal and one selector source file. It receives no shell, filesystem,
network, Git, evaluator, active-pointer, or acceptance-rule authority.

Candidate source passes a restrictive AST gate and runs in a time-bounded child
process. The supervisor hashes protected inputs before and after generation and
evaluation. Adoption requires all of the following: strictly more protected
passes, no regression on an active pass, no critical failure, unchanged protected
hashes, and a healthy fresh-process activation check. A snapshot precedes pointer
change; failed health restores the previous pointer and verifies it in another
fresh process.

The persistent SQLite field contains the canonical 36-IP, 113-relation SToE seed
and runtime architecture, observer-state, state-change, failure, proposal,
implementation, evaluation, activation, and rollback IPs in one directed field.
The canonical seed remains losslessly foldable and has SHA-256
`b327db6dbce9981ed21561b9d1a857e2e3786f1391d41edc0381fead79e59868`.
Seed nodes receive no blanket score bonus and enter prompts only through bounded
navigation.

## 2. Investigation the resulting agent actually performed

In the initial milestone's final bounded real cycle, the active selector was run on three public,
non-protected diagnostic situations: a resource constraint changed, a privacy
constraint remained active, and measured evaluation evidence competed with an
untested claim. The active selector failed all three. Its observed selections
and the exact required-but-missed references were written into the shared field
as evaluation and failure-history IPs.

For the same observer states, the SToE navigator inspected typed, directed paths.
It recovered all three missed references. For example, the storage case followed
`CurrentObserverStateIP -> contains_change -> state-change IP -> invalidates ->
failed constraint IP -> reverse(rejected_by) -> failed reasoning IP`. Competing
items, unselected paths, edge directions, and decomposed scores are retained in
the JSON trace. A synthesis observer state then navigated through directed
`depends_on` links to the observed failures before the model formulated a change.
This is the inspectable connection from SToE operations to an actual research
decision; merely loading the seed is not counted as evidence.

## 3. Candidate change generated through that investigation

The initial milestone's final `qwen3-coder:latest` cycle hypothesized that goal-only lexical overlap
misses state-change, failure, and evaluation relevance. It proposed weighting
typed relations. The generated candidate was syntactically safe, but mapped
relation labels onto `failure_condition`, which is prose. Because the component
input does not contain navigator edges in that field, its intended edge weights
never fired. This was an AI-generated candidate, not a hand-authored desired
discovery.

Earlier preserved local cycles also failed safely: one weakly grounded candidate
tied the baseline, one proposal response was truncated and became `ERROR_REJECT`,
and one model emitted schema values instead of executable source and failed the
static gate. Supervisor defects exposed by those attempts—ungrounded proposals,
empty structured response handling, and fail-closed provider errors—were repaired
without changing protected cases or the acceptance rule. All attempts are kept
under `rebuild_reports/`; rejected executable candidates are kept under
`rejected_candidates/`.

Post-milestone authority-boundary correction: the historical AST static gate was
not a security sandbox. Independent review demonstrated that indirect access via
`__builtins__` could pass validation and would execute with the evaluator child
process's ambient authority. The original attempts and evidence above are not
rewritten. Future generated artifacts are instead inert declarative selection
policies interpreted by trusted, bounded code. This is an infrastructure repair,
not evidence that any research hypothesis or SToE mechanism performs better.

## 4. Evidence supporting adoption or rejection

That final initial-milestone candidate and active selector were evaluated on the same five protected
cases. Both passed 1/5. Both failed the critical privacy case. The candidate
therefore failed the preregistered adoption rule and was not activated. Active
`v1` SHA-256 remains
`7f4b5aa6b50b4f504915792b88b681b68cf6864f669f4504876a9bea3406d56c`.

Protected hashes:

- cases: `76512fc8fda0c0ae31e47c9ba0d8fb6e2555c27f531b0700221673b506444138`
- evaluator: `6be6246238aedb0c37a72be6e2623772ba6ff1b67415fa46ab3ab4272e3fec06`

The evidence supports rejecting the generated successor. It supports the narrower
claim that the lifecycle can observe a limitation, use an SToE field to connect
missed structure to a bounded model decision, evaluate a generated implementation,
and refuse adoption. It does not support successful self-improvement, an advantage
for the full SToE ontology, or a claim that the navigator's public diagnostic wins
generalize to protected selection.

## Recovery, continuity, and boundary

The isolated deliberate-failure probe changed a temporary active pointer to a
component that raises on activation. Health failed, the supervisor restored `v1`,
and a fresh worker process selected `HEALTH_EVAL` while reporting the canonical
seed and persistent field as healthy. The probe passed without touching the live
pointer. Runtime field state and snapshots are local and Git-ignored; code,
tests, compact traces, rejected candidates, and this report are versioned so a
later task can resume from a known commit.

The system can rebuild only agent-owned components admitted by the supervisor.
It cannot rewrite model weights, Ollama, host permissions, protected evaluation,
or the supervisor through this interface. Those remain external dependencies and
human-controlled authority.

## Verification completed

- agent rebuild and continuity suite: 23/23 passed
- memory plugin suite: 9/9 passed, including real stdio integration
- v9.1 experiment suite: 50/50 passed
- v3 experiment suite: 21/21 passed
- canonical seed validator: passed
- deliberate activation-failure recovery probe: passed
- Git whitespace check: passed

The activation-path unit test uses a deterministic fake generator to exercise
mechanics. It is test coverage only, not empirical evidence of model-guided
self-improvement.

## Remaining research question

The investigation reveals a boundary mismatch: SToE navigation can exploit typed
paths that the current owned selector API does not receive. A future preregistered
cycle should decide whether to add a bounded structural feature to that API or
seek a selector improvement using only existing observer/item fields. That is a
new architecture hypothesis and should be evaluated with fresh protected cases;
it was deliberately not resolved by tuning after the rejected result.
