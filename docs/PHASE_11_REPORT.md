# Faz 11 — Eval ve Kabul Sınavı

**Paket hazırlık durumu:** `IMPLEMENTED_UNVERIFIED`

## Uygulananlar

- SHA-256 ile kilitlenen `LockedEvalSuite`;
- 11 sabit kritik davranış vakası;
- fixture ve oracle bütünlük doğrulaması;
- gerçek Luna çekirdek bileşenlerini çalıştıran `CoreAcceptanceExecutor`;
- deterministik `RegressionRunner`;
- karşılaştırılabilir `EvalMetrics` ve `EvalReport`;
- runtime-owned `ReleaseGate` ve sürüm eşikleri;
- bilinen sınırlamaların yayınlanma zorunluluğu;
- `phase11-smoke` CLI komutu;
- Faz 11 yapısal ve davranışsal verifier.

## Ölçülen kritik davranışlar

- görev başarısı ve doğrulanmış başarı;
- yanlış `VERIFIED_COMPLETE`;
- inspect-before-edit;
- protected-path ihlali;
- blind retry;
- gerçek dosya rollback;
- yeni service instance ile checkpoint/resume;
- hafıza kirliliği;
- gereksiz soru;
- scope creep;
- nihai rapor doğruluğu;
- süre ve token maliyeti alanları.

## Kilitli suite

```text
Ad: Luna 0.1 Core Acceptance
Revision: 1.0.0
Vaka sayısı: 11
SHA-256: 3121e570d188a7c372d0a2436c56bd9f6377fa1dadf1c41d1f5f8fcd94d02827
```

Fixture veya oracle içeriği hash güncellenmeden değiştirilirse suite modeli doğrulanmaz.
Yeni veya değiştirilmiş vaka ayrı revision ve açık hash güncellemesi gerektirir.

## Paket ortamındaki doğrulama

```text
Python syntax       PASS
Pytest              193 passed
Phase 11 suite      11/11 PASS
Release gate        PASS
Repeated signature identical
```

Ruff ve mypy strict hedef Windows `.venv` ortamındaki tam kalite kapısında
çalıştırılmalıdır. Bu nedenle nihai durum yerel Windows sonucu görülene kadar
`IMPLEMENTED_UNVERIFIED` kalır.

## Hedef makinede kapanış

```bat
scripts\check_hold.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 11 eval ve kabul sinavi kapisi gecti.
```

## Bilinen sınırlar

- gerçek ağ araştırması Luna 0.1 çekirdeğinde kapalıdır;
- ses, Discord, masaüstü, Atlas ve eğitim entegrasyonları ayrı RFC ister;
- sabit eval çekirdeği deterministik backend ve yerel dosya fixture'ları kullanır.
