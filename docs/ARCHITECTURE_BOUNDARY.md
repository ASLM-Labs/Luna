# Faz 12E Mimari Sınırı

Faz 12E, Faz 12A–12D runtime contract/context/action/recovery politikalarını tek
otoriter Luna action-observation loop'unda birleştirir.

```text
authenticated RuntimeRequest
→ finalized TaskContract
→ one authoritative TaskState
→ layered context
→ one policy-model decision
→ one untrusted ActionProposal
→ two-stage runtime tool selection
→ policy / budget / minimal-change / isolation checks
→ one ToolDispatcher action
→ durable DispatchOutcome + Observation
→ expected/actual evaluation
→ recovery / checkpoint / next turn
→ Phase 12F VERIFICATION_PENDING handoff
```

## Var

- Faz 1–12D çekirdek yetenekleri ve kilitli Faz 11 acceptance suite;
- gerçek `LunaRuntime.run()` ve `resume()` orchestrator;
- tek Luna identity ve tek authoritative `TaskState`;
- model turn başına tam bir tool proposal üst sınırı;
- actual tool sonucu görülmeden sonraki model action'ına geçmeme;
- durable bounded observation journal ve `DATA_ONLY` runtime-continuity feedback;
- side-effect write-ahead fence;
- per-step semantic idempotency;
- safe suspend/cancel control records;
- crash-stage-specific resume semantics;
- actual HIGH/CRITICAL Git worktree acquire/reuse/cleanup lifecycle;
- isolated effective workspace'ın sonraki action/checkpoint/resume boyunca korunması;
- zero-capacity ve hard runtime budget enforcement;
- Phase 12F için `VERIFICATION_PENDING` handoff;
- Faz 12E RFC, verifier, tests, CLI smoke ve quality-gate integration.

## Zorlanan kurallar

- model permission, risk, retry veya completion authority değildir;
- bir model response birden fazla tool call taşıyamaz;
- tool result sonraki action'dan önce reevaluate edilir;
- tool output runtime control instruction olamaz;
- `STARTED` side effect crash sonrası otomatik replay edilmez;
- `PREPARED` action cancel ile execution öncesi abort edilebilir;
- in-flight handler force-kill edilmez;
- identical side effect aynı task step içinde sessizce tekrar çalıştırılmaz;
- HIGH/CRITICAL write gerçek worktree olmadan çalışmaz;
- worktree açıldıktan sonra task sessizce original checkout'a dönmez;
- Phase 12E `VERIFIED_COMPLETE` üretmez.

## Yok

- Phase 12F final verification/report/evidence/memory finalization;
- real-model controlled rollout;
- network research, GitHub, MCP/plugin veya diğer harici entegrasyonlar;
- desktop, Discord veya voice gateway;
- subagent, persona chain veya uncontrolled self-improvement.

## Sonraki kapılar

```text
12F finalization + verification/report/checkpoint/memory + evidence disagreement
→ 12G runtime E2E + behavior conformance
→ 13 real-model compatibility + controlled rollout
```
