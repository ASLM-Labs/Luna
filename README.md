# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 12C — Action Proposal + Tool Selection** durumundadır.

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
→ untrusted ActionProposal
→ Stage 1 ToolFamily selection
→ Stage 2 registered ToolSpec selection
→ argument + runtime policy preflight
→ PREPARED request veya StructuredDenial + BLOCKED Observation
```

Faz 12C, gelecekteki tek policy-agent loop'ta model niyeti ile gerçek tool execution
arasındaki seçim sınırını kilitler. Henüz `LunaRuntime.run()` veya agent loop yoktur;
bu Faz 12E'ye bırakılmıştır.

## Faz 12C action-selection sınırları

- `ActionProposal` untrusted intent'tir; permission değildir;
- proposal runtime-owned risk alanı taşımaz;
- Stage 1 yalnız action kind → tool family seçer;
- Stage 2 yalnız runtime-owned route ve registered ToolSpec kullanır;
- uydurulmuş tool adı executable request'e dönüşmez;
- birden fazla uygun tool varsa tahmin yerine `AMBIGUOUS_TOOL` denial döner;
- preferred tool policy tarafından reddedilirse başka tool'a sessiz fallback yapılmaz;
- strict tool argument schema request preparation öncesi çalışır;
- mevcut autonomy/risk/scope/expectation policy deterministic preflight edilir;
- denial yapılandırılmış `BLOCKED` Observation üretir;
- bir iteration en fazla bir side-effect proposal taşıyabilir;
- selector/resolver handler çalıştırmaz; gerçek execution ToolDispatcher'a aittir.

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
Faz 12A–12C bu suite'i değiştirmez.

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
[PASS] Luna 0.1 Phase 12C action selection gate passed.
```

## Görünür Faz 12C testi

```bat
.venv\Scripts\python.exe -m luna phase12c-smoke
```

Başarılı çıktıda registered read tool PREPARED olur; uydurulmuş tool adı structured
denial ile BLOCKED observation üretir ve gerçek execution'ın dispatcher'a ait olduğu
açık kalır.

## Bilinen sınırlar

- Tek policy-agent loop henüz uygulanmamıştır.
- Action/tool candidate policy Faz 12C ile uygulanmıştır.
- Failure taxonomy ve minimal-change enforcement Faz 12D'dedir.
- Gerçek model rollout sonraki fazdadır.
- Gerçek ağ araştırması ve harici entegrasyonlar kapalıdır.
- GitHub salt-okunur veya diğer dış entegrasyonlar bu fazın kapsamında değildir.
- Ses, Discord, masaüstü ve diğer ürün gateway'leri ayrı faz ister.
- Sabit eval çekirdeği deterministik backend ve yerel dosya fixture'ları kullanır.
