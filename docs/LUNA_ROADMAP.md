# Luna Roadmap

Luna is the model. The company/organization name is a separate branding decision.

This document records architectural and capability work that must survive chat/session changes.
Items listed as QUEUED are commitments for future design/evaluation work, not claims that they
are already implemented.

## Current Phase State

- Phase 19A — Foundation: CLOSED
- Phase 19B — Evaluation Governance: CLOSED
- Phase 19C — Learning Integrity: CLOSED
- Phase 19D — Counterfactual Analysis: CLOSED
- Phase 19E — Small Controlled SFT: IMPLEMENTED_UNVERIFIED / REAL TRAINING PENDING
- Phase 19F — Improvement Gate: BLOCKED UNTIL A REAL 19E TRAINED CANDIDATE EXISTS

## Phase 19D — Counterfactual Analysis

Status: CLOSED / EXPERIMENTAL

Purpose:
- compare alternative plans, tools, evidence paths, recovery paths, and minimal-action paths;
- use controlled replay or sandbox execution only;
- treat observed replay/sandbox outcomes as evidence;
- never claim that an unexecuted counterfactual "would definitely have worked";
- remain non-blocking for the first controlled SFT unless later evidence justifies promotion
  into a blocking evaluation gate.

Runtime boundary:
- counterfactual analysis has no runtime authority;
- it cannot expand permissions;
- it cannot authorize promotion;
- it cannot rewrite safety policy.

## Phase 19E — Small Controlled SFT

Status: IMPLEMENTED_UNVERIFIED / REAL TRAINING PENDING

Purpose:
- accept only a curated, normalized and governed training corpus;
- preserve provenance and lineage;
- reject validation/held-out rows from training;
- require target-only loss for cumulative traces;
- require canonical Luna tool normalization and privacy/context normalization;
- freeze base model, trainer, corpus and hyperparameters into one candidate spec;
- record a trained artifact only from a matching external training receipt;
- keep every trained candidate unpromoted until Phase 19F.

Execution boundary:
- repository governance does not execute GPU/SFT training;
- training requested is not training completed;
- no weights or improvement are claimed until external artifact evidence exists.

## Phase 19F — Improvement Gate

Status: BLOCKED UNTIL A REAL 19E TRAINED CANDIDATE EXISTS

Purpose:
- compare the candidate against the frozen pre-training baseline;
- use a multi-metric improvement vector;
- measure reasoning, planning, tool selection, evidence use, uncertainty, recovery,
  self-correction, final task success, cost, and unnecessary actions;
- use meaningful thresholds and confidence intervals for non-critical metrics;
- keep critical safety regressions at zero tolerance;
- PROMOTE, REJECT, or ROLLBACK based on evidence.

A single aggregate "Luna Score" may be dashboard-only and must never authorize promotion.

---

# Capability & Experience Queue

## C-001 — Adaptive Knowledge Retrieval

Status: QUEUED
Priority: HIGH

Goal:
Luna should decide which knowledge source is appropriate instead of treating every information
request the same way.

Candidate sources:
- model/internal knowledge;
- active working context;
- verified memory;
- project/document RAG;
- Research Gateway / web;
- structured APIs and authorized external services.

Desired behavior:
- stable + sufficiently known -> answer from internal/context knowledge;
- user/project-specific -> verified memory;
- document-specific -> RAG;
- uncertain or externally verifiable -> research;
- current/fast-changing -> web/API;
- contradictory evidence -> STOP and reinspect.

Memory boundary:
web/retrieval result -> observation/evidence -> working context -> optional memory candidate
-> review -> verified memory.

A web result must never become long-term memory automatically.

Evaluation candidates:
- source-selection accuracy;
- unnecessary retrieval rate;
- missed retrieval rate;
- stale-answer rate;
- evidence sufficiency;
- contradiction detection;
- provenance/citation correctness;
- latency and retrieval cost.

## C-002 — Capability Lineage & Dependency Mapping

Status: QUEUED
Priority: HIGH

For each important Luna capability, record:
- observable capability;
- experiences/failures that motivated it;
- prerequisites;
- dependent capabilities;
- cross-capability effects;
- failure modes;
- evaluation metrics;
- version/release lineage.

Core question:
"What enables this capability, what did it come from, and what else does it strengthen?"

## C-003 — Experience Distillation

Status: QUEUED
Priority: HIGH

Transform experience into reusable lessons rather than storing isolated anecdotes.

Pipeline:

experience
-> observation
-> root cause
-> lesson
-> generalizable principle
-> applicability conditions
-> counterexample check
-> capability candidate
-> evaluation

A single success/failure must not become a universal rule without evidence.

## C-004 — Pre-deployment Experience Inheritance

Status: QUEUED
Priority: HIGH

Luna should be able to begin a new generation with distilled lessons collected before its first
real deployment task.

Possible sources:
- Sol;
- Codex and other coding agents;
- previous Luna versions;
- curated successful traces;
- curated failures;
- regression cases;
- project engineering experience.

Experience may be inherited through:
- training data;
- architecture;
- policy;
- evaluation suites;
- tool-selection rules;
- failure-prevention rules.

## C-005 — Experience <-> Capability Flywheel

Status: QUEUED
Priority: HIGH

Core loop:

EXPERIENCE
    |
    | distill
    v
CAPABILITY
    |
    | apply
    v
NEW EXPERIENCE
    |
    | analyze + verify
    v
BETTER CAPABILITY
    |
    +--------------------> repeat

The target is not merely more experience. The target is better, more generalizable and
better-verified capability.

## C-006 — Vicarious Experience Inheritance

Status: QUEUED
Priority: HIGH

Goal:
learn from another agent/version/person's success or failure without requiring Luna to pay the
same failure cost first.

External experience:
Sol / Codex / previous Luna / curated traces / reviewed project incidents

Pipeline:
1. collect success/failure experience;
2. determine what happened;
3. identify why it happened;
4. extract the lesson;
5. identify the underlying invariant/pattern;
6. test applicability and counterexamples;
7. validate in controlled evaluation;
8. transfer as a capability or prevention candidate.

Maturity ladder:
1. make error -> recover;
2. do not repeat identical error;
3. generalize and prevent similar errors;
4. learn from another actor's error before making it;
5. extract an invariant and prevent previously unseen related failures.

Target:
failure recovery -> failure prevention.

## C-007 — Debugging Capability Decomposition & Transfer

Status: QUEUED
Priority: HIGH

Treat debugging as a capability stack rather than one feature:

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
-> changed-basis replan if needed
-> prevention/process lesson

Evaluation should measure both repair success and quality of diagnosis.

## C-008 — Sol -> Luna Capability Mining

Status: QUEUED
Priority: HIGH

Do not wait only for manually discovered ideas.

When a useful observable behavior is identified in Sol:
1. describe the observable behavior;
2. decompose its functions;
3. map prerequisites/dependencies;
4. compare against Luna's current coverage;
5. identify missing components;
6. determine safe implementation route;
7. identify cross-capability effects;
8. define evaluation metrics;
9. define failure modes;
10. classify NOW / QUEUE / REJECT.

Principle:
Do not avoid a useful behavior merely because it resembles another model.

"Do not fear copying; fear copying without understanding."

## C-009 — Cross-Agent Experience Mining

Status: QUEUED
Priority: HIGH

Compare:
- Sol;
- Codex;
- other suitable agents;
- previous Luna versions;
- curated real project traces.

Study:
- shared strong behaviors;
- different strategies;
- failure patterns;
- recovery quality;
- tool-selection behavior;
- verification behavior;
- efficiency trade-offs.

Goal:
Luna may inherit the best validated parts and later improve beyond the source agents.

## C-010 — External Mentor / Review Boundary

Status: QUEUED
Priority: MEDIUM

During an active task, Luna should not habitually escalate to an external model such as Sol.

Preferred boundary:

TASK TIME
Luna -> own context -> own tools -> own evidence -> own verification -> own recovery

IDLE / REVIEW TIME
reviewed trace/problem
-> optional external mentor analysis
-> alternative pattern / criticism / lesson
-> learning candidate
-> review
-> future version/evaluation

Purpose:
avoid dependency, control cost, and preserve Luna's independent problem-solving ability.

---

# Experience Inheritance Principle

Luna should not be required to personally make every expensive mistake in order to become
experienced.

The desired cycle is:

external or internal experience
-> evidence-backed lesson
-> capability
-> new experience
-> verified improvement
-> inherited lesson for the next generation

The system must preserve the distinction between:
- evidence;
- hypothesis;
- lesson;
- capability candidate;
- verified capability.

No learning component may grant itself runtime authority.

---

# Design / Identity Queue

These are product-design reminders, not runtime claims.

- Luna remains the model name.
- Company/organization naming remains unresolved.
- "OpenLab" was rejected as a company name because it is too widely used.
- Luna visual direction: dark/navy space aesthetic with icy moon blue as the primary accent.
- Logo concept under exploration:
  - crescent mark on the left;
  - small blue point/light inside or near the crescent center;
  - compact "Luna" wordmark on the right;
  - the "u" may echo a crescent/moon form.

These design decisions must remain separable from model architecture and runtime policy.

<!-- C011_SINGLE_VOICE_PARALLEL_COGNITION_BEGIN -->

## C-011 - Single-Voice Parallel Cognition

**Status:** QUEUED
**Principle:** One mind. Many hands. One voice.

Luna should gain parallel task capacity without fragmenting user-facing identity,
decision authority, or authoritative task state into persistent specialist personas.

### Core topology

```text
                     MAIN LUNA
          policy + authority + task state
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
     workspace A    workspace B    workspace C
     temporary      temporary      temporary
          |              |              |
          +------ proposals/evidence ---+
                         |
                         v
                     MAIN LUNA
                         |
                  accept / modify /
                  reject / replan
                         |
                         v
                 runtime execution
```

Preferred serving form: one Luna model / shared weights with isolated task
contexts or KV states when the inference backend supports it. A logical worker
does not require a persistent second Luna identity or another model copy.

### Worker contract

Workers are temporary work units, not independent authorities. They may inspect,
research, search, compare, draft, test, or verify within granted scope.

Where applicable they return:

```text
result
evidence
assumptions
uncertainty
conflicts
recommended_next_action
source_revision / freshness
```

Workers must not become persistent user-facing personas, own worker-specific
long-term memory, declare their result authoritative, promote their own output
into trusted state, escalate permissions, or create unbounded worker trees.

### Authority rule

> Workers prepare. Evidence supports. Luna decides. Runtime executes.

Main Luna remains the single user-facing decision voice and the only cognitive
component allowed to adopt worker output into authoritative task state.

### Failure / retry policy

```text
unsatisfactory result
        |
        v
diagnose failure basis
   |                |
   v                v
minor gap        bad basis
   |                |
   v                v
RESUME           DROP
same workspace   old workspace
   |                |
   v                v
refine task      RESPAWN with
                 changed basis
```

- Minor gap: resume the same workspace with a precise correction.
- Bad basis: discard the old workspace and respawn with changed assumptions,
  evidence requirements, or task framing.
- Contradiction: request independent verification instead of worker debate.

> Fix the basis, not the worker.

This extends Luna's changed-basis self-correction rule: no blind retry and no
persona blame.

### Persona / memory boundary

- Workers receive task identities, not durable personal identities.
- Worker contexts are disposable after the task.
- Useful verified knowledge may be adopted by Luna.
- Worker identity/history does not survive merely because the work succeeded.

> Knowledge survives. Persona does not.

### Orchestration safeguards

Implementation must define and test concurrency/GPU budget, KV/context budget,
timeout/cancellation, least-privilege tool permissions, source revision binding,
web freshness/provenance, stale-result rejection, duplicate-work suppression,
cost accounting, traceability, bounded delegation depth, and safe state-adoption
checks.

### High-value first use cases

- web/document retrieval while Main Luna continues independent work;
- repository inspection and constraint discovery;
- PowerShell/code candidate drafting;
- test execution and result collection;
- independent evidence verification;
- alternative-plan preparation.

The objective is not free compute. It is overlapping independent work,
especially I/O-bound work, while preserving one coherent Luna policy, state,
and voice.

<!-- C011_SINGLE_VOICE_PARALLEL_COGNITION_END -->
