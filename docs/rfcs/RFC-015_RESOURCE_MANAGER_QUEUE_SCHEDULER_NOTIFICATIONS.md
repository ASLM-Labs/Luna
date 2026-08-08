# RFC-015 — Resource Manager, Durable Queue, Scheduler, and Notifications

**Status:** ACCEPTED_FOR_PHASE_15

## 1. Purpose

Phase 15 adds Luna's first durable operations layer for work that may wait, become due,
compete for bounded resources, and produce owner-visible events over time.

The governing rule is:

> Becoming eligible for execution is not the same as being authorized to execute.

The Phase 15 components coordinate already-authorized runtime requests. They do not
replace `LunaRuntime`, the tool dispatcher, completion verification, or evidence policy.

## 2. Authority boundary

A queued unit of work is a `WorkEnvelope` containing both:

- the authoritative `RuntimeRequest`;
- an already-bounded `ToolPolicy` that cannot exceed the request's autonomy, tool, risk,
  or FREE_RESEARCH authority.

The queue, scheduler, resource manager, and notification outbox cannot add tools,
network access, workspace writes, process permission, risk ceiling, or completion truth.

```text
already-authorized RuntimeRequest + ToolPolicy
→ durable queue
→ scheduler eligibility
→ resource admission
→ dispatch fence
→ LunaRuntime.run/resume
→ RuntimeOutcome
→ queue finalization + local notification outbox
```

Only the runtime invocation boundary executes the task.

## 3. Shared durable store

`SQLiteOperationsStore` uses short-lived SQLite connections with:

- WAL journaling;
- `synchronous=FULL`;
- `busy_timeout=5000`;
- foreign-key enforcement;
- canonical JSON payloads;
- SHA-256 integrity checks.

One database transaction boundary is shared by queue items, schedules, resource leases,
and the local notification outbox.

## 4. Durable queue

The queue is idempotent by a 64-character SHA-256 idempotency key. Reusing a key for a
different immutable payload is a conflict, not an overwrite.

Ready work is ordered deterministically by:

1. runtime priority, highest first;
2. eligibility time, oldest first;
3. stable SQLite insertion order.

Queue priority is a scheduling preference only. `CRITICAL` priority grants no additional
runtime authority.

## 5. Dispatch replay fence

The queue has separate `LEASED` and `DISPATCHED` states.

A worker first receives a queue/resource lease. Immediately before calling LunaRuntime,
the coordinator persists a dispatch fence:

```text
QUEUED → LEASED → DISPATCHED → LunaRuntime invocation
```

If a lease expires while still `LEASED`, no runtime call has been fenced and the item may
be safely requeued.

If a lease expires after `DISPATCHED`, the runtime may have executed. The item becomes
`RECOVERY_REQUIRED` and its resource reservation becomes `STALE`. It is never blindly
requeued or retried.

This preserves the Phase 12E no-blind-replay rule at the operations layer.

## 6. Resource Manager

`ResourceManager` enforces bounded coordinator capacity for:

- worker slots;
- model slots;
- network slots.

Resource allocation is not permission. A network slot cannot manufacture a
network-enabled `RuntimeRequest`, and a resource lease cannot expand tool or autonomy
policy.

Both `ACTIVE` and `STALE` reservations count against capacity. Ambiguous dispatched work
therefore cannot silently free capacity and cause unsafe overcommit.

## 7. Scheduler

Phase 15 supports two deterministic UTC schedule forms:

- `ONE_SHOT`;
- `FIXED_INTERVAL` with a minimum interval of 60 seconds.

The scheduler only materializes due occurrences into the durable queue. It has no runtime
executor dependency and does not call tools, models, research backends, or LunaRuntime.

Catch-up materialization is explicitly bounded per call.

Fixed-interval occurrences receive deterministic fresh request/task/trace IDs so one
completed task is never reused as a new runtime task. Task-bound Level 4 FREE_RESEARCH
authority cannot be cloned into a recurring schedule; such schedules are rejected.

## 8. Coordinator

`OperationsCoordinator.dispatch_one()` admits at most one runtime invocation per call.
It:

1. performs safe expired-lease recovery;
2. selects ready queue work;
3. obtains resource capacity;
4. persists the queue lease;
5. persists the `DISPATCHED` may-have-executed fence;
6. calls `LunaRuntime.run()` or `LunaRuntime.resume()` according to the existing request;
7. atomically records the `RuntimeOutcome`, releases capacity, and inserts a local
   notification event.

If the runtime call raises after the dispatch fence, the item moves to
`RECOVERY_REQUIRED`; the coordinator does not retry it.

## 9. Notifications

Phase 15 notifications are a local durable outbox only. There is no email, webhook,
Discord, desktop-push, SMS, or other external delivery transport in this phase.

Notification truth is derived from `RuntimeOutcome`, never from model prose.

A `TASK_VERIFIED_COMPLETE` notification requires:

- `RuntimeStopReason.COMPLETED`;
- `CompletionStatus.VERIFIED_COMPLETE`;
- a verification report ID;
- a final report ID.

All other resumable/blocked outcomes use a needs-attention event, and cancellation uses a
cancelled event. Notifications preserve outcome IDs and are idempotent by a deterministic
dedupe key.

## 10. Cancellation and suspension

A queue item may be cancelled directly only while it is still `QUEUED` and therefore has
no worker lease or dispatch fence.

Once runtime execution is fenced, cancellation/suspension remains the responsibility of
the existing durable `LunaRuntime.cancel()` / `LunaRuntime.suspend()` control boundary.
Phase 15 does not force-kill an in-flight handler.

## 11. Deliberate limits

Phase 15 does not add:

- external notification transports;
- operating-system background services;
- webhook triggers;
- distributed multi-node scheduling;
- automatic replay of ambiguous work;
- cloned FREE_RESEARCH grants for recurring jobs;
- automatic memory persistence;
- external account actions;
- desktop, Discord, or voice product gateways.

Those capabilities must build on the Phase 15 durable contracts rather than bypass them.

## 12. Acceptance

Phase 15 is accepted only when:

- queue/schedule/resource/outbox state survives SQLite reopen with SHA-256 integrity;
- queue idempotency conflicts fail closed;
- scheduler eligibility never invokes runtime by itself;
- resource capacity cannot grant runtime authority or oversubscribe configured limits;
- expired pre-dispatch leases may requeue safely;
- expired dispatched leases become recovery-required and never blind replay;
- runtime exceptions after the dispatch fence do not trigger retry;
- successful dispatch finalization and resource release are atomic with outbox creation;
- verified-complete notifications are impossible without authoritative verification;
- external notification delivery remains disabled;
- recurring schedules use fresh task IDs and cannot clone task-bound FREE_RESEARCH grants;
- Phase 14 remains green;
- metadata integrity, pytest, Ruff, mypy strict, and deterministic gates pass.
