# C-011 S4 Bounded Live Read-Only Workers

Status: `C011_S4_LIVE_WORKERS_ACCEPTED`

Owner authorization date: 2026-08-28

Evidence date: 2026-08-29

Baseline commit: `144c2d1bf7fef6a71d1246761f50086cb9868e34`

Baseline tree: `aa0b4446fc98d8e776846f30694ab14b5516bb37`

## Outcome

S4 implements the bounded C-011A live-capable vertical while leaving it default-off:

- an absolute-executable, shell-free subprocess boundary with explicit environment,
  file-bounded output, cooperative cancellation, terminate/kill escalation and
  ephemeral scratch cleanup;
- an exact size/digest/freshness context broker with root-side secret redaction and no
  worker tools, credentials, inherited memory, network or write handles;
- root-owned current S3 admission and all four S3 fences around zero-to-three,
  depth-one attempts;
- a separate S4 SQLite journal that reserves before spawn, refuses blind replay of an
  in-doubt reservation, binds terminal receipts and handoffs, and append-records a fresh
  current-state decision before a durable handoff is reused;
- a generic, optional root-context extension boundary. Core `luna.runtime` imports no
  C-011 module, and absent/disabled injection preserves the solo path;
- root context receives only qualified `DistilledHandoff` artifacts plus root
  consideration receipts. Raw worker output never crosses this boundary.

The deterministic fixture starts local child processes to prove bounded process
lifecycle behavior. It does not call a real model/provider or establish controlled
C-011 execution.

## Evidence classification

### VERIFIED

- Current branch and baseline identity were reverified before S4 implementation.
- Focused S4 fixtures pass `10` cases; the combined C-011 plus solo-boundary targeted
  suite passes `84` cases.
- Default policy is disabled and kill-switched; maximum total and concurrent workers
  are both three, and delegation depth remains one.
- Backend admission denies an implementation missing any bounded-liveness capability.
- Cancellation, timeout, terminate/kill cleanup, no ambient credential inheritance,
  changed source digest, false redaction declaration, durable no-replay, three-lane
  concurrency, fresh reuse fencing, one voice and unchanged `TaskState` are covered.
- Changed-scope Ruff and strict mypy pass.
- The exact staged-tree full local gate passes `1377` tests with one recorded Windows
  symlink-platform skip; repository-wide Ruff, strict mypy, every verifier and CLI
  smoke pass the complete `51/51` chain.

### INFERENCE

- A generic data-only runtime extension is a smaller and safer coupling surface than a
  direct C-011 import inside the authoritative runtime loop.
- A dedicated append-only reuse-fence journal preserves the accepted S3 invariant of
  one phase instance per execution attempt while still requiring a fresh check for
  each later root consideration.

### OPEN

- Real model/profile routing, production numeric budgets and promotion criteria remain
  owner decisions.
- Process termination is proven for deterministic local fixtures; stronger OS sandbox
  and credential-isolation attestation remains open.
- Local SQLite validation does not replace an external integrity anchor or MAC against
  a complete internally valid rollback/rewrite.
- C-011 remains `QUEUED`; default-off code acceptance is not deployment, live-model
  acceptance, or capability promotion.

## Gate state

```text
C-011 capability: QUEUED
S4 gate: C011_S4_LIVE_WORKERS_ACCEPTED
default enabled: false
live model execution: NONE
controlled C-011 execution: NONE
production rollout: NONE
worker write/tool/network/process/delegation/memory/completion authority: NONE
root user-facing voice: MAIN LUNA ONLY
solo runtime default: unchanged
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
controlled execution: NONE
```

ASLM Research is a separate project and was not evaluated or modified by Luna S4. No
hidden chain-of-thought access, persistence, reconstruction or claim is part of S4.
