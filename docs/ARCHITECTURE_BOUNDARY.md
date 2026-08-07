# Faz 12D Mimari Sınırı

Faz 12D, Faz 12C action-selection sınırının üstüne deterministic failure recovery,
minimal-change enforcement ve risk-based workspace isolation policy ekler.

```text
authenticated RuntimeRequest
→ LayeredContextBundle
→ ActionProposal
→ two-stage ToolSpec selection
→ deterministic policy preflight
→ PREPARED request / StructuredDenial
→ structured failure classification
→ RecoveryDecision
→ MinimalChangeDecision
→ IsolationDecision
→ future Phase 12E runtime orchestration
```

## Var

- Faz 1–12C çekirdek yetenekleri ve kilitli Faz 11 acceptance suite;
- stable `FailureCategory` taxonomy;
- Phase 12C denial ve tool failure classification;
- runtime-owned transient error-class allowlist;
- `RETRY / REPLAN / REINSPECT / REQUEST_APPROVAL / ROLLBACK / SUSPEND / STOP`;
- changed-basis-only retry gate;
- explicit path/file/added-line/deleted-line minimal-change budget;
- post-change approved-scope comparison;
- NONE/SNAPSHOT/WORKTREE isolation planning;
- HIGH/CRITICAL worktree requirement with no silent downgrade;
- Faz 12D RFC, verifier, tests, CLI smoke, and quality-gate integration.

## Zorlanan kurallar

- model free-form text cannot grant retryability;
- permission/scope denial is never blind-retried;
- transient failure without changed basis replans instead of retrying;
- stale state requires fresh inspection;
- verification failure after mutation requires rollback;
- integrity failure and hard budget exhaustion stop safely;
- proposed writes must stay within TaskScope and RuntimeBudget;
- observed write scope cannot grow beyond approved estimate;
- high-risk workspace isolation cannot downgrade from WORKTREE to SNAPSHOT;
- recovery/isolation policy code does not execute tools, rollback, subprocess, network, or Git.

## Yok

- actual Git worktree create/resume/cleanup lifecycle;
- `LunaRuntime.run()` / `resume()` orchestrator;
- real model rollout;
- network, GitHub, MCP/plugin, desktop, Discord, or voice integration;
- subagent or uncontrolled self-improvement.

## Sonraki kapılar

```text
12E single policy-agent loop + run/resume/suspend/cancel + idempotency
→ 12F finalization + verification/report/checkpoint/memory
→ 12G runtime E2E + behavior conformance
```
