# RFC-C007 — Debugging Capability Decomposition & Transfer

Status: `IMPLEMENTED_UNVERIFIED`

## Purpose

C-007 turns Luna's existing debugging-related foundations into one observable, measurable transfer
vertical. It does not create an unconstrained autonomous debugger and it does not treat successful
patching alone as proof of debugging skill.

Canonical observable stack:

```text
error observation
-> failure localization
-> hypothesis generation/ranking
-> broken-assumption detection
-> state/context inspection
-> minimal-repair planning
-> correct tool selection
-> patch/action
-> targeted verification
-> full regression verification
-> changed-basis replan if the initial repair failed
-> prevention/process lesson
```

The evaluation must measure both repair success and diagnosis quality.

## Foundations reused

C-007 composes existing governed components rather than replacing them:

- Phase 12D failure classification, minimal change, isolation, and recovery policy;
- Phase 19 failure taxonomy and cognitive-quality dimensions;
- Phase 19 changed-basis self-correction and evidence-bound uncertainty;
- Phase 19F non-self-certifying improvement governance;
- C-001 evidence-aware knowledge routing;
- C-002 capability lineage;
- C-003 evidence-backed review-required lesson candidates.

## Observable decomposition contract

`DebuggingEvaluationCase` records the canonical stage sequence with an independent score and evidence
references for every applicable stage. When an initial repair failed, a changed-basis replan stage is
mandatory before the prevention/process lesson stage.

The contract rejects model self-report as independent evaluation evidence. A model can produce an
attempt, but it cannot independently certify the quality of its own debugging transfer.

## Controlled lesson transfer boundary

A C-003 lesson is not automatically adopted by C-007.

Before transfer evaluation, the lesson must:

1. be a C-003 `REVIEW_REQUIRED_CANDIDATE`;
2. have passed C-003's evidence-bounded generalization check;
3. receive an explicit `ControlledLessonTransferBinding` from a human reviewer;
4. remain evaluation-only.

The binding grants no runtime, training, memory-commit, promotion, deployment, or external-action
authority.

## Held-out transfer evaluation

C-007 uses paired before/after cases with the same case ID, task family, split group, and replan
applicability. Both sides must be `HELD_OUT`.

The baseline case must contain no applied lesson candidate. The transfer case must apply exactly the
reviewed target lesson and no additional lesson candidate, preventing a confounded attribution claim.
Any split group used to support the C-003 lesson is forbidden from the transfer evaluation, preventing
a training-support group from being reused as transfer evidence.

The default foundation requires at least two paired held-out cases.

## Metrics

C-007 computes paired deltas for:

- repair success;
- diagnosis quality;
- failure localization;
- hypothesis quality;
- broken-assumption detection;
- state/context inspection;
- minimal-repair planning;
- tool selection;
- patch/action quality;
- targeted verification;
- full regression verification;
- changed-basis replanning when applicable;
- prevention/process lesson quality.

The default policy is frozen by SHA256. A `SUPPORTED` transfer requires:

- enough paired held-out evidence;
- no metric regression outside the configured tolerance;
- no critical regression;
- meaningful improvement in at least one required outcome metric, where repair success and diagnosis
  quality are both mandatory measured outcomes.

`SUPPORTED` means the controlled evaluation supports the transfer hypothesis. It is not a generic
claim that Luna is globally better and it does not authorize promotion.

## Failure semantics

C-007 returns `INSUFFICIENT_EVIDENCE` when the evaluation basis is invalid, including:

- fewer than the policy minimum paired held-out cases;
- case identity/group/task-family mismatch;
- validation/train data used as transfer evidence;
- reuse of a C-003 support group;
- baseline already containing the lesson;
- transfer case missing the lesson binding;
- lesson/binding mismatch.

It returns `NOT_SUPPORTED` when the evaluation is valid but the measured transfer does not satisfy the
policy, including measurable regression, critical regression, or no meaningful repair/diagnosis
improvement.

## Authority boundary

C-007 is an evaluation and decomposition foundation only.

It cannot:

- execute patches by itself;
- grant tool or runtime authority;
- train a model;
- commit a lesson to long-term memory automatically;
- promote a model or capability;
- mutate the roadmap automatically;
- certify its own improvement;
- convert held-out cases into learning data.

A later capability may consume reviewed C-007 evidence, but that future adoption must preserve its own
independent governance and promotion gates.
