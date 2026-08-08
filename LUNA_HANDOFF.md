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

Verified Phase 19D merge:
0ff1196 Merge pull request #19 from Novopic-Intelligence/phase-19d-counterfactual-analysis

Phase 19D implementation:
0a2f793 feat: complete Phase 19D counterfactual analysis

Roadmap/handoff merge:
739feed Merge pull request #18 from Novopic-Intelligence/docs/capability-roadmap-handoff

Previous checkpoints:
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
IMPLEMENTED_UNVERIFIED / REAL TRAINING PENDING

Then:
Phase 19F — Improvement Gate, blocked until a real trained 19E candidate exists.

## Next Engineering Step

Current working branch: `phase-19e-small-controlled-sft`.
Baseline: merged Phase 19D at `0ff1196`.

Before merge:
1. run the Phase 19E deterministic verifier and targeted tests;
2. run the full Windows `scripts/check.bat`;
3. keep exact Phase 19E scope;
4. commit/push only after the full local gate passes;
5. merge only after GitHub Actions is green;
6. sync main and verify the Phase 19E implementation commit is contained in `origin/main`.

Important: repository governance can audit/freeze a corpus and training specification, but it does not
claim an external GPU/SFT run happened. A real trained artifact requires a matching execution receipt.
Phase 19F cannot start promotion evaluation until such a candidate exists.

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
