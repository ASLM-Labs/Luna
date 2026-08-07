# Phase 12E — Single Policy-Agent Loop

**Package status:** `IMPLEMENTED_UNVERIFIED`

## Added

- `LunaRuntime.run()` and `resume()` as the first authoritative end-to-end policy-agent
  orchestrator;
- one Luna identity and one authoritative `TaskState` across the action/observation loop;
- provider-neutral `ModelPolicyAgent` that converts exactly one model tool call into an
  untrusted Phase 12C `ActionProposal`;
- durable SQLite runtime journal for safe control, write-ahead side-effect receipts, and
  bounded structured dispatch observations;
- recent tool observations fed back into later model turns as `DATA_ONLY`
  `RUNTIME_CONTINUITY` context;
- side-effect stages `PREPARED → STARTED → COMPLETED → OBSERVED → CHECKPOINTED`, with
  `ABORTED` available only before execution starts;
- crash-safe resume rules that never replay an ambiguous `STARTED` side effect;
- durable `suspend()` / `cancel()` control acknowledged only at safe runtime boundaries;
- exact runtime-side write-change inspection before and after supported writes;
- actual deterministic Git worktree lifecycle for HIGH/CRITICAL mutation isolation;
- effective isolated workspace continuity across subsequent actions, checkpoints, resume
  fingerprints, and safe cancellation cleanup;
- model/tool/network zero-budget disable gates and hard usage enforcement;
- Phase 12F handoff through `RuntimeStopReason.VERIFICATION_PENDING` rather than false
  completion;
- Phase 12E verifier, behavior tests, CLI smoke, RFC, metadata, and quality-gate wiring.

## Security and integrity properties

- model responses cannot grant role, permission, risk ceiling, retry authority, or
  completion;
- multiple model tool calls are rejected before dispatch, including multiple read calls;
- every action result is observed before the next policy-model decision;
- tool output is persisted as evidence but remains `DATA_ONLY` in model context;
- `ToolDispatcher` remains the only execution authority;
- side-effect execution is fenced durably before the handler can run;
- an interrupted `STARTED` action is never blindly replayed;
- a completed receipt can be reconciled without rerunning the handler;
- identical side effects are deduplicated per task step, not incorrectly across unrelated
  steps;
- pending cancel can abort a `PREPARED` action before execution;
- in-flight handlers are not force-killed;
- high-risk writes cannot silently fall back from WORKTREE to SNAPSHOT;
- subsequent actions cannot silently jump from an isolated task worktree back to the
  original checkout;
- final verified completion remains outside Phase 12E authority.

## Deliberate boundary

Phase 12E finishes the action/observation orchestration core but intentionally hands off
at `VERIFYING`. Phase 12F will connect deterministic completion verification, final report,
checkpoint finalization, evidence-strength/disagreement handling, and verified
memory/learning candidates to this loop.

## Package-environment verification

The assistant-side package environment must produce:

```text
Python syntax                    PASS
Pytest                           277 passed
Phase 1-12D regression verifiers PASS
Phase 12E verifier               PASS
phase12e-smoke                   PASS
```

The target Windows `.venv` remains authoritative for Ruff and mypy strict before commit
or push.

## Target-machine closure

```bat
scripts\check_hold.bat
```

Expected final line:

```text
[PASS] Luna 0.1 Phase 12E single policy-agent loop gate passed.
```
