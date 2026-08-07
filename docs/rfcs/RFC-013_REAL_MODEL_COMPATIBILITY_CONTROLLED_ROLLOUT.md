# RFC-013 — Real Model Compatibility and Controlled Rollout

**Status:** ACCEPTED_FOR_PHASE_13

## 1. Purpose

Phase 13 connects the Phase 12 runtime foundation to non-scripted model adapters
without allowing model availability, provider behavior, or model confidence to become
runtime authority.

The governing rule is:

> A model may be compatible enough to test without being authorized to drive Luna.

Compatibility and rollout are therefore separate decisions.

## 2. Compatibility probe

`ModelCompatibilityProbe` performs a small provider-neutral probe against a
`ModelBackend`. It records four capability results:

1. `TEXT_RESPONSE` — correlated, non-empty text without a tool call;
2. `SINGLE_TOOL_CALL` — one correlated `compat.echo` tool call;
3. `JSON_TOOL_ARGUMENTS` — exact JSON argument round-trip;
4. `USAGE_ACCOUNTING` — provider token usage reporting.

The first three are required for rollout eligibility. Usage accounting is reported
but remains optional because some local OpenAI-compatible servers omit it.

The probe grants no permissions, tool authority, rollout stage, or completion status.

## 3. Compatibility fingerprint

`ModelCompatibilityReport.fingerprint()` hashes only stable backend identity and
normalized capability results. Random report IDs and timestamps are excluded.

Rollout policy stores an explicitly approved compatibility fingerprint. A later
report with a different fingerprint cannot silently inherit approval.

## 4. Structured backend failures

Real adapters must normalize expected provider failures to stable
`ModelBackendErrorCode` values:

- `TIMEOUT`
- `RATE_LIMITED`
- `AUTHENTICATION`
- `UNAVAILABLE`
- `MALFORMED_RESPONSE`
- `RESPONSE_TOO_LARGE`
- `PROTOCOL_ERROR`
- `ROLLOUT_BLOCKED`
- `UNKNOWN`

Retryability is runtime-visible metadata; it is not permission to retry.

The existing local OpenAI-compatible adapter now maps transport/protocol failures into
this taxonomy and avoids depending on raw provider bodies for runtime-visible reasons.

## 5. Runtime behavior on model failure

`ModelPolicyAgent` converts structured backend failures into
`PolicyTurnStatus.BACKEND_FAILURE`.

The authoritative runtime then behaves as follows:

```text
retryable backend failure
→ one model attempt counted
→ no automatic retry
→ no tool dispatch
→ CHECKPOINTED
→ RESOURCE_SUSPENDED
→ resume only after backend health/availability changes

non-retryable / rollout-blocked failure
→ no fallback model
→ no tool dispatch
→ CHECKPOINTED
→ BLOCKED
→ owner rollout/adapter decision required
```

Unexpected backend exceptions are normalized to a non-retryable `UNKNOWN` boundary
failure so they cannot crash through the policy-agent boundary.

## 6. Rollout stages

`ModelRolloutPolicy` is runtime-owned and supports four stages:

- `BLOCKED` — no authoritative model decision;
- `SHADOW` — evaluation only; output cannot drive authoritative runtime decisions;
- `CANARY` — only deterministic task buckets may use the model;
- `ACTIVE` — model may drive policy decisions only while all gates remain satisfied.

Compatibility does not promote a model between stages.

## 7. Canary allocation

CANARY allocation is deterministic:

```text
SHA256(task_id + backend_id)
→ stable bucket 0..99
→ bucket < canary_percent
```

The model cannot choose its own canary traffic and repeated decisions for the same task
produce the same allocation.

## 8. Health tripwires and rollback criteria

`ModelRolloutHealth` is supplied by runtime/owner-controlled telemetry. Phase 13 gates
on:

- false-success count;
- authority-violation count;
- consecutive backend failure threshold;
- invalid policy-turn threshold.

Any false success or authority violation blocks rollout immediately, including
`ACTIVE`. Backend/invalid-turn thresholds are explicit policy values.

Phase 13 does not automatically promote or demote persistent rollout state. It makes
the decision deterministic and fail-closed; later operational layers may persist
telemetry and owner-approved stage changes.

## 9. Controlled backend

`ControlledModelBackend` wraps a candidate backend and checks the rollout gate before
calling the inner model.

If denied:

- no inner model request is sent;
- no silent fallback occurs;
- a structured `ROLLOUT_BLOCKED` failure is returned to the policy-agent boundary.

If authorized, the ordinary provider-neutral `ModelBackend.generate()` call proceeds.
All Phase 12 runtime authorization, tool, evidence, verification, and completion rules
remain downstream and unchanged.

## 10. Live local probe

`phase13-live-probe` may connect only to the existing loopback OpenAI-compatible
adapter. It prints the compatibility report and fingerprint.

It deliberately does not:

- create `ACTIVE` rollout policy;
- persist approval;
- store credentials;
- connect to arbitrary remote endpoints;
- authorize tools or completion.

Provider-specific cloud adapters and credential storage remain separate work.

## 11. Compatibility with Phase 12

Phase 13 does not weaken the locked Phase 12G runtime conformance suite. The Phase 12G
suite digest remains:

```text
52346f987ad274b02b265c431d309be0dd83e2bc100fb497634474f294ab644e
```

The full quality gate continues to run Phase 1 through Phase 12G before Phase 13.

## 12. Non-goals

Phase 13 does not add:

- web research or evidence RAG;
- cloud credential management;
- automatic provider fallback;
- autonomous rollout promotion;
- GitHub or other external integrations;
- subagents or persona chains;
- desktop, Discord, or voice product gateways;
- autonomous source/policy rewriting.

## 13. Acceptance

Phase 13 is accepted only when:

- required compatibility capabilities pass in deterministic tests;
- compatibility fingerprint is stable;
- SHADOW cannot drive authoritative runtime decisions;
- CANARY allocation is deterministic;
- ACTIVE still obeys compatibility and health tripwires;
- denied rollout does not call the inner model;
- retryable provider failure suspends without blind retry or tool dispatch;
- local live probe remains loopback-only;
- Phase 12G locked foundation remains unchanged;
- metadata integrity passes;
- full Windows pytest, Ruff, mypy strict, and all deterministic gates pass.
