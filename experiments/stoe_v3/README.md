# SToE v3: historical engine and experiments

This separate experimental implementation adds graph-aware operator
preconditions, failure conservation, an LLM-free structural evaluator, and a
topology-versus-keyword retrieval harness. It is not the current v9.1 experiment
and is not a replacement for the v7 browser UI or the MCP plugin.

## Components

| Source | Role |
| --- | --- |
| `core/field.py` | Persistent JSON graph, edge severance, retained failed nodes, navigation |
| `core/operators.py` | Operators that validate graph preconditions and produce typed graph effects |
| `core/evaluator.py` | Novelty, contradiction, bridging, and lexical attractor-distance metrics without LLM self-scoring |
| `harness/context.py` | Topology context and keyword-similarity comparator |
| `harness/runner.py` | Retry loop, failure retention, structural verdicts, and report creation |
| `benchmark/` | Puzzles and deterministic graders |
| `seed/` | Native SToE, music, and chimera controls, with reference seeds |
| `scripts/analyze_experiment_6.py` | Archived A/B analysis procedure |

The original implementation files are preserved. The new README, restore
script, and evidence summary describe packaging and limitations. The redundant
nested `stoe_v3/stoe_v3` copy, manuscript drafts, session logs, runtime fields,
and environment files are not included.

## Verify locally

Use Python 3.11 or later. From this directory, in PowerShell:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python tests/test_slice1.py
python tests/test_slice2.py
python tests/test_slice3.py
python tests/test_slice4.py
python tests/test_experiment_6.py
```

The four slice scripts report 37, 51, 28, and 31 checks respectively; the
Experiment 6 suite has 21 tests. They passed during packaging. These test
mechanical implementation invariants, not superiority on real-model tasks.

For a real run, install `requirements.txt` and separately run Ollama with the
desired model. Inspect `python -m harness.cli --help` before launching: benchmark
runs can be lengthy and create local field files. The historical comparison
script is `run_experiment_6.sh` and requires Bash. It calls the document
`PREREG.md` in comments; the file actually supplied here is
[`PREREG_exp6.md`](PREREG_exp6.md). New runs should use new output locations.

## Restore and inspect existing evidence

```text
python scripts/restore_archived_results.py
python scripts/analyze_experiment_6.py --condition-a runs/exp6_20260514_190304_A_topology.json --condition-b runs/exp6_20260514_190304_B_topology.json
```

The archive contains 61 original JSON reports, including earlier pilots,
exploratory comparisons, and the later Experiment 6 cells. Each has an original
size and SHA-256 in `runs/ARCHIVED_RESULTS.json`. Restoration refuses to
overwrite changed reports. These data include benchmark model-response excerpts;
they are not the author's general-purpose live memory or session logs.

Read the [current evidence summary](runs/README.md) before the
[historical index](runs/historical/INDEX.md). Original historical conclusions
are preserved as provenance, not endorsed as the current interpretation.

## Reproducibility limits

- The protocol document calls itself locked but its lock-date field is blank;
  this package alone cannot establish a timestamped preregistration.
- The v3 client does not send explicit decoder temperature, top-p, or random
  seed options, despite decoder settings stated in the protocol. It does not
  pin a model digest. Historical server defaults cannot be recovered from this
  code alone. The harness's `seed_idx` is a trial label, not an API decoder seed.
- The comparator is keyword similarity, not a dense embedding retriever.
- The six main puzzles were selected using the same model; repeated trials
  on six puzzles are not thousands of independently sampled tasks.
- The analyzer's label `falsification` follows its historical decision rule.
  Failure to detect a difference is not proof that the two systems are equivalent.

See [snapshot history](../../docs/snapshot-history.md) for how this branch
influenced the v7 browser engine.
