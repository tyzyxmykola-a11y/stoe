# Candidate capability-boundary checkpoint v1

Status: **COMPLETED; NO PROVIDER GENERATION; ACTIVE LEGACY RELEASE UNCHANGED**

Stable action: `checkpoint:candidate-capability-boundary-v1`

## What the exploit could do

The former `validate_candidate_source` AST blacklist accepted a selector that
looked up `open` through `__builtins__`. If evaluated, generated Python ran with
the child process's ambient authority. It could read or mutate filesystem paths,
inspect environment variables, launch processes, attempt network access, consume
memory, and perform import-time effects. Because the protected evaluator used
`protected_evals` as its working directory, a candidate could directly read
`cases.json`. The subprocess timeout bounded hangs but did not remove any of
those capabilities.

The bypass was reproduced at validation only as `GateResult(passed=True)` against
commit `4e874015a2fdb37b14fb4dda312f65801df23959`. The payload was not executed.

## Repair

Future candidates are `stoe.selection_policy` version 1 JSON artifacts interpreted
by trusted code. The grammar has no Python, expression evaluator, callback,
template execution, import, attribute traversal, dynamic field name, path, or
external-resource operation. It permits only explicitly enumerated scoring,
comparison, filtering, fixed deterministic sorting, and greedy budget operations.

The interpreter projects only `observer_state.goal`, `active_constraints`,
`changed_constraints`, `evidence`, and `open_questions`, plus the documented item
fields. Extra keys such as a probe path, evaluator path, environment object, or
active pointer are ignored and cannot be named by a valid policy. Policy bytes,
rules, conditions, fields, items, strings, operation count, output count, and
output characters are bounded. Public and protected worker calls retain timeout,
launch-error, crash, malformed-output, and fail-closed handling.

The accepted selector remains an immutable legacy Python release. Trusted loading
requires its exact filename, location, and SHA-256. Arbitrary Python is rejected
before import. The active release was not migrated, rewritten, or reactivated.

## Adversarial verification

The agent suite includes attacks using:

- `__builtins__["open"]`;
- indirect `eval`, `exec`, and `__import__`;
- `getattr`-based dunder traversal;
- top-level side effects and attempts to read `cases.json`;
- environment, network, subprocess, and active-pointer access;
- infinite execution, recursion, excessive output, and excessive allocation;
- malformed, oversized, recursively shaped, unknown-field, and over-complex
  declarative policies.

The executable artifacts are rejected before import by both evaluator paths, and
sentinel effects do not occur. Code-looking strings in valid policies remain inert
while filesystem, evaluator, import, network, subprocess, and environment entry
points are mocked and asserted unused. Invalid or excessive policy/input/output
structures fail closed. These tests establish absence of candidate-supplied code
execution in this interface rather than recognition of a list of dangerous
spellings.

Verification results:

- agent: 30/30;
- v9.1: 50/50;
- v3: 21/21;
- memory plugin, including stdio integration: 9/9;
- total: 110/110;
- fresh-process resume: 1,792 estimated tokens under the fixed 1,800-token
  budget, with full artifacts omitted by reference rather than discarded;
- dependency-blocked tests: none. The plugin stdio test required the already
  authorized local subprocess permission and passed.

The accepted selector replay on previously observed cases remained 1/3 public
and 3/5 protected. It is a compatibility replay, not a new blind experiment and
not scientific evidence for SToE superiority.

## Historical integrity

- accepted report SHA-256:
  `a008eba9e581ccb1850f509c1a535c26b7b6c361c3174a0936fb18dd473677b1`;
- accepted selector SHA-256:
  `d37f48335f87c4c4370ea78d7719cf3a79aa26ef41b0911c81f448f7828d2cb1`;
- protected cases SHA-256:
  `76512fc8fda0c0ae31e47c9ba0d8fb6e2555c27f531b0700221673b506444138`;
- historical protected evaluator SHA-256:
  `6be6246238aedb0c37a72be6e2623772ba6ff1b67415fa46ab3ab4272e3fec06`;
- checkpoint replay artifact SHA-256:
  `12758da3757a7ea83166ccbef07500bd07a2865fd77e05cb5918b6431ce84e4b`.

Historical scores, cases, thresholds, reports, and evidence classifications were
not edited. Documentation now records that “no candidate filesystem/evaluator
authority” was an intended boundary that the Python implementation did not
enforce.

## Remaining limitations

The policy interpreter, evaluator workers, supervisor, Python runtime, and host OS
remain trusted. This repair removes candidate-supplied executable behavior from
the narrow selector interface; it is not a general sandbox for arbitrary code or
a proof against defects in trusted code. Fixed bounds reduce denial-of-service
exposure but do not constitute formal resource-isolation proof. The declarative
grammar may also be too restrictive for useful future hypotheses; that must be
tested scientifically on newly frozen cases, not inferred from these safety tests.

## Exact remaining research question

> Why did changed-constraint invalidation fail to materialize, and can a bounded
> structural input improve it on newly frozen cases without expanding candidate
> authority?

No provider/model generation occurred during this checkpoint. The next cycle
must freeze new cases before outcomes and must not interpret infrastructure tests
or replays of previously observed cases as evidence of SToE superiority.
