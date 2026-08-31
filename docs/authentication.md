# Authentication, request flow, and token handling

The supplied code does **not** implement user authentication. There are three
separate execution paths with different trust boundaries. Repository access
through GitHub is separate from all three.

## Components

| Component | Source | Boundary |
| --- | --- | --- |
| Windows plugin launcher | [`launch_stoe_memory.cmd`](../plugins/stoe-memory/scripts/launch_stoe_memory.cmd), [`.mcp.json`](../plugins/stoe-memory/.mcp.json) | Launches a local process; configuration requests host-side tool approval |
| MCP server | [`server.py`](../plugins/stoe-memory/server.py) | Exposes tools over stdio; does not listen on HTTP |
| Persistent field | [`core.py`](../plugins/stoe-memory/core.py) | Local SQLite file and OS permissions |
| Experiment entry point | [`cli.py`](../experiments/stoe_v9_1_experiment/src/stoe_v9/cli.py) | Local CLI invocation |
| Model/embedding client | [`providers.py`](../experiments/stoe_v9_1_experiment/src/stoe_v9/providers.py) | Unauthenticated requests to configured Ollama URL |
| Earlier web engine | [`server.py`](../engine/v7/server.py), [`field.py`](../engine/v7/field.py) | Flask endpoints and local JSON state; no login checks |

## Plugin flow

```mermaid
sequenceDiagram
    participant H as MCP host
    participant S as server.py (stdio)
    participant F as FieldStore
    participant D as Local SQLite file
    H->>S: Launch configured Python process
    S->>F: initialize()
    F->>D: Initialize schema and validate canonical seed
    H->>S: MCP initialize, list tools, call tool
    S->>F: Tool arguments (for example observer state and navigation limit)
    F->>D: Read/write IPs, relations, states, traces
    D-->>F: Stored records
    F-->>S: Structured result / bounded context
    S-->>H: MCP tool result
```

The server constructs `FieldStore()` at startup and calls `initialize()`, then
runs with `transport="stdio"`. It does not create a web login, cookie, JWT,
access token, or refresh token. `.mcp.json` asks for tool approval using
`default_tools_approval_mode: "approve"`; enforcement belongs to the MCP host,
not to an authentication check inside `FieldStore`.

`default_db_path()` uses `STOE_MEMORY_DB` if provided; otherwise it uses
`LOCALAPPDATA` or the home directory and appends `SToE/field.sqlite3`.
`STOE_MEMORY_DB` is a file location, not a credential. SQLite calls use parameter
binding in the storage layer, but the application adds no encryption or
per-user ACLs. References and `session_id` values identify/group records and
are not authorization tokens.

Retrieved reasoning content is returned to the host and can subsequently enter
model context. The plugin itself does not call a model provider.

## Experiment flow

```mermaid
flowchart LR
    CLI[Local CLI] --> Tasks[Load tasks and build graphs]
    Tasks --> Runner[ExperimentRunner]
    Runner --> Retrieval[Select and serialize bounded context]
    Retrieval --> Provider[OllamaClient / OllamaEmbedder]
    Provider --> Ollama[Configured Ollama endpoint]
    Ollama --> Results[Results and trace JSON]
```

`OllamaClient` requests `/api/tags` and posts task/context messages to
`/api/chat`. `OllamaEmbedder` posts text to `/api/embed`. POST requests set
`Content-Type: application/json`; there is no `Authorization` header or API-key
lookup in these clients. The CLI defaults to `http://127.0.0.1:11434`, but
`--api-base` can target another service. The program does not require loopback,
HTTPS, or an authenticated proxy.

Expected model/embedding digests check model identity for reproducibility.
They are not access credentials. `input_tokens`, `output_tokens`, and
`max_output_tokens` refer to model token counts/budgets. The navigator's
`token_set` refers to lexical tokenization. Neither use represents authentication.

The archived run setup and its narrow experimental claims are documented in
[the frozen invocation](../experiments/stoe_v9_1_experiment/V9_1_REPRODUCTION_COMMAND.txt)
and [the final report](../experiments/stoe_v9_1_experiment/V9_1_FINAL_REPORT.md).

## Earlier v7 web flow

The browser UI calls Flask `/api/...` endpoints. Handlers read and mutate
`InformationField`, persist JSON, and call Ollama through `requests` for model
operations. Some endpoints save or serve logs. The code has no authentication
middleware or route-level ownership checks, including the field wipe/import
and model/chat endpoints.

`load_dotenv()` reads a local `.env`; relevant settings include `VERSION`,
`OLLAMA_URL`, and `OLLAMA_MODEL`. No password/token verification is implemented.
The CORS response lists `Authorization` as an allowed header, but this does not
validate that header or create authentication. CORS is not an authorization
mechanism. The historical entry point binds `0.0.0.0:5000`; the
[v7 README](../engine/v7/README.md) documents a loopback-only invocation.

## Credentials and lifecycle

There are no application passwords to hash, login sessions to expire, tokens
to rotate, or logout/revocation endpoints in the supplied implementations.
GitHub credentials used to publish or clone are managed outside SToE and are
not copied into source, plugin config, or seed data. Operating-system file
permissions and host/client controls are essential for the local components;
shared or remote deployment needs additional authentication and authorization.

This explanation is a static code inspection, not a penetration test or proof
that the applications are safe to expose publicly.
