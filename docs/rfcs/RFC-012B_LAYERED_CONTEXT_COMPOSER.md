# RFC-012B — Layered Context Composer

**Status:** ACCEPTED_FOR_PHASE_12B
**Date:** 2026-08-07
**Scope:** Deterministic, layered, provenance-preserving model context composition only.

## 1. Decision

Luna will not build model context by concatenating arbitrary repository state,
memory, or prior messages. Phase 12B introduces one runtime-owned layered context
composer that admits only explicit, already-observed candidates under hard per-layer
and overall budgets.

```text
explicit observed candidates
→ layer assignment
→ authority / sensitivity / freshness checks
→ per-layer budget
→ overall budget
→ sanitized LayeredContextBundle
→ future single policy-agent model request
```

The composer performs no filesystem, process, network, database, or hidden retrieval.
Source acquisition remains the responsibility of explicit tools and runtime services.

## 2. Canonical layers

Context is emitted in this fixed order:

1. `ACTIVE` — current user/runtime request material;
2. `TASK` — task contract and task-specific constraints;
3. `RUNTIME_CONTINUITY` — authoritative runtime/checkpoint state selected for the model;
4. `WORKSPACE` — already-observed files, listings, command output, and project state;
5. `VERIFIED_MEMORY` — explicitly task-relevant verified memory only.

The order is deliberate. Bulk workspace or long-term memory context cannot crowd out
current intent, task constraints, or runtime continuity state when the overall budget
is tight.

## 3. Instruction boundary

Each admitted entry is marked as either:

- `CONTROL` — authoritative current/task/runtime control material; or
- `DATA_ONLY` — contextual evidence/data that cannot establish runtime authority.

`WORKSPACE` and `VERIFIED_MEMORY` entries are structurally prohibited from being
promoted to `CONTROL`. This is a preparation boundary for prompt-injection resistance:
repository text or memory content may inform the model but cannot become runtime
permission, policy, or authority.

## 4. Observation boundary

The composer only admits `OBSERVED` sources with model-visible content. `MISSING`,
`DECLARED_NOT_OBSERVED`, and observed sources whose content is not actually present in
the model view are excluded explicitly.

A required excluded source becomes a visible context gap. Unseen files are never
represented as read, summarized, or known.

## 5. Memory boundary

The `VERIFIED_MEMORY` layer has three mandatory conditions:

- source kind is `MEMORY`;
- source is marked verified by the runtime-owned memory path;
- the caller supplies an explicit `relevance_basis` showing why the record was
  selected for the current task.

Unverified memory is blocked. Workspace and memory remain `DATA_ONLY`. Secret memory
or secret references are not model context.

Phase 12B does not query the memory database itself. The future orchestrator must
obtain records through `VerifiedMemoryService` and convert only selected results into
context candidates.

## 6. Secret boundary

Two controls apply before model rendering:

- candidates explicitly classified `SECRET` are always excluded;
- model-visible text is passed through the existing deterministic `SecretRedactor`
  before it enters the model view.

The policy cannot disable unverified-memory blocking or secret redaction. Redaction
labels are preserved in the bundle for audit and debugging, while plaintext secret
values are not rendered.

## 7. Freshness

Every observed source preserves its observation timestamp. A candidate may also carry
an explicit `max_age_seconds` requirement.

At composition time:

- future-dated sources are rejected;
- sources older than their explicit freshness window are rejected as stale;
- accepted entries retain an age value for diagnostics.

The composition clock is supplied explicitly when deterministic replay is required.

## 8. Budgets

Phase 12B enforces both:

- hard per-layer `ContextBudget` values; and
- the existing hard overall `ContextBudget`.

Selection order is deterministic: required candidates first, then canonical layer
order, priority, locator, content digest, source kind, then source ID as a final exact
tie breaker.

The bundle fingerprint excludes random bundle IDs and wall-clock age so equivalent
composition content remains comparable. A source crossing a freshness boundary or
changing digest changes the composition result and therefore the fingerprint.

## 9. Model view

`LayeredContextBundle.render_for_model()` renders only admitted sanitized excerpts.
It does not render exclusion metadata, secret references, or hidden source content.
Layer and interpretation labels remain visible so the future model boundary can keep
control material separate from `DATA_ONLY` material.

## 10. Compatibility

Phase 12B is additive:

- existing Phase 2 `ContextCollector` remains unchanged in behavior;
- legacy `ContextCandidate` can be bridged explicitly into a layered candidate;
- Phase 1–12A contracts, state machine, tool dispatcher, verifier, memory store, and
  locked Phase 11 eval suite are not weakened;
- no `LunaRuntime.run()` loop is added;
- no new network, GitHub, MCP/plugin, desktop, Discord, or voice integration is added.

## 11. Acceptance gate

Phase 12B passes only when:

- all previous tests and verifiers remain green;
- canonical five-layer order is deterministic;
- control context is protected from bulk lower-value context;
- unseen and content-unavailable sources are excluded explicitly;
- workspace/memory cannot be promoted to control instructions;
- unverified or unrelated-without-relevance memory cannot enter the verified layer;
- explicit secret candidates are blocked and detected secret text is redacted;
- stale/future sources are rejected deterministically;
- per-layer and overall budgets are enforced;
- model rendering contains only admitted sanitized content;
- bundle fingerprinting is deterministic;
- the composer has no hidden file, process, database, or network I/O;
- Ruff and mypy strict pass on Python 3.12 and 3.13 CI.

## 12. Follow-up

- Phase 12C: action proposal and two-stage tool candidate policy;
- Phase 12D: failure taxonomy and minimal-change policy;
- Phase 12E: single policy-agent runtime loop;
- Phase 12F: verification/report/checkpoint/memory finalization;
- Phase 12G: runtime E2E and behavior conformance acceptance.
