# SToE Structural-Input v3 — Preregistration

Status: **FROZEN — NOT RUN**

The measurement harness was qualified first on three already exposed public
diagnostics. Its third revision completed all six real-Qwen development
pipelines without retry. Only after that result and its code/model hashes were
frozen were the twelve v3 cases authored.

The v3 benchmark contains eight independent changed-constraint targets and four
independent controls. Its names, families, and item content do not occur in the
v1 or v2 holdouts. The model receives no case names, refs, item text, outcomes,
or scores before generating either policy.

Both arms receive the active source, exposed diagnostics, and identical bounded
unstructured memory. The structural arm alone receives the preregistered typed
directed overlay referencing those same memory records. Both arms use the exact
same local Ollama model and digest, fixed-table policy language, seed, context,
generation budgets, retry rule, task order, public gate, protected acceptance
rule, and activation rule.

Primary outcome: structural targeted passes minus ordinary targeted passes.
Success requires at least `+2/8` targeted cases and no control loss. A tie, a
format failure, or failure of either public gate cannot be interpreted as a
structural advantage. No outcome validates the broader SToE ontology.

Benchmark SHA-256:
`f14d953c890e296c392918ce9ac6f821b8ce2020f853f7ea2e8aa9964bd18b65`

Once the run begins, cases, hashes, prompts, grammar, algorithms, budgets,
thresholds, seeds, and specification must not change.
