# Faz 6 — Observation, Append-only Audit ve Evidence Ledger

**Paket hazırlık durumu:** `IMPLEMENTED_UNVERIFIED`

## Uygulananlar

- `AuditSession`
- `AppendOnlyAuditLedger`
- `AuditEvent`
- `ContentAddressedLogStore`
- `SecretRedactor`
- `AuditedToolDispatcher`
- `EvidenceBuilder`
- `EvidenceLedger`

## Zorunlu davranışlar

- audit kayıtları tek satırlık append-only JSONL olaylarıdır;
- her olay sıra numarası, önceki olay hash'i ve kendi SHA-256 hash'ini taşır;
- ledger değiştirildiyse yeni kayıt eklenmesi reddedilir;
- düzeltme eski olayı değiştirmez, yeni `CORRECTION` olayı yazar;
- task, tool, observation ve evidence ortak `trace_id` ile bağlanır;
- stdout/stderr kalıcılaştırılmadan önce redakte edilir;
- tam çıktı state içine gömülmez, content-addressed SHA-256 log artifact olarak saklanır;
- bounded excerpt ile tam log artifact aynı kontrollü dispatch içinde üretilir;
- evidence güncel Observation'dan oluşturulur ve requirement'a bağlanır;
- model beyanı veya completion kararı bu fazda verifier yerine geçmez;
- kullanıcı seçtiği task UUID için audit olaylarını CLI ile inceleyebilir.

## Paket üretim ortamı kanıtı

- syntax: `100 Python files parsed`;
- pytest: `124 passed in 0.91s`;
- Faz 1–6 verifier exit code: `0`;
- CLI smoke: `7/7 PASS`;
- editable install + `audit-smoke`: `PASS`;
- Ruff ve mypy: bu ortamda mevcut olmadığı için `NOT_RUN`.

## Bilinçli sınır

Faz 6 kanıtı toplar ve bütünlüğünü korur. Requirement→evidence eşlemesi,
çelişen kanıt kararı ve `VERIFIED_COMPLETE` üretimi Faz 7'ye aittir.

## Hedef makinede kapanış

```bat
scripts\bootstrap.bat
scripts\check.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 6 observation, audit ve evidence kapisi gecti.
```
