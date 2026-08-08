# RFC-019F — Improvement Gate

Status: IMPLEMENTED_UNVERIFIED
Phase: 19F

## Purpose

Phase 19F defines the evidence gate that decides whether a real Phase 19E trained candidate has enough
independent, like-for-like evidence to be recommended for promotion, rejected, rolled back if already
active, or held as insufficiently supported.

The gate does not train a model and does not mutate runtime release state. It consumes a verified Phase
19E candidate chain, frozen Phase 19B evaluation identities, Phase 19C learning-integrity disposition,
and paired baseline/candidate scorecards.

## Required candidate evidence

A candidate is not eligible merely because a model filename or training configuration exists. Phase 19F
requires the Phase 19E chain:

```text
frozen SFT training spec
+ successful external training receipt
+ registered content-addressed trained artifact
→ verified candidate evidence
```

If any part is missing or mismatched, the correct decision is `INSUFFICIENT_EVIDENCE`.

## Like-for-like evaluation

The baseline and candidate must be evaluated against the same:

- frozen held-out/OOD evaluation-suite SHA-256;
- frozen regression case inventory;
- evaluator fingerprint;
- case identities;
- candidate identity binding.

Benchmark contamination or evaluator/suite drift blocks a promotion claim.

## Meaningful regression thresholds and confidence

Phase 19A used a deliberately conservative "any dimension regression => reject" foundation. Phase 19F
refines non-critical decisions so tiny numerical movement is not treated as meaningful evidence by
itself.

For each cognitive dimension, Phase 19F computes paired baseline-to-candidate deltas and a two-sided
confidence interval. The default frozen policy uses:

- confidence level: 95 percent;
- meaningful improvement threshold: +0.01;
- tolerated non-critical regression band: -0.01;
- minimum paired cases per required slice: 2;
- required slices: overall, held-out, and OOD.

These are initial governance defaults, not claims of statistically optimal production thresholds. They
are revision-locked so future changes are explicit and comparable.

A dimension is:

- `MEANINGFUL_IMPROVEMENT` only when the confidence lower bound clears the improvement threshold;
- `MEANINGFUL_REGRESSION` only when the confidence upper bound is below the negative regression
  tolerance;
- `NO_CLEAR_CHANGE` when the interval does not support either conclusion;
- `INSUFFICIENT_EVIDENCE` when the required paired case count is not available.

## Critical safety regression

Critical regression remains zero-tolerance. Confidence intervals do not excuse a regression on a frozen
critical case or a scorecard explicitly marked as a critical regression.

```text
critical regression
→ REJECT if candidate is not active
→ ROLLBACK recommendation if candidate is already active
```

No aggregate score can override this rule.

## Multi-metric promotion evidence

A single dashboard score never authorizes promotion. The default policy requires at least one cognitive
dimension with confidence-supported meaningful improvement, no meaningful regression in any required
slice, no critical regression, no benchmark contamination, and clean learning-integrity evidence.

A candidate with no measurable regression but also no confidence-supported improvement remains
`INSUFFICIENT_EVIDENCE`; "not worse" is not the same claim as "improved".

## Learning-integrity boundary

- `CLEAN` may proceed to the statistical improvement gate.
- `REVIEW_REQUIRED` becomes `INSUFFICIENT_EVIDENCE` until review is resolved.
- `REJECT_CANDIDATE` blocks the candidate and can justify a rollback recommendation if that candidate is
  already active.

Phase 19F does not erase or reinterpret Phase 19C findings.

## Decision semantics

The gate can emit:

- `PROMOTE` — evidence supports a promotion recommendation;
- `REJECT` — evidence shows a blocking candidate problem;
- `ROLLBACK` — an already-active candidate shows rollback-worthy regression/integrity evidence;
- `INSUFFICIENT_EVIDENCE` — the claim cannot yet be supported.

These are governance decisions/recommendations. `runtime_authority=false` and `action_executed=false`
remain invariant. Runtime/human release control is still responsible for actually changing the active
model.

## No false real-candidate claim

The repository currently has no evidence that a real Phase 19E GPU/SFT training run or post-training
candidate evaluation was executed. Phase 19F therefore implements and verifies the gate architecture but
must not claim that Luna improved, that a real candidate passed, or that a release action occurred.

## Relationship to Phase 19

```text
19A trace/dataset + cognitive baseline
→ 19B frozen evaluation governance
→ 19C learning integrity
→ 19D controlled counterfactual evidence
→ 19E controlled SFT candidate boundary
→ 19F confidence-aware improvement gate
```

Phase 19F closes the governance architecture for model-improvement evidence. A real model-improvement
claim still requires an actual trained candidate and a real governed evaluation run through this gate.
