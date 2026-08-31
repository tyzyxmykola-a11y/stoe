# V9 Ablation Matrix

Condition | Structural region | Goal rank | Change signal | Failure nodes | Core seed | Typed exposure | Edge endpoints
----------|-------------------|-----------|---------------|---------------|-----------|----------------|---------------
NO_MEMORY | none | no | same state channel | no memory | field present, no context | no | n/a
SUCCESS_MEMORY | all successful artifacts | recency | same | no failed artifacts | native field | untyped | n/a
BM25_MEMORY | all eligible artifacts | BM25 | same query/state | yes | native field | untyped | n/a
DENSE_SEMANTIC_MEMORY | all eligible artifacts | dense | same query/state | yes | native field | untyped | n/a
TYPED_SEMANTIC_MEMORY | same dense ranking | dense | same query/state | yes | native field | typed | n/a
QUERY_BLIND_TOPOLOGY | topology | no | no | yes | native field | typed | original
OBSERVER_AWARE_STOE_TOPOLOGY | topology | yes | yes | yes | native | typed | original
OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED | runtime topology | yes | yes | yes | absent | typed | runtime original
OBSERVER_AWARE_STOE_CHIMERA_SEED | topology | yes | yes | yes | chimera | typed | seed target offset 7
OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES | topology | yes | yes | no | native | typed | original
OBSERVER_AWARE_TOPOLOGY_UNTYPED | exact typed selection plan | same | same | yes | native | masked only | original
OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES | topology | yes | yes | yes | native | typed | deterministic randomized
OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL | topology | yes | zeroed | yes | native | typed | original
OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE | topology | zeroed | yes | yes | native | typed | original

All memory conditions use `k=4`, the same character ceiling, canonical ordering, current-state schema, task information, and model call/output budgets. Realized counts are validated and recorded.
