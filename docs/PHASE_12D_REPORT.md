# Phase 12D — Failure Taxonomy + Minimal Change + Risk-Based Isolation

**Package status:** `IMPLEMENTED_UNVERIFIED`

## Added

- stable runtime-owned failure taxonomy;
- structured `FailureRecord` and `RecoveryDecision` contracts;
- `FailureClassifier` for Phase 12C denials, tool results, observations, stale state,
  verification, integrity, budget, and resource failures;
- exact transient-error allowlist instead of model-declared retryability;
- deterministic `RecoveryPolicy` for retry/replan/reinspect/approval/rollback/suspend/stop;
- changed-basis-only transient retry enforcement;
- `ChangeEstimate` and hard minimal-change path/file/line budgets;
- post-change scope-creep detection against the approved change estimate;
- `WorkspaceIsolationPolicy` with NONE/SNAPSHOT/WORKTREE modes;
- HIGH/CRITICAL worktree requirement with no silent snapshot downgrade;
- Phase 12D verifier, unit tests, RFC, CLI smoke, and quality-gate integration.
- Full MANIFEST/SHA256 reconciliation to repair stale Phase 12B/12C metadata hashes carried by the merged baseline.

## Security properties

- model prose cannot make an error transient;
- permission denial is not retryable;
- transient failure cannot retry without `CHANGED_BASIS` evidence;
- stale state requires fresh inspection;
- verification failure after mutation requires rollback;
- integrity failure and budget exhaustion stop safely;
- resource unavailability suspends instead of spinning;
- workspace writes cannot exceed declared scope or hard runtime budgets;
- observed mutations cannot expand beyond approved paths or line estimates;
- HIGH/CRITICAL isolation cannot silently downgrade when worktree support is unavailable;
- Phase 12D policy code performs no hidden execution.

## Deliberate boundary

Phase 12D decides recovery and isolation requirements but does not perform the actual
agent loop or Git worktree lifecycle. Phase 12E will orchestrate these policies with the
existing ToolDispatcher, workspace snapshot/rollback, checkpoint, and verification
services.

## Package-environment verification

Baseline Phase 12C source produced:

```text
Pytest baseline       242 passed
```

After Phase 12D implementation the isolated package environment is expected to produce:

```text
Python syntax         PASS
Pytest                267 passed
Phase 1-12C verifier  PASS
Phase 12D verifier    PASS
phase12d-smoke        PASS
```

Ruff and mypy strict must also pass in the target Windows `.venv` before merge.

## Target-machine closure

```bat
scripts\check_hold.bat
```

Expected final line:

```text
[PASS] Luna 0.1 Phase 12D recovery and isolation gate passed.
```
