# V9.1 Result Summary

Replication type: CORRECTIVE REPLICATION (not independent confirmation)
Model: gemma4:26b (`5571076f…9d251`)
Benchmark: frozen_primary_v1 (`8c74a2af…a43b62`)
N: 18 tasks, 9 family clusters, 252 primary cells
Primary comparison: observer-aware topology vs dense semantic retrieval on 9 targeted tasks
Observer-aware targeted success: 9/9 (100.0%)
Dense targeted success: 6/9 (66.7%)
Absolute difference: 33.3%
95% family-cluster bootstrap CI: [0.0%, 66.7%]
Exact paired p: 0.250000
Observer-aware overall: 18/18 (100.0%)
Dense overall: 14/18 (77.8%)
Typed semantic overall: 15/18 (83.3%)
Query-blind overall: 4/18 (22.2%)
Native / no-seed / chimera: 18/18 / 16/18 / 13/18
Preregistered success criterion met: YES
Overall verdict: SUPPORTED

All 234 memory-bearing cells exposed four selected artifacts; zero exceeded 5000 characters. The primary interval touches zero and the reused, outcome-known benchmark makes this corrective rather than independent confirmation. See the statistical, seed, counterfactual, navigation, and v9-comparison reports for scoped interpretation.
