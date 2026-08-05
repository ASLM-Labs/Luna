# Faz 3 — Plan, Beklenti ve Yeniden Planlama

**Paket hazırlık durumu:** `IMPLEMENTED_UNVERIFIED`

## Uygulananlar

- `TaskPlan`
- `TaskComplexity`
- `PlanStatus`
- `AdaptivePlanner`
- `PlanLifecycle`
- `ExpectationEvaluator`
- `AttemptBasis`
- `AttemptRecord`
- `RetryGuard`
- `FailedAssumption`
- `AdaptiveReplanner`
- `ReplanOutcome`

## Zorunlu davranışlar

- basit görev bir adıma kadar küçülebilir;
- standart yazma planı üç, yüksek riskli plan dört adımla sınırlıdır;
- yüksek etkili değişiklik adımı expectationsız planlanamaz;
- dependency tamamlanmadan sonraki adım aktive edilemez;
- expectation ile observation uyuşmazlığı açık failed assumption üretir;
- aynı action basis ile retry reddedilir;
- yeni evidence, assumption revision, strategy, verification veya scope retry'ı
  ayırt edebilir;
- replan yeni `plan_id`, artan `version`, `supersedes_plan_id` ve gerekçe taşır.

## Hedef makinede kapanış

```bat
scripts\bootstrap.bat
scripts\check.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 3 planning ve replan kapisi gecti.
```
