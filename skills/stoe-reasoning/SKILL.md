---
name: stoe-reasoning
description: "Apply SToE-derived observer-aware reasoning memory: preserve failed hypotheses and provenance, represent state changes with typed directed relations, and retrieve bounded prior reasoning when constraints change. Use for nonlinear diagnosis, debugging, research, planning, agent-memory design, or audits where discarded paths may become relevant. Do not use it to present the full SToE ontology as established science or to inject the entire canonical seed into routine prompts."
---

# SToE Reasoning

Use a persistent, observer-aware reasoning field when a task has changing constraints, competing hypotheses, recoverable failures, or several reasoning stages. For simple one-step work, answer normally and do not manufacture graph overhead.

## Apply the protocol

1. Materialize the current observer state: goal, active constraints, evidence, unresolved questions, and the change since the last state.
2. Preserve substantive reasoning artifacts as Information Points (IPs), including rejected or failed hypotheses. Record the outcome and why it failed; do not preserve undifferentiated scratch text.
3. Connect IPs with typed, directed relations. Interpret direction semantically rather than treating every edge as symmetric.
4. When a premise, capability, rule, or constraint changes, create a state-change IP and connect it to what it invalidates or enables.
5. Retrieve a small, explicit budget of prior IPs. Let topology define a candidate region, then rank candidates against the current state. Do not dump the whole field or seed into context.
6. Prefer a failed path only when its failure condition is now invalidated or otherwise relevant. A nearby failure is not automatically useful.
7. Make the next decision using the retrieved evidence, then record an evaluation IP and any new state change.
8. If claiming that a retrieved failed IP caused success, replay the decision without that IP while holding the rest as constant as practical. Self-reported influence is not causal proof.

Read [references/reasoning-protocol.md](references/reasoning-protocol.md) when applying this workflow to a concrete task. Keep the graph internal unless the user asks for the trace.

## Use the connected persistent field

When the `stoe_memory` MCP tools are available and the task warrants persistent reasoning memory:

1. Call `stoe_field_status` to verify the field and canonical seed before writing.
2. Use a stable, task-specific `session_id`; do not mix unrelated projects into one unlabelled session.
3. Store substantive artifacts with `stoe_add_ip` and connect them using `stoe_add_relation`. A failed IP must include its exact `failure_condition` and use origin `failure_history`.
4. Create the active field position with `stoe_set_observer_state`. Pass explicit `invalidates_refs`, `recent_refs`, and `current_reasoning_ref` where justified; do not invent relations.
5. Call `stoe_navigate` only after the observer state exists. Use returned `selected_items` as bounded context and retain its `run_id`.
6. Use `stoe_get_retrieval_trace` when auditing paths, typed directions, rejected candidates, or scoring.
7. Persist observed outcomes with `stoe_record_evaluation` so later reasoning can traverse them.
8. Use `stoe_prepare_counterfactual_contexts` to produce paired contexts, then actually replay the final decision before assigning a causal category.

Do not write routine one-step work to the field. If the tools are unavailable, apply the in-context protocol and do not imply that memory persisted across tasks.

## Design or audit an agent architecture

Read [references/field-schema.md](references/field-schema.md) for the shared-field schema, navigation rules, scoring safeguards, trace requirements, and controlled comparisons. Require strong semantic retrieval as a comparator when evaluating topology; a weak lexical baseline alone is insufficient.

## Use the canonical SToE seed only when relevant

The byte-preserved seed is [assets/stoe_seed.json](assets/stoe_seed.json). Read [references/canonical-seed.md](references/canonical-seed.md) before loading, folding, unfolding, modifying, or citing it. Never silently rewrite the ontology. Never give seed nodes an origin bonus. Seed and runtime IPs may share one traversable field, but only reached, eligible nodes count against the same retrieval budget as runtime nodes.

Run `python scripts/validate_seed.py` after copying or packaging the skill. Treat any hash or structural mismatch as a fidelity failure.

## Keep claims calibrated

Read [references/scientific-boundaries.md](references/scientific-boundaries.md) when discussing SToE evidence, its mathematical claims, or the v9.1 experiment. Distinguish:

- the operational hypothesis about persistent failed-path memory and observer-aware retrieval;
- the canonical SToE ontology and vocabulary;
- broader mathematical, metaphysical, or Theory-of-Everything claims.

Evidence for the first does not establish the latter two.

## Non-negotiable safeguards

- Preserve provenance, outcome, and failure condition; raw content alone is inadequate.
- Normalize and decay path scores. Never reward a path merely for containing more positive edges.
- Record edge type and traversal direction in retrieval traces.
- Keep current-state information and context budgets equivalent across compared retrievers.
- Separate selection from serialization and verify that every selected artifact actually reaches model-visible context.
- Label confirmatory, corrective-replication, and exploratory evidence honestly.
- Do not claim universal superiority from one benchmark, model, seed, or run.
