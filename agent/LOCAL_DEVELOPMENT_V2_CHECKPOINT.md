# SToE Local Development v2 checkpoint

Status: **BOUNDED PLANNER FAILURE CONSERVED; V2 CONTRACT AND INSTRUCTION LOADER IMPLEMENTED**

The objective is a reusable `stoe-agent develop` flow:

`observer state -> bounded SToE retrieval -> decomposition -> local planner -> local coder -> local reviewer -> deterministic verification -> SToE conservation -> compact result`

Ollama 0.33.3 dynamically exposed sixteen completion-capable installed models.
Interactive routing selected `gemma4:12b`, digest
`4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c`,
for the first architecture-planning action. The call used 644 prompt tokens and
reached its 900-token output limit in 18.545 seconds. Its JSON ended inside a
string, so no plan was accepted and the stable action will not be retried.

The raw response remains local at
`agent/runtime/local_development_v2/artifacts/worker_local-development-v2_architecture-plan-v1/raw_response.json`,
SHA-256 `b5fe1ea438459d6934e32eeb0cd69bb143622b47c703a82228592cdee7d6d70d`.
The deterministic 327-token failure summary has SHA-256
`0cb3a373b3aec077fcd3f6b6b5ef94d1e12b846c48a4612d3aa43af211c0073f`.

The failure directly qualifies the first correction: add and deterministically
test the requested five-field worker contract (`status`, `decision`,
`evidence`, `risks`, `next_action`) before any successor model call. Coding
workers may emit a separately validated inert patch artifact, but cannot apply
it, inspect files, write memory, run Git, or control verification or activation.

The canonical role instructions now live in `agent/local_development/`. Trusted
code loads only `WORKER_CONTRACT_V2.md` and the selected role file, validates the
five-field control response, keeps coder output in a separate inert artifact,
and records instruction hashes and typed action/result provenance in SToE
Memory. This checkpoint does not yet add the `stoe-agent develop` stage runner
or claim that a successor plan or code candidate materialized. No candidate was
generated or applied.

Frozen instruction SHA-256 values:

- `ARCHITECTURE_V2.md`: `2dbeaea94b9a4d9681c37207bcc94da51eb4cf184b9c57d69dff69552dc2fe0a`
- `WORKER_CONTRACT_V2.md`: `939578740058e29daa8ebcbcade8b4363e1b455e2402846463710be9223db2e9`
- `PLANNER.md`: `294ae46fdff3c87b9d28f404613b78c3b3117cf4d4808ada4f2fb732b78f6b9c`
- `CODER.md`: `da720062c1b0b3471af220fd4774ac699cc029d8e5b448bd646443471e6c6fea`
- `REVIEWER.md`: `8a1055576241a5c01a55a31a7eaef010c8d10da8298ad21a3dfe6028635cd7c7`
- `CHATGPT_ESCALATION.md`: `bfb991dda3560566834bc21c311dbf770d6a077b0dbbefd770d0fcb769319f6e`

Deterministic qualification passes 38/38 focused v1+v2 tests. A disclosed
local `qwen3-coder:latest` advisory review (digest
`06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca`)
returned a valid five-field result after reading only the bounded reviewer
packet. Its normalized record is
`agent/LOCAL_DEVELOPMENT_V2_LOCAL_REVIEW.json`, SHA-256
`93f7669c93677e7012904384e3994cf59d8597bd77014e30bc0d07c7a5c7642c`.
It is advisory evidence, not verification authority; its CLI presentation
stream was not preserved as a canonical raw artifact and that limitation is
recorded explicitly.

The connected SToE field records the advisory action as
`LDA_5113b4eb4297f524`, result `LDR_8d898c2d473e4287`, deterministic
evaluation `LDE_9add248a706f637f`, and next action `IP_ldv2stage000001`.
Observer state `STATE_3ab46e87444540ac` can resume the bounded lineage without
reloading repository history. Four instruction artifact IPs retain the exact
architecture, escalation, contract, and reviewer hashes used by this action.

Exact next action: connect the qualified compact contract to a successor stage
runner with stable-action recovery, then run one new disclosed planner action.
Only after that succeeds should a coder and independent reviewer attempt the
bounded `development_report.py` observability improvement. The failed planner
action above remains closed and must not be retried.
