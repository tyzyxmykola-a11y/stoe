# V9.1 Statistical Analysis

## Status and exposure gate

This is a **corrective replication**, not an independent confirmation. It contains 18 distinct tasks in nine family clusters and 14 frozen conditions (252 primary cells). All 234 memory-bearing cells exposed exactly four unique selected references, and no serialized memory block exceeded 5000 characters.

| Condition | Success | Targeted | Controls | Tokens | Solved/1k | Mean latency | Parse/provider/retries | Focal retrieved | Seed selected |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NO_MEMORY | 0/18 (0.0%) | 0/9 | 0/9 | 4877 | 0.000 | 1.111s | 0/0/0 | 0/18 | 0 |
| SUCCESS_MEMORY | 3/18 (16.7%) | 0/9 | 3/9 | 8565 | 0.350 | 0.738s | 0/0/0 | 4/18 | 0 |
| BM25_MEMORY | 14/18 (77.8%) | 5/9 | 9/9 | 12126 | 1.155 | 0.884s | 0/0/0 | 14/18 | 15 |
| DENSE_SEMANTIC_MEMORY | 14/18 (77.8%) | 6/9 | 8/9 | 9100 | 1.538 | 8.934s | 0/0/0 | 15/18 | 0 |
| TYPED_SEMANTIC_MEMORY | 15/18 (83.3%) | 6/9 | 9/9 | 9179 | 1.634 | 8.940s | 0/0/0 | 15/18 | 0 |
| QUERY_BLIND_TOPOLOGY | 4/18 (22.2%) | 0/9 | 4/9 | 11999 | 0.333 | 0.995s | 0/0/0 | 4/18 | 27 |
| OBSERVER_AWARE_STOE_TOPOLOGY | 18/18 (100.0%) | 9/9 | 9/9 | 12171 | 1.479 | 1.034s | 0/0/0 | 18/18 | 27 |
| OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED | 16/18 (88.9%) | 9/9 | 7/9 | 9626 | 1.662 | 0.799s | 0/0/0 | 16/18 | 0 |
| OBSERVER_AWARE_STOE_CHIMERA_SEED | 13/18 (72.2%) | 9/9 | 4/9 | 11132 | 1.168 | 0.848s | 0/0/0 | 13/18 | 26 |
| OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES | 4/18 (22.2%) | 0/9 | 4/9 | 12093 | 0.331 | 0.880s | 0/0/0 | 4/18 | 32 |
| OBSERVER_AWARE_TOPOLOGY_UNTYPED | 18/18 (100.0%) | 9/9 | 9/9 | 11572 | 1.555 | 0.878s | 0/0/0 | 18/18 | 27 |
| OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES | 3/18 (16.7%) | 3/9 | 0/9 | 11451 | 0.262 | 0.825s | 0/0/0 | 3/18 | 45 |
| OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL | 18/18 (100.0%) | 9/9 | 9/9 | 11757 | 1.531 | 0.816s | 0/0/0 | 18/18 | 18 |
| OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE | 13/18 (72.2%) | 9/9 | 4/9 | 12317 | 1.055 | 0.834s | 0/0/0 | 13/18 | 32 |

## Frozen paired comparisons

| Comparison | Subset | Left | Right | Difference | 95% family-cluster CI | Discordant L:R | Exact p |
|---|---|---:|---:|---:|---:|---:|---:|
| OBSERVER_AWARE_STOE_TOPOLOGY vs DENSE_SEMANTIC_MEMORY | topology_targeted | 9/9 | 6/9 | 33.3% | [0.0%, 66.7%] | 3:0 | 0.250000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs QUERY_BLIND_TOPOLOGY | all | 18/18 | 4/18 | 77.8% | [61.1%, 94.4%] | 14:0 | 0.000122 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs QUERY_BLIND_TOPOLOGY | topology_targeted | 9/9 | 0/9 | 100.0% | [100.0%, 100.0%] | 9:0 | 0.003906 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs QUERY_BLIND_TOPOLOGY | negative_control | 9/9 | 4/9 | 55.6% | [22.2%, 88.9%] | 5:0 | 0.062500 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs DENSE_SEMANTIC_MEMORY | all | 18/18 | 14/18 | 22.2% | [0.0%, 44.4%] | 4:0 | 0.125000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs DENSE_SEMANTIC_MEMORY | negative_control | 9/9 | 8/9 | 11.1% | [0.0%, 33.3%] | 1:0 | 1.000000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs BM25_MEMORY | all | 18/18 | 14/18 | 22.2% | [5.6%, 38.9%] | 4:0 | 0.125000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs BM25_MEMORY | topology_targeted | 9/9 | 5/9 | 44.4% | [11.1%, 77.8%] | 4:0 | 0.125000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs SUCCESS_MEMORY | all | 18/18 | 3/18 | 83.3% | [66.7%, 100.0%] | 15:0 | 0.000061 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs SUCCESS_MEMORY | topology_targeted | 9/9 | 0/9 | 100.0% | [100.0%, 100.0%] | 9:0 | 0.003906 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED | all | 18/18 | 16/18 | 11.1% | [0.0%, 27.8%] | 2:0 | 0.500000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED | topology_targeted | 9/9 | 9/9 | 0.0% | [0.0%, 0.0%] | 0:0 | 1.000000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_STOE_CHIMERA_SEED | all | 18/18 | 13/18 | 27.8% | [11.1%, 44.4%] | 5:0 | 0.062500 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_STOE_CHIMERA_SEED | topology_targeted | 9/9 | 9/9 | 0.0% | [0.0%, 0.0%] | 0:0 | 1.000000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES | all | 18/18 | 4/18 | 77.8% | [61.1%, 94.4%] | 14:0 | 0.000122 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES | topology_targeted | 9/9 | 0/9 | 100.0% | [100.0%, 100.0%] | 9:0 | 0.003906 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES | negative_control | 9/9 | 4/9 | 55.6% | [22.2%, 88.9%] | 5:0 | 0.062500 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_UNTYPED | all | 18/18 | 18/18 | 0.0% | [0.0%, 0.0%] | 0:0 | 1.000000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_UNTYPED | topology_targeted | 9/9 | 9/9 | 0.0% | [0.0%, 0.0%] | 0:0 | 1.000000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_UNTYPED | negative_control | 9/9 | 9/9 | 0.0% | [0.0%, 0.0%] | 0:0 | 1.000000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES | all | 18/18 | 3/18 | 83.3% | [66.7%, 100.0%] | 15:0 | 0.000061 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES | topology_targeted | 9/9 | 3/9 | 66.7% | [33.3%, 100.0%] | 6:0 | 0.031250 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES | negative_control | 9/9 | 0/9 | 100.0% | [100.0%, 100.0%] | 9:0 | 0.003906 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL | all | 18/18 | 18/18 | 0.0% | [0.0%, 0.0%] | 0:0 | 1.000000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL | topology_targeted | 9/9 | 9/9 | 0.0% | [0.0%, 0.0%] | 0:0 | 1.000000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL | negative_control | 9/9 | 9/9 | 0.0% | [0.0%, 0.0%] | 0:0 | 1.000000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE | all | 18/18 | 13/18 | 27.8% | [11.1%, 44.4%] | 5:0 | 0.062500 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE | topology_targeted | 9/9 | 9/9 | 0.0% | [0.0%, 0.0%] | 0:0 | 1.000000 |
| OBSERVER_AWARE_STOE_TOPOLOGY vs OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE | negative_control | 9/9 | 4/9 | 55.6% | [22.2%, 88.9%] | 5:0 | 0.062500 |

The confirmatory targeted comparison was observer-aware topology versus dense semantic retrieval: 9/9 versus 6/9, an absolute difference of 33.3%; family-cluster bootstrap 95% CI [0.0%, 66.7%], exact paired p=0.250000. Overall the same comparison was 18/18 versus 14/18.

The frozen all-required success criterion is **MET**. Individual checks: `{"counterfactual_mechanism_fraction_at_least_25_percent": true, "negative_control_guard_no_more_than_two_tasks_worse_than_dense": true, "observer_over_dense_by_at_least_one_of_nine_targeted": true, "observer_over_query_blind_targeted": true}`. A confidence interval containing zero is not called equivalence.

Across primary cells there were 0 provider errors, 0 parse errors, and 0 transport retries. Total primary tokens were 147,965; recorded generation latency was 513.270 seconds. Family-cluster intervals use the frozen 10,000 resamples and seed 9417.
