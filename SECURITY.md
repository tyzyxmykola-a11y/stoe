# Security and trust boundaries

This is research and local tooling, not an authenticated multi-user service.

- The v7 Flask API has no application authentication, authorization, CSRF
  protection, or TLS configuration. Its historical direct entry point listens
  on all interfaces and its CORS policy permits all origins. Use the documented
  loopback command only in a trusted environment; do not expose it publicly.
- The MCP plugin uses stdio and local SQLite. It relies on the MCP client,
  host-side tool approvals, process identity, and filesystem permissions.
  The database is not encrypted by the application, and session IDs are not
  access-control boundaries.
- The v9.1 experiment makes unauthenticated HTTP calls to its configured Ollama
  endpoint. Configuring a remote URL sends task/context text and embedding input
  there. No API-key handling or TLS enforcement is added by the experiment.
- Never put API keys, passwords, personal records, or other secrets into field
  content that may later be retrieved into a model context. Excluding databases
  from Git does not encrypt or otherwise protect them on disk.
- The archived original prototype reads `OPENROUTER_API_KEY` and sends a Bearer
  credential plus prompt content to OpenRouter. No key is included. Historical
  snapshots may contain cloud calls, open listeners, and destructive routes;
  restoration does not execute them or make them safe for public hosting.
- v3's Ollama client has no application authentication. Its test/benchmark
  artifacts are distinct from private live memory; review model-response
  excerpts before redistributing them outside the research archive.
- The research-agent supervisor permits future candidates only inside an explicit
  editable boundary. Declarative selection policies are inert data, and legacy
  Python releases are filename-, location-, and hash-locked. Model-proposed source
  still requires deterministic validation and supervised activation; a worker
  subprocess is not a filesystem, process, environment, network, or memory sandbox.
- The SToE-Hermes candidate environment separates checkout, home, profile,
  sessions, memory, and temporary files from active Hermes A. On the documented
  Windows host it remains a process under the invoking user identity, not a
  container or OS security boundary. Generated code therefore remains inactive
  unless it passes the protected supervisor and receives explicit approval.
- GitHub repository access credentials belong to the GitHub client or Git
  credential manager. They are not SToE application credentials and are not
  included in this repository.

See [the code-based authentication explanation](docs/authentication.md). Avoid
posting credentials or private database exports in public issues.
