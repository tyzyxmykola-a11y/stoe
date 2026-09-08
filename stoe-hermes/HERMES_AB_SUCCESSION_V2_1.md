# Hermes A/B Succession v2.1

Status: **FAILED CONSERVED — NO EXECUTION — NOT ACTIVATED**

Stable action: `self-code-cycle:hermes-ab-v2-1:split-model-deduplicate-context` (closed; never retry)

The approved fixed-table correction worked. Gemma returned the complete fixed plan on its first call, using 4,964 prompt and 307 output tokens; no formatting-repair child was needed. Raw SHA-256: `f377c90dafa77cd2a813e2616db084da9f874f6819b06aded32edad1f7cadf30`.

Qwen Coder then made its one authorized call and returned a complete, syntactically parseable inert patch. It retained all existing deduplication/connection behavior and proposed explicit `canonical_payloads` and `collapsed_duplicates` header counts while preserving the legacy fields. Prompt/output tokens were 744/773. Raw SHA-256: `f899b1f984031a0addf59ff1429816451f1aacbe451fe807c4cc87eaa5f3e1fa`; reconstructable candidate SHA-256: `fc16fd51028967cd9972332ec671f8a3bb0c72815343a495df502cafd5d052ff`.

The trusted validator rejected the candidate before writing or execution because it categorically forbids `ast.Raise`. The proposed `raise ValueError` was not newly introduced: it is byte-equivalent behavior inherited from the trusted parent, which already rejects negative `max_chars`. Thus v2.1 discovered a validator mismatch: every behavior-preserving complete replacement inherits syntax the validator forbids. Removing the guard merely to pass validation would be a regression.

No Qwen retry, Gemma review, candidate application, test execution of generated Python, or activation occurred. The B target still hashes to its parent `b1d11d98c8797c11fcd5ff7f8e337764580ca8c4a6c9ca66a32c336158041155`. Hermes A remains unchanged at `bb924730743cc05934bf0dfd188abdfdb46c03c2`.

Actual retrieved-context canonicalization for the plan reduced the conservative estimate from 5,527 to 3,438 tokens while retaining 10 canonical payloads and 10 connection records; no duplicate payload nodes happened to occur in this retrieval. This is prompt compaction, not candidate-performance evidence.

Docker client 29.5.3 was present but the Linux daemon was unavailable. Because validation failed, neither the container path nor the approved trusted-inspection alternative executed generated code.

SToE Memory conserved the objective, v2 correction, successful plan, exact Qwen failure, diagnosis, evaluation, decision, successor state, and next action with `correction_of`, `successor`, `generated_by`, `diagnoses`, `evaluates`, `depends_on`, `contains`, and `evolved_from` relations. Raw artifacts remain external by path/hash.

Deterministic Hermes A/B tests pass 18/18, including the exact inherited-`Raise` reproduction. Regression suites also pass: Agent 77/77, v9.1 50/50, v3 21/21, and SToE Memory 9/9. Historical v1/v2 artifacts remain unchanged.

The exact approval question is whether v2.2 may modify the protected validator to compare candidate syntax with the trusted parent and grandfather only identical inherited forbidden nodes, while continuing to reject every newly introduced `Raise`. Until approved, v2.1 remains closed and the inert proposal remains rejected.
