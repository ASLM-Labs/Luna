# RFC-012D — Failure Recovery, Minimal Change, and Risk-Based Isolation

**Status:** ACCEPTED_FOR_PHASE_12D
**Date:** 2026-08-07

## Purpose

Phase 12D adds deterministic recovery policy between Phase 12C action selection and the
future Phase 12E single policy-agent loop. Failure classification, retry authority,
workspace change budgets, and isolation strength are runtime-owned decisions.

## Failure taxonomy

The runtime classifies structured evidence into these stable categories:

- `INVALID_ACTION`
- `PERMISSION_OR_SCOPE_DENIED`
- `STALE_STATE`
- `TRANSIENT_ENVIRONMENT`
- `DETERMINISTIC_EXECUTION`
- `VERIFICATION_FAILURE`
- `INTEGRITY_FAILURE`
- `BUDGET_EXHAUSTED`
- `RESOURCE_UNAVAILABLE`
- `UNKNOWN_FAILURE`

Model prose cannot mark an arbitrary failure as transient. Tool transience is recognized
only from a runtime-owned exact error-class allowlist.

## Recovery policy

Allowed recovery actions are:

- `RETRY`
- `REPLAN`
- `REINSPECT`
- `REQUEST_APPROVAL`
- `ROLLBACK`
- `SUSPEND`
- `STOP`

`RETRY` is legal only for an approved transient failure and an existing
`RetryDecision(CHANGED_BASIS)` with explicit changed dimensions. A fresh action is not
used as retry authority, and a transient label alone never permits repeating the same
attempt.

Permission or scope denial requires explicit authority rather than retry. Stale state
requires reinspection. Verification failure after a mutation requires rollback.
Integrity failure and hard budget exhaustion stop safely. Resource unavailability
suspends instead of spinning.

## Minimal-change policy

Every proposed workspace mutation declares a `ChangeEstimate` containing exact touched
paths and line-change bounds. Runtime checks:

1. write scope is enabled;
2. all paths are inside `allowed_paths`;
3. no protected path is touched;
4. changed-file budget is respected;
5. added-line budget is respected;
6. deleted-line budget is respected;
7. the mutation has a declared line-level effect.

After mutation, the observed change is checked again. Observed paths must be a subset of
the approved path set, and observed line changes cannot exceed the approved estimate.
This is the Phase 12D scope-creep boundary.

## Isolation policy

Isolation is selected by runtime task risk:

- no workspace mutation → `NONE`;
- LOW / MEDIUM mutation → `SNAPSHOT`;
- HIGH / CRITICAL mutation → `WORKTREE`.

If a required worktree is unavailable, the runtime returns a denied isolation decision.
It must not silently downgrade a HIGH/CRITICAL task to snapshot-only execution.

Phase 12D defines the worktree requirement and decision contract only. Creating,
resuming, and cleaning an actual Git worktree belongs to the Phase 12E orchestrator and
its execution services.

## Execution boundary

Phase 12D policy objects are pure decision components. They do not call tool handlers,
`ToolDispatcher`, `WorkspaceMutator`, rollback execution, subprocesses, network, or Git.
The future Phase 12E runtime orchestrator consumes these decisions and performs approved
side effects through existing runtime-owned execution services.

## Non-goals

Phase 12D does not implement:

- `LunaRuntime.run()` / `resume()`;
- automatic tool execution;
- actual Git worktree lifecycle;
- model rollout;
- web/GitHub/plugin integrations;
- subagents or uncontrolled self-modification.
