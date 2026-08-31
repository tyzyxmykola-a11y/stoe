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

The old `python server.py` / `python start.py` startup path binds the API to
`0.0.0.0`. Prefer the loopback command above. No login protects graph mutations,
field wipe/import, model operations, or log endpoints. CORS permits all origins;
loopback binding alone does not provide complete protection from browser-based
requests. Use only in a trusted local environment.

The author's runtime `field_data.json` and custom operator state are not shipped.
The field starts empty. The `/api/seed` endpoint imports the supplied
`stoe_seed.json` into the local field; runtime changes are written to the ignored
`field_data.json`. Do not run against a valuable field without a backup.

Dependency entries reflect source imports, not a historical version lock. See
[authentication.md](../../docs/authentication.md) for the request flow.
