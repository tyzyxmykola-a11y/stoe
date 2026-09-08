# Public Response-Grammar Rehearsal — Preflight

Status: `PROVISIONAL_NOT_MODEL_QUALIFIED`

This harness exists to test whether the real local Ollama model can reliably
complete the candidate-generation contract. It uses only the three already
exposed public diagnostics. It does not read protected cases, evaluate a hidden
holdout, or activate a candidate.

## Repaired measurement boundaries

- `diagnostic_findings` is an object whose exact keys are generated from every
  exposed failed diagnostic. Missing and additional keys are schema failures;
  duplicate array entries are no longer possible.
- The response schema contains the complete candidate operation grammar as
  bounded fixed tables. It has no generic policy object and no source-code field.
- Trusted code compiles those tables into the existing inert
  `stoe.selection_policy` representation, fixes deterministic sorting and the
  greedy budget operation, and applies the existing policy validator.
- Every proposal and policy string, array, numeric value, table, condition list,
  and field list is bounded.
- The largest valid proposal is conservatively estimated at 1,200 tokens against
  a 1,400-token output reserve. The largest valid policy-table response is
  estimated at 1,485 tokens against a 1,800-token output reserve.
- The worst complete prompt plan retains 1,363 tokens after generation and
  checkpoint reserves in the fixed 8,192-token context.

## Mock qualification

The complete ordinary and structural pipelines passed maximum-size cooperative
mocks. Adversarial mocks were rejected for missing or additional diagnostic
keys, invented mechanism identifiers, additional response channels, overlong
strings, missing policy tables, embedded source-code objects, invalid operations,
empty required condition lists, ambiguous condition encodings, and empty scoring
tables.

Agent suite: `58/58` passed.

## Real-model qualification rule

The harness is qualified only if Qwen completes three ordinary and three
structural public-development pipelines without retry. All proposal and policy
responses must pass the exact schema and semantic gates and compile to bounded
inert policies. Public diagnostic scores are recorded for debugging but are not
an acceptance criterion and are not evidence about unseen performance.

If any of the six pipelines fails, the failure is preserved and no v3 holdout is
created. If all six succeed, the exact harness and model digest are frozen before
any new unseen v3 cases are authored.

## Development attempt 1

Artifact: `attempt_001.json`

Result: `0/6` complete pipelines. All six exact-key proposals and all six policy
JSON objects were schema-valid. Every failure occurred in the compiler because
Qwen populated both fixed payload columns for an `in` row while the compiler
required the unused scalar column to be empty. That convention was not an
authority or policy-grammar boundary; it was an avoidable serialization trap.

Development revision 2 therefore gives fixed-table columns explicit projection
semantics: `in`/`not_in` read `values`, scalar operators read `value`, and
`nonempty` reads neither. Unused bounded cells are ignored. Supported operators,
fields, table sizes, output bounds, trusted compilation, evaluation scope, and
the no-activation rule are unchanged.
