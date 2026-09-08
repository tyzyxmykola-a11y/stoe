# Structural-Input v2 Harness Qualification

Status: **QUALIFIED WITHOUT MODEL CALLS OR NEW HIDDEN CASES**

The two v1 instrument failures are repaired in a new versioned harness module; the frozen v1 implementation and raw result remain unchanged.

- Proposal grounding now uses schema-enforced mechanism identifiers. A finding must connect at least one identifier such as `item.kind`, `item.outcome`, or `item.failure_condition` to an explicitly declared implementation input. Free prose is not searched for magic words.
- Every string and array in the proposal schema has an explicit `maxLength` or `maxItems`.
- The largest proposal that remains consistent with the observed public failures passes the evidence gate and was inserted into both complete mocked two-call pipelines.
- No local Ollama or other provider call occurred. The mock completed four calls: proposal and policy for both arms.
- Unevaluated candidate performance is represented by `evaluable: false` and `null` pass counts.

The fixed context limit is 8,192 tokens. Budget plans already include 512 checkpoint-reserve tokens. Qualification additionally requires at least 1,024 tokens remaining after the complete prompt and reserved output. The worst arm/stage retained 1,792 tokens:

| Condition | Stage | Total including output and checkpoint reserves | Additional remaining |
|---|---|---:|---:|
| Ordinary | Proposal | 4,072 | 4,120 |
| Ordinary | Policy | 5,599 | 2,593 |
| Structural | Proposal | 4,873 | 3,319 |
| Structural | Policy | 6,400 | 1,792 |

This qualifies prompt capacity and gate representation. It does not supply evidence that SToE structure improves generation. That question requires a newly authored, separately frozen v2 holdout and one non-tuned run.
