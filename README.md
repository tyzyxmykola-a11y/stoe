# SToE: engines, memory, experiments, and supervised agent development

[![Deterministic CI](https://github.com/tyzyxmykola-a11y/stoe/actions/workflows/deterministic-tests.yml/badge.svg?branch=main)](https://github.com/tyzyxmykola-a11y/stoe/actions/workflows/deterministic-tests.yml)
[![Stable evidence release](https://img.shields.io/badge/release-stoe--self--development--v1-blue)](https://github.com/tyzyxmykola-a11y/stoe/releases/tag/stoe-self-development-v1)

SToE is Mykola Voronin's research program for representing information,
observer state, change, failure, correction, and succession as a connected typed
field. This repository conserves the theory and research corpus alongside the
software mechanisms and experiments derived from it.

The ontology remains a research hypothesis. The implementations and archived
measurements are concrete engineering artifacts, but neither their operation nor
a favorable benchmark result proves the full SToE ontology.

Stable citation boundary: [SToE Self-Development Evidence v1](releases/stoe-self-development-v1/README.md)
freezes the evidence before Hermes v2.2. Cite it using [CITATION.cff](CITATION.cff),
verify it with the [release manifest](releases/stoe-self-development-v1/manifest.json),
and consult the [mixed-license boundary](LICENSING.md).

## Current experimental architecture

The current stack has separate, inspectable components rather than one monolithic
runtime:

- [`experiments/stoe_v9_1_experiment`](experiments/stoe_v9_1_experiment) contains
  the corrective observer-aware topology experiment, frozen tasks, providers,
  traces, and reports.
- [`plugins/stoe-memory`](plugins/stoe-memory) provides a local persistent SQLite
  reasoning field over MCP.
- [`skills/stoe-reasoning`](skills/stoe-reasoning) defines the bounded reasoning
  protocol used with that field.
- [`agent`](agent) implements supervised research-agent continuity, Local
  Development v2, and measured delegation to local Ollama workers.
- [`stoe-hermes`](stoe-hermes) implements Hermes A/B succession, the bounded
  Development Governor, and a standalone local-development runtime.

The v3, v7, v9.1, memory-plugin, research-agent, and Hermes packages are separate
runtimes. They do not automatically share state merely because they are in one
repository. See the [snapshot history](docs/snapshot-history.md) for their
development paths and the limits of the version labels.

## SToE Memory

The [SToE Memory plugin](plugins/stoe-memory/README.md) stores information points
and typed directed relations, including observer states, failed paths,
corrections, provenance, and evaluations. Retrieval is bounded and
observer-aware; the complete canonical seed is not automatically placed into
model context. The companion [reasoning skill](skills/stoe-reasoning/SKILL.md)
specifies how agents should use the field.

This is implemented persistent reasoning infrastructure. It is not evidence that
all retained connections are useful or that topology always outperforms semantic
retrieval.

## Supervised research-agent self-development

The [agent overview](agent/README.md) describes the bounded research and rebuild
system. Its [milestone report](agent/SELF_REBUILD_MILESTONE_REPORT.md) records the
implemented lifecycle, preserved failures, evaluation boundary, rollback, and
current evidence.

[Local Development v2](agent/LOCAL_DEVELOPMENT_V2_CHECKPOINT.md) uses versioned,
hashed role instructions and sequential local Ollama workers for planning,
coding, review, and bounded diagnosis. Trusted code retains responsibility for
artifact validation, resource limits, tests, repository mutation, and evidence
conservation. Its [graduation record](agent/LOCAL_DEVELOPMENT_V2_GRADUATION_REPORT.json)
documents one completed plan-code-review-test-apply-commit-push cycle. Identical
artifact payloads can be deduplicated by SHA-256 without discarding their
distinct SToE connections, provenance paths, or observer relationships.

Failures, corrections, evaluations, and successor states are conserved in
[SToE Memory](plugins/stoe-memory/README.md) as typed relations, while large
source, model, and command artifacts remain path-and-hash referenced. This is
the project’s persistent development architecture rather than a claim that
every local-model proposal is correct.

Self-development is limited to explicitly allowlisted agent-owned components.
Future selection-policy candidates are inert bounded data interpreted by trusted
code. Model-proposed source changes are validated and evaluated outside the
active release, and activation remains a supervised decision. Historical failed
attempts and raw evidence are retained rather than rewritten.

This demonstrates bounded, supervised modification machinery. It does **not**
demonstrate unrestricted recursive self-improvement, autonomous authority
expansion, AGI, or reliable improvement from every generated successor.

## SToE-Hermes development and A/B succession

The [SToE-Hermes package](stoe-hermes/README.md) connects a pinned Hermes ancestor
to a test SToE field and supplies a protected A/B supervisor. Candidate Hermes B
uses separate checkout, home, profile, memory, sessions, temporary storage, and
virtual environment. It cannot promote itself.

The later [Hermes v2.2 promotion record](stoe-hermes/HERMES_V2_2_PROMOTION_V3.md)
documents activation of the exact qualified adapter candidate after protected
health passed, with Hermes A retained as the rollback target. The standing
bounded-succession policy permits supervised promotion only when identity,
qualification, protected evaluation, authority, and rollback prerequisites all
remain satisfied; authority expansion still requires explicit approval.

The [Hermes Development Governor v1 evidence](stoe-hermes/HERMES_DEVELOPMENT_GOVERNOR_V1_REPORT.json)
records local Ollama planning, coding, corrective successors, independent
review, deterministic tests, trusted application, commit, and feature-branch
push. The standalone runtime can repeat that bounded workflow from an ordinary
terminal and uses the operator’s existing Git authentication for normal
feature-branch pushes without placing credential material in model context.

These results establish a qualified, supervised local-development baseline.
They do not establish production readiness, unrestricted autonomous
self-modification, or general autonomous successor promotion. The next
development stage is **SToE Coder**: a persistent local development executive
integrated with the existing Information Field Navigator; it is not implemented
in this baseline.

## Reproducible experiments

Python 3.11 or later is required. Deterministic suites use local code and do not
require paid APIs, secrets, or a running Ollama daemon. Real model experiments
require separately installed local models and must follow their frozen manifests.

For v9.1, from the repository root in PowerShell:

```powershell
cd experiments/stoe_v9_1_experiment
$env:PYTHONPATH = (Resolve-Path ./src).Path
python -m unittest discover -s tests -v
python -m stoe_v9 validate --tasks development_tasks/development_v1.json
python -m stoe_v9 run --tasks development_tasks/development_v1.json --provider mock --output mock-results.json
```

The mock provider verifies the pipeline only; it is not model-performance
evidence. The frozen primary run is gated with `--allow-primary`. See the
[v9.1 reproduction command](experiments/stoe_v9_1_experiment/V9_1_REPRODUCTION_COMMAND.txt)
for historical model and embedding digests. Write new runs to new files rather
than overwriting archived results.

Large archived results are stored losslessly as `.json.gz`. From the experiment
directory, `python tools/restore_archived_results.py` restores expected filenames
only after hash verification and refuses to overwrite changed outputs.

The earlier browser engine remains documented at
[`engine/v7`](engine/v7/README.md). Its historical direct entry point is not safe
for exposure to a shared network.

## Research corpus

- [`research/corpus`](research/corpus/README.md) contains the original research
  PDFs, including *Memory Is Connection* and the v9.1 manuscript.
- [`research/texts`](research/texts/README.md) contains searchable text companions.
- [`archive/starting_point`](archive/starting_point) preserves the original engine
  and selected output record.
- [`archive/snapshots`](archive/snapshots) contains deduplicated historical source
  snapshots, hashes, and a safe restore tool.
- [`archive/original_prototype`](archive/original_prototype) preserves the original
  cloud-backed prompt-operator prototype.

## Evidence and limitations

The [v9.1 final report](experiments/stoe_v9_1_experiment/V9_1_FINAL_REPORT.md)
reports 18/18 overall for observer-aware topology and 14/18 for its frozen dense
comparator. The targeted difference was +33.3 percentage points, with a 95%
family-cluster bootstrap interval of 0.0 to 66.7 and exact paired p = .25. This
small, deliberately constructed corrective replication is not independent
confirmation and does not establish the full ontology.

The [v3 evidence archive](experiments/stoe_v3/runs/README.md) includes null and
negative comparisons as well as exploratory findings. Experiment 6 scored
233/300 for native structure and 234/300 for rewired structure. Different
benchmarks, models, and architectures are not a single comparable performance
series.

The agent and Hermes reports also conserve rejected candidates, malformed model
outputs, and boundary defects. Infrastructure tests show that safety and
continuity mechanisms operate as specified; they do not establish a general
scientific advantage for SToE.

## Security and trust boundaries

This repository is research software and local tooling, not an authenticated
multi-user service. Subprocess isolation and separate working directories are
not security sandboxes. Generated artifacts remain bounded by deterministic
validation, explicit edit scopes, resource limits, and human-controlled
activation. Local model and memory processes inherit the authority of their host
unless stronger OS-level isolation is supplied.

Do not store credentials or private records in retrievable field content. Local
databases, profiles, environment files, caches, loose sessions, and temporary
files are excluded from publication. Canonical seeds and archived evidence are
preserved byte-for-byte. See [SECURITY.md](SECURITY.md),
[authentication notes](docs/authentication.md), and
[publication notes](docs/publication.md) for detailed boundaries. Reuse is
governed by [LICENSING.md](LICENSING.md), not by a single repository-wide
license assumption.
