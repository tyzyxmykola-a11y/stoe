# SToE Structural-Input Experiment v1 — Preregistration

Status: **FROZEN NOT RUN**

No candidate has been generated and the twelve new cases have not been scored by the active selector or any candidate. The case file was written before the experiment runner was allowed to call Ollama.

## Question and intervention

This is a paired pipeline intervention, not a test of the full SToE ontology. Both conditions receive the active selector, the full observable public diagnostics, and exactly the same bounded field-node content. `BOUNDED_TYPED_STOE` alone receives an appended relational overlay showing typed edges, traversal directions, paths, selection flags, and navigator scores for those same record IDs. Thus the treatment changes represented connections, not node content, model, policy expressivity, or evaluation access.

The ordinary candidate is generated first and the structural candidate second. Both are generated before the hidden case file is evaluated. The order is frozen and is a remaining nuisance variable because a single local model server cannot literally execute both calls simultaneously.

## Controls

- Local Ollama only: `qwen3-coder:latest`, digest `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca`.
- Two calls per condition: proposal and inert policy generation. No retry.
- Identical system prompts, seeds, output caps, 8,192-token context, sampling settings, policy schema, public gate, hidden acceptance rule, and activation rule.
- Proposal seed 3701; policy seed 4701; temperature 0; top-p 0.9; top-k 40.
- Common memory and typed overlay together are capped at 14 records and 5,000 serialized characters. Unreachable field nodes are absent.
- The generated artifact is inert `stoe.selection_policy` JSON interpreted by trusted code. It receives no structural information at runtime; structural input can affect only the research decision that generates the policy.
- Hidden identifiers are automatically checked against both actual prompt traces before hidden evaluation.

## Frozen cases and analysis

The benchmark contains twelve distinct task instances in twelve families: eight changed-constraint targets and four controls. Its SHA-256 is `10c9e3685bc3634715d65418fb694203309698dfc5d9ec73b257aa9857e9186b`.

Primary metric: structural minus ordinary targeted passes. The preregistered criterion is an advantage of at least two of eight targets with no loss on the four controls. Total passes, exact disagreements, public performance, baseline performance, tokens, and latency are secondary.

Each candidate is separately compared with the frozen active baseline using the established rule: strict hidden pass-count improvement, preservation of all baseline passes, no critical failure, completed evaluation, and prior passage of the public behavioral gate. If both candidates qualify, targeted passes then total passes determine a unique winner; an exact tie causes no activation. SToE gets no preferred tie-break.

## Interpretation boundary

A positive result would be one piece of evidence that typed relational presentation helped this fixed model formulate a more general selector under these cases. It would not prove SToE, establish a population effect, isolate every navigator component, or show that storing provenance alone is useful. A null or negative result is retained without tuning the benchmark or runner. Replication on a larger independently authored set would still be required.
