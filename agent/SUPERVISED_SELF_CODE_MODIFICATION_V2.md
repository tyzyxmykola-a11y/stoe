# Supervised self-code-modification cycle v2

Status: **FAILED SAFELY AT FORMATTING QUALIFICATION — NO REAL CANDIDATE CALL, NO ACTIVATION**

Stable action ID: `self-code-cycle:v2:deduplicate-development-context`

## Outcome

The v2 infrastructure is complete, but the requested source candidate did not materialize. The first disclosed `gemma4:26b` formatting qualification passed. The trusted client terminated the second qualification at its then-active 64,000-byte raw NDJSON capture limit before Ollama emitted a terminal event. The mandatory two-of-two gate therefore failed, and the workflow made **zero** real candidate-generation calls. It did not fabricate a patch, weaken validation, retry a closed call, modify the active reporter, activate, merge, or install anything.

This is an engineering failure of the measuring instrument, not evidence for or against SToE and not conclusive evidence that the model violated the schema.

## Operational SToE use

The installed `stoe-reasoning` skill governed the workflow: observer state was explicit; the v1 malformed-response failure remained a first-class failed IP; the v2 correction pointed to that failure; the new failure was preserved rather than overwritten; and evidence, decision, correction, and succession were joined by typed directed relations.

SToE Memory was used as the actual persistent field, not as a label. Before implementation, observer state `STATE_fb700af6df5d4ad8` navigated through `contains_change`, `invalidates`, `diagnoses`, `evolved_from`, and `constrained_by` relations. Retrieval run `RETRIEVAL_e9545d17775f4a8f` selected 8 of 10 candidates under depth/item/character limits, including the v1 failure, raw-response-loss diagnosis, editable boundary, token policy, objective, and exact successor action. Large sources and responses were represented by paths and hashes.

The completed attempt wrote connected objective, observation, retrieved-evidence, constraint, correction, qualification, model-attempt, raw-response, failed-attempt, evaluation, decision, successor-state, and exact-next-action IPs. Important refs include:

- failure `IP_f58a2d8c03324ce4`;
- raw artifact `IP_fceadd1fc2c04314`;
- evaluation `IP_f12af6b51d974449`;
- decision `IP_74fe235d9aa642c4`;
- successor state `IP_4b9f7f3760e042fc`;
- next action `IP_dc939f9e5f1d4e6f`.

Final observer state `STATE_7a275e2914914a94` produced bounded resume retrieval `RETRIEVAL_81092e46f67f4499`: 8 selected IPs, 1,612 content characters, no seed dump, and exact-next-action/failure/boundary continuity. The tracked continuity snapshot contains references only; the plugin database remains the canonical persistent field.

## Infrastructure and validation

`self_code_cycle_v2.py` adds:

- lossless raw NDJSON persistence with flush and `fsync` before parsing;
- exact model/digest/context verification against Ollama 0.33.3;
- native JSON-schema structured-output requests;
- strict duplicate-field JSON parsing;
- a simpler inert `stoe.line_patch` envelope containing bounded replacement lines rather than a JSON-escaped whole source file;
- exact editable path and parent-hash locking;
- UTF-8, byte, line, AST-operation, metadata, secret, dependency, protected-path, and stale-parent checks;
- stable started/completed/failed call state that prevents replay after interruption;
- SHA-canonical payload deduplication that retains a separate record for every typed/provenance connection;
- isolated candidate copying plus bounded process-tree, memory, time, output, and disk monitoring for trusted tests.

The discovered defect was corrected for a future successor: raw wire capture is now bounded at 8,000,000 bytes and has a distinct `RAW_CAPTURE_LIMIT_ABORT` classification. This does not reopen or reinterpret the immutable v2 call ledger or raw evidence.

## Model, calls, and diagnosis

- Ollama: `0.33.3`
- model: `gemma4:26b`
- digest: `08ae7ec1744bd7f451c4a530afb39d2673ad9d07a8369b8a33a3613b41212a68`
- advertised context: 262,144; controlled effective context: 16,384
- disclosed formatting calls: 2
- real modification calls: 0
- qualification 1: passed, 86 prompt tokens, 460 output tokens, 16.422 seconds
- qualification 2: stopped at 64,001 wire bytes after 9.578 seconds; no terminal token/duration metrics
- raw response 1 SHA-256: `b21d45d5eb913bd475bd83c8798f555f50382d78dcfe115a353da81a2a0c244f`
- raw response 2 SHA-256: `1512af925030006660c501c8436701f5953498166c1e52f5082b195582536f33`

The second reconstructed response was 1,766 characters and ended inside `expected_effect`; its last event had `done:false`. `num_predict=1400` was not shown as reached, and no Ollama terminal metrics existed. The exact cause of termination was the trusted harness's raw-wire byte cap, precipitated by highly repetitive model metadata.

## Context conservation

The main preflight used 3,977 conservatively estimated input tokens, down from v1's 9,009 provider-counted input tokens, although those values use different measurement methods and are not an exact paired comparison. Within the v2 retrieved field material, SHA canonicalization changed 14 payload appearances to 8 canonical payloads while retaining all 14 connection records:

- before deduplication: 1,954 estimated tokens;
- after deduplication: 1,811 estimated tokens;
- collapsed payload copies: 6;
- estimated saving: 143 tokens.

The complete main plan fit 10,719/16,384 tokens, including a dynamically calculated 5,718-token output reserve and 1,024-token checkpoint reserve. No main prompt was sent.

## Tests and isolation

Final active-tree results:

- agent: 77/77 passed;
- v9.1: 50/50 passed;
- v3: 21/21 passed;
- SToE Memory plugin: 9/9 passed;
- compile checks and `git diff --check`: passed.

Adversarial tests cover truncation, broken escaping, missing terminators, extra prose, duplicate fields, oversized content, interrupted streams, malicious/protected paths, stale parents, code hidden in metadata, source authority attempts, payload-hash mismatch, and non-repeatable interrupted action IDs. A first focused invocation lacked `PYTHONPATH`; the correctly configured rerun passed. The plugin suite required permission for its local stdio subprocess and then passed. These were invocation/environment issues, not product failures.

No candidate directory was created because the qualification gate stopped before main generation. The implemented candidate evaluator would use an isolated repository copy and monitored trusted subprocesses, but that is **not an OS security sandbox**: it would retain the invoking Windows user's host authority. Generated code therefore remains constrained by static capability checks and inactivity pending human review; the remaining host-isolation limitation is not disguised.

## Hash conservation and activation

- parent reporter: `cd31b0dd4ce7a2c8fdfec4553c02171b2510527fddf251fee901ea5c0279dce7` (unchanged)
- candidate: none
- active selector: `d37f48335f87c4c4370ea78d7719cf3a79aa26ef41b0911c81f448f7828d2cb1` (unchanged)
- v1 attempt manifest: `f3be8a9fb6e4d02b4ac564163e3805215c3aa9ec03d924f9e5839a724407249c` (unchanged)
- v1 failed attempt: `f13d74d3e81b4673462bf2448e8dca4371252c9e3e8a0517a6b8992db968bbfb` (unchanged)
- v1 report: `0f5b1f4b88b0243b4ab9768478d53466204ebf02a009a43729817e7aa7f07982` (unchanged)

The v2 report hash is recorded in the adjacent manifest after this file is finalized. Activation status is **unchanged; no candidate exists**.

## Decision and exact next action

Reject v2 as a successor candidate, preserve the call-level evidence and failure condition, and retain the corrected infrastructure for independent review. The original reporter and accepted selector remain recoverable.

Exact next action requiring Mykola's approval: create a new successor action with new stable qualification IDs, first exercise the corrected bounded raw-wire capture on disclosed fixtures, and allow one real `gemma4:26b` modification call only if both qualifications complete. Do not retry either v2 qualification ID.
