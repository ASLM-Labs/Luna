# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 12A — runtime kontratları ve dependency boundary**
durumundadır.

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
→ authenticated request source + verified actor role
→ explicit runtime scope/autonomy/context/execution budgets
→ deterministic duplicate-task fingerprint
→ explicit dependency manifest
→ TaskState-bound RuntimeOutcome
```

Faz 12A, gelecekteki tek policy-agent loop'un giriş/çıkış ve dependency
sınırlarını kilitler. Henüz `LunaRuntime.run()` veya agent loop yoktur; bu
bilinçli olarak Faz 12E'ye bırakılmıştır.

## Faz 12A güvenlik sınırları

- owner/trusted/system rolleri runtime doğrulaması olmadan kabul edilmez;
- model actor rolü veya yetki kaynağı olamaz;
- read-only istekler varsayılan olarak sıfır write ve sıfır network bütçesidir;
- write scope açık bir değişiklik bütçesi ister;
- `DRY_RUN` workspace yazma yetkisi taşıyamaz;
- resume task ID'si otoriter task ID ile aynı olmalıdır;
- `COMPLETED`, kapalı `TaskState`, `VERIFIED_COMPLETE` ve final report referansı ister;
- orchestrator bağımlılıkları açıkça enjekte edilir; global fallback yoktur.

## Faz 11 sabit kabul seti

Faz 11 suite'i fixture ve oracle içeriğini SHA-256 ile kilitler. Suite revision
ve hash açıkça değiştirilmeden kabul görevleri sessizce değiştirilemez.
Phase 12A bu suite'i değiştirmez.

## Kurulum

```bat
scripts\bootstrap.bat
```

## Testler

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
[PASS] Luna 0.1 Phase 12A runtime contracts gate passed.
```

## Görünür Faz 12A testi

```bat
.venv\Scripts\python.exe -m luna phase12a-smoke
```

Başarılı çıktıda doğrulanmış owner rolü, read-only bütçe, deterministik
fingerprint ve request/outcome JSON round-trip sonuçları görülür.

## Bilinen sınırlar

- Tek policy-agent loop henüz uygulanmamıştır.
- Context composer, action/tool selector ve failure taxonomy sonraki 12B–12D fazlarındadır.
- Gerçek ağ araştırması ve harici entegrasyonlar kapalıdır.
- Ses, Discord, masaüstü ve eğitim entegrasyonları ayrı faz ve RFC ister.
- Sabit eval çekirdeği deterministik backend ve yerel dosya fixture'ları kullanır.
