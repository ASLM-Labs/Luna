# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 11 — eval ve kabul sınavı** durumundadır.

## Çalışan zincir

```text
intent → context → contract → plan → expected observation
→ controlled tool use → snapshot/rollback
→ append-only observation/evidence
→ deterministic verification → audited completion
→ SQLite WAL checkpoint → guarded restart/resume
→ memory candidate → policy/verification → commit or reject
→ scoped retrieval → expiry/supersede
→ versioned identity profile → runtime autonomy level 0–4
→ gate-bound final report → explicit evidence/uncertainty/risk
→ revision-locked fixed eval suite → comparable metrics
→ runtime-owned release gate → PASS or BLOCKED
```

Faz 11 suite'i fixture ve oracle içeriğini SHA-256 ile kilitler. Suite revision
ve hash açıkça değiştirilmeden kabul görevleri sessizce değiştirilemez.
`RegressionRunner`, gerçek Luna çekirdek bileşenlerini kullanarak şunları ölçer:

- yanlış `VERIFIED_COMPLETE`;
- inspect-before-edit;
- protected-path ihlali;
- blind retry;
- gerçek dosya rollback;
- checkpoint/restart/resume;
- hafıza kirliliği;
- gereksiz soru;
- scope creep;
- nihai rapor doğruluğu.

Release kararı model metninden değil, `EvalReport`, kilitli suite hash'i ve
runtime-owned `ReleaseThresholds` üzerinden üretilir. Kritik yanlış başarı,
protected-path ihlali ve blind retry eşiği sıfırdır. Bilinen sınırlamalar
yayınlanmadan release gate PASS vermez.

## Kurulum

```bat
scripts\bootstrap.bat
```

## Testler

Windows üzerinde düz `python -m pytest` komutu proje içindeki `.pytest_tmp`
klasörünü kullanır; böylece sistem geçici klasöründeki izin sorunlarından
etkilenmez.

```bat
python -m pytest
```

## Kalite kapısı

Pencerenin sonuçtan sonra açık kalması için:

```bat
scripts\check_hold.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 11 eval ve kabul sinavi kapisi gecti.
```

## Görünür Faz 11 testi

```bat
.venv\Scripts\python.exe -m luna phase11-smoke
```

Başarılı çıktıda `total_cases: 11`, `passed_cases: 11` ve
`release_status: PASS` görülür.

## Bilinen sınırlar

- Gerçek ağ araştırması Luna 0.1 çekirdeğinde kapalıdır.
- Ses, Discord, masaüstü, Atlas ve eğitim entegrasyonları ayrı RFC ister.
- Sabit eval çekirdeği deterministik backend ve yerel dosya fixture'ları kullanır.
