# SToE Agent Hermes A/B Succession v1

Status: **INFRASTRUCTURE QUALIFIED; MODEL CANDIDATE REJECTED; NO ACTIVATION**

Stable action: `self-code-cycle:hermes-ab-v1:deduplicate-context` (closed; one call; never retry)

## Outcome

Hermes is now represented as the operational body of SToE Agent, while the canonical SToE Memory field supplies observer-aware continuity and the SToE-owned protected supervisor controls succession. The adapter and A/B infrastructure are real and deterministically qualified. The one permitted local model proposal did not become candidate B: its structured patch contained invalid, repetitive Python and was rejected before candidate checkout creation or execution. No model-generated source was merged, pushed, or activated.

## Installed Hermes A

- version: `0.20.3 (2026.8.16.2)`
- pinned commit: `bb924730743cc05934bf0dfd188abdfdb46c03c2`
- launch: `hermes` / `hermes-agent` in the managed Python 3.11.15 venv
- active profile: `default`; config at the external `HERMES_HOME/config.yaml`
- configuration SHA-256: `1cd7a8c9c38812b6cfe47b2085dd796ceb4e93f65ac2a2b8339ac33831200b80`
- model: custom provider, `gemma4:26b`
- checkout state: dirty (one pre-existing user modification) and divergent (ahead 1, behind 1)
- license: MIT, Nous Research; LICENSE SHA-256 `821556e6336796450ab852d375117b48a4887e71d255794fd6318d99982a5ab6`

The active checkout, profile, configuration, credentials, and working change were inspected read-only and left unchanged. Dirty/divergent ancestry is an explicit activation blocker.

## Architecture implemented

`plugin.py` uses the exact installed Hermes `register(ctx)` surface, exact hooks `on_session_start`, `pre_llm_call`, and `on_session_end`, and capability-gated `ctx.call_mcp`. It registers the canonical external `stoe-reasoning` skill path rather than copying it. It uses `stoe_field_status`, `stoe_list_recent`, `stoe_set_observer_state`, `stoe_navigate`, `stoe_add_ip`, and `stoe_add_relation`; it never opens the SQLite field directly. Session start links a new observer state to the previous field state and retrieves bounded connected context. End-of-session outcomes and failures are conserved.

`context_renderer.py` emits canonical content once per SHA-256, preserves every connection/provenance record, reports collapsed copies, and respects a complete-line character budget. On a disclosed two-connection fixture with a large repeated payload, canonicalization reduced the conservative estimate from 1,832 to 1,032 tokens while preserving both relations: 800 tokens saved and one payload copy collapsed.

`succession.py` is outside the model-editable path. It pins ancestry, constructs a clean committed Hermes checkout beside A, creates a separate profile/home/session/memory/temp/venv, omits production credentials and gateways, exposes only the integration-owned plugin loader, validates inert single-file line patches, measures time/output/process/RAM/disk bounds, requires a Mykola-bound approval token, switches a protected pointer atomically, and rolls back on failed health checks. Release records include explicit parent/successor identity and typed state.

The active integration keeps Hermes' existing memory and compressor context engine distinct from the canonical SToE field. Replacing either is deferred.

## Operational SToE use

The installed `stoe-reasoning` protocol drove explicit observer state, conserved failures/corrections, typed directed relations, bounded navigation, and calibrated claims. SToE Memory retrieval `RETRIEVAL_e2a393835c9c4f2a` selected the prior capability-boundary correction, failed v2 cycle, next action, token decisions, and lineage without loading the complete field or seed.

New field records include architecture `IP_53cdd56bf8144246`, qualification `IP_8637864afa7d460d`, model attempt `IP_4e2a15a3a41f44ce`, raw artifact `IP_68becf3abc584e36`, failed candidate `IP_1f723d4454b64d93`, exact evaluation `IP_6638082e2bc34a2e`, decision `IP_66b946664879488d`, successor state `IP_f5251b1c42e64591`, and next action `IP_466b872d21104589`. They are linked by `generated_by`, `evaluates`, `rejected_by`, `depends_on`, `contains`, `constrained_by`, `correction_of`, and `evolved_from`. Large raw output is referenced once by path/hash, not copied into memory.

Final observer state is `STATE_0612346daac749e8`; bounded resume retrieval is `RETRIEVAL_4f08778dbd1149b6` with no seed dump. A fresh process resolves the active release, rejected-candidate state, rollback target, and next action from those SToE IPs using `HERMES_AB_RESUME.json`.

## Qualification

- Hermes A/B integration: 12/12 passed
- SToE Agent: 77/77 passed
- v9.1: 50/50 passed
- historical v3: 21/21 passed
- SToE Memory plugin: 9/9 passed
- compilation and `git diff --check`: passed

Coverage includes deterministic B creation, clean/stale/dirty/divergent ancestry, allowlisted/forbidden patches, isolated profile/no credentials, interrupted recovery, launch crash/timeout/resource bounds, approval, atomic switch/rollback, unchanged A, exact Hermes hook/skill registration, fresh-session field persistence, and one-payload/many-connections behavior.

## Model attempt

- Ollama: `0.33.3`
- model/digest: `gemma4:26b` / `08ae7ec1744bd7f451c4a530afb39d2673ad9d07a8369b8a33a3613b41212a68`
- context: advertised 262,144; fixed 16,384
- call count: 1 qualification-free real proposal call; no retries
- budget: 3,768/16,384 estimated including 1,800 output and 1,024 checkpoint reserves; 12,616 reserve
- provider tokens: 770 input, 1,651 output, 2,421 total
- duration: 25.406 seconds; terminal `stop`; complete JSON stream
- raw: 173,964 bytes; SHA-256 `a8acfba748b8cbbf6faa417a2bbc956168ad46debf2181d17cc877a54eafde74`
- result: envelope passed; reconstructed source failed AST parsing at line 17; candidate SHA/release: none

The failure is not evidence against SToE. It is a single observation about this model's patch reliability. It was conserved without reopening the action.

## Isolation and residual authority

Candidate construction provides directory/profile/environment separation, static source capabilities, and monitored resource bounds. It does not provide a Windows OS security sandbox. A subprocess still runs as the invoking user and could possess host filesystem/network authority if arbitrary code escaped static validation. No generated code reached execution in this attempt. Network denial was not claimed because it cannot be genuinely enforced with the available mechanism.

## Activation and next action

Active A remains `hermes-a-bb924730743c`; rollback target remains A. Candidate B does not exist. Activation status is unchanged.

Exact next action requiring Mykola: review this pushed supervisor and the conserved malformed proposal, then decide whether to reconcile the dirty/divergent active Hermes checkout and authorize a new successor action with a new stable ID. Do not retry or activate Hermes A/B v1.
