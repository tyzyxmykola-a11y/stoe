# Persistent reasoning field and audit rules

## Shared-field requirements

Store the current observer state, runtime reasoning, failures, evaluations, state changes, and any canonical seed nodes in one traversable directed multigraph. A query object outside the field cannot participate in reciprocal runtime-to-seed or seed-to-runtime paths.

Every node must include a stable reference, origin, kind, semantic content, visibility, creation order, and outcome metadata. Every edge must include source, target, relation type, weight or strength, and direction semantics.

Allowed origin labels are:

- `canonical_seed`
- `runtime_reasoning`
- `failure_history`
- `evaluation`
- `state_change`
- `current_observer_state`

## Navigator invariants

- Start from `CurrentObserverStateIP`.
- Traverse only relation/direction combinations declared semantically valid.
- Record reverse traversal explicitly.
- Bound depth and candidate count before ranking.
- Remove bookkeeping containers from model-visible top-k while allowing them to support paths.
- Use a distance-decayed, length-normalized structural score.
- Combine structure with current-goal and state-change relevance.
- Penalize redundant artifacts and recent local dead ends without an applicable change path.
- Give canonical seed nodes no blanket bonus.
- Break ties deterministically and record the tie key.

For each candidate, record the current-state ref, path, directions, edge types, component scores, final score, eligibility, selection decision, origin, and deterministic reason.

## Failure semantics

Retaining failed content is insufficient. The field must encode what rejected it and whether that rejecting condition still holds. A typical reactivation path is:

```text
CurrentObserverStateIP
→ StateChangeIP
--invalidates--> ConstraintIP
<--rejected_by-- FailedHypothesisIP
```

The navigator may then retrieve the failed hypothesis because its recorded rejection basis has changed. Never reward all failures, and never infer reactivation from lexical similarity alone.

## Selection/serialization integrity

Treat ranking and prompt exposure as separate stages. After serialization, assert:

- every selected visible artifact appears in the prompt;
- no unselected semantic artifact leaks into the prompt;
- ordering matches the frozen selection plan;
- visible artifact counts and token/character caps match the condition's budget;
- truncation is recorded per artifact;
- internal IDs or relation labels do not leak into conditions intended to hide them.

## Fair evaluation

When testing topology against semantic retrieval:

- provide equivalent task and current-state information to every condition;
- use a strong dense embedding retriever and, if practical, BM25 as an additional baseline;
- freeze model/digest, prompts, settings, seeds, budgets, task order, and retry policy;
- use genuinely independent task instances and report family clustering;
- keep the same accessible memory corpus unless the ablation explicitly changes it;
- verify each ablation changes only its named mechanism;
- do not tune after observing primary results.

Useful ablations include no failures, randomized adjacency with preserved relation-type counts, no current-state relevance, no core seed, and a preregistered chimera rewiring. An “untyped” display ablation that reuses a typed selector tests label exposure, not typed navigation.

## Outcome metrics

At minimum capture task/family, model and digest, prompts, responses, calls, tokens, latency, retrieved refs and origins, traversal paths and directions, failed/evaluation nodes encountered, final answer, objective score, errors/retries, seed/config, storage growth, and counterfactual replay results.

Do not characterize a win over no-memory or a weak lexical retriever as evidence that topology beats modern semantic memory. The primary scientific comparison must be against the strongest credible semantic baseline.
