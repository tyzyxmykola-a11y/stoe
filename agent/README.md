# SToE research-agent rebuild supervisor

Local bounded Ollama delegation for development is documented in
[LOCAL_WORKER_DELEGATION.md](LOCAL_WORKER_DELEGATION.md). It reuses SToE Memory
and SToE Reasoning while keeping workers non-authoritative and preserving
interactive machine resources.

This directory adds one bounded self-rebuild capability to the existing SToE
repository. It does not alter model weights or provider infrastructure. It can
inspect, revise, test, activate, and roll back an agent-owned selection policy.

The first owned component is the research-context selector in
`owned_components/context_selector/versions`. The trusted supervisor, protected
evaluation cases, activation checks, and rollback rules are outside that
component's editable boundary. A local Ollama model receives the active artifact,
its public contract, and an observed limitation; it does not receive protected
cases or expected answers. Model output is data, not a shell command.

## Trust boundary

The earlier implementation intended generated Python to lack filesystem and
evaluator authority, but its AST blacklist did not enforce that boundary. A
candidate could bypass it through `__builtins__` and would then execute with the
worker process's filesystem, environment, process, and network authority. A
subprocess timeout contained hangs only. This implementation defect is recorded
without rewriting the historical evaluation evidence.

Future candidates are inert, versioned `stoe.selection_policy` JSON data. Trusted
code permits only bounded scoring, comparison, filtering, deterministic sorting,
and output-budget operations. It projects only the documented observer and item
fields; the policy has no expression language or way to name files, environment
variables, processes, network resources, evaluator state, active pointers, or
protected cases. Public and protected execution remains time bounded and
exception safe. See [SELECTION_POLICY_FORMAT.md](SELECTION_POLICY_FORMAT.md).

Runtime databases, snapshots, traces, and active pointers live under
`agent/runtime/` and are excluded from Git. Accepted source and cycle reports are
versioned in the worktree. The SToE memory database conserves architecture,
component, limitation, proposal, candidate, evaluation, activation, and rollback
IPs with typed directed relations.

The accepted Python selector remains an immutable legacy release. A trusted
adapter loads only the two historical Python releases by exact filename, location,
and SHA-256; arbitrary Python is rejected before import. No migration or
reactivation occurs during the capability-boundary checkpoint. Activation
exceptions still restore the previous pointer and verify recovery in another
fresh process.

## Run one bounded cycle

From `agent/`:

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
python -m unittest discover -s tests -v
python -m stoe_agent inspect
python -m stoe_agent cycle --model qwen3-coder:latest --action-id model-cycle:NEW_UNIQUE_ID
python -m stoe_agent status
```

The cycle makes two local Ollama calls: a preregistered proposal and a policy
generation call. It performs no cloud or paid API request. It does not iterate on
held-out evaluation failures. A declarative validation repair may be attempted once,
and both attempts remain in the trace.

Rollback is explicit:

```powershell
python -m stoe_agent rollback --version v1
```

`python -m stoe_agent failure-probe` runs a deliberately broken activation in an
isolated temporary runtime and verifies that the previous component and field
remain usable.

## Current evidence

The first completed local-Ollama investigations found a real limitation: the
goal-only `v1` selector passed 0/3 public diagnostics, while bounded SToE
navigation reached the required missed IP in all three. Several generated
successors failed safely. After a contract-feasibility correction, one new bounded
cycle produced a partial improvement: 0/3 to 1/3 on disclosed diagnostics and
1/5 to 3/5 on protected cases. It cleared both critical cases, preserved the
baseline pass, and passed fresh-process activation.

The active source is named by `owned_components/context_selector/active_release.json`
so a clean checkout can reconstruct the current pointer. The successor still
fails both changed-constraint reactivation cases, so this is evidence of a
limited self-development step—not topology superiority or general intelligence.
See [SELF_REBUILD_MILESTONE_REPORT.md](SELF_REBUILD_MILESTONE_REPORT.md) and the
immutable JSON traces under `rebuild_reports/`.

For compact cross-session state, artifact-backed summaries, token estimates,
provider token counts, action reconciliation, and fresh-process resume, see the
[post-acceptance checkpoint](POST_ACCEPTANCE_CHECKPOINT.md). A stopped process is
not described as continuously active; continuity means the next bounded session
can recover the recorded state.

Runtime continuity is reconciled rather than selected by file precedence. The
loader compares the ignored runtime state, the tracked latest checkpoint, and the
tracked bootstrap through content fingerprints plus verified parent ancestry. It
fast-forwards stale state, retains only provably ahead state, and fails explicitly
on divergent or cross-branch histories. The runtime component pointer is
reconciled with `active_release.json` by the same rule. See
[the continuity reconciliation checkpoint](CONTINUITY_RECONCILIATION_CHECKPOINT.md).

The isolated failure probe separately demonstrates recovery of the previous
pointer and fresh-process health after a deliberately failed activation.
