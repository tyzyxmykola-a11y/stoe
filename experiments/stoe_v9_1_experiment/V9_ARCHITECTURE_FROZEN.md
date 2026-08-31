# V9 Architecture

## Narrow hypothesis

Conserved failed artifacts become useful when topology identifies a structurally justified candidate region and an explicit observer state ranks candidates according to current goals and changed constraints. This is narrower than claiming universal graph-memory superiority.

## Information flow

`CurrentObserverStateIP -> structural traversal -> eligible candidate region -> observer-aware ranking -> fixed artifact budget -> model context`

The observer state contains the current question, goal, active constraints, changed constraints, recent evidence, and current reasoning position. State changes and evaluations are first-class IPs.

## Canonical SToE bootstrap field

Initialization verifies and loads the byte-preserved canonical `data/stoe_seed.json` into the same `InformationGraph` as runtime reasoning. Its 36 core IPs retain canonical IDs in metadata and use namespaced field refs such as `SEED_3bd7d9b844ed469b`; its 113 native typed relations are preserved. The hidden fold container `STOE_Seed_IP` stores a lossless copy that unfolds to the exact source structure.

Typed bridges connect observer, failure, state-change, and evaluation runtime IPs to structurally relevant core concepts. They provide runtime→seed and reverse seed→runtime traversal without a seed-origin score bonus. The seed is never concatenated wholesale into a prompt: seed nodes compete under the same reachability, eligibility, rank, four-artifact, and character limits.

## Separation of responsibilities

- `Graph`: canonical seed and runtime nodes in one field, directed typed edges, origin, and eligibility metadata.
- `CandidateRegionBuilder`: bounded structural traversal only; it never searches the full graph semantically.
- `QueryBlindNavigator`: v8-style locality baseline using structural path score plus a fixed `0.50` bonus for the recorded current-reasoning IP. The bonus is independent of task text, node outcome, and answer, preserving the legacy recency/locality bias without leaking observer semantics.
- `ObserverAwareNavigator`: combines structural, goal, state-change, provenance, failure, distance, redundancy, and stale-locality components inside the candidate region.
- `Retrievers`: BM25 and dense semantic baselines over the same stored eligible artifacts.
- `Runner`: identical prompts/settings/budgets, schema enforcement, traces, scoring, and pilot counterfactuals.

## Current state and change paths

Targeted tasks explicitly encode:

`CurrentObserverStateIP --contains_change--> StateChangeIP --invalidates--> ConstraintIP <--rejected_by-- CandidateIP`

Traversing the last edge from constraint to candidate is recorded as incoming `rejected_by`, meaning “find hypotheses previously rejected because of this constraint.” It is not treated as a symmetric edge.

## EvaluationIPs

Each task contains a prior evaluation of the recent reasoning branch. The EvaluationIP is reachable and eligible at the later measured stage, allowing evaluation evidence to affect navigation and reasoning. V9 makes no claim that autonomous evaluation generation is solved.

## Identity boundary

Runtime references use `IP_00001` handles; seed references use `SEED_<canonical-id>` while retaining the untouched canonical ID. Model-visible context separates `MEMORY_REF` from `SEMANTIC_CONTENT`. Exact scoring rejects UUID-, `IP_`-, and `SEED_`-shaped answers and never treats memory references as task answers.
