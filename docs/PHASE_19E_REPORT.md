# Phase 19E — Small Controlled SFT Governance Report

## Status

`IMPLEMENTED_UNVERIFIED`

Phase 19E adds a trainer-neutral controlled-SFT governance layer on top of the merged Phase 19D
counterfactual foundation.

## Implemented

- frozen first-SFT policy with no runtime or promotion authority;
- streaming JSONL corpus audit;
- target-only cumulative loss-mask verification;
- train-only split enforcement;
- canonical Luna tool-schema enforcement;
- privacy/context normalization enforcement;
- source-derivation requirement;
- explicit raw hidden chain-of-thought rejection;
- duplicate record and duplicate training-fingerprint checks;
- conservative initial implementation/judge/harness/seed/security mixture policy;
- frozen base-model/trainer/corpus/hyperparameter candidate specification;
- external training-receipt contract;
- held-out-use rejection at both corpus and training-receipt boundaries;
- trained-candidate artifact registration that remains unpromoted;
- permanent Phase 19E no-promotion-authority boundary.

## Important execution boundary

This repository intentionally does not pretend that creating a training specification is equivalent to
training a model. The Phase 19E library does not invoke a GPU trainer, `torch`, shell command, or Luna
runtime tool dispatcher.

A real trained candidate can be registered only after an external controlled training run produces a
matching receipt and content-addressed artifact evidence.

## Relationship to Phase 19F

Phase 19F remains blocked until a real Phase 19E trained candidate exists. Training completion alone is
not improvement evidence. Phase 19F must compare that candidate against the frozen pre-training
baseline using held-out/OOD and regression evidence before any promotion decision.

## Not claimed

This package does not claim:

- full-corpus ingestion;
- GPU/SFT execution;
- trained Luna weights;
- post-training improvement;
- candidate promotion.
