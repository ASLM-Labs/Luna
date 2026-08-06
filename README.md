# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 8 — checkpoint ve görev devamlılığı** durumundadır.

## Çalışan zincir

```text
intent → context → contract → plan → expected observation
→ controlled tool use → snapshot/rollback
→ append-only observation/evidence
→ deterministic verification → audited completion
→ SQLite WAL checkpoint → guarded restart/resume
```

Luna artık task state ve checkpoint'i aynı SQLite transaction içinde saklar.
Runtime revision, workspace veya environment değişmişse otomatik devam etmez.
Aktifken kesilmiş bir eylemi körlemesine yeniden çalıştırmaz ve tamamlanmış
adımları replay-prohibited olarak taşır.

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
[PASS] Luna 0.1 Faz 8 checkpoint ve continuity kapisi gecti.
```

## Görünür restart testi

```bat
.venv\Scripts\python.exe -m luna checkpoint-smoke
```
