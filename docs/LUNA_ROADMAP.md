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
- Phase 19E — Small Controlled SFT: CLOSED / GOVERNANCE IMPLEMENTED / REAL TRAINING NOT CLAIMED
- Phase 19F — Improvement Gate: IMPLEMENTED_UNVERIFIED / REAL CANDIDATE EVALUATION PENDING

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

Status: IMPLEMENTED_UNVERIFIED / REAL CANDIDATE EVALUATION PENDING

Purpose:
- require a verified Phase 19E spec/receipt/artifact candidate chain;
- compare the candidate against the frozen pre-training baseline;
- bind evaluation to frozen held-out/OOD suite, evaluator fingerprint, and regression inventory;
- reject benchmark contamination and evaluator/case drift;
- use a multi-metric improvement vector rather than one aggregate score;
- use paired confidence intervals plus meaningful thresholds for non-critical metrics;
- keep critical safety regressions at zero tolerance;
- require clean Phase 19C learning-integrity evidence;
- emit PROMOTE, REJECT, ROLLBACK, or INSUFFICIENT_EVIDENCE;
- never directly execute runtime promotion or rollback.

Default initial governance bounds are revision-locked at 95% confidence, +0.01 meaningful improvement,
-0.01 tolerated non-critical regression band, and at least two paired cases per required slice. These are
initial conservative governance defaults, not claims of statistically optimal production thresholds.

A candidate with no meaningful regression but also no confidence-supported improvement remains
INSUFFICIENT_EVIDENCE. "Not worse" is not automatically "better".

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

Status: IMPLEMENTED_UNVERIFIED
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

### Spawn / admission policy

Workers are not spawned merely because parallelism is available.

Before spawning a worker, Main Luna should estimate whether the task is
independent enough and whether expected value exceeds orchestration cost.

```text
candidate subtask
      |
      v
independent enough?
      |
      v
expected benefit > orchestration cost?
      |
   +--+--+
   |     |
  yes    no
   |     |
   v     v
 SPAWN   Main Luna continues directly
```

> Parallelize when useful, not because possible.

Admission decisions should consider expected latency reduction, evidence value,
tool or I/O wait, token cost, GPU/KV pressure, duplication risk, and whether the
result can be safely merged into the authoritative task state.

### Context hygiene / result distillation

A worker's entire working context must not be copied into Main Luna merely
because the worker completed successfully.

Before state adoption, worker output should be distilled to the minimum useful
packet:

```text
result
evidence
assumptions
uncertainty
conflicts
source_refs
freshness / source_revision
recommended_next_action
```

Verbose scratch context, redundant source material, transient role framing, and
unverified intermediate claims remain outside authoritative state by default.

> Distill worker context before state adoption.

This reduces context growth, persona contamination, duplicated evidence, and
stale intermediate assumptions.

### Parallel cognition evaluation

Parallel cognition is evaluated by useful system-level outcomes, not by the
number of workers created.

Minimum evaluation dimensions should include:

- end-to-end task latency;
- task quality / verification quality;
- evidence quality and adoption rate;
- token, tool, wall-clock, GPU, and KV/context cost;
- unnecessary worker-spawn rate;
- duplicate-work rate;
- worker rejection rate;
- resume vs changed-basis respawn rate;
- stale-result rejection rate;
- authoritative-context growth;
- contradiction resolution quality;
- user-voice consistency.

> Measure parallelism by quality + latency + compute, not worker count.

A parallel strategy that creates more workers but increases cost, context
pollution, contradiction, or latency without meaningful quality gain is a
regression, not an improvement.

<!-- C011_SINGLE_VOICE_PARALLEL_COGNITION_END -->

<!-- C012_SELF_OPTIMIZATION_SANDBOX_BEGIN -->

## C-012 - Self-Optimization Sandbox

**Status:** QUEUED

**Principle:** Optimize freely in the sandbox; promote only with evidence.

Luna may investigate and propose improvements to its own supporting system, but
self-optimization must remain separated from production authority.

Candidate optimization classes may include:

- code and algorithm changes;
- tool-selection or orchestration policies;
- configuration changes;
- inference / serving optimizations;
- training or fine-tuning recipe candidates;
- retrieval, caching, batching, scheduling, or resource-use improvements.

### Controlled optimization loop

```text
observe bottleneck / opportunity
            |
            v
form optimization hypothesis
            |
            v
produce candidate change
            |
            v
SANDBOX / CONTROLLED REPLAY
            |
            v
independent verification
            |
            v
baseline-vs-candidate comparison
            |
            v
IMPROVEMENT GATE
      |       |       |
   PROMOTE  REJECT  ROLLBACK
```

The optimization workspace may experiment. Production does not inherit the
candidate merely because Luna created it or because one metric improved.

### Authority boundary

Luna MUST NOT:

- directly rewrite or replace production state without an external promotion gate;
- treat its own claim of success as independent evidence;
- self-promote a candidate;
- silently expand permissions, blast radius, or optimization scope;
- bypass frozen held-out / OOD evaluation;
- hide quality or safety regression behind latency, throughput, or cost gains;
- recursively approve its own self-modification chain.

Promotion remains an explicit authority boundary outside the optimization
workspace.

### Evidence contract

Every optimization candidate should preserve:

```text
candidate_id
base_revision
changed_scope
optimization_hypothesis
expected_benefit
measured_results
independent_evidence
quality_delta
safety_delta
latency / throughput delta
compute / memory / cost delta
known_regressions
reproduction_steps
rollback_plan
provenance
decision
```

Claims must be reproducible against a known baseline and evaluation revision.

### Decision rules

- Critical safety or correctness regression -> **REJECT**.
- Evaluation contamination -> **REJECT**.
- Missing independent evidence -> **INSUFFICIENT_EVIDENCE**.
- Missing reproducibility or rollback evidence -> no production promotion.
- Efficiency gain with material quality regression -> **REJECT** unless an
  explicitly governed tradeoff policy authorizes that exact tradeoff.
- Aggregate score alone cannot authorize promotion.
- Successful sandbox evidence remains candidate evidence until the promotion
  authority accepts it.

### Bounded self-optimization

Self-optimization must have explicit:

- time / token / GPU / memory / tool budgets;
- maximum iteration and delegation depth;
- allowed file / subsystem scope;
- sandbox isolation;
- cancellation and timeout;
- deterministic or independently repeatable verification where possible;
- stop conditions for contradictory evidence;
- changed-basis replanning after failed attempts;
- audit trace linking hypothesis -> experiment -> evidence -> decision.

The system should prefer the smallest independently testable optimization
before attempting wider changes.

### Relationship to Phase 19F

Phase 19F Improvement Gate provides the governance pattern that C-012 must reuse:

```text
candidate
  -> identity / provenance validation
  -> frozen baseline comparison
  -> held-out / OOD evaluation
  -> critical regression checks
  -> meaningful thresholds / confidence
  -> independent evidence
  -> PROMOTE / REJECT / ROLLBACK / INSUFFICIENT_EVIDENCE
```

C-012 does not weaken Phase 19F. It creates a controlled source of future
optimization candidates that must still pass an evidence-based gate.

> A system may propose its own improvement. It may not certify itself improved.

<!-- C012_SELF_OPTIMIZATION_SANDBOX_END -->

<!-- ROADMAP_DEPENDENCY_REVIEW_BEGIN -->

## Roadmap Dependency Review

The queued capability implementation order is now governed by
`docs/ROADMAP_DEPENDENCY_REVIEW.md`.

Current recommended sequence:

```text
C-002 Capability Lineage Mapping
 -> C-001 Adaptive Knowledge Retrieval
 -> C-003 Experience Distillation
 -> C-005 Advanced Debugging Transfer
 -> C-006 Cross-Agent Experience Mining
 -> C-004 Pre-deployment Inheritance
 -> C-011 Single-Voice Parallel Cognition
 -> C-012 Self-Optimization Sandbox
```

This sequence is a planning recommendation, not an implementation claim.

Before assigning a new numbered phase, reconcile this review with any existing
canonical Phase 20 contract so the project does not silently reuse a phase
number for a different purpose.

<!-- ROADMAP_DEPENDENCY_REVIEW_END -->

<!-- LEGACY_ROADMAP_RECONCILIATION_BEGIN -->

## Legacy Roadmap Reconciliation

The historical `LUNA_GUNCELLENMIS_FAZ_PLANI_V2.md` was reconciled with current
repository reality.

Canonical reservations preserved:

```text
Phase 20 — Final Conformance Comparison and Release Candidate
Phase 21 — Post-v0.1 Research
```

Consequences:

- **C-002 must not be named Phase 20A.**
- C-002 remains the recommended next capability implementation.
- Recommended C-002 branch: `capability/c002-lineage-foundation`.
- C-011 remains a QUEUED governed parallel-cognition design.
- C-012 remains a QUEUED governed self-optimization-sandbox design.
- Uncontrolled self-modification remains prohibited.
- Automatic deployment / external actions require separate security governance.
- New roadmap discoveries require an explicit Delta Review.

Full reconciliation and Phase 20/21 contracts:

`docs/LEGACY_ROADMAP_RECONCILIATION.md`

<!-- LEGACY_ROADMAP_RECONCILIATION_END -->\n\n<!-- C002_LINEAGE_IMPLEMENTATION_BEGIN -->\n\n## C-002 Capability Lineage Implementation Checkpoint\n\nC-002 now has a read-only canonical registry, dependency validation, repository evidence/freshness\nmetadata, and deterministic blast-radius queries. It remains `IMPLEMENTED_UNVERIFIED` until final\nmerge/CI evidence supports a separate verified status transition.\n\nSource inspection also found that the dependency-review shorthand labels for C-005/C-006 conflict\nwith the explicit capability-queue identities C-005/C-006/C-007/C-009 above. C-002 preserves the\nexplicit queue identities and does not silently renumber them. Any correction to the recommended\nimplementation order requires a Delta Review.\n\nC-002 grants no runtime authority, promotion authority, automatic roadmap mutation, training, worker\nexecution, or self-optimization execution.\n\n<!-- C002_LINEAGE_IMPLEMENTATION_END -->\n
