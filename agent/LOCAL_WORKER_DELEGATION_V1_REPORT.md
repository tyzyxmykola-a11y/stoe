# SToE Local Worker Delegation v1 — Qualification Report

Status: **qualified as a bounded, fail-closed delegation mechanism; worker research answer not accepted**.

This checkpoint made exactly one real Ollama generation call. It did not modify
Hermes, implement v2.2, read protected evaluations, apply a patch, or grant the
worker filesystem, Git, network, activation, or SToE Memory write authority.

## Discovery and routing

Ollama `0.33.3` exposed seventeen installed entries. Sixteen were usable worker
models; `qwen3-embedding:0.6b` was correctly excluded as embedding-only. Models
relevant to the routing decision included:

- `gemma4:12b`, digest `4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c`;
- `gemma3:12b`, digest `f4031aab637d1ffa37b42570452ae0e4fad0314754d17ded67322e4b95836f8a`;
- `phi4:latest`, digest `ac896e5b8b34a1f4efa7b14d7520725140d5512484457fab45d2a4ea14c69dba`;
- `qwen3-coder:latest`, digest `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca`;
- `gemma4:26b`, digest `08ae7ec1744bd7f451c4a530afb39d2673ad9d07a8369b8a33a3613b41212a68`.

The deterministic router selected `gemma4:12b`. It was the highest-ranked
high-difficulty reviewer that fit the interactive VRAM policy. The two larger
models had useful conserved role evidence but their approximately 18.6 GB model
files could not preserve the configured 2 GiB VRAM reserve on the measured
15.92 GiB device.

Before dispatch the governor observed 66,157,801,472 bytes total RAM,
45,692,350,464 bytes available RAM, an NVIDIA GeForce RTX 5070 Ti with
17,094,934,528 bytes total VRAM and 14,560,526,336 bytes free VRAM, and no loaded
model. It returned `RUN` in `interactive` mode. CPU utilization and process RAM
were unavailable and were recorded as unavailable. After the call Ollama
reported `gemma4:12b` resident with 8,389,698,518 bytes of VRAM; an immediate
GPU observation reported about 5.1 GiB free. This is evidence that pre-dispatch
policy admitted the selected model; it is not a guarantee of browser
responsiveness or continuous reserve after every driver allocation.

## Bounded task and SToE continuity

The worker received one AST-narrowed excerpt of
`stoe-hermes/src/stoe_hermes/succession.py` plus six items selected through the
current observer state. The retrieval run was
`RETRIEVAL_d7c32a4ca42e4fc4`; it included the v2.2 unresolved action, prior
checkpoint/evaluation, current objective, and connected state change. The
canonical seed was not dumped into the prompt.

Relevant supplied context was 4,734 characters (4,734 UTF-8 bytes), about 1,578
estimated tokens. Ollama reported 1,749 prompt tokens after the task contract
and system instruction were included. Trusted AST-aware narrowing removed the
validator's own secret-signature table from the excerpt; the packet secret
scanner itself remained unchanged.

The field conserves the live action (`IP_5c3e57f576684c97`), failure
(`IP_c6efa4c83cad49aa`), raw artifact (`IP_6a50b1637a164477`), and evaluation
(`IP_1fcf066c50e548b6`) with `depends_on`, `generated_by`, `observed_under`, and
`evaluates` links. Earlier pre-dispatch context-size and secret-signature
collisions remain preserved as failures with explicit corrections. Those
attempts made no model call.

A new observer state, `STATE_48abcf2a0ec94f57`, compacted the completed call,
no-retry constraint, evaluation, and exact next action. A separate navigation
(`RETRIEVAL_a7d573ed35b14b62`) reconstructed the raw artifact reference, next
action, active objective, and Hermes v2.2 succession context without rereading
repository history or injecting the seed.

## Live result

Ollama completed in 17.694 seconds, reporting 650 output tokens and
`done_reason=length`. The 2,284-character response ended inside a JSON string.
Parsing failed with an unterminated-string error, so schema validation rejected
the response before any conclusion was accepted. The partial text was also not
research-quality evidence: it drifted toward contextual allowance of
`ast.Raise` instead of completing the required parent-relative and adversarial
analysis.

The canonical raw envelope is intentionally ignored runtime data at:

`agent/runtime/local_workers_v1/artifacts/worker_hermes-v2.2_validator-analysis-v1/raw_response.json`

Its SHA-256 is
`a0017d9e05a55cc5c76a1c22f6323d8ac38df31c6996c7c2a8240d1702c98007`
and its size is 16,417 bytes. A deterministic postprocessor produced a 355-token
compact failure packet serialized to 1,070 bytes, a 93.5% reduction from the raw
artifact. No second generation call was made.

## Qualification judgment

- **Worker quality:** failed; no coherent complete answer was accepted.
- **Contract quality:** passed fail-closed behavior; malformed output could not masquerade as a result.
- **Context efficiency:** passed; bounded field/source context was used and full evidence remained artifact-backed.
- **SToE continuity:** passed; objective, observer state, retrieval, action, failure, artifact, evaluation, and next action are connected.
- **Routing:** reasonable under the measured interactive constraint, but one run cannot establish optimality.
- **Resource behavior:** pre-run reserve checks passed; CPU/process RAM telemetry remains unavailable.
- **Authority boundary:** passed at the application-contract level. This is not an OS sandbox.

Deterministic regression after the live call passed: Agent 101/101 (including
Local Worker 24/24), Hermes 18/18, SToE Memory 9/9, v9.1 50/50, and v3 21/21.
Canonical seed validation and Python compilation passed, and `git diff --check`
reported no errors.

The next action is not to rerun this stable worker action. After PR review, begin
Hermes v2.2 as a separately supervised implementation task using the conserved
failure to budget a smaller response schema or a justified larger output reserve.
That task must independently validate a parent-relative structural design; this
failed worker response supplies no accepted solution.
