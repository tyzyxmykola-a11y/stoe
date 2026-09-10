# StoeCoder

SToE Coder is the standalone development line for the local SToE development executive.

This root-level project begins from the qualified SToE Coder v1 runtime that was first integrated into `engine/v7` with the Information Field Navigator. The Navigator baseline remains in `engine/v7` and is intentionally left untouched by future StoeCoder development.

## Baseline

The initial standalone development baseline preserves the trusted Coder executive, operator-intent helper, deterministic Coder tests, and Python requirements from the merged v1 implementation.

Current capabilities include local Ollama workers, isolated candidate worktrees, deterministic verification, independent review, SToE Memory provenance, explicit model commit/push authorization, and operator Git controls for Diff, Commit, Pull, Push, and Merge to main.

## Development rule

New SToE Coder development belongs under this `StoeCoder/` tree. Do not modify `engine/v7` merely to evolve StoeCoder; that directory is now the preserved Navigator integration baseline.

The next planned self-hosted work is configurable persistent worker roles, editable role contracts, Auto/manual Ollama model selection, role enable/disable checkboxes, task-start role logging, distinct task-finished metrics, and a stage-based progress indicator.
