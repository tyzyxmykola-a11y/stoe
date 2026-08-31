# SToE: engines, persistent memory, and research

SToE work by **Mykola Voronin**, collected with engine source, the `stoe-memory`
plugin, the `stoe-reasoning` skill, canonical seed data, and research artifacts.

| Directory | Contents |
| --- | --- |
| [`experiments/stoe_v9_1_experiment`](experiments/stoe_v9_1_experiment) | v9.1 corrective replication: observer-aware navigator, retrieval baselines, providers, tests, frozen tasks, reports, and raw results |
| [`engine/v7`](engine/v7) | Earlier interactive information-field engine, Flask API, and browser interface |
| [`plugins/stoe-memory`](plugins/stoe-memory) | Local persistent SQLite reasoning field exposed through MCP over stdio |
| [`skills/stoe-reasoning`](skills/stoe-reasoning) | Reusable reasoning protocol, references, seed, and seed validator |
| [`research/corpus`](research/corpus) | Original research PDFs and the v9.1 ResearchGate manuscript |
| [`docs/authentication.md`](docs/authentication.md) | Authentication components, request flows, credential handling, and trust boundaries |

The v7 engine and v9.1 experiment are separate programs. The plugin is a third
runtime; it does not automatically share v7's JSON field or the experiment's graphs.

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

## Publication and privacy

This repository includes source and archived research results, not the author's
live memory. Local databases, v7 runtime `field_data.json`, environment files,
caches, session logs, and temporary files are excluded. Canonical seed files are
preserved byte for byte. Original reports retain historical paths and provenance.
See [publication notes](docs/publication.md) and the [security notes](SECURITY.md).

