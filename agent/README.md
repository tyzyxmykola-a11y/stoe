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

Generated selectors are never executed in the supervisor process during public
diagnostics. A bounded child process converts timeout, crash, malformed output,
and invalid selection into recorded rejection. Activation exceptions restore the
previous pointer and verify recovery in another fresh process.

## Run one bounded cycle

From `agent/`:

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
python -m unittest discover -s tests -v
python -m stoe_agent inspect
python -m stoe_agent cycle --model qwen3-coder:latest --action-id model-cycle:NEW_UNIQUE_ID
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

The isolated failure probe separately demonstrates recovery of the previous
pointer and fresh-process health after a deliberately failed activation.
