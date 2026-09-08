# Licensing boundaries

This repository uses more than one license. A license applies only to material
for which the identified rights holder has authority to grant it. Existing
notices and provenance-specific terms override the defaults below.

## A. Original software — MIT

© Mykola Voronin. Licensed under the MIT License in
[LICENSES/MIT.txt](LICENSES/MIT.txt).

The MIT boundary covers original executable implementation, tests, software
configuration, CI, and utility code in these functional paths:

- .github/workflows/**;
- agent/src/**, agent/tests/**, agent/tools/**,
  agent/protected_evals/evaluator.py, agent/selection_policy support files,
  agent/owned_components/context_selector/versions/v1.py, and the package
  configuration in agent/;
- stoe-hermes/src/**, stoe-hermes/tests/**, stoe-hermes/tools/**,
  stoe-hermes/hermes_plugin/**, stoe-hermes/releases/**, and
  stoe-hermes/pyproject.toml;
- executable and interface source under engine/v7/;
- implementation, harness, benchmark-execution, test, and utility source under
  experiments/stoe_v3/ and experiments/stoe_v9_1_experiment/;
- plugins/stoe-memory/core.py, plugins/stoe-memory/server.py,
  plugins/stoe-memory/scripts/**, plugins/stoe-memory/tests/**, its plugin
  manifests, and its requirements file;
- skills/stoe-reasoning/scripts/**;
- archive/original_prototype/engine.py and
  archive/snapshots/restore_snapshot.py.

This boundary is functional rather than extension-based. A Python or JSON file
that is a preserved model output, generated candidate, frozen result, or
historical artifact falls under section C instead.

## B. Original research texts and documentation — CC BY 4.0

© Mykola Voronin. Licensed under Creative Commons Attribution 4.0
International, whose canonical text is in
[LICENSES/CC-BY-4.0.txt](LICENSES/CC-BY-4.0.txt).

Subject to the exceptions in section C, this covers:

- root explanatory documentation, including README.md, SECURITY.md, and
  docs/**;
- Mykola Voronin's original SToE papers and searchable companions under
  research/**;
- repository-authored README, design, preregistration, report, limitation,
  reproduction, and architecture documents under agent/, stoe-hermes/,
  engine/, experiments/, plugins/, skills/, and archive/;
- the canonical SToE seed and original ontology descriptions under
  skills/stoe-reasoning/assets/**, to the extent authored by Mykola Voronin;
- release catalog and citation documentation under releases/** and
  CITATION.cff.

When sharing adapted material, identify Mykola Voronin, link to this repository
and CC BY 4.0, and indicate changes. Third-party marks, formatting, quotations,
or other embedded material are not licensed beyond rights held by Mykola
Voronin.

## C. Existing or provenance-specific terms — not relicensed by this release

The following remain governed by their existing terms or provenance. Inclusion
in the repository or release does not assert ownership or grant a new license:

- stoe-hermes/THIRD_PARTY_NOTICES.md and any referenced Hermes/Nous Research
  material; Hermes Agent itself is not vendored;
- stoe-hermes/snapshots/hermes_a_tracked.patch;
- archive/starting_point/*.pdf and the model-output compilation they preserve;
- archived source bytes under archive/snapshots/**, except the repository-
  authored README and restore utility identified above;
- model responses, raw streams, generated/rejected candidates, and machine
  traces under agent/public_response_rehearsal/**, agent/runtime/**,
  agent/rejected_candidates/**, agent/self_code_candidates/**,
  agent/rebuild_reports/*.json, agent/research_checkpoints/**,
  agent/self_code_v2/**, and agent/structural_input_experiment*/results/**;
- generated selector implementations matching
  agent/owned_components/context_selector/versions/generated_*.py;
- frozen tasks, raw outputs, compressed results, manifests, environment
  captures, and model-response evidence under the experiment directories,
  except repository-authored narrative documentation and original executable
  software identified above;
- any embedded quotation, third-party logo, publisher/platform formatting,
  external dataset fragment, or other material carrying its own notice.

Some of these artifacts may contain original contributions alongside material
with uncertain or mixed provenance. This release deliberately makes no broader
licensing claim for them. Historical files are not mass-edited to add headers,
because doing so would change conserved evidence and published hashes.

## License texts and precedence

- MIT: [LICENSES/MIT.txt](LICENSES/MIT.txt)
- CC BY 4.0: [LICENSES/CC-BY-4.0.txt](LICENSES/CC-BY-4.0.txt)

If a file has an explicit license or notice, that file-specific statement
controls. If ownership or provenance remains unclear, treat the material as not
relicensed and seek permission from the relevant rights holder.
