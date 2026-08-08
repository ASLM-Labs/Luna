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

Verified Phase 19C merge:
ba47e8b Merge pull request #17 from Novopic-Intelligence/phase-19c-learning-integrity

Phase 19C implementation:
08cbf00 feat: complete Phase 19C learning integrity

Previous checkpoints:
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

Next:
Phase 19D — Counterfactual Analysis

Then:
Phase 19E — Small Controlled SFT
Phase 19F — Improvement Gate

## Next Engineering Step

After this documentation checkpoint is merged:

1. sync clean main;
2. create `phase-19d-counterfactual-analysis`;
3. verify the branch starts at the documentation/main merge;
4. prepare Phase 19D from that baseline;
5. keep counterfactual evidence limited to controlled replay/sandbox observations.

Do not claim an unexecuted alternative would have succeeded.

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
