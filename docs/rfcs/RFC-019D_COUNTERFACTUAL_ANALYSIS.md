# RFC-019D — Counterfactual Analysis

Status: IMPLEMENTED_UNVERIFIED
Phase: 19D

## Purpose

Phase 19D adds an experimental controlled-replay/sandbox layer for testing observable alternatives to
an already observed Luna decision. It is intended to answer a narrower question than generic post-hoc
speculation: whether an actually replayed alternative produced a different observed outcome under a
like-for-like controlled environment.

This phase does not execute real training, does not alter runtime policy, and does not authorize model
promotion.

## Counterfactual candidates

A `CounterfactualCandidate` records one observable alternative at a known decision point. Supported
families are:

- plan;
- tool selection;
- evidence path;
- recovery path;
- minimal path.

The candidate records the source case/revision, baseline decision reference, changed basis, and the
hypothesis provenance. A candidate definition alone is a hypothesis, not evidence.

## Controlled evidence boundary

Phase 19D accepts observations only from:

- `CONTROLLED_REPLAY`;
- `SANDBOX`.

A `ReplayObservation` represents an actually executed observation supplied by the controlled harness.
The analysis package itself does not dispatch production/runtime tools and therefore cannot silently
acquire runtime authority.

An alternative that has not been executed returns `HYPOTHESIS_ONLY`. It receives no replay-derived
metric deltas and cannot be described as a demonstrated improvement.

## Like-for-like comparison

Baseline and alternative observations must use:

- the same evaluation case;
- the same source revision;
- the same replay environment;
- different tested decision references.

The comparison preserves the existing Phase 19 multi-dimensional cognitive scorecard. It also records:

- verified task-success preservation;
- action-count delta;
- unnecessary-action delta;
- cost delta;
- critical-safety-regression delta.

A cheaper/shorter path is not treated as better if it regresses a cognitive dimension, verified
success, or critical safety.

## Evidence independence

Replay observations reference an explicit `CounterfactualEvidence` catalog. Candidate output cannot
self-declare as independent evidence. When the frozen policy requires independent observation
evidence, both the baseline and alternative need at least one independent evidence source.

This prevents the model from saying "my alternative worked better" and using that statement itself as
the proof.

## Interpretation boundary

`EVIDENCE_SUPPORTED` means only that the tested alternative showed an observed advantage inside the
specific controlled replay/sandbox conditions. It does not authorize a generalized causal claim about
all tasks or future runs.

`generalized_causal_claim_authorized` is permanently false in Phase 19D.

Likewise, `promotion_authorized` is permanently false. Phase 19F remains responsible for release
promotion/rollback decisions after real training and statistical comparison.

## Relationship to Phase 19C

Phase 19C can flag observational shortcut dependence and other learning-integrity risks. Those signals
are not counterfactual causal proof. Phase 19D may test a relevant changed-basis alternative in a
controlled environment, but only the observed replay result counts as Phase 19D counterfactual
evidence.

## Non-blocking first-SFT boundary

Counterfactual analysis is experimental and remains non-blocking for the first small controlled SFT.
It may produce useful evidence for debugging, capability analysis, and later evaluation design, but it
must not silently become a promotion gate before its reliability is itself evaluated.

## Not claimed

Phase 19D does not claim:

- import of the real large trace corpus;
- GPU/SFT training;
- reward optimization;
- trained weights;
- real large-scale benchmark execution;
- generalized causal proof;
- measured post-training improvement;
- candidate promotion.
