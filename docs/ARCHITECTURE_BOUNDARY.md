# Faz 12A Mimari Sınırı

Faz 12A, Luna'nın mevcut Faz 1–11 çekirdek bileşenlerini değiştirmeden gelecekteki
tek policy-agent loop için açık request, authority, budget, dependency ve outcome
kontratlarını ekler.

```text
authenticated RequestSource + verified RuntimeActor
→ RuntimeRequest
→ future single policy-agent runtime
→ RuntimeOutcome bound to TaskState and completion gate
```

## Var

- Faz 1–11 yetenekleri ve kilitli acceptance suite;
- `RequestSource`, `ActorRole`, `ActorVerificationSource`, `RuntimeActor`;
- read-only default `RuntimeBudget`;
- task/trace/scope/autonomy/context/budget bağlı `RuntimeRequest`;
- `DRY_RUN`, `EXECUTE`, `RESUME` modları;
- açık `RuntimeStopReason` kümesi;
- transient ID'leri dışarıda bırakan versioned `TaskFingerprint`;
- mevcut çekirdek servisler için explicit `RuntimeDependencies`;
- serializable dependency readiness manifest;
- gözlenebilir `RuntimeUsage`;
- `TaskState` ile birebir bağlantılı `RuntimeOutcome`;
- Faz 12A RFC, baseline, evidence map, verifier, unit test ve CLI smoke.

## Zorlanan kurallar

- privileged actor runtime doğrulaması ister;
- model actor authority veya autonomy grant kaynağı olamaz;
- read-only scope write/network bütçesi taşıyamaz;
- write scope açık change budget olmadan oluşturulamaz;
- dry-run workspace write açamaz;
- resume task ID uyuşmazlığı kabul edilmez;
- completed outcome yalnız CLOSED + VERIFIED_COMPLETE + final report ile oluşur;
- dependency eksikliği açık hata üretir; global fallback yoktur.

## Yok

- `LunaRuntime.run()` veya `resume()` orchestrator;
- layered context composer;
- action proposal/tool selection policy;
- ortak failure taxonomy;
- minimal-change enforcement;
- end-to-end agent loop;
- gerçek model rollout;
- ağ, GitHub, MCP/plugin, masaüstü, Discord veya ses entegrasyonu;
- subagent veya kontrolsüz self-improvement.

## Sonraki kapılar

```text
12B context composer
→ 12C action/tool policy
→ 12D failure + minimal change
→ 12E single policy-agent loop
→ 12F finalization
→ 12G E2E + behavior acceptance
```
