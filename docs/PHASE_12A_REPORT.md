# Phase 12A — Runtime Contracts and Dependency Boundary

**Package status:** `IMPLEMENTED_UNVERIFIED`

## Added

- authenticated `RequestSource` and runtime-owned `RuntimeActor` contracts;
- explicit `RuntimeBudget` with read-only defaults and bounded-write constructor;
- `RuntimeRequest` with task/trace identity, scope, autonomy, context, budgets,
  constraints, priority, mode, and resume coherence;
- versioned deterministic `TaskFingerprint` excluding transient IDs;
- explicit `RuntimeDependencies` and serializable dependency manifest;
- `RuntimeUsage`, `RuntimeStopReason`, and gate-bound `RuntimeOutcome`;
- RFC-012A and Phase 11 source baseline/evidence map;
- Phase 12A unit tests and structural/behavioral verifier.

## Security properties

- privileged actor roles require runtime verification;
- model output cannot be an actor verification source;
- read-only scope cannot carry write or network budget;
- write scope requires an explicit change budget;
- dry-run cannot authorize writes;
- resume target must match the authoritative task ID;
- `COMPLETED` requires closed state, `VERIFIED_COMPLETE`, and final report reference;
- orchestrator dependencies cannot silently fall back to globals.

## Deliberate boundary

Phase 12A does not implement `LunaRuntime.run()`, context composition, action/tool
selection, failure classification, or the agent loop. No network or external
integration is added.

## Package-environment verification

The supplied Phase 11 source baseline passed 193 tests and the Phase 11 verifier
before modification. The Phase 12A package environment produced:

```text
Python syntax       PASS
Pytest              205 passed
Phase 1-11 verifier PASS
Phase 12A verifier  PASS
phase12a-smoke      PASS
```

Ruff and mypy strict must run in the target Windows `.venv`; those tools were not
available in the isolated package environment. Final target status therefore remains
`IMPLEMENTED_UNVERIFIED` until `scripts\check_hold.bat` passes.

## Target-machine closure

```bat
scripts\check_hold.bat
```

Expected final line:

```text
[PASS] Luna 0.1 Phase 12A runtime contracts gate passed.
```
