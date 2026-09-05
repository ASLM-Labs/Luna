# C-011 S2 Durable Event and Recovery Core

Status: `C011_S2_DURABLE_RECOVERY_ACCEPTED`

Next gate: `C011_S3_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`

Owner authorization date: 2026-08-24

Acceptance evidence date: 2026-08-26

Baseline commit: `8c82cab7eebafd04fdd6a7990115ac1019176ad1`

Baseline tree: `149bbc2b3274505a18b2b5d91a5527af37be9e6e`

## Scope

S2 adds an isolated durable coordination core under `luna.parallel_cognition`:

- a task-scoped SQLite event chain whose sequence, hashes and issuer fields are store-issued;
- a single active root lease with a memory-only fencing token and monotonically increasing
  coordination epoch;
- default-deny attempt lifecycle transitions and stale-epoch fencing;
- a deterministic in-process fake backend with durable request/result idempotency;
- store-authored outcome, cleanup, payload, and execution receipt committed atomically
  from exact durable fake results;
- durable recovery decisions that never blindly replay an ambiguous invocation.

S2 does not wire `LunaRuntime`, alter legacy C7 semantics, create a live worker, call a model,
tool, network or child process, mutate `TaskState`, or grant completion/user-voice authority.

## Evidence classification

### VERIFIED

- S1 is accepted at the declared baseline and its working tree was clean before S2.
- Live `origin/main`, local `main` and `origin/main` were identical when S2 began.
- The owner separately authorized S2 on 2026-08-24.
- RFC-C011 limits S2 to durable events, root lease/epoch, an idempotent fake backend and
  crash/recovery tests with no live execution.

### INFERENCE

- SQLite `BEGIN IMMEDIATE`, WAL and full synchronous durability are the smallest repo-aligned
  local transaction boundary for this stage.
- A memory-only lease token plus durable token digest is safer than owner-name resumption:
  losing the token after restart must fail closed until expiry and a new epoch.

### OPEN

- Store-mediated lease provenance does not cryptographically authenticate a human or OS process.
- An attacker able to replace the complete database with an older internally valid snapshot, or
  recompute the complete chain and durable head, requires an external anchor or MAC to detect.
- Production storage location, retention, cancellation semantics, evidence resolution, real
  backend isolation and live enablement remain later-stage decisions.

## Acceptance state

The deterministic S2 suite has `19 passed`; the combined S2, S1, C7, solo-runtime,
continuity, audit and metadata regression set has `195 passed`. The exact accepted staged-tree
full local gate has `1339 passed, 1 skipped`, repository-wide Ruff and strict mypy pass, and the
verifier/CLI chain passes `49/49`. S2 is accepted for this declared isolated durable-recovery
scope; C-011 remains `QUEUED` and no later-stage or production authority is granted.

```text
C-011 capability: QUEUED
production Ultra/subagents: NOT IMPLEMENTED
production coordination call sites: NONE
live C-011 execution: NONE
ASLM Research Saturation Gate: NOT_READY
ASLM Target Spec: BLOCKED
ASLM controlled execution: NONE
worker completion authority: NONE
solo runtime default: unchanged
```

No hidden chain-of-thought access, persistence, reconstruction or claim is part of S2.
