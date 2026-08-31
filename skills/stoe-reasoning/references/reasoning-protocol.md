# Observer-aware reasoning protocol

Use this protocol for tasks where the reasoning state can change and an earlier rejection may become useful. The field is a working memory structure, not a requirement to expose chain-of-thought. Store concise artifacts, decisions, outcomes, and provenance; report only the conclusions and requested trace.

## 1. Represent the current observer state

Create one active `CurrentObserverStateIP` containing:

```yaml
goal: the decision or artifact currently needed
active_constraints: rules that presently bind the solution
evidence: facts currently treated as available
state_change: what changed since the prior attempt, if anything
open_questions: unresolved uncertainties
```

The current observer state belongs to the same field as prior reasoning. It is not an external query object.

## 2. Preserve useful IPs

Record only reasoning artifacts that could affect later work:

```yaml
ref: stable local identifier
origin: runtime_reasoning | failure_history | evaluation | state_change | current_observer_state | canonical_seed
kind: hypothesis | constraint | observation | plan | result | evaluation | state_change
content: concise proposition or operation
outcome: untested | supported | rejected | failed | superseded
failure_condition: the exact premise, rule, resource, or observation responsible
created_order: monotonic order
```

Do not erase failed IPs. Mark them rejected or inactive and sever or supersede obsolete connections when appropriate. Preserve the reason for failure; otherwise later reactivation is guesswork.

## 3. Use typed direction

Prefer precise relations such as:

- `state_change --invalidates--> constraint`
- `hypothesis --rejected_by--> constraint`
- `result --generated_by--> operation`
- `evaluation --evaluates--> result`
- `evidence --contradicts--> hypothesis`
- `new_hypothesis --extends--> prior_hypothesis`

Reverse traversal is allowed only when its meaning is explicit. For example, from an invalidated constraint, reverse `rejected_by` traversal finds hypotheses that the constraint formerly rejected. It does not imply that rejection itself is symmetric.

## 4. Retrieve under a budget

Use this order:

1. Traverse from the current observer state through semantically permitted directed steps to form a bounded candidate region.
2. Score candidates for current-goal relevance, applicable state change, provenance, failure relevance, path distance, redundancy, and stale locality.
3. Select at most the fixed budget.
4. Serialize exactly those selected artifacts within the fixed character/token cap.
5. Verify selected count, visible count, order, truncation, and origins.

Topology answers “where may relevant evidence be?” Current-state relevance answers “which eligible evidence matters now?” Do not use topology alone as a substitute for semantic relevance.

A safe normalized structural component for a path of length `d` is:

```text
sum(decay^i * edge_strength(type_i) * direction_weight(type_i, direction_i))
----------------------------------------------------------------------------
       sum(decay^i) * (1 + length_penalty * max(0, d - 1))
```

This prevents longer paths from winning merely by accumulating positive edges.

## 5. Decide and evaluate

For each retrieved artifact, distinguish:

- why it was reached;
- why it is relevant now;
- what operation it supports;
- whether the operation succeeded.

Create an EvaluationIP after an observable result. Later reasoning must be able to traverse evaluation nodes; otherwise evaluation is only logging, not a tested mechanism.

## 6. Test causal reliance

When a successful decision used a failed, rejected, or contradictory IP:

1. Preserve the successful result as `WITH_IP`.
2. Remove only the focal IP from accessible context/field for the relevant replay.
3. Keep model, settings, seed, task, budgets, ordering, retry policy, and all other accessible artifacts as identical as practical.
4. Record `WITHOUT_IP` and classify:

- `NECESSARY_FOR_SUCCESS`
- `CONTRIBUTORY_BUT_NOT_NECESSARY`
- `NO_DETECTABLE_EFFECT`
- `COUNTERFACTUAL_IMPROVED`
- `REPLAY_INVALID`

Describe graph-level replays as pipeline interventions, not byte-identical causal experiments, when removal changes downstream retrieval.

## Compact task-facing trace

When the user asks for an audit, report:

```text
CurrentObserverStateIP
→ typed path with traversal directions
→ selected prior IP and origin
→ relevance under the changed state
→ subsequent operation
→ observed result/evaluation
```

Otherwise keep the machinery unobtrusive and lead with the solution.
