# Faz 1 Doğrulama Raporu

## Uygulanan çekirdek kontratlar

1. TaskContract
2. TaskState
3. PlanStep
4. ExpectedObservation
5. Observation
6. Evidence
7. Checkpoint
8. CompletionStatus

Faz 2 kalite kapısı, `scripts/verify_phase1.py` komutunu yeniden çalıştırarak
bu kontratların regresyona uğramadığını doğrular.

Hedef makinede güncel kapanış komutu:

```bat
scripts\bootstrap.bat
scripts\check.bat
```

Faz 2 komutu exit code `0` vermeden Faz 1 ve Faz 2 birlikte doğrulanmış sayılmaz.
