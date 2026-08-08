# RFC-019B — Evaluation Governance

Status: IMPLEMENTED_UNVERIFIED
Phase: 19B

## Purpose

Phase 19B turns the Phase 19A cognitive-quality contracts into a repeatable evaluation-governance
layer. It freezes what is evaluated, which evaluator revision is trusted, how held-out and OOD cases
remain isolated from training exposure, and how releases are compared without granting promotion
authority to the evaluation subsystem.

This RFC defines governance infrastructure only. It does not claim that the external large trace
corpus has been imported, that a real model baseline has been executed, or that any SFT candidate has
improved.

## Frozen evaluation suite

A `FrozenEvaluationSuite` binds:

- an explicit suite name and semantic revision;
- a versioned evaluator identity and implementation SHA-256;
- immutable evaluation case identities;
- at least one `HELD_OUT` and one `OOD` partition;
- task, repository, and trajectory-family identities for every case;
- content SHA-256 and evidence references for each case;
- a deterministic suite SHA-256.

A family group cannot span both held-out and OOD partitions. This prevents a single evaluation group
from being relabeled across partitions after the suite is frozen.

## Benchmark contamination

Training exposure is represented only by the minimum fingerprints required for comparison. The
contamination checker detects overlap by:

- exact content SHA-256;
- source trajectory identity;
- task family;
- repository family;
- trajectory family.

A contamination finding is evidence, not an automatic repair instruction. Evaluation data is never
silently moved into training or rewritten to make the report pass.

## Evaluator version and independence

Every evaluator has a semantic revision and implementation SHA-256. The evaluator must explicitly be
independent from candidate artifacts and training data. A model-judge evaluator must name its model
identity, and a candidate model cannot judge itself.

Changing evaluator revision or implementation changes the evaluator fingerprint and therefore blocks
a like-for-like release comparison until a new governed baseline is established.

## Frozen regression suite

`FrozenRegressionSuite` locks the complete required case inventory and an optional critical-case
subset against one frozen evaluation suite SHA-256. Critical cases are zero-tolerance evidence for
later promotion policy, but Phase 19B does not itself authorize promotion.

The regression inventory is versioned independently from future Phase 19F thresholds. This keeps
case identity governance separate from statistical promotion policy.

## Release comparison

A `ReleaseEvaluationSnapshot` binds one release/model identity to:

- one frozen evaluation suite SHA-256;
- one evaluator fingerprint;
- exactly the frozen case inventory;
- one cognitive scorecard per case.

Release comparison is permitted only when suite, evaluator, regression inventory, and case IDs remain
like-for-like and benchmark contamination is absent. The comparison reports per-dimension deltas and
regressed case IDs.

The comparison status can be:

- `COMPARABLE`;
- `REGRESSION_DETECTED`;
- `BLOCKED`.

`promotion_authorized` is permanently false in this layer. Phase 19F owns any later accept/reject or
rollback decision using meaningful thresholds, confidence intervals, and zero-tolerance critical
rules.

## Authority boundary

Evaluation Governance may observe, freeze, compare, and report. It cannot:

- modify runtime authority;
- dispatch tools;
- modify training data to eliminate a failing result;
- promote a candidate model;
- change evaluator identity during a comparison;
- claim a real benchmark run that did not occur.

The runtime and release-governance layers remain authoritative.

## Deferred work

The following is intentionally deferred:

- real large-corpus contamination scans;
- actual baseline execution against the selected model;
- real held-out/OOD benchmark population;
- evaluator agreement studies;
- statistical confidence intervals and minimum meaningful deltas;
- candidate promotion or rollback.

Those belong to later Phase 19 subphases after this governance layer passes the Windows quality gate
and CI.
