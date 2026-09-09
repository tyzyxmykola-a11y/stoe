# SToE Local Worker Delegation v1

Status: development tooling; local model output is data, never authority.

This thin layer lets Codex supervise bounded local Ollama workers while reusing the existing SToE Reasoning protocol, SToE Memory field, navigator, retrieval traces, evaluations, token estimator, and canonical artifact conventions. It does not introduce another memory system or modify SToE retrieval.

The trusted flow is deterministic narrowing → machine-state observation → deterministic capability routing → resource-governor decision → one bounded localhost Ollama call → strict result validation → artifact storage → trusted field write → compact return packet. Codex retains source inspection, security decisions, test interpretation, commits, and activation decisions.

## Contracts and authority

Workers receive only a goal, bounded constraints, supplied relevant context, an explicit file/scope allowlist, a response schema, provenance, and resource/time limits. They receive no shell, filesystem, external network, Git, patch-application, activation, secret, protected-evaluation, or direct SToE Memory write authority. Raw responses are preserved before parsing. Malformed, oversized, identity-mismatched, secret-like, or out-of-schema results fail closed.

Detailed output remains under ignored `agent/runtime/local_workers_v1/`; Codex normally receives an estimated ≤400-token packet containing decisions, evidence references, failures, hashes, uncertainties, and next action. The trusted recorder writes only substantive task/result/artifact/evaluation IPs and typed relations to the shared field.

## Resource governor

`interactive` is the default and preserves conservative RAM/VRAM reserves, serializes heavy models, and limits small-worker concurrency. `idle` is explicit configuration. `full_power` cannot be constructed unless the caller records explicit human selection. Metrics unavailable on a host are stored as unavailable. Monitoring and subprocess limits are policy containment, not an OS sandbox.

The router uses installed model digests, actual context capacity when exposed, loaded state, measured or conserved role evidence, task requirements, and current resource pressure. Unqualified models receive only probationary status. It prefers the smallest adequate capability, but security-sensitive or difficult work may justify a stronger model. No model chooses its own authority.

## Commands

Deterministic tests do not require Ollama:

```powershell
$env:PYTHONPATH=(Resolve-Path agent/src).Path
python -m unittest agent.tests.test_local_workers -v
```

Discover installed capabilities without downloading or changing anything:

```powershell
$env:PYTHONPATH=(Resolve-Path agent/src).Path
python agent/tools/local_worker.py discover
```

Run the single bounded interactive pilot after tests pass:

```powershell
$env:PYTHONPATH=(Resolve-Path agent/src).Path
python agent/tools/local_worker.py pilot --observer-state STATE_ea54e40a1786498c
```

The pilot only analyzes the conserved Hermes v2.1 inherited-`Raise` validator mismatch. It does not edit Hermes, implement v2.2, apply patches, or activate anything.

## Current limitations

- Windows resource telemetry is best-effort; CPU/process RAM may remain unavailable without an approved dependency.
- Resource governance preserves configured margins but is not a security sandbox or a perfect predictor of model offload behavior.
- Initial routing evidence is sparse. Future validated evaluations should update role scores without declaring a permanent winner.
- Workers cannot inspect files themselves; deterministic trusted tooling supplies bounded excerpts.
- Hosted-token billing savings are not measurable here. The engineering metric is reduction of detail reinjected into Codex-visible context.

