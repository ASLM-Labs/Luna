# Faz 12B Mimari Sınırı

Faz 12B, Faz 12A'da kilitlenen request/authority/budget/outcome sınırlarının üstüne
tek policy-agent runtime için katmanlı context hazırlama sınırını ekler.

```text
authenticated RuntimeRequest
→ explicit observed context candidates
→ LayeredContextComposer
→ ACTIVE / TASK / RUNTIME_CONTINUITY / WORKSPACE / VERIFIED_MEMORY
→ sanitized + budgeted LayeredContextBundle
→ future single policy-agent loop
```

## Var

- Faz 1–12A çekirdek yetenekleri ve kilitli Faz 11 acceptance suite;
- canonical beş context layer;
- `CONTROL` ve `DATA_ONLY` yorumlama ayrımı;
- explicit required/missing context takibi;
- per-layer ve overall context budget;
- freshness (`max_age_seconds`) ve future timestamp reddi;
- verified-memory için açık `relevance_basis` zorunluluğu;
- workspace/memory control escalation engeli;
- secret candidate bloklama ve model-view öncesi deterministic redaction;
- deterministic selection ve bundle fingerprint;
- yalnız admitted/sanitized içerik üreten model render;
- eski Phase 2 `ContextCandidate` için explicit compatibility bridge;
- Faz 12B RFC, verifier, unit test ve CLI smoke.

## Zorlanan kurallar

- context composer gizli file/process/database/network I/O yapamaz;
- `MISSING` veya `DECLARED_NOT_OBSERVED` kaynak model context'e giremez;
- gözlendi denilen ama model-visible content taşımayan kaynak admitted olamaz;
- lower-value workspace/memory, active/task/runtime context'i budget ile ezemez;
- workspace ve memory `CONTROL` olamaz;
- unverified memory verified-memory layer'a giremez;
- verified memory task relevance gerekçesi olmadan eklenemez;
- secret bloklama ve redaction policy ile kapatılamaz;
- future veya freshness sınırını aşan kaynak context'e giremez;
- excluded required source açık context gap üretir.

## Yok

- `LunaRuntime.run()` / `resume()` orchestrator;
- model action proposal veya tool selection policy;
- ortak failure taxonomy;
- minimal-change enforcement;
- gerçek model rollout;
- ağ, GitHub, MCP/plugin, masaüstü, Discord veya ses entegrasyonu;
- subagent veya kontrolsüz self-improvement.

## Sonraki kapılar

```text
12C action proposal + tool candidate policy
→ 12D failure taxonomy + minimal change
→ 12E single policy-agent loop
→ 12F finalization
→ 12G E2E + behavior acceptance
```
