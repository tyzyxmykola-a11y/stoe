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
- All **86 copied source/research files** match their originals byte for byte,
  with five archived JSON outputs compared after lossless decompression.
- All **33 original Python files** parsed successfully; packaged JSON parsed successfully.
- New documentation's relative links resolved locally.
- Pattern checks found no private-key blocks, recognizable GitHub/API/cloud
  token formats, credential-bearing URLs, or obvious assigned secrets in the
  staged text files. This is a limited scan, not a security guarantee or PDF audit.

Validation used the existing Python 3.11.15 runtime and `mcp` 2.0.0. The v7 web
engine was syntax-checked but was not started or tested against a model; its
Flask dependency was absent from that runtime. No new primary benchmark or
real-model run was performed. Existing archived results were preserved.

## Historical additions

The v3 engine's four unchanged self-test scripts passed 147 checks (37 + 51 +
28 + 31) in an isolated copy, and its Experiment 6 suite passed 21 tests. The
Experiment 6 suite was also rerun from the publication package. No real-model
benchmark was launched.

All 457 file occurrences across 78 snapshots were verified against their
SHA-256 manifest, as were all 61 archived v3 JSON reports. Three representative
snapshots and all report files were restored successfully; a changed output
file was correctly refused rather than overwritten. Recomputing the archived
Experiment 6 A/B verdict produced an exact match.

The 39 copied source/document files match their recorded publication hashes.
Five paper texts underwent documented reversible single-byte-to-UTF-8
transcoding. Pattern scans of source, decoded snapshot blobs, and report JSON
found no recognizable credentials. This remains a limited pattern scan, not a
guarantee that every possible secret or sensitive narrative has been detected.
See [the validation record](historical-validation.json) and
[source manifest](historical-source-manifest.json).
