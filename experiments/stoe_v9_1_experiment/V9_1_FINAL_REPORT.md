# SToE V9.1 Corrective Replication Final Report

## Measurement integrity

The correction worked as specified. All 234 memory-bearing primary cells exposed the same four references selected before serialization, in the same order; none exceeded the unchanged 5000-character cap. Frozen v9 selected refs matched in all 252 cells. Primary and replay execution used the exact frozen Gemma and embedding digests, with zero provider errors, parse errors, or retries. The completed raw result SHA-256 is `1546d7f9950cbfbff869213eb0198f96d955e277cfbb5bf3ef6c648e0cd41503`.

## Primary result

Observer-aware topology scored **18/18 overall** and **9/9 targeted**. Frozen dense semantic retrieval scored **14/18 overall** and **6/9 targeted**; BM25 **14/18** and **5/9**; query-blind topology **4/18** and **0/9**. Typed semantic retrieval, a secondary frozen baseline, was the strongest conventional retriever overall at **15/18**, while also scoring **6/9 targeted**.

The preregistered targeted observer-minus-dense estimate is **+33.3 percentage points**. Its family-cluster bootstrap 95% CI is **0.0 to 66.7 points**, and the exact paired p-value is **0.25**. Thus the point estimate meets the frozen effect threshold, but the small nine-family sample remains statistically imprecise and does not provide conventional significance by itself. Overall observer-minus-dense was +22.2 points (18/18 vs 14/18; exact p=.125).

All four frozen success checks passed: observer-aware exceeded query-blind targeted; exceeded dense by at least one targeted task; all three topology-only targeted wins had preregistered causal-mechanism support; and the negative-control guard passed. The formal frozen verdict is therefore **SUPPORTED**.

## What the correction changed

Relative to invalid v9, 233/252 cells retained the same correctness. Eighteen improved and one worsened. Sixteen improvements occurred in cells whose previously selected references had been lost before model exposure; three correctness flips occurred despite unchanged exposure and are conservatively labeled stochastic. Observer-aware improved from 13/18 to 18/18, with all five gains in previously underexposed control cells. This alignment is consistent with the serializer correction mattering, but one deterministic-seeded run cannot prove every answer flip was caused by exposure.

## Mechanism and ablations

The three observer-only targeted wins over dense—`primary-enzyme-control`, `primary-witness-chain`, and `primary-robot-capability`—all had four-visible-artifact integrity, no internal-ID contamination, and a selected `invalidates`→`rejected_by` path. Removing the focal failed IP or the critical typed relation changed success to failure in all three while maintaining four visible replacement artifacts. This is strong pipeline-level dependence on the implemented failed-history/topology mechanism.

Without failures scored 4/18 and randomized edges 3/18, supporting the importance of failure availability and non-random topology in this benchmark. Without query relevance scored 13/18, with losses confined to controls. Untyped tied native at 18/18, but it inherits the typed navigator's selected plan; this shows no benefit from displaying relation labels to the LLM, not that typed relations are irrelevant to navigation. WITHOUT_STATE_CHANGE_SIGNAL also tied 18/18, but structural/provenance terms still use relations such as `invalidates` and `rejected_by`; the isolated numerical state-change term was unnecessary here, not all state-change structure.

## Canonical seed

Native/no-seed/chimera scored **18/18, 16/18, and 13/18**. All three were 9/9 targeted; differences occurred only on controls. Native selected 27 seed artifacts, nine truncated, and displaced 29 runtime slots. Native-minus-no-seed was +2 tasks (exact p=.5); native-minus-chimera was +5 (exact p=.0625), both secondary comparisons. This is compatible with useful native integration on these controls, but it does not establish that canonical SToE ontology is generally beneficial or that native adjacency is uniquely superior.

## Adversarial limitations

- This is a corrective replication on a benchmark whose v9 outcomes were already inspected, not an independent confirmation.
- There are only nine independent family clusters; the primary targeted interval touches zero.
- The benchmark is deliberately constructed around changed constraints and retained failures; general tasks and models may behave differently.
- Only one generation model/digest and one completed seeded run were tested. Three exposure-unchanged correctness flips demonstrate residual nondeterminism.
- Equal artifact counts and a common maximum budget do not imply equal semantic information volume or quality. Conditions used different actual character totals, and oversized seed content was truncated.
- Counterfactuals are pipeline interventions: removing nodes/relations changes downstream retrieval, so they are not byte-identical text-only causal manipulations.
- Query-blind and several ablations are intentionally diagnostic, not equally strong modern retrieval baselines.

## Verdict

The frozen v9.1 architectural criterion is **SUPPORTED** after correcting the context-budget defect. The defensible claim is narrow: on this benchmark and local Gemma model, observer/current-state-aware topology with retained failed information outperformed the frozen dense comparator on targeted tasks and conventional retrievers overall, with pipeline-level mechanism evidence. It does not establish the full SToE ontology, a universal information law, universal graph-memory superiority, autoinjection as a mathematical class, or AGI superiority. Independent confirmation requires a new unseen holdout benchmark.
