# C-007 Debugging Capability Decomposition & Transfer Report

## Result

C-007 implements a deterministic, non-executing foundation for decomposing debugging behavior and
testing whether a reviewed C-003 lesson transfers to unseen debugging cases.

Status: `IMPLEMENTED_UNVERIFIED`

Final `VERIFIED` status still requires normal local Windows gates, GitHub CI, merge containment, and a
separate evidence-status transition.

## Implemented behavior

C-007 adds:

- a canonical observable debugging stage stack;
- stage-level evidence and quality scoring;
- explicit changed-basis replan evidence after a failed initial repair;
- an evaluation-only explicit human-review binding for C-003 lesson candidates;
- paired held-out before/after transfer evaluation;
- C-003 support-group contamination rejection and additional-lesson confound rejection;
- repair-success and diagnosis-quality outcome measurement;
- debugging-specific metric deltas across diagnosis, repair, verification, and prevention;
- deterministic `SUPPORTED`, `NOT_SUPPORTED`, and `INSUFFICIENT_EVIDENCE` outcomes;
- critical-regression and metric-regression blocking;
- explicit absence of runtime, training, automatic memory, promotion, and action authority.

## What C-007 proves

The foundation can test a narrow hypothesis:

> Does an explicitly reviewed, evidence-backed C-003 lesson improve observable debugging behavior on
> paired unseen held-out cases without causing measured debugging regressions?

A positive foundation fixture demonstrates that the evaluation contract can represent and detect such
a transfer. It does not prove a real trained Luna model has improved until real independent held-out
cases are evaluated.

## What C-007 does not claim

- no real model training was run by C-007;
- no lesson was automatically adopted into runtime behavior;
- no long-term memory was written;
- no patch/external action was executed by the evaluator;
- no global "Luna is better" claim is made;
- no generic debugging score authorizes promotion;
- no held-out data becomes learning data.

## Rollback

C-007 can be disabled by removing the debugging transfer evaluator and its CLI/verifier wiring. C-003
lesson candidates and the existing Phase 12D/19 debugging foundations remain intact because C-007 has
no automatic adoption or runtime authority.
