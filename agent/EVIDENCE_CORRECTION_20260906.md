# Evidence-label correction for accepted cycle 20260906T125305Z_92e7e913

This note supplements, and does not rewrite, the original JSON report at
`rebuild_reports/20260906T125305Z_92e7e913.json`.

The historical field name `public_feasibility` and its “mechanism check” wording
should be read as **public behavioral improvement check**. That check established
only that the generated selector improved disclosed outputs from 0/3 to 1/3
without regressing a disclosed pass. Because the model saw those cases, the check
was never sufficient for adoption and provides no causal identification of the
model's proposed mechanism.

Three propositions must remain separate:

1. Observed behavior: the candidate selected the required evaluation IP on one
   disclosed case and later improved the protected replay from 1/5 to 3/5.
2. Model explanation: the proposal attributed misses partly to absent invalidation
   and state-change prioritization.
3. Implemented mechanism: the source added fixed boosts for supported outcomes
   and evaluation-like kinds. It did not implement reliable changed-constraint
   reactivation, and both protected reactivation cases remained failed.

The correction is also stored as IP
`REBUILD_post_acceptance_correction_public_evidence_label_correction_be1bcc`.
It is connected in the persistent field to the generated implementation, the
historical public behavioral result, and the protected evaluation. The next
question IP is
`REBUILD_post_acceptance_question_next_research_question_bb57bd`.

This correction changes interpretation and future terminology only. It does not
change the original report, selector, public cases, protected cases, scores,
acceptance threshold, or activation decision.
