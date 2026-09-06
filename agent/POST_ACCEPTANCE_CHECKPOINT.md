# Post-acceptance safety and research-continuity checkpoint

Status: **ACCEPTED SUCCESSOR PRESERVED; INFRASTRUCTURE REPAIRED; NO NEW GENERATION**

## Preserved accepted result

The original accepted cycle remains byte-preserved in
`rebuild_reports/20260906T125305Z_92e7e913.json` with source SHA-256
`d37f48335f87c4c4370ea78d7719cf3a79aa26ef41b0911c81f448f7828d2cb1`.
It records local Ollama `qwen3-coder:latest`, digest
`06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca`.
The tracked active-release manifest points to that exact source.

An independent software replay on the previously used cases reproduced 1/3
public and 3/5 protected for the accepted selector, versus 0/3 and 1/5 for `v1`.
These are verification replays, not new blind experiments. Protected cases and
thresholds were unchanged.

## Infrastructure repairs

Activation is now exception-safe across an unhealthy worker, timeout, process
launch error, and release-manifest failure. An activation attempt is materialized
before pointer change. On failure, the supervisor attempts restoration, runs a
fresh-process verification of the restored version, and stores connected attempt,
failure, restoration, and recovery-evaluation IPs. Restoration or recovery
failure is explicit in the result rather than hidden behind the original error.

Public diagnostic loading and execution now occur in a time-bounded child process
for both the active implementation investigation and generated candidates. A
nonterminating selector is killed at the boundary. Child crash, launch error,
malformed output, invalid selection, and captured-output truncation become
structured rejection evidence; none can change the active pointer.

Future code and field labels use “public behavioral improvement check.” The
separate [evidence correction](EVIDENCE_CORRECTION_20260906.md) preserves the
accepted source's real limitation and leaves historical reports unchanged.

## Token budgeting and progressive context

`token_budget.py` reserves generation capacity and a separate checkpoint reserve
inside the fixed context window. It records estimated system, whole-prompt,
task-context, retrieved-material, and tool-result allocations. Ollama's
`prompt_eval_count` and `eval_count` are retained as actual provider usage when
available. The default counter is explicitly labelled
`conservative_utf8_bytes_div_3`; it is an estimate because Ollama does not expose
the exact model tokenizer through this workflow. An exact compatible tokenizer
can be injected later. The verification environment had no `tokenizers`,
`transformers`, `tiktoken`, or `sentencepiece` package installed, so no
model-compatible local tokenizer was silently assumed.

`research_state.py` maintains a versioned compact state with objective, task,
hypothesis, typed evidence, author definitions, corrections, decisions,
questions, versions, action status, artifacts, measurements, and next step.
Summaries carry hashes and paths to full originals and are explicitly marked as
not exact source recovery. Large tool output is preserved completely as a hashed
artifact while only a bounded preview enters active context.

Resume context is progressive: essential state, failures, corrections, and next
action are loaded first; artifact summaries are added within budget; requested
full sources are expanded only when they fit. Known artifact hashes suppress
unchanged material. If essential state itself cannot fit, resume fails explicitly
instead of silently truncating required information.

Actions have stable IDs. A completed action cannot be silently started again;
running or uncertain actions require reconciliation. Immutable checkpoints and a
hashed `LATEST.json` allow a fresh process to reconstruct state. This is bounded
session continuity, not a claim that an agent process remains active while stopped.

## Persistent next question

The following remains unresolved and is stored in the shared SToE field, linked
to the original proposal, generated implementation, observed failures, protected
improvement, activation, and evidence correction:

> Why did the proposed invalidation mechanism fail to materialize, and what
> evidence or interface change would let the agent investigate that discrepancy
> using SToE?

It is deliberately a question, not a prescribed next implementation.

## Verification

- agent suite: 23 tests, including timeout and launch-error restoration, failed
  recovery reporting, public nontermination/crash/malformed/invalid-output paths,
  budgeting, oversized artifact recovery, fresh-process resume, relevant failure
  and correction retention, hash deltas, and duplicate-action suppression;
- memory plugin: 9 tests, including real stdio integration;
- v9.1 experiment: 50 tests;
- v3 experiment: 21 tests;
- canonical seed validator: passed;
- accepted and `v1` evaluation replays: reproduced their original 1/3 + 3/5 and
  0/3 + 1/5 results respectively.

All new continuity tests use deterministic synthetic fixtures. They verify
software behavior, not live-model understanding or another self-development
event. No model generation was launched for this checkpoint.

## Commands

From `agent/`:

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
python -m unittest discover -s tests -v
python -m stoe_agent status
python -m stoe_agent replay --source owned_components/context_selector/versions/generated_20260906T125305Z_92e7e913.py
python -m stoe_agent checkpoint --reason "meaningful research boundary"
python -m stoe_agent resume --max-tokens 1800
python -m stoe_agent action --id research-step-001 --status running --description "bounded investigation"
python -m stoe_agent action --id research-step-001 --status completed --result-ref ARTIFACT_REF
```

Do not use `cycle` merely to reconstruct the accepted result; its original trace
and exact source are already preserved.
