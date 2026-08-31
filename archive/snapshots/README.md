# Historical source snapshots

This archive preserves the source from 78 available `stoe_field*` directories.
It contains 457 file occurrences represented by 266 distinct SHA-256-addressed
blobs: six allowlisted source paths where present, plus historical
`stoe_seed.json` assets. Identical files are stored once in
`source-snapshots.tar.gz`; `manifest.json` maps each snapshot to its source bytes.

Included paths: `engine_v2.py`, `field.py`, `server.py`, `operators.py`,
`start.py`, `static/index.html`, and `stoe_seed.json` when present. Environment
files, runtime fields, custom operator state, logs, caches, and original ZIPs
are omitted. The cumulative changelog is already published at
[`engine/v7/CHANGELOG.md`](../../engine/v7/CHANGELOG.md).

```text
python archive/snapshots/restore_snapshot.py
python archive/snapshots/restore_snapshot.py stoe_field_34
python archive/snapshots/restore_snapshot.py stoe_field_82 --output ./tmp/snapshots
```

Run from the repository root. Restoration verifies hashes before writing and
refuses to overwrite changed files. The default destination is the ignored
`archive/snapshots/restored/<snapshot>` directory. Scripts are restored as
historical source, not run automatically. Old versions can contain bugs, open
network listeners, deletion endpoints, and external model calls.

The numbering has gaps, and directory labels are not Git ancestry or verified
release dates. See the [history guide](../../docs/snapshot-history.md) for
observed changes and the distinction between source evidence and research claims.
