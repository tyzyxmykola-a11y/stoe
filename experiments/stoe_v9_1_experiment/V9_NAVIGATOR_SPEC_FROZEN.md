# V9 Navigator Specification

## Candidate region

Starting from `CurrentObserverStateIP`, traverse directed edges in either permitted direction to depth four. Reverse traversal is recorded explicitly. Bookkeeping edges and non-visible structural containers may support paths but are removed before ranking and top-k.

The candidate graph is the shared canonical-seed plus runtime field. Native core seed nodes receive no origin bonus. A seed node can be selected only when it is within the same bounded structural region and wins the same score/budget competition as a runtime node.

## Structural path score

For path edges `i=0..d-1`:

`structural = sum(decay^i * edge_strength(type) * direction_weight(type,direction)) / sum(decay^i) / (1 + 0.18*(d-1))`

with `decay=0.65`. This normalized, distance-penalized score cannot grow merely by adding positive edges.

## Observer-aware score

For each eligible candidate in the structural region:

`final = 0.25*structural + 0.15*goal + 0.30*state_change + 0.10*provenance + 0.10*failure_relevance - 0.05*distance - 0.10*redundancy - 0.15*stale_locality`

- `goal`: bounded token relevance between candidate content and current question/goal/constraints.
- `state_change`: 1.0 for a path containing both `invalidates` and reverse `rejected_by`; 0.55 for a direct changed-constraint association; otherwise 0.
- `provenance`: 1.0 for the explicit invalidation/rejection chain; 0.5 for other typed causal provenance; otherwise 0.
- `failure_relevance`: 1.0 only when a failed/rejected candidate lies on an applicable change path.
- `distance`: `max(0, path_length-1)/4`.
- `redundancy`: maximum bounded token overlap with already selected artifacts.
- `stale_locality`: 1.0 for a recent local dead end without an applicable state-change path.

Scores are not exposed to the LLM. They are machine-readable audit evidence.

## Query-blind control

The legacy query-blind control ranks by normalized structural path score plus a fixed `0.50` bonus for the exact IP recorded as `current_reasoning_ref`. This term uses no question, goal, constraint, outcome, or answer content. It intentionally preserves v8's current-branch locality bias as a diagnostic baseline rather than presenting it as the v9 policy.

## Ablations

- `WITHOUT_STATE_CHANGE_SIGNAL`: zeroes state-change and failure-reactivation components.
- `WITHOUT_QUERY_RELEVANCE`: zeroes goal relevance.
- `RANDOMIZED_EDGES`: deterministically changes typed transition endpoints while preserving nodes/content and relation-type multiset.
- `UNTYPED`: uses the exact typed selection plan and masks relation types in model-visible context. This is a clean relation-exposure ablation; critical-relation removal is separately tested counterfactually.
- `WITHOUT_CORE_SEED`: removes the folded domain, 36 core IPs, 113 native relations, and fixed bridges while preserving runtime graph, prompt, ranker, and budget.
- `CHIMERA_SEED`: preserves core node refs/content/categories/expressions and the relation-type multiset, but rewires native seed-edge targets by the preregistered offset-7 rule. Runtime bridges remain unchanged.

## Trace schema

Every candidate, selected or rejected, records current-state ref, path, directions, edge types, component scores, final score, eligibility, selection, canonical tie key, deterministic reason, and origin (`canonical_seed`, `runtime_reasoning`, `failure_history`, `evaluation`, `state_change`, or `current_observer_state`). Every result row also records selected origins and seed mode.
