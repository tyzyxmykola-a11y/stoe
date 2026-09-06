# SToE research-agent rebuild supervisor

This directory adds one bounded self-rebuild capability to the existing SToE
repository. It does not alter model weights or provider infrastructure. It can
inspect, revise, test, activate, and roll back agent-owned Python components.

The first owned component is the research-context selector in
`owned_components/context_selector/versions`. The trusted supervisor, protected
evaluation cases, activation checks, and rollback rules are outside that
component's editable boundary. A local Ollama model receives the active source,
its public contract, and an observed limitation; it does not receive protected
cases or expected answers. Model output is data, not a shell command.

## Trust boundary

The model can propose a JSON change specification and one Python source file.
The supervisor writes only inside a candidate directory, rejects unsafe syntax
and imports, executes evaluation in a time-bounded subprocess, checks protected
file hashes, and activates only after a fixed acceptance rule. The model cannot
change the evaluator, acceptance threshold, active pointer, or rollback logic
through the generation interface. This is a software boundary, not an OS-level
security sandbox; the human-controlled repository and process permissions remain
the ultimate authority.

Runtime databases, snapshots, traces, and active pointers live under
`agent/runtime/` and are excluded from Git. Accepted source and cycle reports are
versioned in the worktree. The SToE memory database conserves architecture,
component, limitation, proposal, candidate, evaluation, activation, and rollback
IPs with typed directed relations.

## Run one bounded cycle

From `agent/`:

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
python -m unittest discover -s tests -v
python -m stoe_agent inspect
python -m stoe_agent cycle --model qwen3-coder:latest
python -m stoe_agent status
```

The cycle makes two local Ollama calls: a preregistered proposal and a source
generation call. It performs no cloud or paid API request. It does not iterate on
held-out evaluation failures. A syntax/static-gate repair may be attempted once,
and both attempts remain in the trace.

Rollback is explicit:

```powershell
python -m stoe_agent rollback --version v1
```

`python -m stoe_agent failure-probe` runs a deliberately broken activation in an
isolated temporary runtime and verifies that the previous component and field
remain usable.

## Current evidence

The completed local-Ollama investigations found a real limitation: the active
goal-only selector passed 0/3 public diagnostics, while bounded SToE navigation
reached the required missed IP in all three. No generated successor passed the
fixed adoption rule. The final candidate tied the active selector at 1/5 protected
cases and failed a critical privacy case, so it was rejected and `v1` remains
active. See [SELF_REBUILD_MILESTONE_REPORT.md](SELF_REBUILD_MILESTONE_REPORT.md)
and the immutable JSON traces under `rebuild_reports/`.

The successful activation path is covered only by a controlled test fixture; it
is not presented as evidence of successful self-improvement. The isolated
failure probe demonstrates recovery of the previous pointer and fresh-process
health after a deliberately failed activation.
