# Faz 3 Mimari Sınırı

Faz 3, planning ve recovery kararlarını gerçek araç yürütmeden kanıtlar.

## Var

- Faz 1 çekirdek kontratları;
- Faz 2 intent, contract draft ve context hazırlığı;
- kısa ve deterministik adaptive planner;
- TaskPlan ve plan-adımı yaşam döngüsü;
- yüksek etkili adımlar için expected observation;
- yapılandırılmış expectation assessment;
- failed-assumption kaydı;
- blind-retry guard;
- observation-driven replan ve plan versioning.

## Yok

- gerçek model inference;
- dosya sistemi veya internetten otomatik context okuma;
- tool registry ve dispatcher;
- shell;
- workspace yazma;
- deterministic completion verifier;
- kalıcı checkpoint veya hafıza;
- subagent.

Retry izni yalnız eylem veya gözlemlenebilir basis değiştiğinde verilir. Aynı
eylem, aynı context, aynı evidence, aynı assumption revision, aynı strateji ve
aynı scope ile tekrar önerilirse runtime kararı `BLIND_RETRY_BLOCKED` olur.
