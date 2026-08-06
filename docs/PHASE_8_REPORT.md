# Faz 8 — Checkpoint ve Görev Devamlılığı

**Paket hazırlık durumu:** `IMPLEMENTED_UNVERIFIED`

## Uygulananlar

- `SQLiteContinuityStore`
- `CheckpointEnvelope`
- `StoredCheckpoint`
- `ContinuityService`
- `ResumePolicy`
- `ResumeDecision`
- `ContinuityIntegrity`

## Zorunlu davranışlar

- task state ve checkpoint aynı SQLite transaction içinde yazılır;
- SQLite `WAL`, `FULL synchronous`, foreign key ve busy timeout ile açılır;
- migration sürümü `schema_migrations` tablosunda tutulur;
- checkpoint payload ve TaskState payload ayrı SHA-256 digest taşır;
- checkpoint kayıtları update edilmez; yalnız append edilir;
- önceki checkpoint bağlantısı görev başına zincir olarak doğrulanır;
- stale revision aynı görev state'inin üzerine yazamaz;
- terminal checkpoint ve terminal task state değiştirilemez;
- restart sonrası runtime revision, workspace fingerprint ve environment
  fingerprint birebir eşleşmeden otomatik resume yapılmaz;
- aktifken kesilmiş eylem observation reconciliation olmadan yeniden
  çalıştırılmaz;
- tamamlanmış adımlar ve kalıcı attempt history replay-prohibited olarak
  taşınır;
- aynı checkpoint ikinci kez resume edilemez;
- blind-retry kontrolü restart sonrasında persist edilmiş AttemptRecord
  geçmişiyle devam eder;
- checkpoint creation ve resume decision append-only audit olaylarıdır.

## Bilinçli sınır

Faz 8 uzun dönem kullanıcı hafızası değildir. Memory candidate, doğrulama,
commit/reject ve kullanıcı profili Faz 9'a aittir.

## Hedef makinede kapanış

```bat
scripts\bootstrap.bat
scripts\check.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 8 checkpoint ve continuity kapisi gecti.
```

## Windows SQLite hotfix

Windows üzerinde salt-okuma `sqlite3.Connection` nesneleri açık kaldığı için
`checkpoint-smoke` sonundaki geçici klasör temizliği `WinError 32` veriyordu.
Bütün read bağlantıları artık `_read_connection()` ile kesin olarak kapatılır.
Windows dosya-kilidi regresyon testiyle test sayısı `156 passed` oldu.
