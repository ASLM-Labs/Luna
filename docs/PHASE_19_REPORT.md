# Phase 19 — Trace/Dataset Governance and Cognitive Quality Foundation Report

## Status

`FOUNDATION_IMPLEMENTED_UNVERIFIED`

This report covers the deterministic Phase 19 foundation. It intentionally does not claim a real
SFT run or a measured post-training model improvement because the repository source package does
not contain the external large trace corpus, trained weights, or a completed hardware training run.

## Track A — Dataset Governance

Implemented:

- observable `StructuredDecisionTrace` schema;
- explicit task/repository/trajectory family identities;
- reconstruction that refuses missing/duplicate source sequence gaps;
- dataset taxonomy for coding, security/harness, judge/review, seed-authoring, and risky/failed work;
- semantic tool-event normalization without executable authority;
- grouped deterministic train/validation splitting;
- explicit unseen task-family held-out split;
- held-out exclusion before training transformation;
- license and PII review gates;
- target-only training examples using observable decision targets;
- raw hidden chain-of-thought prohibition.

## Track B — Cognitive Quality

Implemented:

- multi-axis cognitive failure taxonomy;
- reasoning/planning/tool-selection/failure-recovery/evidence/uncertainty/self-correction dimensions;
- evidence-bound uncertainty policy;
- contradictory-evidence hard stop;
- changed-basis self-correction contract;
- frozen pre-training cognitive baseline with SHA-256 integrity;
- like-for-like candidate comparison;
- any-dimension regression, critical-regression, and held-out-contamination rejection.

## Verification evidence

The Phase 19 targeted suite covers structured traces, reconstruction gaps, failure labels, tool
normalization, leak-free splitting, held-out exclusion, training transformation, uncertainty,
self-correction, baseline locking, comparison deltas, and rejection behavior.

The Phase 19 verifier also runs the Phase 18 verifier to prove the new dataset/cognition layer does
not weaken the Voice Gateway foundation.

## Deferred execution work

The following remains intentionally outside this foundation package:

- import/reconstruction of the external large trace corpus;
- corpus-level deduplication and contamination reports;
- frozen baseline execution against the selected real model;
- actual small SFT run;
- post-training held-out cognitive comparison;
- accept/reject decision for trained weights.

Those steps should begin only after this foundation passes local Windows quality gates and CI.
