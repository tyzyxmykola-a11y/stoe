# SToE Memory

A local persistent observer-aware reasoning field. `server.py` exposes ten MCP
tools over stdio; `core.py` implements seed validation, SQLite persistence, typed
relations, observer states, bounded retrieval, evaluation, and retrieval traces.

## Setup and verification

Use Python 3.11 or later with the dependency version used by the original
development runtime:

```text
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Run these commands from this plugin directory. `server.py` imports
`MCPServer` from `mcp.server`; an older package exposing only another server API
is not interchangeable.

The supplied `.mcp.json` is the existing Windows configuration. It launches
`scripts/launch_stoe_memory.cmd`, which first checks the optional Hermes Python
runtime under the current user's profile, then falls back to `python` on PATH.
The chosen runtime must contain the `mcp` dependency. `.codex-plugin/plugin.json`
contains the plugin metadata; no marketplace registration is bundled.

For a generic MCP client, configure a stdio server using an absolute path to
the Python interpreter containing the dependency, pass the absolute path to
`server.py` as its argument, and set the working directory to this plugin
directory. Starting `python server.py` in a terminal alone waits for MCP input;
it does not open a web UI.

The companion reasoning skill lives at `../../skills/stoe-reasoning`.

## Persistence and security

The default database is `%LOCALAPPDATA%/SToE/field.sqlite3` on Windows, or
`~/SToE/field.sqlite3` when `LOCALAPPDATA` is unavailable. Set `STOE_MEMORY_DB` to
choose a different database. The canonical seed is validated and initialized
when the server starts. Tests use isolated temporary databases.

There is no OAuth, password login, token issuance, encryption layer, or per-user
authorization in this server. The boundary is the local MCP client, tool
approvals, process identity, and OS file permissions. Session IDs organize data;
they do not restrict access. Do not store passwords or API tokens as reasoning
content. See [authentication.md](../../docs/authentication.md).
