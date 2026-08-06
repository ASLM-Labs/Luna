# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 7 — deterministik verifier ve completion gate**
durumundadır.

## Faz 7'de çalışan zincir

```text
intent → context → contract → plan → expected observation
→ controlled tool use → snapshot/rollback
→ append-only observation/evidence
→ deterministic verification → audited completion decision
```

Luna artık yalnızca bütün required condition ve forbidden-outcome absence
claim'leri güncel, doğrudan ve yeterli kanıtla PASS olduğunda
`VERIFIED_COMPLETE` üretebilir.

Eski revision, yanlış environment, stale kanıt, model çıkarımı, çelişen kanıt
veya eksik evidence requirement otomatik başarıya çevrilmez.

## Kurulum

```bat
scripts\bootstrap.bat
```

## Kalite kapısı

```bat
scripts\check.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 7 verifier ve completion gate kapisi gecti.
```

## Görünür smoke

```bat
.venv\Scripts\python.exe -m luna verify-smoke
```
