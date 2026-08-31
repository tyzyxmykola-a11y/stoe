# Packaging validation — 2026-08-31

- v9.1 experiment: **50 existing tests passed**.
- Development task validation: **4 tasks valid**.
- Mock development run: **56 result rows**, pipeline completed. This is not
  a new model-performance measurement; the mock knows the expected answers.
- Memory plugin: **9 existing tests passed**, including stdio MCP initialization,
  tool listing, and the field-status call. The stdio test required running
  outside the Windows sandbox because sandboxed named-pipe creation was denied.
- Plugin manifest validator: **passed**.
- Reasoning skill canonical-seed validator: **passed** (36 core IPs, 113 typed
  relations, and the expected SHA-256).
- All **86 copied source/research files** match their originals byte for byte.
- All **33 Python files** parsed successfully; packaged JSON parsed successfully.
- New documentation's relative links resolved locally.
- Pattern checks found no private-key blocks, recognizable GitHub/API/cloud
  token formats, credential-bearing URLs, or obvious assigned secrets in the
  staged text files. This is a limited scan, not a security guarantee or PDF audit.

Validation used the existing Python 3.11.15 runtime and `mcp` 2.0.0. The v7 web
engine was syntax-checked but was not started or tested against a model; its
Flask dependency was absent from that runtime. No new primary benchmark or
real-model run was performed. Existing archived results were preserved.
