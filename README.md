# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 12B — Layered Context Composer** durumundadır.

## Çalışan zincir

```text
intent → explicit context candidates → contract → plan → expected observation
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
→ TaskState-bound RuntimeOutcome
→ layered context composer
→ ACTIVE / TASK / RUNTIME_CONTINUITY / WORKSPACE / VERIFIED_MEMORY
→ sanitized + freshness-aware + budgeted model context
```

Faz 12B, gelecekteki tek policy-agent loop'a verilecek context'i kilitler.
Henüz `LunaRuntime.run()` veya agent loop yoktur; bu Faz 12E'ye bırakılmıştır.

## Faz 12B context sınırları

- yalnız caller tarafından zaten gözlenmiş açık kaynaklar candidate olabilir;
- `MISSING` ve `DECLARED_NOT_OBSERVED` kaynaklar context'e giremez;
- active/task/runtime control context lower-value workspace/memory'den önce seçilir;
- workspace ve verified memory daima `DATA_ONLY` kalır;
- verified memory açık task relevance gerekçesi ister;
- unverified memory blocking policy ile kapatılamaz;
- secret candidate model context'e giremez;
- model-visible metin mevcut deterministic secret redactor'dan geçer;
- secret redaction policy ile kapatılamaz;
- per-source freshness ve future timestamp kontrolleri vardır;
- per-layer ve overall hard budget uygulanır;
- required source dışlanırsa açık `missing_sources` gap oluşur;
- composer file/process/database/network I/O yapmaz;
- bundle fingerprint random bundle ID ve wall-clock age'den bağımsızdır.

## Faz 12A runtime sınırları

- owner/trusted/system rolleri runtime doğrulaması olmadan kabul edilmez;
- model actor rolü veya yetki kaynağı olamaz;
- read-only istekler varsayılan sıfır write ve sıfır network bütçesidir;
- write scope açık değişiklik bütçesi ister;
- `DRY_RUN` workspace yazma yetkisi taşıyamaz;
- resume task ID'si otoriter task ID ile aynı olmalıdır;
- `COMPLETED`, kapalı `TaskState`, `VERIFIED_COMPLETE` ve final report referansı ister;
- orchestrator bağımlılıkları açıkça enjekte edilir; global fallback yoktur.

## Faz 11 sabit kabul seti

Faz 11 suite'i fixture ve oracle içeriğini SHA-256 ile kilitler. Suite revision
ve hash açıkça değiştirilmeden kabul görevleri sessizce değiştirilemez.
Faz 12A–12B bu suite'i değiştirmez.

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
[PASS] Luna 0.1 Phase 12B layered context composer gate passed.
```

## Görünür Faz 12B testi

```bat
.venv\Scripts\python.exe -m luna phase12b-smoke
```

Başarılı çıktıda canonical layer sırası, secret-safe model view, unverified-memory
bloklama, data-only memory sınırı, deterministic fingerprint ve JSON round-trip
görülür.

## Bilinen sınırlar

- Tek policy-agent loop henüz uygulanmamıştır.
- Action/tool candidate policy Faz 12C'dedir.
- Failure taxonomy ve minimal-change enforcement Faz 12D'dedir.
- Gerçek model rollout sonraki fazdadır.
- Gerçek ağ araştırması ve harici entegrasyonlar kapalıdır.
- GitHub salt-okunur veya diğer dış entegrasyonlar bu fazın kapsamında değildir.
- Ses, Discord, masaüstü ve diğer ürün gateway'leri ayrı faz ister.
- Sabit eval çekirdeği deterministik backend ve yerel dosya fixture'ları kullanır.
