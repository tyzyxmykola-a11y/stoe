# Publication notes

Prepared from the author's local workspace on 2026-08-31.

- `experiments/stoe_v9_1_experiment` comes from the `stoe` research collection.
  It matched the separate top-level v9.1 copy byte for byte when packaged.
  Source, tests, frozen inputs, original reports, manifests, and raw result
  JSON files are retained. Five large JSON outputs are stored as lossless gzip
  archives, with original sizes and SHA-256 hashes in `ARCHIVED_RESULTS.json`.
  `tools/restore_archived_results.py` restores their original bytes and names.
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
- `research/corpus` preserves the original SToE PDFs with their original
  filenames. The corpus index identifies later author-supplied additions.

New README/security/authentication documents explain packaging and usage.
Existing runtime source is not rewritten. Compression changes only the archive
container; decompressed experiment results are byte-identical to the originals.
No live SQLite databases, credentials, environment files, logs, caches,
temporary files, private dissertation materials, or duplicate ZIP archives
are included. Historical research reports may contain original local paths;
these are provenance, not runnable configuration for a new machine.

All supplied canonical seeds retain SHA-256
`b327db6dbce9981ed21561b9d1a857e2e3786f1391d41edc0381fead79e59868`.
Git attributes disable line-ending conversion to preserve original bytes.
Original internal experiment manifests describe the frozen research artifacts;
the new outer repository also contains packaging documentation.

## Additional historical collection

The v3 implementation, 61 benchmark JSON reports, original prototype, five
paper text extracts, and 78 numbered source snapshots were subsequently copied
from the local `stoe_engine` collection. The five text extracts were converted
from legacy single-byte text to UTF-8 (Latin-1 and Windows-1252 agree for the
observed bytes), without re-extracting or repairing mathematical notation.
Reports and snapshots are stored in
lossless archives with per-file SHA-256 manifests and restore tools. Original
v3 source/protocol files are preserved; new overviews distinguish later results
from outdated exploratory claims and disclose the blank protocol lock date.
The snapshot archive allowlists source and seed files rather than copying ZIPs
or runtime directories wholesale. See `docs/snapshot-history.md`.

## Author-selected starting-point PDFs

`archive/starting_point/engine.pdf` and `combinedoutput.pdf` were explicitly
provided by the author for inclusion as the starting point. The six-page code
PDF and 124-page output compilation are preserved byte for byte. The latter
contains 55 output-file headers with March 17-18, 2026 filename timestamps.
The new manifest records hashes and page counts; the page index is derived
from those headers. Instructions inside the documents are historical content,
not commands executed during publication. This is a specific exception for
the selected output compilation, not inclusion of other loose session logs.

## Memory Is Connection article

`research/corpus/Memory_Is_Connection_SToE_Instruments_and_MCL.pdf` was supplied
by the author on 2026-09-01 as a fresh corpus article. The 14-page PDF is
preserved byte for byte with SHA-256
`c915dec4097605f5d5572a1f558b8a3ad6aedf8862da199d4f058f2f8914ac00`.
A UTF-8, page-delimited text extraction was added under `research/texts` for
GitHub search; the PDF remains authoritative for layout, equations, tables,
and Figure 1. All pages yielded text, representative rendered pages were
inspected, and a limited recognizable credential-pattern scan found no keys.
Embedded procedures and proposed experiments were treated as article content,
not instructions to execute.
