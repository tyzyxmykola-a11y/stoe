# V9.1 Navigation Postmortem

Observer-aware and query-blind selected different contexts on 18/18 tasks; those changes improved 14, harmed 0, and left binary correctness unchanged on 4. Observer-aware scored 9/9 targeted versus query-blind 0/9; dense scored 6/9 and BM25 5/9.

| Task | Subset | Observer | Query-blind | Dense | BM25 | No seed | Chimera | Focal rank | Observer selected refs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| primary-canyon-supply | topology_targeted | ✓ | ✗ | ✓ | ✗ | ✓ | ✓ | 1 | IP_00002, IP_00010, SEED_8be9448ca5ee4525, IP_00004 |
| primary-planning-direct | negative_control | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | 3 | IP_00006, SEED_05d9d98dddc9034a, IP_00002, SEED_ba07b5ebd68445d4 |
| primary-decoder-revival | topology_targeted | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | 1 | IP_00002, IP_00010, SEED_8be9448ca5ee4525, IP_00004 |
| primary-debug-recent | negative_control | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 1 | IP_00005, IP_00006, SEED_05d9d98dddc9034a, SEED_ba07b5ebd68445d4 |
| primary-orchard-layout | topology_targeted | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | 1 | IP_00002, IP_00010, SEED_8be9448ca5ee4525, IP_00004 |
| primary-constraint-direct | negative_control | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | 3 | IP_00006, SEED_05d9d98dddc9034a, IP_00002, SEED_ba07b5ebd68445d4 |
| primary-harbor-rule | topology_targeted | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | 1 | IP_00002, IP_00010, SEED_8be9448ca5ee4525, IP_00004 |
| primary-legal-recent | negative_control | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 1 | IP_00005, IP_00006, SEED_05d9d98dddc9034a, SEED_ba07b5ebd68445d4 |
| primary-enzyme-control | topology_targeted | ✓ | ✗ | ✗ | ✗ | ✓ | ✓ | 1 | IP_00002, IP_00010, SEED_8be9448ca5ee4525, IP_00004 |
| primary-science-direct | negative_control | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | 2 | IP_00006, IP_00002, SEED_05d9d98dddc9034a, SEED_ba07b5ebd68445d4 |
| primary-vector-patch | topology_targeted | ✓ | ✗ | ✓ | ✗ | ✓ | ✓ | 2 | IP_00010, IP_00002, SEED_8be9448ca5ee4525, IP_00004 |
| primary-code-recent | negative_control | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 1 | IP_00005, IP_00006, SEED_05d9d98dddc9034a, SEED_ba07b5ebd68445d4 |
| primary-symbol-rule | topology_targeted | ✓ | ✗ | ✓ | ✗ | ✓ | ✓ | 1 | IP_00002, IP_00010, SEED_8be9448ca5ee4525, IP_00004 |
| primary-hidden-direct | negative_control | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | 3 | IP_00006, SEED_05d9d98dddc9034a, IP_00002, SEED_ba07b5ebd68445d4 |
| primary-witness-chain | topology_targeted | ✓ | ✗ | ✗ | ✓ | ✓ | ✓ | 1 | IP_00002, IP_00010, SEED_8be9448ca5ee4525, IP_00004 |
| primary-contradiction-recent | negative_control | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | 1 | IP_00005, IP_00006, SEED_05d9d98dddc9034a, SEED_ba07b5ebd68445d4 |
| primary-robot-capability | topology_targeted | ✓ | ✗ | ✗ | ✓ | ✓ | ✓ | 1 | IP_00002, IP_00010, SEED_8be9448ca5ee4525, IP_00004 |
| primary-agent-direct | negative_control | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | 3 | IP_00006, SEED_05d9d98dddc9034a, IP_00002, SEED_ba07b5ebd68445d4 |

The untyped condition scored 18/18; it inherits the typed navigator's selected plan, so this compares relation labels shown to the LLM, not whether typed semantics matter during navigation. WITHOUT_STATE_CHANGE_SIGNAL scored 18/18; `invalidates` and `rejected_by` can still affect structural/provenance terms, so this does not remove all state-change structure.
