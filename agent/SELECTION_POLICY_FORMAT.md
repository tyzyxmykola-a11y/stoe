# Declarative selection-policy format v1

Status: **TRUSTED INTERPRETER BOUNDARY; FUTURE CANDIDATES ARE INERT DATA**

The former Python-source AST gate was not a sandbox. A candidate could reach
`__builtins__` indirectly, perform import-time side effects, read the evaluator's
working directory, or use ordinary process authority. A child-process timeout
bounded duration but did not remove filesystem, environment, process, network,
or memory authority.

Future candidates therefore use `stoe.selection_policy`, version 1. The candidate
artifact is JSON parsed without hooks and interpreted by trusted
`stoe_agent.selection_policy` code. It contains no expression language,
callbacks, imports, templates, attribute access, dynamic field names, paths, or
resource identifiers.

## Permitted operations

- scoring: `token_similarity`, `constant_if`, and `conditional_similarity`;
- comparison: `eq`, `not_eq`, `in`, `not_in`, `contains_token`, and `nonempty`;
- filtering: `exclude_if` over bounded conditions;
- sorting: the fixed deterministic order `score desc`, `created_order desc`,
  `ref asc`;
- budgeting: `greedy_skip_oversize`, constrained by `max_items` and `max_chars`.

Only the declared observer fields (`goal`, `active_constraints`,
`changed_constraints`, `evidence`, `open_questions`) and item fields (`ref`,
`content`, `origin`, `kind`, `outcome`, `failure_condition`, `created_order`) are
projected into the trusted interpreter. Extra keys are not exposed to the policy.

## Bounds

- policy file: 16,384 bytes;
- score rules: 24; filters: 12;
- conditions per rule: 8; fields per similarity rule: 8;
- input items: 512; selected output items: 128;
- one field: 8,192 characters; total projected text: 262,144 characters;
- output content budget: 65,536 characters;
- estimated interpreter operations: 200,000;
- tokens retained from one compared text value: 1,024.

The public and protected workers remain separately time bounded and convert
timeout, launch error, crash, malformed output, and invalid policy into structured
rejection. These bounds reduce denial-of-service exposure for this narrow
interpreter. They do not turn the trusted Python supervisor or host OS into a
general adversarial-code sandbox.

## Legacy compatibility

`v1.py` and `generated_20260906T125305Z_92e7e913.py` remain immutable historical
releases. The legacy adapter loads only those exact filenames from the versioned
component directory when their hard-coded SHA-256 values match. Arbitrary Python
is rejected before import. No legacy file is migrated, regenerated, or activated
by this repair.
