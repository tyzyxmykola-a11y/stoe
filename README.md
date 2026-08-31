# SToE: engines, persistent memory, and research

SToE work by **Mykola Voronin**, collected with engine source, the `stoe-memory`
plugin, the `stoe-reasoning` skill, canonical seed data, and research artifacts.

**Start with the [original engine and output record](archive/starting_point)**
to see where this project began, then follow the documented development path
to the graph engines and experiments.

| Directory | Contents |
| --- | --- |
| [`archive/starting_point`](archive/starting_point) | Original code PDF, selected March 2026 output compilation, provenance, and page index |
| [`experiments/stoe_v9_1_experiment`](experiments/stoe_v9_1_experiment) | v9.1 corrective replication: observer-aware navigator, retrieval baselines, providers, tests, frozen tasks, reports, and losslessly compressed raw results |
| [`engine/v7`](engine/v7) | Earlier interactive information-field engine, Flask API, and browser interface |
| [`experiments/stoe_v3`](experiments/stoe_v3) | Historical graph-aware engine, structural evaluator, benchmark suite, and Experiment 6 evidence |
| [`plugins/stoe-memory`](plugins/stoe-memory) | Local persistent SQLite reasoning field exposed through MCP over stdio |
| [`skills/stoe-reasoning`](skills/stoe-reasoning) | Reusable reasoning protocol, references, seed, and seed validator |
| [`research/corpus`](research/corpus) | Original research PDFs and the v9.1 ResearchGate manuscript |
| [`research/texts`](research/texts) | Searchable text versions of five papers |
| [`archive/snapshots`](archive/snapshots) | 78 deduplicated historical source snapshots, hashes, and a safe restore tool |
| [`archive/original_prototype`](archive/original_prototype) | Original cloud-backed prompt-operator prototype |
| [`docs/authentication.md`](docs/authentication.md) | Authentication components, request flows, credential handling, and trust boundaries |

The v3, v7, and v9.1 engines and the plugin are separate runtimes. They do not
automatically share a field. Read the [snapshot history](docs/snapshot-history.md)
for their development paths and the limits of the version labels.

## Start with the experiment

Python 3.11 or later is required. Its Python code uses the standard library;
real model runs require a separately running Ollama service and installed models.
From the repository root, in PowerShell:

```powershell
cd experiments/stoe_v9_1_experiment
$env:PYTHONPATH = (Resolve-Path ./src).Path
python -m unittest discover -s tests -v
python -m stoe_v9 validate --tasks development_tasks/development_v1.json
python -m stoe_v9 run --tasks development_tasks/development_v1.json --provider mock --output mock-results.json
```

The mock provider returns expected answers and is only a pipeline check, not
evidence of model reasoning performance. The frozen primary run is intentionally
gated with `--allow-primary`. See the original
[reproduction command](experiments/stoe_v9_1_experiment/V9_1_REPRODUCTION_COMMAND.txt)
for the model and embedding digests; replace its historical machine-specific
Python executable path with your own. Run new experiments into new output files
instead of overwriting the archived results.

Large archived JSON outputs are stored as `.json.gz` for reliable transfer.
Restore the original filenames and verify their SHA-256 hashes before running
tools that read those outputs:

```text
python tools/restore_archived_results.py
```

Run this from the experiment directory. The restore script refuses to overwrite
changed results. Source, tasks, small JSON inputs, and reports remain directly
readable without restoration.

## Use the memory plugin

See the [plugin README](plugins/stoe-memory/README.md) for dependencies and launch
instructions. The plugin manifest and MCP configuration are included. The
companion [reasoning skill](skills/stoe-reasoning/SKILL.md) is packaged separately.

## Run the earlier browser engine

See [engine/v7/README.md](engine/v7/README.md). Use the documented loopback-only
Flask command. The historical `server.py` entry point binds to all interfaces and
has no authentication; do not expose it to a shared network or the Internet.

## Evidence and limitations

The [v9.1 final report](experiments/stoe_v9_1_experiment/V9_1_FINAL_REPORT.md)
reports 18/18 overall for observer-aware topology versus 14/18 for the frozen
dense comparator. The targeted difference was +33.3 percentage points, with a
95% family-cluster bootstrap interval of 0.0 to 66.7 and exact paired p = .25.
This is a small, deliberately constructed corrective replication, not an
independent confirmation or evidence establishing the full SToE ontology.
Read the report's limitations alongside its results.

The earlier [v3 evidence archive](experiments/stoe_v3/runs/README.md) includes
null/negative comparisons as well as exploratory findings. Its Experiment 6
native-versus-rewired comparison scored 233/300 versus 234/300. It used a
different model, benchmark, and architecture from v9.1; these runs are not a
single directly comparable performance series.

## Publication and privacy

This repository includes source and archived research results, not the author's
live memory. Local databases, v7 runtime `field_data.json`, environment files,
caches, loose session logs, and temporary files are excluded. The author-selected
historical output PDF is explicitly included under `archive/starting_point`.
Canonical seed files are
preserved byte for byte. Original reports retain historical paths and provenance.
See [publication notes](docs/publication.md) and the [security notes](SECURITY.md).
