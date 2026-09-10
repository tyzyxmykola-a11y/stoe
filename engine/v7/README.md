# SToE v7 interactive engine

This is the source from the sanitized v7 review package. It predates the v9.1
experiment; version labels inside historical scripts and the changelog are
retained as supplied.

Components: `field.py` stores graph data in JSON, `operators.py` defines
operators, `engine_v2.py` runs the console engine, `server.py` provides the
Flask API, and `static/index.html` provides the browser interface.

## Local startup

From this directory, with a Python environment containing these dependencies:

```text
python -m pip install -r requirements.txt
python -m flask --app server run --host 127.0.0.1 --port 5000
```

Open `http://127.0.0.1:5000`. Ollama defaults to `http://localhost:11434` and the
model defaults to `llama3`. `OLLAMA_URL` and `OLLAMA_MODEL` can be set in the
environment or in a local `.env` file, which is excluded from Git.

`python server.py` and `python start.py` also bind to loopback. The Agent area
contains the original Field Agent and a default SToE Coder mode. Coder questions
use `/api/coder/chat` without repository mutation; explicit Run actions use the
server-side FULL LOCAL executive, an isolated Git worktree, local Ollama workers,
deterministic checks, and an independent local review. Its privileged routes
reject non-loopback clients and non-local browser origins. There is intentionally
no generic browser `/api/shell` endpoint. This is still a trusted-user local
development tool, not a hostile-code sandbox.

The author's runtime `field_data.json` and custom operator state are not shipped.
The field starts empty. The `/api/seed` endpoint imports the supplied
`stoe_seed.json` into the local field; runtime changes are written to the ignored
`field_data.json`. Do not run against a valuable field without a backup.

Dependency entries reflect source imports, not a historical version lock. See
[authentication.md](../../docs/authentication.md) for the request flow.
