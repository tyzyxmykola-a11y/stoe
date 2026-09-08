# Hermes A/B Succession v2

Status: **QUALIFICATION FAILED — NO SOURCE CANDIDATE — NOT ACTIVATED**

Stable action: `self-code-cycle:hermes-ab-v2:split-model-deduplicate-context` (closed; never retry)

## Outcome

The checkpoint established a clean, pinned, inactive Hermes B base and implemented deterministic split-model routing. The first disclosed Gemma planning-format qualification reached its fixed 700-token output limit and ended with an unterminated JSON string. The supervisor rejected it. Qwen was not called, no real-stage call occurred, no source candidate materialized, and neither Hermes A nor the active `stoe-hermes` adapter was changed.

This is evidence about the selected formatting budget/schema, not evidence that Gemma is unsuitable as the agent's reasoning personality.

## Hermes A: preserved working ancestor

- Version: `0.20.3 (2026.8.16.2)`
- HEAD: `bb924730743cc05934bf0dfd188abdfdb46c03c2`
- Branch/upstream: `main` / `origin/main`
- Upstream HEAD: `520e63661c8eaa2135ebd60a07192f0d8aa45e6e`
- Ancestry: no merge base; rev-list `+1/-1`; genuinely divergent/unrelated histories
- Staged/untracked/submodules: none / none / none
- Apparent dirty file: `contributors/emails/agent@Agents-Mac-mini.local`

The dirty status is a Windows case-collision artifact, not an intentional local source edit: the pinned commit contains two paths differing only by filename case, and a case-insensitive checkout cannot represent both blobs. The exact tracked diff is preserved in `snapshots/hermes_a_tracked.patch` (SHA-256 `841f54537c5f7db3c597ae0a173323b8222a2c190c8a4724c84adc165c8b8f6d`). Credential-bearing external profile files were recorded only by category and presence; their contents were not read or copied. A was not reset, stashed, committed, normalized, reconciled, updated, or otherwise modified.

## Clean Hermes B

B is a sparse runtime-source checkout at the exact pinned parent `bb924730743cc05934bf0dfd188abdfdb46c03c2`, detached and clean. It has release identity `hermes-b-base-bb924730743c`, parent `hermes-a-bb924730743c`, fingerprint `cd15314f4557779e7a01a673d4962b1043c25d3dc16c7afabd52b792dd6dedf6`, separate profile, sessions, temporary memory, `HERMES_HOME`, and virtual environment. It contains no copied credentials, enabled gateway, production schedule, or promotion authority.

A harmless diagnostic imported Hermes from B and communicated with B's test SToE field. Production-field SHA-256 remained `086d2eab28e065b2e82acbae56b52cb3fce21acb64f8a9584cc4942be0ddcb4e` during the diagnostic, and A's configuration remained `1cd7a8c9c38812b6cfe47b2085dd796ceb4e93f65ac2a2b8339ac33831200b80`.

Two construction failures are conserved, not erased: the initial full checkout encountered Windows long-path handling; the next full checkout exposed the case-collision. The successful correction uses a bounded sparse checkout of runtime source directories. Partial failure directories remain under ignored runtime evidence.

Isolation is administrative and process/profile separation, not an OS security sandbox. B's virtual environment is outside its checkout but uses system site packages, so it shares installed Python package bytes with the host. The diagnostic process retained ordinary host read/process/network authority. No generated code reached that process in this checkpoint.

## Split-model qualification

Ollama version: `0.33.3`. Both models advertise 262,144 tokens; the supervisor fixes the effective cap at 16,384.

| Role | Model | Digest | Calls |
|---|---|---|---:|
| planner/reviewer | `gemma4:26b` | `08ae7ec1744bd7f451c4a530afb39d2673ad9d07a8369b8a33a3613b41212a68` | 1 planner qualification; 0 reviewer |
| code instrument | `qwen3-coder:latest` | `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca` | 0 |

The disclosed planner call used 80 input tokens, produced 700 output tokens, reported `done_reason=length`, completed its stream, and took 25.39 seconds. The captured NDJSON is 72,184 bytes with SHA-256 `6c2ca9bbc7e3d2f44b05e9e054dbf3a2ef55664eaa753aadbad4508d72f6c18f`. Parsing failed at an unterminated string. The pre-call conservative budget was 1,808/16,384 including 700 generation tokens and 1,024 checkpoint reserve; this protected context capacity but underestimated the output needed for Gemma's repetitive response.

Because the plan gate failed, the real sequence stopped before SToE-context prompt construction, code generation, deterministic candidate validation, B application, tests of a generated diff, or Gemma review. There is no parent-file/candidate SHA because no candidate exists.

The existing active adapter's disclosed duplicate fixture remains 1,832 tokens before canonicalization and 1,032 after: one payload copy collapsed, both typed connection records retained. These are deterministic adapter measurements, not measurements from a v2 model candidate.

## SToE Memory operation

Before work, observer state `STATE_480a6c6a3a6b4b4a` navigated a bounded typed neighborhood (`RETRIEVAL_fc084fd11c5c4b5f`) and recovered the v1 malformed attempt, security boundary, lineage, correction, and unresolved decision without dumping the field or canonical seed.

The v2 field records active ancestor, redacted snapshot, clean B base, model identities, planner failure, raw-response artifact, evaluation, decision, corrected construction failures, successor state, and next action. Relations include `evolved_from`, `successor`, `conserved_by`, `generated_by`, `evaluates`, `rejected_by`, `correction_of`, `contains`, `uses`, and `depends_on`. Canonical artifact bytes are referenced by path/hash; semantic connections remain distinct.

## Verification

- Hermes A/B and split-cycle tests: 13/13
- Agent suite: 77/77
- v9.1 suite: 50/50
- v3 suite: 21/21
- SToE Memory plugin: 9/9
- Clean B diagnostic: passed
- Historical v1 supervisor/test hashes: unchanged and match `HERMES_AB_MANIFEST.json`
- `git diff --check`: passed
- Active Hermes A configuration and source-state fingerprint: unchanged

The first in-sandbox test attempt was dependency-blocked by Windows ACLs on Python-created temporary directories. The identical suite passed outside that filesystem sandbox with temporary files still scoped to the workspace; this was an execution-environment issue, not a product-test failure.

## Decision and next action

Active: Hermes A. Candidate base: Hermes B, inactive. Source candidate: none. Rollback target: Hermes A. No approval to activate is currently applicable.

The exact decision required from Mykola is whether to authorize a new successor action (v2.1) that changes only the disclosed Gemma planning qualification—either a larger fixed planning output reserve or a smaller fixed-table plan schema. The closed v2 action must not be retried, and no code-model call should occur until the new qualification passes.
