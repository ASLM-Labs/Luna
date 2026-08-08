# Phase 19D — Counterfactual Analysis Report

## Status

`IMPLEMENTED_UNVERIFIED`

Phase 19D adds a deterministic, experimental controlled-replay/sandbox comparison layer on top of the
merged Phase 19C learning-integrity foundation.

## Implemented

- revision-locked counterfactual-analysis policy;
- observable alternative families for plan, tool, evidence, recovery, and minimal paths;
- explicit hypothesis-only state for unexecuted alternatives;
- controlled replay/sandbox observation contracts;
- same-case, same-revision, same-environment comparison guard;
- independent counterfactual evidence catalog;
- candidate self-evidence rejection;
- cognitive-dimension deltas without a promotion-authorizing aggregate score;
- verified-success preservation checks;
- action, unnecessary-action, and cost deltas;
- critical-safety zero tolerance;
- permanent no-promotion-authority boundary;
- permanent no-generalized-causal-authority boundary.

## Interpretation

An `EVIDENCE_SUPPORTED` result means that an actually executed alternative showed an observed advantage
inside its specific controlled replay/sandbox conditions. It must not be rewritten as "this alternative
would always have been better" or as a general causal law.

Unexecuted alternatives remain hypotheses.

## Relationship to prior subphases

- Phase 19A supplies observable cognitive dimensions and evidence-bound reasoning structures.
- Phase 19B supplies frozen evaluation identities and like-for-like comparison governance.
- Phase 19C distinguishes observational integrity risks from counterfactual proof.
- Phase 19D supplies the controlled experimental layer for specific alternative-path observations.

## Not claimed

This package does not claim:

- real external corpus import;
- GPU/SFT training;
- reward optimization;
- trained weights;
- generalized causal proof;
- real post-training improvement;
- candidate promotion.
