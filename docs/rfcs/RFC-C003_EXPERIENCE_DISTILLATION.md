# RFC-C003 — Experience Distillation

Status: `IMPLEMENTED_UNVERIFIED`

## Purpose

C-003 turns governed observable experience into evidence-backed reusable lesson candidates.

It does not treat a model's explanation of why something worked as proof. A candidate lesson must be
grounded in source-trace evidence, checked across independent governed cases, bounded to the observed
scope, and kept review-required until a later governed adoption or promotion decision.

Canonical flow:

```text
governed experience
-> evidence-bound case relation
-> lesson proposal
-> cross-case generalization check
-> contradiction check
-> review-required reusable candidate
```

## Inputs

C-003 consumes existing Phase 19 `StructuredDecisionTrace` records plus their governed split
assignments.

Each lesson-case relation must include:

- source trajectory ID;
- `SUPPORTS` or `CONTRADICTS`;
- evidence refs that actually occur in the source trajectory;
- evidence origin;
- evaluator/reviewer reference;
- concise observable summary.

`MODEL_SELF_REPORT` is explicitly rejected as an evidence origin.

## Learning/evaluation separation

Reusable distillation consumes `TRAIN` experience only.

`VALIDATION` and `HELD_OUT` assignments remain evaluation-only and are rejected by the distiller.
This prevents C-003 from quietly converting evaluation material into learning material.

The distiller also verifies that the split assignment's task family and split-group key match the
source trace.

## Generalization

One supporting case is not enough.

The default C-003 foundation requires at least two distinct Phase 19 split groups before emitting a
`REVIEW_REQUIRED_CANDIDATE`.

The resulting scope is evidence-bounded:

- multiple independent groups in one task family -> `WITHIN_TASK_FAMILY`;
- support spanning multiple task families -> `CROSS_TASK_FAMILY`;
- insufficient support or any contradiction -> no generalization claim.

`CROSS_TASK_FAMILY` is not a universal-law claim.

## Contradiction handling

Any cited observable contradiction produces `REJECTED_CONTRADICTION`.

C-003 does not average away contradictory cases or allow a larger support count to hide them.

## Privacy and provenance

Every cited source trace must already be license-reviewed and PII-reviewed.

Candidate output carries:

- source trajectory IDs;
- supporting split groups;
- supporting task families;
- evidence refs;
- source provenance refs;
- deterministic decision basis.

Raw hidden chain-of-thought is neither required nor accepted by the Phase 19 trace contract.

## Authority boundary

C-003 has no authority to:

- execute runtime actions;
- train a model;
- commit long-term memory;
- promote a model or capability;
- certify its own improvement;
- mutate the roadmap automatically.

Every reusable result remains review-required.

## Known limitations

This foundation validates structural evidence lineage and cross-case support. It does not prove the
semantic truth of arbitrary natural-language lesson wording.

`evaluator_ref` is provenance metadata, not cryptographic identity proof. Stronger reviewer identity
and semantic evaluation can be added by later governed capability work.

Empirical transfer quality is not claimed until a later independent evaluation demonstrates it.
