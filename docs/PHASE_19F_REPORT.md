# Phase 19F — Improvement Gate Report

## Status

`IMPLEMENTED_UNVERIFIED`

Phase 19F adds the final model-improvement evidence gate on top of the merged Phase 19E controlled-SFT
governance boundary.

## Implemented

- frozen, SHA-256-locked improvement policy;
- per-dimension meaningful-improvement and tolerated-regression thresholds;
- paired baseline/candidate confidence intervals;
- separate overall, held-out, and OOD evaluation slices;
- minimum paired-case evidence requirement;
- Phase 19E spec/receipt/artifact candidate-chain verification;
- frozen evaluation-suite, regression-suite, evaluator, case, and candidate identity checks;
- benchmark-contamination rejection;
- Phase 19C learning-integrity gating;
- critical-regression zero tolerance;
- meaningful non-critical regression handling using threshold + confidence rather than tiny-delta panic;
- explicit `PROMOTE`, `REJECT`, `ROLLBACK`, and `INSUFFICIENT_EVIDENCE` decisions;
- no runtime release execution authority.

## Promotion rule

Promotion evidence requires a verified real trained candidate, like-for-like clean evaluation evidence,
no critical or meaningful regression, and at least one confidence-supported meaningful cognitive
improvement. A candidate that is merely "not detectably worse" is not automatically called improved.

## Rollback rule

Rollback is a recommendation only for an already-active candidate when regression or blocking integrity
evidence is strong enough to justify it. The gate does not switch model weights or mutate runtime state.

## Current evidence state

The repository does not contain evidence that a real external Phase 19E training run was executed or
that a real trained candidate was evaluated. The visible Phase 19F smoke therefore intentionally returns
`INSUFFICIENT_EVIDENCE` while proving that the gate refuses to fabricate a promotion.

## Not claimed

This package does not claim:

- a GPU/SFT training run happened;
- trained Luna weights exist in the repository;
- a real post-training benchmark run happened;
- Luna improved on any cognitive dimension;
- a model was promoted or rolled back;
- runtime release authority was granted.
