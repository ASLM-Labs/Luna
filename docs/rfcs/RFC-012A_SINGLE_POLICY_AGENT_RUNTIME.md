# RFC-012A — Single Policy-Agent Runtime Contracts

**Status:** ACCEPTED_FOR_PHASE_12A
**Date:** 2026-08-06
**Scope:** Contracts and dependency boundary only; no agent loop or side effects.

## 1. Decision

Luna will use one active identity, one authoritative `TaskState`, and one runtime-owned
policy-agent loop. Phase 12A does not implement that loop. It freezes the request,
identity, budget, dependency, fingerprint, usage, stop-reason, and outcome contracts
that the later orchestrator must obey.

```text
RuntimeRequest
→ future LunaRuntime.run / resume
→ RuntimeOutcome
```

The model may later propose actions, but it cannot establish actor authority, raise
autonomy, change budgets, execute tools directly, or assign completion status.

## 2. Non-goals

Phase 12A deliberately does not add:

- an orchestrator or action loop;
- tool selection;
- context composition beyond existing Phase 2 contracts;
- failure taxonomy;
- web, GitHub, MCP, plugin, desktop, Discord, or voice integration;
- subagents;
- model training or self-modification.

Atlas architecture and migration artifacts are not inputs to this RFC.

## 3. Runtime request boundary

`RuntimeRequest` contains the complete runtime-owned envelope before intent
resolution or planning:

- stable request, task, and trace identifiers;
- raw request text;
- authenticated request source;
- verified actor and role;
- task scope;
- runtime-owned autonomy policy;
- context and execution budgets;
- context candidates and contract constraints;
- risk, priority, execution mode, and optional resume target.

A request is rejected before execution when its identifiers, scope, budgets, mode,
or authority are incoherent.

## 4. Request source and actor authority

Supported initial sources are desktop, web UI, voice, Discord, scheduler, internal
research, system event, and deterministic test.

Actor roles are owner, trusted team, community, guest, and system. Privileged roles
must be verified by a runtime or gateway source. Model text, conversational warmth,
or a claimed user name cannot establish authority.

## 5. Runtime budgets

Budgets are hard limits, not hints. Read-only is the default:

- zero changed files;
- zero added/deleted lines;
- zero network requests.

Write or network capability requires an explicit non-zero budget and a matching task
scope. The future loop must stop with `BUDGET_EXHAUSTED` instead of silently
continuing or weakening the task contract.

## 6. Duplicate-task fingerprint

A deterministic SHA-256 task fingerprint is produced from normalized goal, actor
scope, request source, workspace scope, path boundaries, and contract constraints.
Transient request/task/trace IDs are intentionally excluded.

The fingerprint is only a duplicate candidate. It is not permission, evidence, or a
completion signal. Later queue logic must still compare active task state and user
intent before merging tasks.

## 7. Dependency injection

The future orchestrator receives existing Luna services explicitly. Phase 12A names
these dependencies:

- task preparer;
- planner;
- model backend;
- tool dispatcher;
- completion gate;
- report composer;
- continuity service;
- verified memory service.

No module-global service locator or silent fallback is permitted.

## 8. Runtime outcome

`RuntimeOutcome` is the only authoritative return envelope for run, resume, suspend,
or cancel operations. It links:

- request/task/trace IDs;
- task fingerprint;
- authoritative `TaskState`;
- explicit stop reason;
- completion status and final report reference;
- checkpoint, observation, evidence, and memory decision references;
- resource usage;
- reasons and unresolved uncertainty;
- start and finish timestamps.

A `COMPLETED` result requires a closed task, `VERIFIED_COMPLETE`, and a final report
reference. The runtime outcome must agree with the authoritative state.

## 9. Compatibility

Phase 12A is additive. It does not change the Phase 1–11 state machine, verifier,
completion gate, audit ledger, memory policy, or release suite. The existing Phase 11
locked suite remains revision `1.0.0` and is not modified.

## 10. Acceptance gate

Phase 12A passes only when:

- all Phase 1–11 tests and verifiers remain green;
- runtime contracts round-trip deterministically;
- privileged unverified roles are rejected;
- read-only requests cannot carry write/network budgets;
- resume identifiers are coherent;
- fingerprints ignore transient IDs but change with task meaning or scope;
- completed outcomes remain gate-bound;
- explicit dependencies are complete and immutable;
- Ruff and mypy strict pass on Python 3.12 and 3.13 CI.

## 11. Follow-up

- Phase 12B: layered context composer.
- Phase 12C: action proposal and tool candidate policy.
- Phase 12D: failure taxonomy and minimal-change policy.
- Phase 12E: single policy-agent loop.
- Phase 12F: finalization.
- Phase 12G: end-to-end and behavior acceptance.
