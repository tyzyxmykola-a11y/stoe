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
