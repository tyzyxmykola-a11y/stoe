# Frozen V9 Context Exposure Audit

## Result

All 252 frozen v9 primary rows were audited against the exact `memory_context` sent to Gemma. The old prefix was independently reconstructed from the frozen selected refs, graph nodes, typed paths, and serializer. Every row matched its reconstructed prefix.

- Rows selecting four artifacts: **234**
- Four-selected rows exposing fewer than four: **68**
- Selected refs lost before model exposure: **137**
- Scientific status: **V9_PRIMARY_INVALID_CONTEXT_BUDGET**

## By condition

| Condition | Rows | Selected 4 | Exposure violations | Lost refs | Visible blocks |
|---|---:|---:|---:|---:|---:|
| BM25_MEMORY | 18 | 18 | 12 | 17 | 55 |
| DENSE_SEMANTIC_MEMORY | 18 | 18 | 0 | 0 | 72 |
| NO_MEMORY | 18 | 0 | 0 | 0 | 0 |
| OBSERVER_AWARE_STOE_CHIMERA_SEED | 18 | 18 | 2 | 2 | 70 |
| OBSERVER_AWARE_STOE_TOPOLOGY | 18 | 18 | 9 | 22 | 50 |
| OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED | 18 | 18 | 0 | 0 | 72 |
| OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES | 18 | 18 | 0 | 0 | 72 |
| OBSERVER_AWARE_TOPOLOGY_UNTYPED | 18 | 18 | 9 | 22 | 50 |
| OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES | 18 | 18 | 9 | 23 | 49 |
| OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE | 18 | 18 | 9 | 20 | 52 |
| OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL | 18 | 18 | 9 | 22 | 50 |
| QUERY_BLIND_TOPOLOGY | 18 | 18 | 9 | 9 | 63 |
| SUCCESS_MEMORY | 18 | 18 | 0 | 0 | 72 |
| TYPED_SEMANTIC_MEMORY | 18 | 18 | 0 | 0 | 72 |

## By benchmark subset

| Subset | Rows | Selected 4 | Exposure violations | Lost refs |
|---|---:|---:|---:|---:|
| topology_targeted | 126 | 117 | 6 | 9 |
| negative_control | 126 | 117 | 62 | 128 |

## First block responsible for old break

| Ref | Rows |
|---|---:|
| `SEED_05d9d98dddc9034a` | 55 |
| `SEED_104b70c3e43ee10d` | 11 |
| `SEED_57a01496da4fd547` | 2 |

The JSON artifact contains every task, family, condition, stage, selected/visible ref list, lost refs, reconstructed original line lengths, responsible block, exact memory characters, exact context, and invariant flag. This audit is diagnostic only and does not alter or rescore v9.
