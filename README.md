# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 10 — kimlik, raporlama ve özerklik** durumundadır.

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
```

Luna kimliği model ağırlıklarına veya sabit bir kullanıcı adına bağlı değildir.
Runtime profili; `user_id`, `display_name`, `alias` ve `preferred_address`
alanlarını isteğe bağlı olarak taşır. İletişim ilkeleri doğal, sıcak, açık ve dürüst
olmayı; bilinç, duygu veya kanıtsız kesinlik rolü yapmamayı zorunlu tutar.

Özerklik seviyeleri runtime tarafından uygulanır:

- Level 0: danışman, araç çalıştırmaz;
- Level 1: salt-okunur;
- Level 2: kontrollü uygulama;
- Level 3: görev özerkliği ve açık yüksek-risk onayları;
- Level 4: yalnız ayrı, süreli ve scope sınırlı `FREE_RESEARCH` kontratıyla.

Model kendi yetkisini yükseltemez. Level 4 varsayılan olarak kapalıdır ve mevcut
paket gerçek ağ aracı içermez; yalnız izin kontratı ve runtime guard'ı vardır.

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
[PASS] Luna 0.1 Faz 10 kimlik, raporlama ve ozerklik kapisi gecti.
```

## Görünür Faz 10 testi

```bat
.venv\Scripts\python.exe -m luna phase10-smoke
```
