# Faz 7 — Deterministik Verifier ve Completion Gate

**Paket hazırlık durumu:** `IMPLEMENTED_UNVERIFIED`

## Uygulananlar

- `DeterministicVerifier`
- `VerificationPolicy`
- `VerificationClaim`
- `ClaimAssessment`
- `EvidenceRequirementAssessment`
- `VerificationReport`
- `CompletionDecision`
- `CompletionGate`

## Zorunlu davranışlar

- required condition ve forbidden-outcome absence claim kimlikleri kontrattan
  SHA-256 ile deterministik üretilir;
- başka göreve ait evidence kabul edilmez;
- eski veya eksik revision evidence güncel görev için kullanılamaz;
- environment uyuşmazlığı, eksik freshness, stale evidence ve ileri zaman
  damgası açık rejection kaydı üretir;
- yalnız güncel, doğrudan, yeterli confidence taşıyan ve gerektiğinde
  reproducible evidence PASS için yeterlidir;
- belge, hafıza veya düşük güvenli kanıt tek başına VERIFIED_COMPLETE üretemez;
- aynı claim için güncel PASS ve FAIL varsa CONFLICTING_EVIDENCE üretilir;
- herhangi bir required claim FAIL ise FAILED;
- blocked claim BLOCKED;
- eksik claim veya evidence requirement UNVERIFIED;
- bütün claim ve evidence requirement sonuçları PASS olmadan
  VERIFIED_COMPLETE üretilemez;
- completion kararı modelden değil yalnız CompletionGate'ten çıkar;
- VerificationReport ve CompletionDecision append-only audit ledger'a yazılır;
- audit bütünlüğü bozuksa CompletionGate karar üretmez;
- TaskState'e completion status yalnız VERIFYING → REPORTING geçişinde uygulanır.

## Evidence requirement eşlemesi

Faz 7, insan tarafından yazılmış `evidence_required` değerlerini kapalı ve
deterministik bir kelime haritasıyla değerlendirir: test, hash, diff,
measurement/ölçüm, document/belge, memory/hafıza, observation/gözlem,
ToolResult/ToolOutput ve generic evidence/kanıt.

Haritada karşılığı olmayan bir ifade başarıya çevrilmez; UNVERIFIED kalır.

## Paket üretim ortamı

Paket üretim ortamında syntax, pytest, Faz 1–7 verifier ve CLI smoke
çalıştırılır. Ruff ve mypy mevcut değilse hedef Windows kapısına bırakılır.

## Hedef makinede kapanış

```bat
scripts\bootstrap.bat
scripts\check.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 7 verifier ve completion gate kapisi gecti.
```
