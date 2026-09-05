# C-011 S5B Local-Native Driver Adapter

Status: `C011_S5B_LOCAL_NATIVE_DRIVER_ADAPTER_ACCEPTED`

Owner authorization date: 2026-08-30

Evidence date: 2026-08-30

Baseline commit: `3d302c1ace97d65c612cd4c040c5d54f3c5bec00`

Baseline tree: `bca0ae37a9e57e1f7c71782cad44aef656382171`

## Outcome

S5B adds a fixture-first local-native driver adapter that composes two already accepted
boundaries without adding a production route:

- S5A exact-profile selection is recomputed immediately before execution and must still
  be non-executable `SHADOW_ELIGIBLE` for the same profile and backend;
- the approved binding content-addresses the profile/backend, absolute executable,
  driver and model paths and hashes, the exact explicit child-environment digest, and
  the protocol version;
- only a `fixture:*` NR-2B Slice 1 profile and `DETERMINISTIC_FIXTURE` mode are admitted;
- S4 retains shell-free process creation, bounded output, cooperative cancellation,
  terminate/kill escalation and ephemeral cleanup;
- all three artifacts are canonical regular files and are hashed before and after the
  delegated execution;
- S4 result identities remain unchanged. A separate S5B result subtype binds the exact
  provider binding ID and retains zero state, completion and user-facing voice authority.

The default S5B policy is disabled and kill-switched. The adapter is not wired into the
production Luna runtime. A real local-native model/provider was not called.

## Evidence classification

### VERIFIED

- Current branch, accepted S5A baseline and unchanged local/remote `main` identities were
  reverified before mutation.
- The focused S5B suite passes `13` cases; changed-scope Ruff and strict mypy pass.
- Tests cover content tampering, missing binding approval, default/kill denial, current
  provider-policy/compatibility/resource drift, request/profile mismatch, pre-spawn and
  post-execution artifact drift, ambient-secret exclusion, cooperative cancellation,
  timeout/termination/cleanup, and non-fixture profile rejection.
- Deterministic temporary fixture child processes executed. No real provider/model,
  credential, network or production runtime call occurred.
- The exact staged-tree full local gate passes `1409` tests with one recorded Windows
  symlink-platform skip; repository-wide Ruff, strict mypy, every verifier and CLI smoke
  pass the complete `53/53` chain.

### INFERENCE

- Composing S5A admission with S4 process controls is the smallest testable boundary for
  a later real local-native evidence run while preserving default-off production behavior.
- A distinct S5B result subtype avoids silently changing already accepted S4 content
  identities and makes the provider binding independently auditable.

### OPEN

- Current deployment-host executable, driver and model asset identities and their trusted
  provenance.
- Current workstation CPU/GPU/RAM values, justified numeric ceilings and a real
  compatibility report for the exact assets.
- Race-free OS containment between artifact verification and process loading, stronger
  process sandbox attestation, and external journal anchoring.
- Real local-native execution evidence, equal-compute non-inferiority, S5C
  non-authoritative shadow evaluation and every later promotion decision.

## Gate state

```text
C-011 capability: QUEUED
S5B gate: C011_S5B_LOCAL_NATIVE_DRIVER_ADAPTER_ACCEPTED
next evidence gate: C011_S5B_REAL_LOCAL_NATIVE_EXECUTION_BLOCKED_PENDING_EXTERNAL_EVIDENCE
default enabled: false
fixture child process executed: true
provider call executed: false
live model execution: NONE
controlled C-011 execution: NONE
controlled execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
production rollout: NONE
root user-facing voice: MAIN LUNA ONLY
```

ASLM Research is a separate project and was not evaluated or modified by Luna S5B. No
hidden chain-of-thought access, persistence, reconstruction or claim is part of S5B.
