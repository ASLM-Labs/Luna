# RFC-014 — Research Gateway and Evidence RAG

**Status:** ACCEPTED_FOR_PHASE_14

## 1. Purpose

Phase 14 introduces a read-only Research Gateway for current external information.
The gateway preserves source provenance and produces citation-bound document evidence
without allowing retrieved text to become runtime policy, tool authority, or memory
truth.

The governing rule is:

> Retrieved content is untrusted data. A source may support a claim without becoming an instruction.

## 2. Authority boundary

Research requires both an explicit `ResearchPolicy(network_enabled=True, ...)` and an
already-authorized `RuntimeRequest` whose task scope permits network access and whose
runtime budget has non-zero `max_network_requests`.

```text
RuntimeRequest network authority
+ ResearchPolicy explicit allowlist
+ optional Level 4 FREE_RESEARCH contract
→ ResearchGateway
→ read-only GET requests only
```

Neither a model response nor web content can enable the network boundary.

## 3. Domain and SSRF policy

Domains are normalized as bare hosts. Deny rules take precedence over allow rules and
both exact-host and subdomain matching are deterministic.

The gateway blocks before dispatch:

- targets outside the explicit allowlist;
- explicitly denied hosts;
- localhost, `.local`, loopback, private, link-local, reserved, multicast, and
  unspecified IP literals;
- Level 4 targets outside the existing `FREE_RESEARCH` contract.

The standard-library backend refuses automatic redirects, preventing a permitted URL
from silently contacting a second domain. The gateway also validates the final URL of
all backend responses.

## 4. Budget ownership

The effective request cap is the minimum of:

- `ResearchPolicy.max_requests`;
- `RuntimeBudget.max_network_requests`;
- remaining Level 4 `FREE_RESEARCH` request allowance, when applicable.

The gateway additionally enforces:

- elapsed-time budget;
- per-source character budget;
- total admitted token-estimate budget.

Every backend call increments network usage before the call. A failure is not retried
implicitly.

## 5. Provenance

An admitted `ResearchSource` retains:

- requested URL and final URL;
- normalized domain;
- title;
- publisher;
- source family;
- retrieval timestamp;
- optional publication timestamp;
- exact admitted content;
- SHA-256 content digest;
- request index and token estimate.

The retrieval timestamp is assigned by Luna, not accepted from provider prose.

## 6. Prompt injection

`ResearchInjectionGuard` detects common instruction-override, system-prompt, tool
execution, authority-escalation, and secret-exfiltration patterns.

Detection does not grant control semantics. Every research source is structurally:

```text
interpretation = DATA_ONLY
runtime_control_allowed = false
external_action_allowed = false
```

The guard is a risk signal, not a semantic truth detector.

## 7. Citation-bound claims

A `ResearchClaim` is not publishable merely because a model proposed it. Phase 14
requires explicit match terms and exact source excerpts.

`EvidenceRAGAdapter` creates a citation only when all claim match terms occur in the
exact quoted source excerpt. The citation preserves source ID, source SHA-256, URL,
publisher, retrieval time, quote, and quote SHA-256.

`ResearchResult.publishable_claims` contains only `SUPPORTED` claims that carry one or
more valid citations. Unsupported current claims remain visible as unsupported but are
not publishable.

## 8. Source-family discipline

Evidence RAG admits at most one citation per `source_family` for a claim before moving
to another family. Multiple pages from the same publisher family therefore cannot
masquerade as independent corroboration.

## 9. Phase 12F evidence bridge

Citation-backed claims may be adapted to ordinary Luna `Evidence` records with
`source_kind=DOCUMENT`.

These records are deliberately:

```text
reproducible = false
strength = MODERATE under the Phase 12F verifier
```

Therefore a web document cannot by itself satisfy the default `STRONG` evidence
threshold or manufacture `VERIFIED_COMPLETE`.

## 10. Memory boundary

A research result cannot auto-write verified memory:

```text
automatic_memory_commit_allowed = false
memory_review_required = true
```

Phase 14 does not call the memory service or create an automatic research-memory
commit path. Later persistent research memory requires an explicit review policy.

## 11. External actions

Phase 14 research supports read-only HTTP `GET` only. POST, mutation, purchase,
message-send, account action, and other external side effects are outside the Research
Gateway contract.

## 12. Non-goals

Phase 14 does not add:

- autonomous research scheduling;
- automatic memory persistence;
- external account actions;
- browser automation;
- GitHub integration;
- subagents/persona chains;
- cloud credential management;
- desktop, Discord, or voice gateways.

## 13. Acceptance

Phase 14 is accepted only when:

- network access is closed by default;
- out-of-domain targets never dispatch;
- redirects cannot bypass domain policy;
- request/time/token budgets cannot be bypassed;
- current publishable claims always have provenance-bound citations;
- citation/claim mismatch is rejected;
- prompt-injection text remains DATA_ONLY with zero runtime authority;
- research output cannot perform external actions;
- research output cannot auto-persist memory;
- Phase 13 remains green;
- metadata integrity, pytest, Ruff, mypy strict, and all deterministic gates pass.
