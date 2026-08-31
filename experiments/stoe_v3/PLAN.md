# SToE v3 — Build Plan

Third experiment. v1 was the linear LLM-prompt chain (`_reference/v82/_v1_engine.py.txt`).
v82 was the second (`_reference/v82/*.py`). v3 starts fresh, using v82 as reference only.

The substrate is `seed/stoe_seed.json` — 36 information points, 113 edges. Permanent ontology.
Never wiped between experiments.

---

## Slice 0 — Falsification target (DONE)

**Target locked: B — multi-step puzzles with intentional dead-ends.**

Falsifies: does conservation + topology-aware navigation actually find solutions
that similarity-RAG misses, on problems where the path requires returning to a
previously-abandoned node?

**Benchmark: `benchmark/puzzles.json` — 26 puzzles, all with verified unique answers
(except CA-004 marked unverified pending hand-check).**

| Category | Count | What it tests |
|---|---|---|
| Logic grid | 10 | Constraint-satisfaction across N entities and M attribute axes. Backtracking forced when partial assignment violates a later constraint. |
| Cryptarithmetic | 4 | Letter-to-digit assignment. Each guess constrains others; contradictions force revisiting earlier guesses. |
| Knights & Knaves | 6 | Truth-teller / liar puzzles. Hypothesis chains hit contradictions; flipping an earlier assumption is required. |
| CSP word problems | 6 | Discrete state-space search (river crossings, jug puzzles, 4×4 Sudoku, 4-queens, Tower of Hanoi). |

**Difficulty mix:** 9 easy, 13 medium, 4 hard.

**Grader: `benchmark/grader.py` — deterministic, no LLM.** Extracts `FINAL_ANSWER:` marker
from LLM output, normalizes per format (`kv_pipe`, `letter_to_digit`, `kn_list`, `single_value`),
compares against expected. Order-insensitive within tolerance (e.g., KK answers).

The grader is LLM-free by design. v3's structural evaluator (slice 3) is also forbidden
from using LLM judgment, so keeping the benchmark grader deterministic preserves
separability between "did we get the right answer" and "did the engine evaluate well."

**Locked scoring protocol** (do not change after slice 1 starts):
- K = 5 seeds per puzzle per mode (run each puzzle five times with temperature variation)
- Two modes compared: `--context=topology` (v3's claim) vs `--context=similarity` (the v82 baseline)
- Per-puzzle metrics: solve rate (0–5), avg steps to solution, `failed_from` edge traversals

**Locked pass / fail thresholds** (do not change after results are in):
- **Strong pass** (paper 4 confirmed for this task class): topology solve rate ≥
  similarity solve rate + 15 percentage points, AND topology shows ≥ 3× more
  `failed_from` edge traversals than similarity.
- **Weak pass**: solve rates equal but topology uses fewer steps on average.
  Architecture works, doesn't yet matter for solve rate at this difficulty.
- **Falsification**: solve rates equal AND topology shows no extra dead-end traversal.
  The LLM is ignoring the topology context. Architecture is decorative.

**Open items deferred to after slice 1:**
- Optional: grow the benchmark to ~50 puzzles once the harness is running.

---

## Slice 1 — Minimum graph + monotonic guarantee (DONE)

**Checkpoint observation achieved:** "graph persists across runs, no endpoint can delete a node."

**Files:**
- `core/field.py` — `InformationField` class, ~440 LOC. Implements I1–I4 from PLAN.md invariants.
  - `add_point`, `connect`, `sever`, `add_failed` are the only mutators. No public deletion methods.
  - `get_adjacent`, `navigate_from`, `dead_end_query`, `path_query` are the topology-first reads.
  - `_search` is private; `cold_start_lookup` is the audited public wrapper.
  - `assert_no_deletion_methods()` is a static guard against future drift.
- `core/seed_loader.py` — `load_seed_if_empty(field)`. Idempotent. Preserves seed IDs.
- `tests/test_slice1.py` — 37 invariant checks. All passing.

**Verified:**
- Severed edges remain in storage; included only when `include_severed=True`.
- Ghost nodes from `add_failed` are first-class, found by `dead_end_query`.
- `navigate_from(depth=2)` returns the right multi-hop subgraph.
- `path_query` finds shortest paths with edge-type annotation.
- Field state survives `InformationField` recreation (persistence works).
- Seed (36 nodes, 113 edges) loads cleanly into empty field; second load is no-op.

**What is intentionally NOT yet present:**
- HTTP server. None needed until slice 4 comparison harness.
- Operators. They go in slice 2 — and will use field as their substrate.
- Score function. Forbidden until slice 3 (and even then, structural-only).
- Visualizer. Slice 5.



### Original spec (kept for reference)

Port from `_reference/v82/field.py`. Keep:
- typed edges (`generated_by`, `evolved_from`, `synergy_with`, `connected_to`, `failed_from`,
  `contradicts`, `evaluates`, `adjacent_to`, ...)
- `severed: true` instead of delete
- `add_point`, `connect`, `get_adjacent`, `navigate_from`, `dead_end_query`, `path_query`
- JSON persistence
- the failure-as-Ghost pattern (this is the cleanest part of v82)

Drop:
- `DELETE /api/points/<id>` and `wipe_field` HTTP endpoints. The conservation law has no exceptions.
  If you need cleanup, it's `severed=true`.
- `field.search()` as a primary path. Keep it as a private cold-start helper only.

Load `seed/stoe_seed.json` on first run. Persist to `field_data.json` (which lives outside
this repo / in `.gitignore` — the field is data, not code).

---

## Slice 2 — Graph-aware operators, not prompt verbs (DONE)

**Checkpoint observation achieved:** "operators sometimes can't fire and that's correct behavior."

**Files:**
- `core/llm.py` — `LLMClient` protocol, `OllamaClient`, `MockLLM`. Operators take an `LLMClient` argument; tests inject `MockLLM` to capture prompts.
- `core/operators.py` — `Operator` base class with declared `arity` and a `_fire` template method. Six concrete operators: `ConnectionOp` (`+`), `SynergyOp` (`×`), `RecursionOp` (`↻`), `DisruptionOp` (`!`), `RemovalOp` (`−`), `SummarizeOp` (`∑`).
- `tests/test_slice2.py` — 51 invariant checks covering preconditions, effects, prompt content, dedup, failure conservation. All passing.

**Verified:**
- Arity / existence preconditions short-circuit before any LLM call (zero `MockLLM.call` invocations on refused operators).
- `SynergyOp` prompt actually contains the depth-1 neighborhood of each input — the v82 gap (operator prompts ignored field state) is closed.
- `DisruptionOp` refuses when there are no `failed_from` / `contradicts` neighbors — closes the v1/v82 mode where `!` collapsed to a generic "challenge this".
- `RecursionOp` dedup: output that's near-identical (≥0.85 similarity) to the input or to any prior `evolved_from` chain element is refused. Refusal is **conserved as a Ghost node** with `failed_from` edge — nothing is silently dropped.
- `RemovalOp` makes zero LLM calls (it's pure graph logic).
- `SummarizeOp` requires `min_arity=3` — refuses on smaller inputs to avoid collapsing into a weaker operator.
- LLM transport errors become Ghost nodes via `field.add_failed`. Failure is structurally recorded.

**What's intentionally NOT yet present:**
- A driver/engine that picks operators or chains them. Slice 4 builds that.
- A scoring or evaluation function. Slice 3 — and structural-only.
- Any HTTP server or visualizer.



This is the v1/v82 inheritance v3 must break.

In v1 and v82, operators are prompt-templates: `+` means "Combine ideas:", `↻` means
"Evolve:", `!` means "Challenge:". An LLM responds to all of them with rephrasings of the
same training-data attractor. The operator name shapes the *register*, not the *content*.

### Original spec (kept for reference)

In v3, every operator must:
1. consume graph state (preconditions on the graph)
2. produce graph state (effects on the graph)

Concrete shape:

| Op | Precondition | Effect |
|----|--------------|--------|
| `+` (Connection) | requires 2 existing node IDs | LLM asked what ties them; new node with `connected_to` edges to both |
| `×` (Synergy) | requires 2 existing node IDs | LLM sees both nodes' content **and their existing neighborhoods**; new node with `synergy_with` edges |
| `↻` (Recursion) | requires 1 node ID; refuses if `evolved_from` neighborhood already contains a near-duplicate (cosine > 0.9) | new node, `evolved_from` edge |
| `!` (Disruption) | requires 1 node ID; pulls its `contradicts` and `failed_from` neighbors into prompt | "given these failed/contradicted attempts, what assumption was wrong?"; new node |
| `−` (Removal) | requires 1 node ID with ≥1 outgoing edge | severs lowest-weight edge; no new node |
| `∑` (Summarize) | requires ≥3 nodes in current session | autoinjective collapse over the session subgraph |

If a precondition isn't met, the operator is a no-op. This alone solves the v1/v82 problem
of every operator producing the same paragraph.

Drop `MODES` (`"🧠 Balanced": ["↻", "^", "!"]` etc.). Pre-scripted operator chains are
incompatible with graph-conditioned operators — operators may refuse to fire. Operator
selection emerges from graph state.

---

## Slice 3 — Structural evaluator, no LLM self-scoring (DONE)

**Checkpoint observation achieved:** "evaluator picks differently from LLM scoring on this run."

**Files:**
- `core/evaluator.py` — `Verdict` dataclass + `StructuralEvaluator` class. Pure stdlib, zero LLM imports.
- `tests/test_slice3.py` — 28 invariant checks. All passing.

**Four metrics, all derived from graph state alone:**

| Metric | Definition | Closes |
|---|---|---|
| Novelty | edges to nodes outside seed's depth-2 nbhd | "did this reach somewhere new?" |
| Coherence penalty | active `contradicts` edges incident to candidate | recorded tension, severable |
| Bridging | candidate's neighbours sit in ≥2 components of (G − candidate) | "did this close a previously-existing gap?" |
| Attractor distance | 1 − \|cand_tokens ∩ centroid\| / \|cand_tokens\| (asymmetric) | the v1/v82 collapse-to-attractor failure mode |

The asymmetric attractor distance — normalized by candidate-side, not by union — was a deliberate choice. Symmetric Jaccard saturates when the centroid is large (which it always is by mid-session), so every candidate ends up looking equally distant. The asymmetric form directly answers "what fraction of this candidate's vocabulary is new?", which is the question the v1/v82 evidence demands an answer to.

**Verdict structure:**
- A `Verdict` dataclass carries the four numbers + `composite_score()` for default ranking.
- When `write_verdict=True`, the verdict is added to the field as an `Evaluation` category node.
- An `evaluates` edge connects the verdict to the candidate. Edge weight = composite score (so a topology query later can find "which candidates received highest-weighted verdicts").
- Verdict metadata is machine-readable: `is_verdict`, `evaluates` (back-pointer), and the four metric values.

**Verified by tests:**
- Each metric independently behaves as specified.
- Severed `contradicts` edges no longer count toward coherence penalty.
- Bridging requires ≥2 neighbours in different components of (G − candidate); single-neighbour candidates can't bridge.
- Verdict is added as a node + edge, persists across field reload.
- LLM-saturated scoring (every candidate gets 25/25) ties — the structural evaluator picks the high-novelty/bridging candidate. **This is the slice 3 checkpoint observation.**
- `evaluator.py` does not import or reference any LLM backend (verified by source-text grep in the test).



### Original spec (kept for reference)

Replace v82's `score_step` (which is `_reference/v82/engine_v2.py:106`) entirely.

The verdict on a new node `n` is computed graph-locally:

- **Novelty:** count of edges to nodes outside the depth-2 neighborhood of the seed.
  (Did it reach somewhere new?)
- **Coherence:** count of `contradicts` edges to existing nodes. Higher = less coherent.
- **Bridging:** is `n` on a shortest path between two previously-disconnected components?
- **Attractor distance:** content distance from the centroid of existing nodes in the
  current session. Are we drifting back to the LLM's prior?

The verdict is itself a node, connected by an `evaluates` edge to `n`. Verdict content
is the structural facts, not a 1–5 number.

No LLM in the scoring loop. The "best idea" picker stops being argmax over saturated noise
and starts being a graph property.

---

## Slice 4 — Comparison harness (DONE)

**Checkpoint observation achieved:** "topology run vs similarity run produce measurably different subgraphs on benchmark X."

In the slice-4 self-test, on a synthetic backtrack-required puzzle with a deterministic MockLLM that uses `[failed_from]` context productively:

```
topology  solve rate: 100%   (2/2)   failed_from in context (cumulative): 2
similarity solve rate: 0%    (0/2)   failed_from in context (cumulative): 0
delta: +100pp     verdict: strong_pass
```

The divergence is mechanical, not emergent. The topology context builder surfaces `failed_from` neighbors; the similarity builder doesn't. With an LLM that uses that information, the modes produce different solve rates. With an LLM that ignores it (e.g., a real model that doesn't notice the `[failed_from]` tag), both modes will perform identically — and that's the falsification path.

**Files:**
- `harness/context.py` — `TopologyContext` (uses `navigate_from`, surfaces `[failed_from]` and `[contradicts]` tags) and `SimilarityContext` (uses `cold_start_lookup`, baseline).
- `harness/runner.py` — `BenchmarkRunner` with multi-attempt retry, failure conservation, structural verdict per attempt, JSON-serializable `BenchmarkReport`.
- `harness/cli.py` — `python -m harness.cli --mode {topology|similarity|both}` with all the protocol locks from PLAN.md (`--seeds 5`, `--max-attempts 3`).
- `tests/test_slice4.py` — 31 invariant checks. All passing.

**Verified by tests:**
- `TopologyContext` output contains `[failed_from]` edge tags and the failure-reason content; `SimilarityContext` output contains `[sim]` tags and never `[failed_from]`.
- On the synthetic puzzle: topology mode solves 100%, similarity mode 0%, delta is +100pp.
- `failed_from_neighbors_in_context` is exactly 0 on attempt 1 (no failure exists yet) and ≥1 on attempt 2 in topology mode (the just-conserved failure is reachable). Similarity mode is 0 throughout.
- LLM transport failure during a run is conserved as a Ghost via `field.add_failed`; the run continues, and a subsequent successful attempt is recorded normally.
- `BenchmarkReport.to_json()` round-trips: header / aggregate / runs sections present, mode preserved, solve rate consistent with in-memory aggregate.
- Each attempt carries a structural verdict (the slice-3 evaluator runs per-attempt, attached to the report).
- `diff_reports` verdict logic correctly distinguishes `strong_pass` (significant pp gap + failed_from advantage), `falsification` (zero gap + no failed_from divergence), and `weak_pass` (delta but no overwhelming failed_from differential).

**What's still required to actually run paper 4's experiment:**
- A real LLM behind `OllamaClient`. The CLI is wired up; just `python -m harness.cli --mode both --model llama3` against a running Ollama.
- Reasonable wall-time budget. Full benchmark = 26 puzzles × 5 seeds × 2 modes × ≤3 attempts = ≤780 LLM calls. Per-puzzle timeouts can cap this.
- Interpretation discipline: a "strong_pass" on this benchmark confirms paper 4's prediction *for this task class*. Other task classes (the slice-0 alternative was anti-attractor scoring on idea generation) would need separate harnesses.

**What's intentionally NOT yet present:**
- Slice 5 (visualizer). Deferred per PLAN ordering. The JSON reports in `runs/*.json` are the only output for now; cytoscape comes when there's something worth visualizing.



### Original spec (kept for reference)

CLI flag: `--context=topology` vs `--context=similarity`.
Same seed, same operator chain, two field copies, persist both.
Diff:
- distinct subgraph regions touched
- attractor distance per step
- dead-end visits
- evaluator verdicts (novelty/coherence/bridging)

This is the actual experiment. Until this exists, every prior slice is unvalidated.

---

## Slice 5 — Visualizer (last, deferred)

v82 spent ~3.4k lines on `static/index.html`. Don't repeat that until slice 4 produces
something worth looking at. A 100-line `cytoscape.js` page reading `field_data.json` is
enough until then.

---

## Ordering discipline

Don't start slice N+1 until slice N produces an observation:

- Slice 1 → "graph persists across runs, no endpoint can delete a node."
- Slice 2 → "operators sometimes can't fire and that's correct behavior."
- Slice 3 → "evaluator picks differently from LLM scoring on this run."
- Slice 4 → "topology run vs similarity run produce measurably different subgraphs on benchmark X."

Each slice is a checkpoint where you stop and reassess.

---

## Invariants v3 must not violate

1. **No node deletion.** Edges can be `severed: true`. Nodes never disappear.
2. **No LLM self-scoring.** Evaluation is graph-local or it doesn't exist.
3. **Operators are graph functions.** They have preconditions on graph state and
   effects on graph state. Prompt templates are an implementation detail of an
   operator, not the operator itself.
4. **Context retrieval is topology-first.** `_field_context` walks edges from the
   current node. Cold-start is the only exception.
5. **The seed is permanent.** `seed/stoe_seed.json` is never wiped. Load on first
   run, ignore on subsequent runs (it's already in the field).

---

## What `_reference/` is and isn't

`_reference/v82/` — read-only. Port idioms from `field.py` and the registry pattern
from `operators.py`. **Do not port** `engine_v2.py` (linear loop), `score_step`,
`_field_context`, `MODES`, or any HTTP DELETE endpoint.

`_reference/papers/` — five papers in plain text. Paper 4 (`04_architectural_gap.txt`)
is the spec v3 implements. Paper 5 (`05_three_laws.txt`) is the law statement.
The others are background.

`_reference/v82/_v1_engine.py.txt` and `_v1_session_outputs.txt` — the first experiment.
Read them when designing slice 2 — they are the strongest evidence for why operators
must be graph-aware. The session outputs show three different seeds collapsing to the
same concept stew because the operators were prompt-templates.
