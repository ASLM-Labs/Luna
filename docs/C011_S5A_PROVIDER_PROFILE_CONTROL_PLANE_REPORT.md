# C-011 S5A Provider/Profile Control Plane

Status: `C011_S5A_PROVIDER_PROFILE_CONTROL_PLANE_ACCEPTED`

Owner authorization date: 2026-08-29

Evidence date: 2026-08-30

Baseline commit: `4374d7e78bdb67e87dfebdeef24288520c44eb8f`

Baseline tree: `967a99a21c45460cb612ec10012752d466c8dc01`

## Outcome

S5A adds a pure, immutable and deny-by-default provider/profile control plane:

- profile identity binds provider kind, backend/model/driver identities, compatibility
  fingerprint, evidence reference, exact neural resource budget, assignment capacity
  and admitted worker roles;
- current compatibility, resource budget, assignment and injected routing policy are
  fully revalidated at selection time;
- the accepted NR-2B Slice 1 evidence boundary remains CPU-only, ephemeral, one
  generation at a time and at most 256 output tokens;
- default disabled and kill-switched policies deny; `CANARY` and `ACTIVE` are rejected;
- an exact match can produce only non-executable `SHADOW_ELIGIBLE` evidence. It grants
  no provider call, state/adoption, completion, worker voice or promotion authority.

The module has no provider, model, child-process, filesystem, network or production
runtime call site. S5A does not bind S4 to a driver and does not execute a fixture model.

## Evidence classification

### VERIFIED

- The current implementation baseline, branch and unchanged `main` identities were
  reverified before mutation.
- The focused S5A suite passes `17` cases; changed-scope Ruff and strict mypy pass.
- Content tampering, GPU/residency/parallel/output expansion, duplicate profiles,
  default/kill denial, stale compatibility, resource drift, role/budget expansion and
  `CANARY`/`ACTIVE` promotion attempts are rejected.
- Exact selection is only `SHADOW_ELIGIBLE`, with every execution, adoption, state,
  completion, voice and promotion authority fixed false.
- The exact staged-tree full local gate passes `1395` tests with one recorded Windows
  symlink-platform skip; repository-wide Ruff, strict mypy, every verifier and CLI
  smoke pass the complete `52/52` chain.

### INFERENCE

- A pure content-addressed registry is the smallest safe boundary between accepted S4
  process controls and a later local-native driver adapter.
- Reusing Phase 13 compatibility fingerprints and neural resource contracts reduces
  contradictory provider-specific policy surfaces.

### OPEN

- Current external model/driver asset paths and hashes on the deployment host.
- Target workstation CPU/GPU/RAM values and justified production concurrency ceilings.
- A real provider/profile compatibility run and equal-compute non-inferiority evidence.
- S5B driver binding, S5C non-authoritative shadow ledger, OS containment attestation,
  external journal anchoring and every S5D promotion decision.

## Gate state

```text
C-011 capability: QUEUED
S5A gate: C011_S5A_PROVIDER_PROFILE_CONTROL_PLANE_ACCEPTED
next gate: C011_S5B_LOCAL_NATIVE_DRIVER_ADAPTER_PENDING_IMPLEMENTATION
default enabled: false
provider call executed: false
live model execution: NONE
controlled C-011 execution: NONE
controlled execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
production rollout: NONE
root user-facing voice: MAIN LUNA ONLY
```

ASLM Research is a separate project and was not evaluated or modified by Luna S5A. No
hidden chain-of-thought access, persistence, reconstruction or claim is part of S5A.
