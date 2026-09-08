# Structural-Input Experiment v2 — Result

Status: **RUN ONCE — NOT EVALUABLE**

V2 was not rerun or tuned. Neither candidate reached hidden evaluation, so it supplies no evidence for or against a structural SToE advantage. Candidate pass counts are correctly recorded as `null` with `evaluable: false`.

## Frozen identity

- Freeze commit: `44c66e13dc14133a2c5af78fc06e6d1a3e750264`
- Model: local Ollama `qwen3-coder:latest`
- Model digest: `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca`
- New holdout: 12 independent cases; 8 targets and 4 controls
- Case SHA-256: `d5c84df8d1c6d0268c556b8ded363cfc8ad9bb26a16ddfc7625365489cdd10cc`
- Raw-result SHA-256: `7f9de2fffb99def23b1b8d94cc78206cf128c01e6c93fd422c75e58a7f1c651c`

## Execution

Three of four allowed model calls occurred, without retries:

| Condition | Stage | Input/output/total tokens | Outcome |
|---|---|---:|---|
| Ordinary | Proposal | 1,722 / 600 / 2,322 | Rejected: returned findings for only 2 of 3 observed failures |
| Structural | Proposal | 2,566 / 666 / 3,232 | Passed bounded schema and evidence validation |
| Structural | Policy | 3,093 / 974 / 4,067 | Rejected by inert-policy validator |
| Ordinary | Policy | — | Not run after proposal rejection |

The structural policy response used an arbitrary object shape and embedded Python source in a string. It remained inert data and was rejected before import or execution. Thus the capability boundary worked, but the policy response schema was too generic to force the declarative policy grammar.

The ordinary proposal satisfied the bounded JSON schema because `diagnostic_findings` allowed 1–3 entries, but failed the separate exact-evidence gate requiring all three observed failures. The gate behaved correctly; the schema did not encode the already-known exact cardinality.

The qualified context budget was not the problem. All three actual calls fit, and the preregistered worst-case proof retained 1,792 tokens beyond output and checkpoint reserves.

## Observed baseline and conclusion

The frozen active selector passed 4/12: **0/8 targets and 4/4 controls**. This independently reconfirms the changed-constraint limitation on a second new set.

- Structural success criterion: **NOT EVALUABLE**.
- Candidate comparison: **NONE**.
- Activation: **NO**.
- SToE structural advantage: **NOT TESTED BY THE COMPLETED PIPELINE**.

The exact remaining instrumentation question is whether a future harness can force, through complete schemas rather than cooperative mocks, exactly one finding per observed public failure and the complete inert selection-policy grammar. That instrument must be qualified using adversarial malformed mock outputs as well as maximum valid outputs before any further hidden set is authored. V2 cases must not be reused for confirmation.
