# V9.1 Serialization Validation

Status: **PASS**

This was a full 252-cell primary serialization dry run. The generation model was forbidden; the frozen local embedding model was used only to reconstruct dense selections.

- Rows: 252
- Memory-bearing rows: 234
- Generation-model calls: 0
- Embedding calls: 36
- Four-selected/fewer-than-four-visible violations: 0
- Memory blocks over 5000 characters: 0
- Selected-ref differences from frozen v9: 0

## Condition totals

| Condition | Rows | Selected | Visible | Truncated | Selection mismatches | Exposure violations | Budget violations |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25_MEMORY | 18 | 72 | 72 | 15 | 0 | 0 | 0 |
| DENSE_SEMANTIC_MEMORY | 18 | 72 | 72 | 0 | 0 | 0 | 0 |
| NO_MEMORY | 18 | 0 | 0 | 0 | 0 | 0 | 0 |
| OBSERVER_AWARE_STOE_CHIMERA_SEED | 18 | 72 | 72 | 2 | 0 | 0 | 0 |
| OBSERVER_AWARE_STOE_TOPOLOGY | 18 | 72 | 72 | 9 | 0 | 0 | 0 |
| OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED | 18 | 72 | 72 | 0 | 0 | 0 | 0 |
| OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES | 18 | 72 | 72 | 0 | 0 | 0 | 0 |
| OBSERVER_AWARE_TOPOLOGY_UNTYPED | 18 | 72 | 72 | 9 | 0 | 0 | 0 |
| OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES | 18 | 72 | 72 | 9 | 0 | 0 | 0 |
| OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE | 18 | 72 | 72 | 9 | 0 | 0 | 0 |
| OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL | 18 | 72 | 72 | 9 | 0 | 0 | 0 |
| QUERY_BLIND_TOPOLOGY | 18 | 72 | 72 | 9 | 0 | 0 | 0 |
| SUCCESS_MEMORY | 18 | 72 | 72 | 0 | 0 | 0 | 0 |
| TYPED_SEMANTIC_MEMORY | 18 | 72 | 72 | 0 | 0 | 0 | 0 |

## Interpretation

PASS means every frozen selected-reference list was reproduced before serialization, every selected reference appeared in the exact constructed memory string in the same order, and no memory string exceeded the unchanged 5000-character budget. It does not inspect or predict scientific outcomes.
