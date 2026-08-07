# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 12F — Verification, Evidence & Learning** durumundadır.

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
→ structured failure taxonomy
→ deterministic recovery decision
→ changed-basis-only retry / replan / reinspect / approval / rollback / suspend / stop
→ minimal-change path + file + line budget
→ observed scope-creep check
→ risk-based NONE / SNAPSHOT / WORKTREE isolation
→ single Luna policy-agent loop
→ exactly one model action proposal per iteration
→ one ToolDispatcher dispatch → durable observation → reevaluation
→ write-ahead side-effect journal + safe suspend/cancel
→ actual HIGH/CRITICAL Git worktree lifecycle
→ effective isolated workspace continuity across later steps/resume
→ Phase 12F deterministic evidence finalization
→ runtime-owned evidence strength + explicit disagreement
→ gate-bound final report + terminal checkpoint
→ review-required learning candidate (no auto-commit)
```

Faz 12F, Phase 12E'nin `VERIFYING` sınırını deterministic evidence assessment,
completion gate, truthful final report, terminal checkpoint ve review-gated learning
candidate akışına bağlar. Model completion veya evidence-strength authority değildir.

## Faz 12F verification/evidence/learning sınırları

- evidence strength runtime tarafından `WEAK / MODERATE / STRONG / DETERMINISTIC` olarak atanır;
- varsayılan completion politikası en az `STRONG` evidence ister;
- generic `TOOL_OUTPUT` doğrudan observation olsa da tek başına completion kanıtı değildir;
- revision, environment ve freshness uyuşmayan evidence reddedilir;
- current qualifying PASS/FAIL çelişkisi explicit disagreement üretir ve success'i engeller;
- durable evidence store SQLite WAL + canonical payload SHA-256 integrity kullanır;
- evidence ID aynı payload ile idempotent, farklı payload ile conflict'tir;
- `CompletionGate` completion status'un tek otoritesidir;
- final report gate status'undan daha iyimser olamaz ve evidence strength'i görünür kılar;
- no-evidence durumda runtime `VERIFICATION_PENDING` kalır ve resumable checkpoint üretir;
- `UNVERIFIED / INCONCLUSIVE / BLOCKED / CONFLICTING_EVIDENCE` sonuçları terminal değildir;
- bu sonuçlar stronger/current evidence için `VERIFYING` resume checkpoint'i bırakır;
- yalnız terminal completion/failure `REPORTING → CLOSED` sonrası terminal checkpoint yazar;
- learning candidate yalnız review önerisidir: `review_required=true`;
- `automatic_commit_allowed=false`; memory/policy/source otomatik değiştirilmez.

## Faz 12E single policy-agent loop sınırları

- tek Luna identity ve tek authoritative `TaskState` kullanılır;
- role/persona chain veya subagent yoktur;
- model response en fazla bir tool call taşıyabilir; çoklu call dispatch öncesi reddedilir;
- her tool sonucu sonraki model kararından önce structured observation olarak görülür;
- recent dispatch evidence `RUNTIME_CONTINUITY` içinde `DATA_ONLY` olarak modele geri verilir;
- side effect `PREPARED → STARTED → COMPLETED → OBSERVED → CHECKPOINTED` fence'inden geçer;
- crash `STARTED` aşamasındaysa otomatik replay yasaktır;
- `PREPARED` action safe cancel ile execution öncesi `ABORTED` olabilir;
- suspend/cancel yalnız safe runtime boundary'de acknowledge edilir; in-flight handler force-kill edilmez;
- HIGH/CRITICAL mutation gerçek Git worktree gerektirir; sessiz snapshot downgrade yoktur;
- worktree açıldıktan sonra sonraki action/checkpoint/resume aynı effective isolated root'u kullanır;
- zero-capacity model/tool/network budget capability'yi dispatch öncesi kapatır;
- Phase 12E `VERIFIED_COMPLETE` üretmez; başarılı son handoff `VERIFICATION_PENDING` olur.

## Faz 12D recovery ve isolation sınırları

- failure category yalnız structured runtime evidence üzerinden sınıflandırılır;
- model prose arbitrary failure'ı transient ilan edemez;
- transient retry yalnız `RetryDecision(CHANGED_BASIS)` ile mümkündür;
- permission/scope denial retry yerine explicit approval ister;
- stale workspace tekrar işlem yerine reinspection ister;
- mutation sonrası verification failure rollback gerektirir;
- integrity failure ve hard budget exhaustion safe stop üretir;
- unavailable resource spin yerine suspension üretir;
- declared change exact path + file + line bütçesine bağlanır;
- observed change approved scope/line estimate dışına çıkamaz;
- LOW/MEDIUM mutation snapshot ister; HIGH/CRITICAL mutation worktree ister;
- required worktree yoksa snapshot'a sessiz downgrade yapılmaz;
- Phase 12D policy kodu gerçek tool/worktree/rollback execution yapmaz.

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
Faz 12A–12E bu suite'i değiştirmez.

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
[PASS] Luna 0.1 Phase 12F verification, evidence and learning gate passed.
```

## Görünür Faz 12F testi

```bat
.venv\Scripts\python.exe -m luna phase12f-smoke
```

Başarılı çıktıda strong evidence verification, weak tool-output rejection, explicit
disagreement, durable evidence-store integrity ve review-only learning boundary görünürdür.

## Bilinen sınırlar

- Single policy-agent action/observation loop Faz 12E ile uygulanmıştır.
- Deterministic verification/report/evidence finalization Faz 12F ile uygulanmıştır.
- Action/tool candidate policy Faz 12C ile uygulanmıştır.
- Failure taxonomy, minimal-change ve risk-based isolation Faz 12D ile uygulanmıştır.
- Runtime E2E ve behavior conformance Faz 12G, gerçek model rollout Faz 13 kapsamındadır.
- Gerçek ağ araştırması ve harici entegrasyonlar kapalıdır.
- GitHub salt-okunur veya diğer dış entegrasyonlar bu fazın kapsamında değildir.
- Ses, Discord, masaüstü ve diğer ürün gateway'leri ayrı faz ister.
- Sabit eval çekirdeği deterministik backend ve yerel dosya fixture'ları kullanır.
