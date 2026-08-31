# V9.1 Corrected Counterfactual Report

The frozen replay suite ran after all 252 primary cells and used the corrected serializer plus fatal model-visible exposure assertions. It replayed 18 successful observer-aware cases with 108 model calls. Self-reported `used_memory_refs` are not causal evidence.

| Intervention | Necessary | Contributory | No effect | Improved | Invalid |
|---|---:|---:|---:|---:|---:|
| RANDOMIZE_CRITICAL_EDGES | 14 | 0 | 4 | 0 | 0 |
| REMOVE_CRITICAL_TYPED_RELATION | 9 | 0 | 9 | 0 | 0 |
| REMOVE_FOCAL_FAILED_IP | 14 | 0 | 4 | 0 | 0 |
| REMOVE_QUERY_RANKING | 5 | 2 | 11 | 0 | 0 |
| REMOVE_STATE_CHANGE_IP | 0 | 3 | 15 | 0 | 0 |

Topology-only targeted wins versus dense: primary-enzyme-control, primary-witness-chain, primary-robot-capability. Counterfactually supported under the frozen criterion: primary-enzyme-control, primary-witness-chain, primary-robot-capability (100.0%). These are pipeline interventions that can change the replacement context; they support dependence on the implemented mechanism, not philosophical claims about the full SToE ontology.

## Clean causal-mechanism cases

All three topology-only targeted wins had the same integrity pattern: observer-aware succeeded, frozen dense retrieval failed, all four selected observer artifacts were model-visible in the same order, no UUID/internal-ID answer contamination occurred, and the selected navigation trace contained both `invalidates` and `rejected_by`. In every corresponding removal replay, four replacement artifacts also remained visible and the corrected memory stayed below 5000 characters.

| Task | Observer memory chars | Remove focal failed IP | Remove critical relation | Randomize critical edges | Remove state-change IP | Remove query ranking |
|---|---:|---|---|---|---|---|
| primary-enzyme-control | 1177 | success→failure; necessary | success→failure; necessary | success→failure; necessary | survives; no detectable effect | survives; no detectable effect |
| primary-witness-chain | 1182 | success→failure; necessary | success→failure; necessary | success→failure; necessary | survives; contributory | survives; no detectable effect |
| primary-robot-capability | 1189 | success→failure; necessary | success→failure; necessary | success→failure; necessary | survives; contributory | survives; no detectable effect |

This is the strongest evidence in the experiment for the narrow implemented mechanism: both the formerly failed IP and its critical typed relation were necessary in all three topology-only targeted wins. It is still not a minimal text-only intervention—the graph change alters retrieval and replacement artifacts—so it should be described as pipeline-level causal dependence.
