# SToE–Hermes integration

This package connects Hermes Agent to the canonical local SToE Memory field through Hermes' capability-gated MCP facade. It does not replace Hermes' native memory provider or context engine. It registers the canonical installed `stoe-reasoning` skill by path, retrieves bounded connected context at session start, exposes explicit retrieval/conservation tools, and records session outcomes.

The protected `succession.py` supervisor creates candidate Hermes B from a pinned commit in a separate checkout, profile, memory database, home, temporary directory, and virtual environment. It validates only inert line-patch data for the single declared integration file. Candidates cannot promote themselves; activation requires a Mykola-bound approval token and rolls back atomically after a failed health check.

## Pinned installation inspected

- Hermes version: `0.20.3 (2026.8.16.2)`
- installed commit: `bb924730743cc05934bf0dfd188abdfdb46c03c2`
- installed checkout: external to this repository; deliberately not vendored
- license: MIT, copyright Nous Research (see `THIRD_PARTY_NOTICES.md`)
- launch commands: `hermes` / `hermes-agent` from its dedicated Python 3.11 virtual environment

The inspected active checkout was dirty and divergent from its upstream. That state is preserved, not repaired here, and blocks candidate activation even though the exact committed parent can be materialized separately.

## Isolation boundary

Separate directories and a sanitized process environment prevent intentional inheritance of Hermes profiles, `.env`, credentials, sessions, memories, and production gateways. Resource monitoring bounds time, output, process-tree size, RAM, and disk growth. On this Windows host it is still an ordinary subprocess under the invoking user identity: it is **not** an OS security sandbox and cannot prove network/filesystem denial against arbitrary native code. For that reason generated source is additionally constrained by a small static capability allowlist and remains inactive pending review.

Later stages may investigate a native SToE memory provider or context engine only after this adapter is qualified.
