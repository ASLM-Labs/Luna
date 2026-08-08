# Luna 0.1 — Phase 15 Report

## Status

`IMPLEMENTED_UNVERIFIED`

Phase 15 adds Luna's first durable operations layer. Tasks can now wait in an idempotent
queue, become eligible on a UTC schedule, compete for bounded resources, and produce
local outcome notifications without giving scheduling infrastructure any runtime
authority.

## Delivered

- `src/luna/operations/` package with shared SQLite store, durable queue, resource
  manager, UTC scheduler, local notification outbox, and runtime coordinator;
- WAL + FULL-sync operations persistence with canonical JSON and SHA-256 integrity;
- priority/eligibility ordering and idempotent queue insertion;
- pre-runtime `DISPATCHED` replay fence;
- safe requeue only for expired pre-dispatch leases;
- `RECOVERY_REQUIRED` + `STALE` resource semantics for ambiguous dispatched work;
- worker/model/network capacity limits that cannot expand runtime authority;
- one-shot and fixed-interval UTC schedules with bounded catch-up;
- deterministic fresh IDs for recurring occurrences;
- explicit rejection of recurring task-bound Level 4 FREE_RESEARCH authority;
- one-runtime-invocation-per-coordinator-dispatch boundary;
- atomic outcome finalization, resource release, and local outbox insertion;
- verification-bound success notifications and no external delivery transport;
- deterministic Phase 15 verifier, tests, CLI smoke, RFC, metadata, and CI gate.

## Operations flow

```text
RuntimeRequest + ToolPolicy
→ durable QueueItem
→ Scheduler marks/materializes eligible work
→ ResourceManager capacity lease
→ Queue LEASED
→ durable DISPATCHED fence
→ LunaRuntime.run/resume
→ RuntimeOutcome
→ atomic queue finalization + resource release + notification outbox
```

## Replay safety

```text
expired LEASED
→ safe resource release
→ QUEUED

expired DISPATCHED
→ resource STALE
→ RECOVERY_REQUIRED
→ no automatic replay
```

The second path intentionally prefers manual/runtime reconciliation over duplicated side
effects.

## Notification semantics

Phase 15 does not send notifications to external systems. It records channel-neutral
local events only. A success event is possible only when the authoritative runtime
outcome is `COMPLETED` with `VERIFIED_COMPLETE` plus verification/final-report evidence.

## Deliberate limitations

Phase 15 is a single-database local operations layer, not a distributed scheduler.
External notification channels, OS service hosting, webhook triggers, multi-machine
workers, and product-facing notification UX remain later phases.

## Target-machine closure

```bat
scripts\check_hold.bat
```

Expected final line:

```text
[PASS] Luna 0.1 Phase 15 resource manager, queue, scheduler, and notifications gate passed.
```
