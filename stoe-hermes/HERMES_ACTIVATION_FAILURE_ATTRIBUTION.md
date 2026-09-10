# Hermes activation failure attribution

Status: **INFRASTRUCTURE FAILURE IDENTIFIED; HERMES A REMAINS ACTIVE; NO PROMOTION**

The exact candidate remained `fc16fd51028967cd9972332ec671f8a3bb0c72815343a495df502cafd5d052ff` over trusted parent `b1d11d98c8797c11fcd5ff7f8e337764580ca8c4a6c9ca66a32c336158041155`. No model call, candidate edit, validator change, or production-pointer switch occurred in this diagnostic checkpoint.

## Instrumentation correction

`run_bounded_preserved` retains separate stdout and stderr artifacts while preserving the existing 60-second, 300,000-byte, 2 GB RAM, 12-process, and 250 MB disk-growth limits used by the activated-layout suite. It records original and preserved byte counts, stream hashes, and explicit truncation flags. Preserved output never exceeds the configured combined cap.

## Reproduction and exact attribution

The candidate layout was copied into a disposable release state. Its pointer selected `hermes-b-fc16fd510289`; the immutable root replay parent remained the parent hash; the candidate artifact remained the candidate hash. Production stayed on Hermes A before and after every run.

With the exact minimal environment from the failed promotion, 4 of 40 tests errored:

- `test_clean_stale_and_dirty_parent_checks`
- `test_divergent_parent_is_rejected`
- `test_fixture_candidate_creation_and_active_bytes_unchanged`
- `test_interrupted_build_is_not_silently_reused`

Every error was `FileNotFoundError: [WinError 2]` at `subprocess.run(["git", ...])`. The environment contained only the Hermes Python `Scripts` directory in `PATH`; Git was absent. The candidate renderer, release resolver, parent-relative validation, protected behavior, output bounds, and other tests passed.

The complete untruncated failing stderr is stored locally at `agent/runtime/hermes_activation_diagnostic_v2/artifacts/activated_minimal_env.stderr.txt`, SHA-256 `1f1ffc104fd6c09b81613b211ec2bc753ce4385068af2836e847082d8656b575` (14,152 bytes). Stdout was empty.

## Infrastructure-only correction

Trusted supervisor test environments now add only explicitly required tool directories. For this suite, `git` resolved to `C:\Program Files\Git\cmd\git.exe`; candidate execution receives no general inherited `PATH` expansion. With that correction, the identical disposable candidate layout passed 40/40. Its complete untruncated stderr is stored locally at `agent/runtime/hermes_activation_diagnostic_v3/artifacts/activated_git_qualified.stderr.txt`, SHA-256 `61cf448538c5596d8a5ad724d6d12ba569e5c84306b03621273bb418824a01b5` (6,390 bytes).

## Decision

The activation failure is attributed to the protected health harness, not candidate behavior. The candidate remains qualified but inactive. The standing policy remains `inactive_after_failed_activation`; this checkpoint does not attempt promotion.

Exact next action: construct a new protected promotion action using the preserved-output runner and explicit trusted Git test dependency, then qualify it without regenerating or modifying the candidate.
