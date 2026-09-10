# StoeCoder

SToE Coder is the standalone local development executive derived from the SToE self-development work in this repository. It combines local Ollama workers, isolated candidate worktrees, deterministic verification, independent review, Git lifecycle controls, and SToE Memory provenance behind a localhost-only browser UI.

The current root-level project begins from the SToE Coder v1 implementation first integrated into `engine/v7` with the Information Field Navigator. That integrated Navigator version is now a preserved baseline. New Coder development belongs under `StoeCoder/`.

## Project boundary

`engine/v7` preserves the historical Navigator-integrated SToE Coder baseline. `StoeCoder/` is the active standalone development line.

Future Coder changes should be made under `StoeCoder/` unless a task is explicitly about the preserved Navigator itself. This separation lets Coder evolve without repeatedly modifying the earlier browser engine.

The standalone folder currently contains:

```text
StoeCoder/
├─ README.md
├─ server.py
├─ ui_server.py
├─ stoe_coder.py
├─ coder_intent.py
├─ field.py
├─ stoe_seed.json
├─ requirements.txt
├─ static/
│  └─ index.html
└─ tests/
   └─ test_stoe_coder.py
```

`server.py` is the standalone launcher. `ui_server.py` and `static/` provide the copied browser surface. `stoe_coder.py` contains the trusted local executive. The repository root remains the Git working repository controlled by Coder.

## Requirements

- Python 3.11 or later
- Git available on `PATH`
- Ollama installed and running locally for model-backed work
- at least one suitable local Ollama model
- Windows PowerShell commands below assume the repository is already cloned

Python dependencies are listed in `requirements.txt` (`Flask`, `requests`, `python-dotenv`, and `networkx`).

## First start on Windows

From the repository root:

```powershell
cd StoeCoder
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python server.py
```

Open:

```text
http://127.0.0.1:5000
```

The server intentionally binds to loopback only.

## Later starts

After the virtual environment already exists:

```powershell
cd StoeCoder
.\.venv\Scripts\Activate.ps1
python server.py
```

If Ollama is not already running, start it separately before asking Coder to execute model-backed work.

## What the UI currently provides

The copied UI exposes the existing SToE Coder workflow from the standalone folder. Conversation requests can ask Coder questions without repository mutation. Explicit **Run** actions execute development work through the trusted local executive.

Current Run options:

```text
[ ] allow commit
[ ] allow push
```

These permissions are explicit capabilities for that Run. Words such as `commit` or `push` inside the objective do not by themselves grant Git authority.

Current operator Git controls:

```text
Diff | Commit | Pull | Push | Merge to main
```

The model-driven Git path and the operator Git path are separate. A development Run can be completed without a commit, leaving the reviewed integrated candidate available for operator inspection through **Diff** and later **Commit**.

## Development lifecycle

The current governed path is:

```text
operator objective
→ observer/context state
→ isolated Git worktree
→ local Ollama worker actions
→ candidate artifact
→ deterministic verification
→ independent local review
→ trusted integration into the active feature tree
→ deterministic verification again
→ SToE conservation
→ optional explicitly-authorized commit/push
```

The active repository must normally be clean before a new development Run. A reviewed integrated dirty candidate can instead be inspected and completed through the operator Git controls.

Large model and command outputs remain local artifacts; compact provenance and reasoning state are conserved separately.

## Git lifecycle

### Diff

Read-only inspection of the current repository changes. The complete diff is also preserved as a local artifact when needed, while the browser display is bounded.

### Commit

Commits only the exact working-tree state that still matches the recorded deterministic-test and accepted-review lineage. A changed or stale candidate is rejected rather than silently committed.

### Pull

Uses the tracked upstream with `git pull --ff-only`. Dirty trees and diverged history are rejected; Coder does not rebase, force, or silently resolve conflicts.

### Push

The generic operator Push is limited to the current `feature/*` branch and does not force. Main/master are deliberately refused by this generic action.

### Merge to main

Merge is an explicit operator action, separate from Run commit/push permission. It requires a clean qualified feature HEAD, passed current tests, accepted review lineage, a confirmed pushed feature branch, and synchronized local/remote main identity. A detached trial merge is verified before local main is changed. The current action merges local main; it does not implicitly push main.

## SToE Memory and provenance

When the SToE Memory plugin is available, Coder records development and Git transitions as connected information points rather than treating successful output as the only history worth retaining.

The lifecycle conserves useful evidence including objectives, worker actions, evaluations, commits, pushes, Git transitions, successor observer state, and exact failure conditions. Failed development paths remain available as history and can become relevant again when the rejecting condition changes.

The runtime database is local and is not intended for publication. Large raw artifacts are referenced by path/hash rather than injected wholesale into model context.

## Local model policy

Coder uses local Ollama workers by default. Model selection is capability- and resource-aware rather than assuming the largest installed model is always the best choice. Deterministic tools remain the verification authority.

The trusted executive owns filesystem, Git, process, and repository authority. Local model workers receive bounded task context and an isolated candidate workspace; role names or model instructions do not themselves grant additional authority.

## Tests

From the repository root with the StoeCoder virtual environment active:

```powershell
python -m unittest discover -s StoeCoder/tests -q
```

The deterministic Coder suite exercises candidate isolation/integration, local-boundary behavior, explicit model Git permissions, operator Diff/Commit/Pull/Push/Merge behavior, stale review/test rejection, and failure recording.

## Security and trust boundary

SToE Coder is a trusted-user local development tool, not a hostile-code sandbox and not an authenticated multi-user service.

The browser API is loopback-only. Models are not given credential material. Destructive Git actions such as force push and history rewriting remain outside the normal worker authority. Separate process/worktree boundaries reduce accidental coupling but should not be treated as OS-level sandboxing.

Do not expose the service to an untrusted network without adding a real authentication and isolation boundary.

## Self-development direction

The purpose of the standalone project is to let SToE Coder become the implementation environment for its own bounded successors:

```text
Coder_n
× repository
→ candidate Coder_n+1
× deterministic tests
× independent review
→ accepted Coder_n+1
× operator Git succession
→ active Coder_n+1
```

The next planned self-hosted feature is a persistent configurable worker-role system. The initial registry should seed roles such as `planner`, `coder`, `reviewer`, `debugger`, and `test-analyst`, while treating them as editable initial configuration rather than mandatory hardcoded roles.

Planned role behavior includes persistent custom roles, editable contracts, Auto/manual Ollama model selection, enable/disable checkboxes without losing role definitions, deliberate deletion, task-start role/model logging, a distinct task-finished event with metrics, and a stage-based progress bar. Role configuration must never expand trusted runtime authority.
