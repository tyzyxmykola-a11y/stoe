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
- GitHub repository access credentials belong to the GitHub client or Git
  credential manager. They are not SToE application credentials and are not
  included in this repository.

See [the code-based authentication explanation](docs/authentication.md). Avoid
posting credentials or private database exports in public issues.
