# Supervised self-code-modification cycle v1

Status: **FAILED SAFELY — NO VALID SOURCE CANDIDATE, NO ACTIVATION**

Stable action ID: `self-code-cycle:v1:deduplicate-development-context`

## Outcome

The milestone infrastructure is implemented and one bounded local-model generation was attempted. The required `gemma4:26b` response was malformed JSON (`Unterminated string starting at line 4 column 14 (char 340)`), so it never became an inert patch artifact. The boundary failed closed. No model-proposed source file was created, applied, imported, executed, activated, merged, or pushed as an active release.

This is a connected failed attempt under the requested lifecycle, not a successful self-modification and not evidence for SToE superiority. The request's success-path definition of done—one model-proposed source candidate—was therefore not reached. The same stable action must not be retried.

## 1. Infrastructure built

- `development_report.py` establishes a deliberately narrow, non-security-critical agent-owned reporting component. Its public contract renders already-authorized retrieved records under a deterministic character budget.
- `self_code_cycle.py` defines a bounded objective, one exact editable path, a bounded JSON schema, parent-hash locking, secret and binary rejection, normalized path checks, protected-prefix checks, dependency-file rejection, pure-reporting syntax restrictions, isolated-directory application, rollback metadata, prompt budgeting, exact model/digest verification, SToE retrieval, stable interruption state, and success/failure conservation.
- Candidate patches are complete-file JSON data. They are not shell commands or directly executable instructions.
- `run_self_code_cycle.py` is the explicit operator entry point. It performs no fallback and requires `--allow-generation` for the model call.
- `conserve_self_code_failure.py` closed this specific uncertain call as a non-repeatable failed attempt.

The model could edit only:

`agent/src/stoe_agent/development_report.py`

The allowlist excludes the supervisor, this cycle implementation, policy interpreter, selector loader, active selector releases, protected evaluations, research history/checkpoints, Git metadata, dependencies, activation rules, and every other repository path.

## 2. Investigation actually performed

A disclosed two-record fixture was passed through the baseline report. Both records had the same non-empty SHA-256 but different references. The baseline rendered both:

```text
A | evaluation | report | supported | same evidence
B | runtime_reasoning | report | supported | same evidence
```

Observed limitation: duplicate content hashes consume bounded development-context space. This was recorded as a failed Information Point and linked to the development objective, source snapshot, and editable-boundary constraint.

The ObserverAwareNavigator then selected four reachable runtime IPs under a six-item/7,000-character retrieval budget:

1. parent source snapshot;
2. bounded development objective;
3. editable/security constraint;
4. observed duplicate-hash failure.

The exact selected content, all candidate scores, typed directed traversal paths, prompt, schema, and generation configuration are preserved in `self_code_candidates/self_code_cycle_v1_deduplicate_context/attempt_manifest.json`.

## 3. Candidate change requested

The requested change was to preserve deterministic order and provenance while keeping the first record for each non-empty SHA-256, never collapsing records with a missing/empty hash, never mutating inputs, and never exceeding `max_chars`.

No valid candidate change was produced. The only model output failed JSON parsing before the patch boundary. Because the existing frozen Ollama client raises before returning its trace on malformed JSON, the malformed raw response body was not available to the cycle. This is an instrumentation limitation, explicitly conserved rather than silently repaired after the call.

## 4. Model and budget evidence

- Ollama version: `0.33.3`
- Model: `gemma4:26b`
- Exact digest: `08ae7ec1744bd7f451c4a530afb39d2673ad9d07a8369b8a33a3613b41212a68`
- Advertised context from `/api/show`: 262,144 tokens (`gemma4.context_length`)
- Fixed effective context: 16,384 tokens
- Temperature: 0
- Seed: 910241
- Output reserve: 4,096 estimated tokens
- Checkpoint reserve: 1,024 estimated tokens
- Conservative total with reserves: 14,129/16,384
- Pre-call reserve: 2,255 estimated tokens
- Retry count: 0
- Actual generation calls: 1

The exact model was present and its digest was recorded before generation. No paid/cloud API or fallback model was used.

## 5. Boundary and recovery evidence

Model-free tests demonstrated rejection of path traversal, `.git/config`, protected evaluations, supervisor edits, dependency manifests, NUL/binary-like source, oversized artifacts, generated-secret patterns, imports, direct file reads, dunder access, unbounded loops, stale parent hashes, malformed artifacts, and no-op/invalid candidates. They also demonstrated interrupted-call reconciliation and restoration of an isolated candidate copy without changing the active source.

The parent reporting source SHA-256 is `cd31b0dd4ce7a2c8fdfec4553c02171b2510527fddf251fee901ea5c0279dce7`. It remains unchanged. The accepted selector remains active and no active pointer changed.

Rollback for this attempt is trivial and complete: no candidate was applied, so there is nothing to undo. The original source and accepted selector remain recoverable at their recorded hashes.

## 6. Isolation actually achieved

The infrastructure can write a validated candidate only into a separate candidate directory and never directly into the active release. Generated source is parsed and compiled without import as a static validity check. In this failed attempt, parsing the proposal failed before even that stage.

This is **not a security sandbox**. A Git worktree or subprocess on this Windows host retains the invoking user's filesystem, environment, process, and network authority. The repository has no configured low-authority Windows account, container, VM, or hardened Job Object boundary. Consequently, generated Python is never executed by this cycle. Candidate behavioral tests and activation must remain blocked until such an executor exists; source can still be preserved for human inspection.

Trusted regression tools run with time/output controls, but RAM, disk, and descendant-process limits are not a hardened containment boundary on this host. Those limits must not be represented as security guarantees.

## 7. Regression results

Pre-generation qualification:

- Agent: 67/67 passed (including 6 new self-code-cycle tests)
- v9.1: 50/50 passed
- v3: 21/21 passed
- memory plugin: 9/9 passed
- Python compile check: passed
- `git diff --check`: passed

Initial v9.1 and plugin invocations failed for environmental reasons only: missing `PYTHONPATH` and sandbox denial of the plugin's local stdio subprocess. Corrected/re-authorized reruns passed. These are not product failures and are reported rather than hidden.

## 8. Historical conservation

No historical experiment, score, case, threshold, active release, or evidence classification was edited. Key hashes after implementation:

- accepted cycle report: `a008eba9e581ccb1850f509c1a535c26b7b6c361c3174a0936fb18dd473677b1`
- accepted selector: `d37f48335f87c4c4370ea78d7719cf3a79aa26ef41b0911c81f448f7828d2cb1`
- canonical seed: `b327db6dbce9981ed21561b9d1a857e2e3786f1391d41edc0381fead79e59868`
- frozen v3 `ollama.py`: `274dede0edb992c1d745e9be14a4862088ccb8b08327316b4af1fa6c2ee8747d`
- frozen v3 `cli.py`: `fca641b2bc136e01441f2f22b36fa493cd662da082ece5ec38d3cfae306567e7`

The frozen v3 hash suite detected and prevented accidental changes to `ollama.py` and `cli.py` during this milestone. Those attempted infrastructure placements were removed before generation; the correction is part of this report.

## 9. Decision and next objective

Decision: reject this generation as a candidate, conserve it as a failed attempt, do not retry its stable action, and do not activate anything.

Exact next development question:

> How can a successor cycle preserve the raw Ollama body before schema parsing and demonstrate schema-complete `gemma4:26b` patch responses on disclosed development fixtures, while keeping the same inert patch boundary and without executing generated Python on a host that lacks hardened low-authority isolation?

That instrumentation/qualification work should use a new stable action ID. A new model generation requires Mykola's explicit approval; it must not be treated as a retry of this cycle.
