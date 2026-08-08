# Luna 0.1 — Phase 14 Report

## Status

`IMPLEMENTED_UNVERIFIED`

Phase 14 adds Luna's first runtime-owned research boundary. Current external material
can be retrieved through explicit network authority, preserved with provenance, and
linked to claims with exact citations while remaining untrusted DATA_ONLY content.

## Delivered

- `src/luna/research/` package with gateway, policy, source/provenance contracts,
  injection guard, and evidence adapter;
- network-closed-by-default research policy;
- runtime-request and runtime-budget binding for network authority;
- exact/subdomain allowlist plus deny-first policy;
- private/local address defense and no automatic redirect following;
- request, elapsed-time, per-source character, and admitted-token budgets;
- publisher, source-family, retrieval-time, URL, and SHA-256 provenance;
- prompt-injection risk signals with structurally DATA_ONLY research content;
- citation-backed current-claim publication boundary;
- exact quote/source digest validation and claim match-term validation;
- source-family citation deduplication;
- Phase 12F `DOCUMENT` evidence adapter that remains non-deterministic/moderate;
- explicit no-external-action and no-auto-memory-commit invariants;
- deterministic Phase 14 verifier, tests, CLI smoke, RFC, metadata, and CI gate.

## Research flow

```text
RuntimeRequest(network_allowed + network budget)
→ ResearchPolicy(explicit domain/budget policy)
→ read-only ResearchGateway
→ backend GET
→ domain/final-URL/budget validation
→ provenance-bound ResearchSource
→ injection scan (DATA_ONLY)
→ EvidenceRAGAdapter
→ citation-backed SUPPORTED claim or UNSUPPORTED claim
→ optional moderate DOCUMENT evidence
```

## Security boundary

A retrieved page cannot:

- enable network access;
- change autonomy or runtime policy;
- invoke a tool;
- perform an external action;
- become verified memory automatically;
- create a publishable current claim without a matching citation.

## Evidence semantics

Web/document evidence remains `MODERATE` under the existing Phase 12F verifier and is
marked non-reproducible. Phase 14 therefore enriches factual context without weakening
the default completion threshold.

## Deliberate limitations

Phase 14 does not perform autonomous web search discovery. The initial gateway consumes
explicit targets selected by a caller and exposes a provider-neutral backend boundary.
The included standard-library backend is read-only and refuses redirects. Search
providers, browser automation, account actions, and persistent research memory remain
future controlled integrations.

## Target-machine closure

```bat
scripts\check_hold.bat
```

Expected final line:

```text
[PASS] Luna 0.1 Phase 14 research gateway and evidence RAG gate passed.
```
