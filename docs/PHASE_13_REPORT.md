# Luna 0.1 — Phase 13 Report

## Status

`IMPLEMENTED_UNVERIFIED`

Phase 13 introduces the first controlled bridge from the deterministic/scripted model
boundary to real model adapters. Compatibility testing, rollout authorization, and
runtime failure handling are separated so a model cannot gain authority merely by
responding successfully.

## Delivered

- provider-neutral model backend failure taxonomy;
- compatibility probe with required text, single-tool-call, and exact JSON argument checks;
- optional usage-accounting capability;
- stable compatibility report fingerprint;
- runtime-owned `BLOCKED / SHADOW / CANARY / ACTIVE` rollout contracts;
- deterministic task-based canary allocation;
- explicit rollout health tripwires;
- `ControlledModelBackend` fail-closed wrapper;
- model policy-agent normalization of provider failures;
- resumable `RESOURCE_SUSPENDED` behavior for retryable backend failures;
- no-fallback `BLOCKED` behavior for non-retryable or rollout-denied failures;
- loopback-only real-model compatibility CLI probe;
- Phase 13 verifier, tests, CLI smoke, RFC, metadata, and quality-gate integration.

## Compatibility requirements

Required for rollout eligibility:

```text
TEXT_RESPONSE
SINGLE_TOOL_CALL
JSON_TOOL_ARGUMENTS
```

Optional/report-only:

```text
USAGE_ACCOUNTING
```

Compatibility success is not rollout approval.

## Controlled rollout behavior

```text
compatibility report
→ stable SHA-256 fingerprint
→ runtime-approved policy fingerprint
→ health snapshot
→ BLOCKED / SHADOW / CANARY / ACTIVE
→ deterministic ModelRolloutDecision
→ inner model called only if authorized
```

`SHADOW` has zero authoritative action power. `CANARY` traffic is deterministic by
task. `ACTIVE` remains subject to false-success, authority-violation, backend-failure,
and invalid-turn tripwires.

## Runtime provider failure behavior

Retryable timeout/rate-limit/unavailable failures return control as
`RESOURCE_SUSPENDED` after exactly one model attempt and zero automatic retry.
Non-retryable failures and rollout denial return `BLOCKED`. Neither path silently
falls back to another model.

## Real-model boundary

The shipped live probe uses the existing OpenAI-compatible adapter but still accepts
loopback endpoints only. This lets local real models be compatibility-tested without
introducing cloud credential storage or arbitrary network authority.

The probe prints a compatibility report and fingerprint only. It does not persist an
approval or create an `ACTIVE` rollout policy.

## Phase 12 preservation

The locked Phase 12G suite and its SHA-256 remain unchanged. Phase 13 changes how a
model becomes eligible and authorized to reach the existing policy-agent boundary; it
does not weaken downstream action, tool, evidence, verification, completion, or
continuity rules.

## Package-environment verification

The assistant-side package environment runs syntax checks, Phase 13 targeted tests,
Phase 13 deterministic verifier, CLI smoke, and the full pytest suite. Ruff and mypy
strict are not installed in the package environment; the target Windows `.venv`
quality gate remains authoritative before commit or push.

## Deliberate boundary

Phase 13 does not add cloud provider credentials, automatic provider fallback,
autonomous rollout promotion, web research, GitHub integrations, subagents, desktop,
Discord, or voice gateways.

## Target-machine closure

```bat
scripts\check_hold.bat
```

Expected final line:

```text
[PASS] Luna 0.1 Phase 13 real-model compatibility and controlled rollout gate passed.
```
