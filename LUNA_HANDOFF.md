# Luna Handoff

This file is the persistent engineering checkpoint for continuing Luna work across chats,
windows, tools, or contributors.

Terminal/Git evidence always overrides this document if they disagree.

## Repository

Project root:
C:\Users\istem\Projects\Luna

Canonical remote:
Novopic-Intelligence/Luna

Model name:
Luna

Company/organization naming:
UNRESOLVED — do not rename Luna while resolving company branding.

## Verified Git Checkpoint

Baseline branch:
main

Latest verified main before Phase 19F branch:
4f0784e Merge pull request #22 from Novopic-Intelligence/docs/c011-orchestration-completion

C-011 completion implementation:
e66817c docs: complete C-011 orchestration design

C-011 base design merge:
fc92a3d Merge pull request #21 from Novopic-Intelligence/docs/single-voice-parallel-cognition

Phase 19E merge:
be3facd Merge pull request #20 from Novopic-Intelligence/phase-19e-small-controlled-sft

Phase 19E implementation:
a816915 feat: complete Phase 19E small controlled SFT

Previous checkpoints:
- Phase 19D merge: 0ff1196
- Phase 19D implementation: 0a2f793
- Phase 19C merge: ba47e8b
- Phase 19C implementation: 08cbf00
- Phase 19B merge: 91a94ad
- Phase 19B implementation: b68b88e
- Phase 19A merge: 69d648b
- Phase 19A implementation: f8660ff
- Phase 18 merge: b1bd19f
- Phase 18 implementation: f838405

## Phase State

Phase 19A — Foundation:
CLOSED

Phase 19B — Evaluation Governance:
CLOSED

Phase 19C — Learning Integrity:
CLOSED

Phase 19D — Counterfactual Analysis:
CLOSED

Phase 19E — Small Controlled SFT:
CLOSED / GOVERNANCE IMPLEMENTED / REAL TRAINING NOT CLAIMED

Phase 19F — Improvement Gate:
IMPLEMENTED_UNVERIFIED / REAL CANDIDATE EVALUATION PENDING.

## Next Engineering Step

Current working branch: `phase-19f-improvement-gate`.
Baseline: merged C-011 documentation completion at `4f0784e`.

Before merge:
1. apply the exact Phase 19F kit scope;
2. run `scripts/verify_phase19f.py` and targeted Phase 19F tests;
3. run the full Windows `scripts/check.bat`;
4. require Ruff + strict mypy + all deterministic gates green;
5. commit/push only after the full local gate passes;
6. require GitHub Actions Python 3.12/3.13 push + PR checks green;
7. merge, sync main, verify implementation containment and clean status.

Important evidence boundary: Phase 19F can implement the promotion/reject/rollback evidence gate before a
real trained candidate exists, but it must return `INSUFFICIENT_EVIDENCE` when the Phase 19E real
training receipt/artifact or real governed evaluation snapshots are absent. No Luna improvement claim is
valid until a real candidate passes the frozen gate.

## Phase 19 Program Boundaries

Learning lab:
observe
-> reconstruct
-> evaluate
-> propose/train candidate
-> benchmark
-> compare
-> request promotion

Runtime:
verify
-> authorize
-> execute
-> audit

Learning/evaluation components:
- cannot grant runtime authority;
- cannot expand permissions;
- cannot bypass safety boundaries;
- cannot self-authorize promotion.

## Promotion Evidence

Primary promotion evidence is a multi-metric vector covering:
- reasoning;
- planning;
- tool selection;
- evidence use;
- uncertainty;
- failure recovery;
- self-correction;
- task success;
- critical regressions;
- unnecessary actions;
- cost/latency where relevant.

Critical safety regression:
zero tolerance.

Non-critical regression:
use meaningful thresholds and confidence intervals before real training promotion.

Single aggregate score:
dashboard-only, never promotion authority.

## Queued Capability / Experience Program

Persistent queue is defined in:
docs/LUNA_ROADMAP.md

High-priority queued items:
- Adaptive Knowledge Retrieval;
- Capability Lineage & Dependency Mapping;
- Experience Distillation;
- Pre-deployment Experience Inheritance;
- Experience <-> Capability Flywheel;
- Vicarious Experience Inheritance;
- Debugging Capability Decomposition & Transfer;
- Sol -> Luna Capability Mining;
- Cross-Agent Experience Mining.

Supporting item:
- External Mentor / Review Boundary.

Core principle:

Experience
-> Capability
-> New Experience
-> Better Capability

External experience:
Sol / Codex / previous Luna / curated traces
-> lesson extraction
-> controlled validation
-> prevention before failure.

## Capability Mining Rule

Useful behaviors observed in Sol or other agents should be proactively surfaced as candidates
instead of waiting for Murat to discover every capability manually.

For each candidate:
observable behavior
-> decomposition
-> dependencies
-> Luna coverage
-> missing prerequisites
-> safe route
-> evaluation
-> NOW / QUEUE / REJECT

Do not reject a behavior merely because it is copied.
Reject unexamined copying.

## Experience Rule

Luna does not need to personally make every known mistake.

A reviewed external failure may become a prevention candidate only after:
- root cause is supported;
- lesson is explicit;
- applicability is bounded;
- counterexamples are considered;
- controlled evaluation supports the transfer.

Do not confuse one anecdote with a universal invariant.

## Knowledge Retrieval Direction

Future Adaptive Knowledge Retrieval must distinguish:
- internal knowledge;
- working context;
- verified memory;
- project/document RAG;
- web/research;
- structured APIs.

Internet/retrieval results are evidence/context, not automatic long-term memory.

Contradictory evidence:
STOP and reinspect.

## External Model Boundary

During active tasks:
Luna should solve using its own governed cognition/tool/evidence loop.

External model consultation should primarily happen during selected idle/review/mentoring work,
not become a default dependency during execution.

## Identity / Design Reminders

- Luna is the model name.
- Company name is still unresolved.
- OpenLab was rejected because the name is too widely used.
- Luna visual direction uses dark/navy with icy moon blue.
- Current logo direction: crescent + small blue point/light + compact Luna wordmark.
- The wordmark "u" may echo the crescent form.

## Working Style

Preferred development flow:

clean merged main
-> phase/docs branch
-> exact-scope changes
-> targeted verification
-> full Windows `scripts/check.bat`
-> `git diff --check`
-> commit
-> push
-> PR
-> GitHub Actions green
-> merge
-> sync main
-> verify implementation commit is contained in origin/main.

Do not commit/push before the full local quality gate passes.

LF -> CRLF Git messages on Windows are warnings unless an actual check fails.

## Handoff Rule

When starting a new chat/window, refresh:
- current phase;
- current branch;
- latest merge and implementation commits;
- local test/gate status;
- CI state;
- known blocker;
- exact next step.

Trust order:
terminal/Git evidence
> committed handoff/roadmap
> conversation memory.

"Baba, bi doğrula önce."

<!-- HANDOFF_C011_SINGLE_VOICE_BEGIN -->

## Single-Voice Parallel Cognition Design Checkpoint

Queued capability: **C-011 - Single-Voice Parallel Cognition**

Canonical principles:

- **One mind. Many hands. One voice.**
- **Workers prepare. Evidence supports. Luna decides. Runtime executes.**
- **Fix the basis, not the worker.**
- **Knowledge survives. Persona does not.**

Architecture intent:

- Main Luna keeps the single authoritative task state, decision authority, and
  user-facing voice.
- Temporary workers/workspaces may research, inspect, draft, test, or verify in
  parallel.
- Preferred serving form is shared Luna weights with isolated task contexts/KV
  state when supported; workers do not require persistent specialist personas.
- Worker outputs are proposals/evidence, never automatically trusted state.
- Minor gaps resume the workspace; a bad basis causes drop + changed-basis
  respawn; contradictory results trigger independent verification.
- Worker-specific long-term memory and independent authority are prohibited by
  default.
- Delegation depth, concurrency, GPU/KV budget, tool permissions, cancellation,
  freshness, provenance, cost, and state adoption must be bounded/measurable.

Verified checkpoint when recorded:

```text
Phase 19E - Small Controlled SFT: CLOSED
implementation: a816915
merge:          be3facd
PR:             #20
GitHub Actions:  4/4 PASS
main status:     clean
next phase:      Phase 19F - Improvement Gate
```

C-011 is documentation/roadmap state only here; this update must not claim the
parallel-cognition capability is already implemented.

### C-011 completion notes

Three additional design rules are part of the queued capability and must survive
future implementation work:

1. **Spawn / Admission Policy**
   - Spawn only when expected benefit exceeds orchestration cost.
   - Parallelism is optional, not a default reflex.
   - Admission considers latency, evidence value, I/O wait, token/GPU/KV cost,
     duplication risk, and mergeability into authoritative state.

2. **Context Hygiene / Result Distillation**
   - Do not inject a worker's whole working context into Main Luna.
   - Adopt only distilled result, evidence, assumptions, uncertainty, conflicts,
     source references/freshness, and recommended next action.
   - Transient role framing and unverified intermediate claims remain disposable.

3. **Parallel Cognition Evaluation**
   - Measure quality, latency, evidence value, context growth, and compute/tool
     cost together.
   - Track unnecessary spawn, duplicate work, rejection, resume/respawn,
     stale-result rejection, contradiction handling, and voice consistency.
   - Worker count is never a success metric by itself.

Canonical completion principles:

> Parallelize when useful, not because possible.

> Distill worker context before state adoption.

> Measure parallelism by quality + latency + compute, not worker count.

<!-- HANDOFF_C011_SINGLE_VOICE_END -->

## Phase 19F Improvement Gate Checkpoint

Phase 19F architecture now requires:
- real Phase 19E spec + training receipt + trained artifact evidence before candidate eligibility;
- frozen held-out/OOD evaluation suite, regression inventory, and evaluator fingerprint;
- benchmark contamination and candidate-identity checks;
- clean learning-integrity disposition;
- paired baseline/candidate confidence intervals for every cognitive dimension;
- separate overall, held-out, and OOD evidence slices;
- meaningful non-critical regression thresholds;
- critical regression zero tolerance;
- at least one confidence-supported meaningful improvement for PROMOTE;
- ROLLBACK only as a recommendation for an already-active candidate with rollback-worthy evidence;
- runtime authority and release action execution remain outside the improvement gate.

Current repository evidence does not prove a real external training run or a real candidate evaluation.
The correct current smoke behavior is therefore `INSUFFICIENT_EVIDENCE`.

<!-- HANDOFF_C012_SELF_OPTIMIZATION_BEGIN -->

## C-012 - Self-Optimization Sandbox Design Checkpoint

A post-Phase-19 queued capability was added after Phase 19F closed:

**C-012 - Self-Optimization Sandbox**

Canonical principle:

> Optimize freely in the sandbox; promote only with evidence.

Intent:

- Luna may discover bottlenecks and produce candidate optimizations for code,
  configuration, orchestration, serving, retrieval, caching, scheduling, or
  governed training recipes.
- Candidate changes run only in sandbox / controlled replay before promotion.
- Luna's own success claim is never independent evidence.
- Quality, correctness, safety, latency, throughput, compute, memory, and cost
  are compared against a frozen baseline where applicable.
- Efficiency gains cannot silently mask material quality or safety regressions.
- Every candidate keeps provenance, changed scope, hypothesis, measured
  evidence, reproduction information, and rollback plan.
- Self-optimization has bounded scope, budget, iteration depth, delegation,
  permissions, cancellation, and stop conditions.
- Failed experiments use changed-basis replanning rather than blind retry.
- Production promotion remains a separate authority decision and must reuse the
  Phase 19F Improvement Gate pattern.
- Recursive self-promotion is prohibited.

Canonical boundary:

> A system may propose its own improvement. It may not certify itself improved.

Verified project checkpoint when this design was recorded:

```text
Phase 19F - Improvement Gate: CLOSED
implementation: 0aa94b2
merge:          394f04c
PR:             #23
GitHub Actions:  4/4 PASS
main status:     clean
Phase 19 umbrella: CLOSED
```

C-012 is QUEUED documentation/design only. This update does not claim that Luna
currently performs autonomous self-optimization or production self-modification.

<!-- HANDOFF_C012_SELF_OPTIMIZATION_END -->

<!-- HANDOFF_ROADMAP_DEPENDENCY_REVIEW_BEGIN -->

## Roadmap Dependency Review Checkpoint

A dependency-first review of queued capabilities is persisted in:

`docs/ROADMAP_DEPENDENCY_REVIEW.md`

Recommended implementation sequence:

```text
C-002 -> C-001 -> C-003 -> C-005 -> C-006 -> C-004 -> C-011 -> C-012
```

Recommended next implementation:

**C-002 — Capability Lineage Mapping**

Reason: later retrieval, experience transfer, parallel cognition, and
self-optimization all benefit from an explicit map of prerequisites,
implementation components, evidence, metrics, downstream dependencies, and
regression blast radius.

Important phase-number guard:

Do not automatically call the next work `Phase 20A` until the repository's
canonical phase-number roadmap is checked for an existing Phase 20 definition.

Current repository checkpoint when this review is being added:

```text
main: a74eca8
Phase 19: CLOSED
C-011 design/docs: CLOSED, capability QUEUED
C-012 design/docs: CLOSED, capability QUEUED
working tree before review branch: clean
```

<!-- HANDOFF_ROADMAP_DEPENDENCY_REVIEW_END -->

<!-- HANDOFF_LEGACY_ROADMAP_RECONCILIATION_BEGIN -->

## Legacy Roadmap Reconciliation Checkpoint

A previously external historical roadmap document was reviewed before deletion.

Preserved canonical intent:

```text
Phase 20 = Final Conformance Comparison and Release Candidate
Phase 21 = Post-v0.1 Research
```

Therefore the previously considered name `Phase 20A — Capability Lineage
Foundation` is rejected.

The next implementation remains:

```text
C-002 — Capability Lineage Mapping
branch: capability/c002-lineage-foundation
```

C-011 and C-012 remain QUEUED designs only.

The historical detailed Phase 12-19 implementation plan is not re-imported; real
repository implementation, verifiers, tests, manifests, merge history, and the
current roadmap supersede stale planning details.

An explicit Delta Review rule is now preserved for future roadmap discoveries.

Canonical reconciliation document:

`docs/LEGACY_ROADMAP_RECONCILIATION.md`

After this reconciliation is merged, contained in `origin/main`, and the working
tree is clean, the external historical plan file may be deleted without losing
the still-relevant Phase 20 / Phase 21 / Delta Review intent.

<!-- HANDOFF_LEGACY_ROADMAP_RECONCILIATION_END -->\n\n<!-- HANDOFF_C002_LINEAGE_BEGIN -->\n\n## C-002 Capability Lineage Checkpoint\n\nCurrent implementation target: **C-002 — Capability Lineage & Dependency Mapping**.\n\nBranch: `capability/c002-lineage-foundation`\n\nImplemented boundary:\n\n```text\ncanonical C-001..C-012 identity registry\n+ hard/preferred dependency fields\n+ source/implementation/verifier/evidence/freshness metadata\n+ deterministic duplicate/unknown/self/cycle checks\n+ blast-radius query\n+ no runtime or promotion authority\n```\n\nC-002 status is `IMPLEMENTED_UNVERIFIED`; final merge containment and CI evidence must occur before\nany separate `VERIFIED` transition.\n\nImportant source finding: the dependency review's C-005/C-006 shorthand labels conflict with the\nexplicit queue identities in `docs/LUNA_ROADMAP.md`. C-002 does not silently remap those IDs. A Delta\nReview is required before future implementation order relies on the conflicting labels.\n\nPhase 20 remains reserved for Final Conformance Comparison and Release Candidate.\nPhase 21 remains reserved for post-v0.1 research.\n\n<!-- HANDOFF_C002_LINEAGE_END -->\n

<!-- HANDOFF_C001_RETRIEVAL_BEGIN -->

## C-001 Adaptive Knowledge Retrieval Checkpoint

Current implementation target: **C-001 — Adaptive Knowledge Retrieval**.

Branch: `capability/c001-adaptive-knowledge-retrieval`

Implemented boundary:

```text
request/source-availability profile
-> deterministic source-family routing
-> freshness/citation requirements for external evidence
-> contradictory evidence STOP_REINSPECT
-> no public fallback for missing private user-specific knowledge
-> no automatic long-term memory commit
-> no runtime/network/external-action authority
```

C-001 status is `IMPLEMENTED_UNVERIFIED`; final merge containment and CI evidence are required before
a separate `VERIFIED` transition. Existing Phase 9 verified memory, Phase 12B layered context, and
Phase 14 Research Gateway remain authoritative execution boundaries.

<!-- HANDOFF_C001_RETRIEVAL_END -->

<!-- HANDOFF_C003_DISTILLATION_BEGIN -->

## C-003 Experience Distillation Checkpoint

Current implementation target: **C-003 — Experience Distillation**.

Branch: `capability/c003-experience-distillation`

Implemented boundary:

```text
Phase 19 governed TRAIN traces
-> explicit evidence-bound lesson cases
-> source evidence-ref validation
-> independent split-group support
-> contradiction rejection
-> bounded generalization scope
-> REVIEW_REQUIRED_CANDIDATE
```

C-003 rejects validation/held-out contamination and `MODEL_SELF_REPORT` as lesson evidence. It does
not require or preserve raw hidden chain-of-thought.

C-003 status is `IMPLEMENTED_UNVERIFIED`; final merge containment and CI evidence are required before
a separate `VERIFIED` transition.

Authority remains absent: no runtime execution, no training execution, no automatic memory commit,
no promotion, and no automatic roadmap mutation.

The C-005/C-006 shorthand identity conflict in the historical dependency review remains unresolved.
C-003 uses the canonical capability identities from `docs/LUNA_ROADMAP.md` and does not silently
renumber later capabilities.

<!-- HANDOFF_C003_DISTILLATION_END -->
