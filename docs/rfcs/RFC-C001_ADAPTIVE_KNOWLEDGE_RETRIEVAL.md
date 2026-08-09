# RFC-C001 — Adaptive Knowledge Retrieval

Status: IMPLEMENTED_UNVERIFIED

## Purpose

C-001 gives Luna a deterministic decision layer for choosing the appropriate knowledge source instead
of treating every information request as a generic search problem.

The capability answers one question:

> Which source family should be trusted for this request, and is retrieval actually necessary?

C-001 is a routing capability. It does not create new network authority, execute arbitrary tools, or
turn retrieved material into long-term memory automatically.

## Canonical source families

```text
INTERNAL
WORKING_CONTEXT
VERIFIED_MEMORY
PROJECT_RAG
RESEARCH_GATEWAY
STRUCTURED_API
```

The router consumes observable request properties and source availability. It never assumes a source
exists merely because that source family is defined.

## Routing order

The deterministic safety order is:

```text
contradictory evidence
  -> STOP_REINSPECT

fresh working context that already answers the request
  -> WORKING_CONTEXT

user-specific knowledge
  -> VERIFIED_MEMORY
  -> authorized structured API when current structured data is required
  -> otherwise STOP_REINSPECT

document/project-specific knowledge
  -> PROJECT_RAG
  -> otherwise STOP_REINSPECT

current or fast-changing knowledge
  -> STRUCTURED_API when suitable and available
  -> RESEARCH_GATEWAY
  -> otherwise STOP_REINSPECT

high uncertainty / explicit external verification
  -> STRUCTURED_API when suitable and available
  -> RESEARCH_GATEWAY
  -> otherwise STOP_REINSPECT

stable + low uncertainty + sufficiently known
  -> INTERNAL
```

Public research is not a fallback for missing private/user-specific knowledge.

## Contradiction boundary

Contradictory evidence is stronger than convenience. If the caller reports contradictory evidence,
C-001 returns `STOP_REINSPECT` before selecting another source.

Confidence is not truth, and a model's own answer is not independent evidence.

## Freshness and provenance

Research Gateway and structured API routes require freshness tracking and provenance/citation. The
router itself performs no network request. Existing Phase 14 network/domain/budget/injection policies
remain authoritative for research execution.

Project/document RAG and verified memory are selected only when the caller reports those governed
sources as available.

## Memory boundary

```text
retrieval result
-> observation/evidence
-> working context
-> optional memory candidate
-> review
-> verified memory
```

`automatic_memory_commit_allowed` is always false.

## Authority boundary

C-001 cannot:

- enable network access;
- bypass Phase 14 Research Gateway policy;
- authorize external actions;
- create or promote a model;
- write verified memory automatically;
- invent unavailable project RAG/API sources;
- mutate the roadmap automatically.

## Evaluation dimensions

Primary evaluation candidates are:

- source-selection accuracy;
- unnecessary retrieval rate;
- missed retrieval rate;
- stale-answer rate;
- evidence sufficiency;
- contradiction detection;
- provenance/citation correctness;
- retrieval latency;
- retrieval cost.

## Out of scope

This implementation does not add a generic project vector database, a new web backend, API credentials,
or autonomous retrieval execution. Existing governed source systems remain separate boundaries.

C-001 may select a source only when that source is reported available. Otherwise it stops or selects a
safer existing source according to policy.
