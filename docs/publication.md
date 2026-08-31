# Publication notes

Prepared from the author's local workspace on 2026-08-31.

- `experiments/stoe_v9_1_experiment` comes from the `stoe` research collection.
  It matched the separate top-level v9.1 copy byte for byte when packaged.
  Source, tests, frozen inputs, original reports, manifests, and raw result
  JSON files are retained.
- `engine/v7` comes from the sanitized v7 AI review package. Python, HTML,
  changelog, and canonical seed are retained. The runtime `field_data.json`
  snapshot is intentionally omitted; the program can initialize an empty
  field and import the seed.
- `plugins/stoe-memory` comes from the plugin-development source. The original
  server, core, manifest, launcher, MCP config, tests, and seed are retained.
  Dependency and usage documentation have been added. This upload does not
  register a marketplace or change the author's installed plugin.
- `skills/stoe-reasoning` includes the original skill, supporting references,
  agent metadata, seed, and fidelity validator.
- `research/corpus` preserves the seven PDFs in the local SToE corpus with
  their original filenames.

New README/security/authentication documents explain packaging and usage.
Existing runtime source and archived experiment results are not rewritten.
No live SQLite databases, credentials, environment files, logs, caches,
temporary files, private dissertation materials, or duplicate ZIP archives
are included. Historical research reports may contain original local paths;
these are provenance, not runnable configuration for a new machine.

All supplied canonical seeds retain SHA-256
`b327db6dbce9981ed21561b9d1a857e2e3786f1391d41edc0381fead79e59868`.
Git attributes disable line-ending conversion to preserve original bytes.
Original internal experiment manifests describe the frozen research artifacts;
the new outer repository also contains packaging documentation.
