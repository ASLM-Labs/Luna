# RFC-019C — Learning Integrity

Status: IMPLEMENTED_UNVERIFIED
Phase: 19C

## Purpose

Phase 19C adds deterministic integrity checks around the Phase 19 learning lab. It is designed to
catch cases where apparent improvement can be explained by shortcuts, benchmark/evaluator exposure,
proxy optimization, confirmation bias, self-confirmation, or overfitting rather than robust behavior.

This phase does not execute training, reward optimization, counterfactual replay, or candidate
promotion. It observes governed artifacts and reports integrity findings only.

## Frozen learning-integrity policy

`LearningIntegrityPolicy` locks the initial integrity thresholds and requirements with a semantic
revision and SHA-256 digest. The default revision freezes:

- maximum train-to-held-out gap;
- maximum train-to-OOD gap;
- maximum matched shortcut-slice gap;
- maximum primary/independent evaluator disagreement;
- benchmark identity exposure blocking;
- evaluator identity exposure blocking;
- independent claim-evidence requirement;
- zero-tolerance handling for critical governed regressions.

Changing those values changes the policy digest. Threshold changes therefore require an explicit new
policy revision rather than silent tuning around a candidate.

## Shortcut learning

A `ShortcutSliceProbe` compares matched observational slices where a suspected shortcut is present or
absent. A gap beyond the frozen policy threshold is surfaced as `SHORTCUT_LEARNING` risk.

This is deliberately not called counterfactual evidence. Phase 19C can identify an observational
shortcut dependency signal, but it cannot claim that removing the shortcut caused the outcome.
Controlled replay/sandbox counterfactual evidence remains Phase 19D work.

## Benchmark and evaluator gaming

`LearningExposureRecord` captures explicit learning-time exposure to frozen benchmark case identities,
evaluator fingerprints, and optimization metric identities. Exposure to a Phase 19B frozen evaluation
case or governed evaluator is blocking evidence for benchmark/evaluator gaming risk.

`EvaluatorAgreementProbe` additionally compares the governed evaluator with a distinct independently
verified evaluator. Excessive disagreement is surfaced as evaluator-gaming/evaluator-dependence risk.
A candidate cannot declare the same evaluator to be its independent cross-check.

These checks complement Phase 19B benchmark contamination. Contamination checks dataset overlap;
Phase 19C also checks whether benchmark/evaluator identities themselves were exposed to optimization.

## Proxy and specification optimization

A proxy metric can improve while governed cognitive evaluation regresses. Phase 19C surfaces that
pattern as `PROXY_SPECIFICATION_OPTIMIZATION` instead of treating the proxy gain as generic
improvement.

When a critical regression is present and the frozen policy has zero tolerance enabled, the integrity
finding is blocking. Non-critical proxy/regression divergence requires review. Final statistical
promotion thresholds and confidence intervals remain Phase 19F responsibility.

## Confirmation bias and self-confirmation

`ClaimEvidenceReview` records supporting, contradicting, and actually considered evidence IDs.
Contradictory evidence that exists but is not considered is surfaced as `CONFIRMATION_BIAS`.

Evidence also carries an explicit origin and candidate-independence flag. Candidate output can never
mark itself independent. If a claim has no independent supporting evidence, the report surfaces
`SELF_CONFIRMATION`.

The learning system may search for errors in its own output, but successful verification requires an
independent source such as a deterministic verifier, independent evaluator, external observation, or
human review.

## Overfitting

`GeneralizationProfile` records the same metric across train, validation, held-out, and OOD partitions.
Phase 19C compares train-to-held-out and train-to-OOD gaps against the frozen policy. Excessive gaps
are blocking overfitting evidence.

The phase does not manufacture missing scores or reinterpret unrelated metrics as comparable.

## Report and authority boundary

`LearningIntegrityReport` can be `CLEAN`, `REVIEW_REQUIRED`, or `REJECT_CANDIDATE`. Those states are
learning-lab dispositions, not runtime or release-promotion authority. `promotion_authorized` is
permanently false in this layer.

Learning Integrity may observe, compare, classify, and recommend rejection/review. It cannot:

- change runtime permissions or autonomy;
- dispatch tools;
- rewrite benchmark/training data to remove a finding;
- change evaluator identity during an assessment;
- promote a candidate;
- claim a real training/reward-optimization run that did not occur;
- claim counterfactual causality without controlled replay/sandbox evidence.

## Deferred work

The following remains intentionally deferred:

- Phase 19D controlled replay/sandbox counterfactual analysis;
- Phase 19E real curated-corpus import and small controlled SFT;
- Phase 19F statistical release thresholds, confidence intervals, promotion, and rollback;
- real large-scale shortcut/evaluator agreement studies;
- real measured post-training improvement claims.
