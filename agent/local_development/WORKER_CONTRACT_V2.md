# SToE Local Worker Contract v2

Return exactly: `status`, `decision`, `evidence`, `risks`, `next_action`.

- `status`: `success`, `failure`, or `deferred`
- `decision`: at most 320 characters
- `evidence`: at most 4 items, each at most 180 characters
- `risks`: at most 3 items, each at most 160 characters
- `next_action`: at most 240 characters

Success requires evidence. Failure or deferred status requires risks, and
`risks[0]` is the exact blocking condition.

Do not repeat task ID, model, role, hashes, resource metrics, artifact paths,
tests, confidence, or other supervisor-known metadata. Detailed work belongs in
a separate artifact. Conserve information; do not carry unnecessary information
forward.
