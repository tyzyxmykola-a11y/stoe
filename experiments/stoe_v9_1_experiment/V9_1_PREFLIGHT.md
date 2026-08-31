# V9.1 Final Preflight

Status: **PASS**

V9.1 is a corrective replication. No primary generation call had occurred when this record was written.

| Gate | Result |
|---|---|
| full_test_suite_50_of_50 | PASS |
| canonical_seed_hash | PASS |
| benchmark_hash | PASS |
| seed_byte_identical_to_v9 | PASS |
| benchmark_byte_identical_to_v9 | PASS |
| navigator_byte_identical_to_v9 | PASS |
| graph_seed_task_construction_identical | PASS |
| condition_list_exact | PASS |
| retrieval_k_exact | PASS |
| memory_budget_exact | PASS |
| generation_parameters_exact | PASS |
| dry_run_252_cells | PASS |
| dry_run_zero_exposure_violations | PASS |
| dry_run_zero_budget_violations | PASS |
| dry_run_zero_selection_mismatches | PASS |
| dry_run_no_generation_calls | PASS |
| generation_model_digest_exact | PASS |
| embedding_model_digest_exact | PASS |
| manifest_all_hashes_match | PASS |
| frozen_components_byte_identical | PASS |
| no_partial_primary_result | PASS |
| fresh_primary_state | PASS |

## Recorded details

- Tests: 50 passed, 0 failed
- Ollama: 0.32.13
- Generation digest: `5571076f3d70050487b26b341705799e0ab29b808164f90d20d4cf84f699d251`
- Embedding digest: `ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d`
- Pre-primary manifest: `adfbbddf57717c5c4266ac7b16b225bd57f4c398379a4b1384da3e7c982dfd98` (41 files)
- Manifest failures: []
- Dry run: 252 cells; zero exposure violations; zero budget violations; zero frozen-selection mismatches; zero generation calls.

If this file says FAIL, primary generation is forbidden.
