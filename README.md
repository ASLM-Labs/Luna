# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 6 — yapılandırılmış gözlem, append-only audit ve
evidence ledger** durumundadır.

## Faz 6'da çalışan parçalar

- Faz 1–5 intent, context, planning, model, tool, safe process ve rollback katmanları;
- append-only JSONL audit olayları;
- her olay için sıra, payload SHA-256, previous hash ve event hash;
- değiştirilen audit zincirine yeni kayıt eklemeyi reddetme;
- düzeltmeyi eski satırı değiştirmeden yeni olay olarak yazma;
- task, tool request/result/event, Observation ve Evidence için ortak trace;
- hassas stdout/stderr ve audit payload redaksiyonu;
- tam çıktıyı content-addressed log artifact olarak saklama;
- bounded ToolResult excerpt ve SHA-256 Observation referansı;
- güncel Observation'dan requirement-linked Evidence oluşturma;
- task UUID ile audit inspection.

## Bilinçli olarak kapalı yetenekler

- deterministic completion verifier ve `VERIFIED_COMPLETE` kararı;
- SQLite checkpoint ve hafıza;
- internet/web araçları;
- dosya silme;
- subagent.

## Kurulum ve kalite kapısı

```bat
scripts\bootstrap.bat
scripts\check.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 6 observation, audit ve evidence kapisi gecti.
```

## CLI

```bat
.venv\Scripts\python.exe -m luna status
.venv\Scripts\python.exe -m luna audit-smoke
.venv\Scripts\python.exe -m luna audit-inspect runtime_data\audit TASK_UUID
```

Audit kayıtları gizli iç muhakeme değildir. Luna yalnız gözlemlenebilir araç
olaylarını, sonuçları, redaksiyonları ve kanıt dayanaklarını kaydeder.
