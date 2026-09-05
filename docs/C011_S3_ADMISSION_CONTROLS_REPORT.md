# C-011 S3 Admission and Hierarchical Controls

Status: `C011_S3_ADMISSION_CONTROLS_ACCEPTED`

Next gate: `C011_S4_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`

Owner authorization date: 2026-08-28

Acceptance evidence date: 2026-08-28

Baseline commit: `5620d8e428f003b1ca5c8a6392e64e213145132a`

Baseline tree: `64ab6a54d168d43286f68043cbd9ab27ec9df935`

## Outcome

S3 adds an isolated, non-executable control plane under `luna.parallel_cognition`:

- whole-plan current-state admission rebuilt from actual task, policy, capability,
  root-lease and source objects;
- explicit zero-to-three worker, depth-one, per-worker and aggregate ceilings with no
  permissive production defaults;
- runtime-owned rechecks before creation, execution, result admission and root
  consideration;
- atomic pre-start denial/cleanup and durable late, cancelled or wrong-runtime result
  quarantine;
- authoritative source, evidence and observation resolution that recomputes content
  digests instead of trusting worker identifiers;
- deterministic, arrival-order-independent reconciliation where disagreement produces
  `CONFLICT` and malformed or ineligible inputs produce `VERIFY`;
- `ACCEPT` means eligible for root consideration only. It grants no state mutation,
  completion, automatic adoption or user-facing voice authority.

S3 does not wire `LunaRuntime`, create a live worker, call a model, tool, network or
child process, mutate `TaskState`, or promote C-011 beyond `QUEUED`.

## Evidence classification

### VERIFIED

- The branch started from accepted S2 commit
  `5620d8e428f003b1ca5c8a6392e64e213145132a`; local `main` and `origin/main` were both
  `0154390581e6f145eb8b912fe91595cdd54496af` when S3 state was reverified.
- The focused S3 suite passes `24` tests.
- The combined S1/S2/S3 suite passes `72` tests.
- Changed-scope Ruff and strict mypy pass.
- The exact staged-tree full local gate passes `1364` tests with one recorded Windows
  symlink-platform skip; repository-wide Ruff, strict mypy, all verifiers and CLI smoke
  pass the complete `50/50` chain.
- Adversarial fixtures cover zero and three workers, whole-plan budget denial, fresh
  rechecks, pre-start and in-flight cancellation, late/wrong-runtime quarantine,
  store migration/tamper, source/evidence/observation resolution, fabricated/stale/
  cross-task/digest-changed rejection, pre-adoption subject binding, arrival-order
  stability and two-to-one contradiction.

### INFERENCE

- Explicit policy-supplied limits are safer than guessed production defaults.
- Exact agreement plus root-issued claim keys is the smallest deterministic
  reconciliation rule consistent with one authoritative Luna voice.

### OPEN

- Real interruptible backend isolation, termination proof, feature flag/kill switch,
  root-context adoption and one-voice live integration remain S4.
- Local SQLite hash chains still require an external anchor or MAC to detect a complete
  internally valid rollback or authorized full-chain rewrite.
- Production budget values and retention policy require separate owner judgment.

## Gate state

```text
C-011 capability: QUEUED
S3 gate: C011_S3_ADMISSION_CONTROLS_ACCEPTED
next gate: C011_S4_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION
production Ultra/subagents: NOT IMPLEMENTED
production coordination call sites: NONE
live C-011 execution: NONE
controlled C-011 execution: NONE
worker completion authority: NONE
solo runtime default: unchanged
```

ASLM Research is a separate project and was not evaluated or modified by Luna S3.
No hidden chain-of-thought access, persistence, reconstruction or claim is part of S3.
