# SToE Local Development Architecture v2

ChatGPT is the SToE architect. Codex is the thin repository supervisor and
integrator. Local Ollama agents are the default development workers.
Deterministic tools are the verification authority. SToE Memory is the
persistent development field, and `stoe-reasoning` is the reasoning protocol.

Default flow:

`observer -> bounded SToE retrieval -> local planner -> local coder artifact -> local reviewer -> deterministic verification -> SToE conservation -> next observer`

Trusted local supervisor code loads `WORKER_CONTRACT_V2.md`, exactly one
role-specific instruction artifact, and only the bounded SToE context selected
for that action. Codex references this architecture by version; it does not
reread or relay the instruction files on every cycle. Local Ollama workers
receive those canonical artifacts from the supervisor.

Every instruction artifact is hashed with SHA-256, and the exact hashes used by
an action are connected to its `WorkerActionIP`. A coding worker returns source
or patch content only through a separately bounded, inert candidate-artifact
channel. Its five-field response remains control information and cannot apply
the artifact or control verification.

Conservation does not imply injection into active context. Use the smallest
adequate local capability, preserve interactive PC resource reserve, keep
routine work local, and attempt only the configured bounded local recovery
before escalation. Escalate architecture, unresolved trust questions, material
local-agent disagreement, or failures that remain unresolved after that bound
to ChatGPT.
