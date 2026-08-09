# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 19F — Improvement Gate** mimari durumundadır; gerçek eğitilmiş candidate evaluation henüz yürütülmemiştir.

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
→ revision-locked runtime behavior conformance suite
→ 11 critical real-runtime E2E scenarios
→ exact oracle comparison + repeatable semantic signature
→ Phase 12 runtime foundation conformance gate
→ real-model compatibility probe
→ structured backend failure normalization
→ runtime-owned BLOCKED / SHADOW / CANARY / ACTIVE rollout gate
→ deterministic canary allocation + rollback tripwires
→ runtime-owned read-only Research Gateway
→ explicit domain allow/deny + request/time/token budgets
→ provenance-bound source + prompt-injection DATA_ONLY boundary
→ citation-backed supported claim / unsupported claim
→ moderate DOCUMENT evidence without false completion
→ durable SQLite operations queue
→ UTC schedule eligibility + bounded catch-up
→ worker/model/network resource admission
→ pre-runtime DISPATCHED replay fence
→ LunaRuntime outcome-bound local notification outbox
→ local light-first desktop product shell
→ runtime-bound desktop command gateway + evidence-aware task cards
→ verified Discord transport + configured channel/role mapping
→ read-only Discord RuntimeRequest → durable queue + append-only audit
```

Faz 12G, Faz 12A–12F katmanlarını gerçek runtime senaryolarında birlikte sınar.
Component testlerinin yeşil olması tek başına yeterli değildir; completion truth,
evidence discipline, policy boundary, safe control, side-effect replay, scope integrity,
isolation ve budget davranışları entegre olarak da doğru kalmalıdır.


## Faz 18 Voice Gateway sınırları

Faz 18, yerel voice transport'u mevcut runtime, queue ve audit sinirlarina baglar. Sesli
transkript authority degildir ve Luna'nin nihai sesi bu fazda secilmez.

- STT/TTS adapter kontratlari provider-neutral kalir;
- verified local session + configured speaker identity gerekir;
- transcript view capture mode, command/chat ve confirmation durumunu gorunur tutar;
- read-only command bir explicit confirmation ister;
- high-impact request iki confirmation ister;
- double confirmation sonrasi high-impact istek yalniz read-only approval-review olur;
- voice source project write, process/terminal veya network authority vermez;
- interrupt/cancel pending confirmation'i temizler ve safe pre-dispatch queue'yu iptal eder;
- audit raw transcript/audio yerine SHA-256 digest tutar;
- final TTS provider/voice profile/persona sesi sonraki urun kararina birakilir.

Görünür Phase 18 smoke:

```bat
.venv\Scripts\python.exe -m luna phase18-smoke
```

## Faz 17 Discord Gateway sınırları

Faz 17, Discord mesajlarını mevcut runtime identity, autonomy, durable queue ve audit sınırlarına
bağlar. Discord mesajı veya samimi üslup yeni yetki kaynağı değildir.

- guild/channel purpose yalnız runtime-owned configured allowlist'ten çözülür;
- owner user ID ve trusted/community role ID eşleşmeleri yalnız verified transport metadata'sından gelir;
- eşleşmeyen doğrulanmış üye `GUEST` olur; mesaj metni rolü değiştiremez;
- accepted Discord işleri `RequestSource.DISCORD` + `LEVEL_1_READ_ONLY` ile durable queue'ya gider;
- project write, process/terminal ve network authority Phase 17 Discord ingress'te kapalıdır;
- ana model kullanılamıyorsa accepted message `QUEUED_FOR_MODEL` olarak durable queue'da bekler;
- duplicate Discord delivery deterministic idempotency ile ikinci task üretmez;
- role-bound fixed-window rate limit ve bot/webhook/mass-mention ingress moderation uygulanır;
- audit raw mesajı saklamaz; content SHA-256 + routing/decision metadata'sı yazar;
- reply route ingress channel + source message'e kilitlidir; gateway doğrudan network send yapmaz.

Görünür Phase 17 smoke:

```bat
.venv\Scripts\python.exe -m luna phase17-smoke
```

Deterministic verifier:

```bat
.venv\Scripts\python.exe scripts\verify_phase17.py
```




## Faz 16 Desktop Product Shell sınırları

Faz 16, Luna'nın mevcut runtime/operations çekirdeğinin üstüne yerel masaüstü ürün kabuğunu
ekler. UI otorite üretmez; yalnızca runtime ve durable operations durumunu dürüstçe sunar.

- light-first beyaz/graphite/soft-surface/Luna-blue tema ve Codex-benzeri sakin yerleşim;
- conversation-first workspace, sol navigation, alt composer ve isteğe bağlı details drawer;
- composer varsayılanı `READ_ONLY`; `CONTROLLED_WRITE` yalnız açık kullanıcı onayı + path/line/file
  bütçesiyle oluşturulabilir;
- desktop kaynaklı işler `RequestSource.DESKTOP` ile `RuntimeRequest → WorkEnvelope → durable queue`
  yolundan geçer;
- desktop shell model veya tool'u doğrudan çağıramaz;
- `Doğrulandı` etiketi yalnız `COMPLETED + VERIFIED_COMPLETE + verification_report_id +
  final_report_id` birleşiminden üretilebilir;
- queue, schedule, resource ve local notification durumu read-model olarak gösterilir;
- notification external delivery Phase 16'da hâlâ kapalıdır;
- Tk renderer lazy-load edilir; headless verifier/test ortamı GUI açmaz.

Görünür Phase 16 smoke:

```bat
.venv\Scripts\python.exe -m luna phase16-smoke
```

Desktop shell:

```bat
.venv\Scripts\python.exe -m luna desktop --workspace .
```

Deterministic verifier:

```bat
.venv\Scripts\python.exe scripts\verify_phase16.py
```

## Faz 15 Resource Manager / Queue / Scheduler / Notifications sınırları

Faz 15, Luna'nın zaman içinde bekleyen ve uygun olduğunda çalıştırılan işleri güvenli
şekilde koordine eden ilk durable operations katmanıdır.

- `WorkEnvelope`, mevcut `RuntimeRequest + ToolPolicy` otoritesini taşır; queue/scheduler
  yeni tool, network, write, process veya risk yetkisi veremez;
- shared `SQLiteOperationsStore` WAL + FULL sync + canonical JSON SHA-256 integrity kullanır;
- queue idempotent'tir ve ready sırası priority → eligibility time → insertion order'dır;
- `LEASED → DISPATCHED` geçişi runtime çağrısından önce durable may-have-executed fence yazar;
- expired `LEASED` item safe requeue olabilir; expired `DISPATCHED` item
  `RECOVERY_REQUIRED` olur ve blind replay edilmez;
- worker/model/network resource slot'ları yalnız kapasite admission'ıdır, permission değildir;
- `STALE` resource lease belirsizlik çözülmeden kapasiteden düşmez;
- scheduler UTC `ONE_SHOT` ve `FIXED_INTERVAL` destekler ve yalnız queue work materialize eder;
- recurring occurrence fresh deterministic task/request/trace ID alır; task-bound Level 4
  `FREE_RESEARCH` grant recurring schedule'a kopyalanamaz;
- coordinator dispatch başına en fazla bir runtime invocation yapar;
- successful finalization, resource release ve local outbox event aynı SQLite transaction'ında yazılır;
- notification yalnız `RuntimeOutcome` truth'undan üretilir; verified success için
  `VERIFIED_COMPLETE` + verification report + final report gerekir;
- external notification transport Phase 15'te yoktur.

Görünür Phase 15 smoke:

```bat
.venv\Scripts\python.exe -m luna phase15-smoke
```

Deterministic verifier:

```bat
.venv\Scripts\python.exe scripts\verify_phase15.py
```

## Faz 14 Research Gateway / Evidence RAG sınırları

Faz 14, güncel dış bilgiyi Luna'ya doğrudan otorite olarak değil, provenance ve
citation taşıyan untrusted `DATA_ONLY` research evidence olarak alır.

- network varsayılan olarak kapalıdır; runtime network scope + budget ve ayrıca
  `ResearchPolicy(network_enabled=True)` gerekir;
- domain allowlist/denylist dispatch öncesi uygulanır; Level 4 `FREE_RESEARCH`
  kontratı varsa onun domain/request sınırı da ayrıca korunur;
- araştırma yalnız read-only `GET` yapabilir; external action ve runtime-policy
  mutation yasaktır;
- request, elapsed-time, per-source character ve total admitted-token budget'ları
  runtime-owned biçimde uygulanır;
- admitted source URL, publisher, source family, retrieval timestamp, optional
  publication timestamp ve SHA-256 provenance taşır;
- prompt-injection sinyalleri risk etiketi olarak kalır; web içeriği hiçbir zaman
  runtime control instruction'a yükseltilmez;
- current factual claim yalnız exact source excerpt'e bağlanan citation ile
  `SUPPORTED` olabilir; kaynaksız claim publishable değildir;
- aynı source family bağımsız corroboration gibi çoğaltılmaz;
- research citation `DOCUMENT` evidence'a çevrilse bile Phase 12F altında
  `MODERATE` ve non-reproducible kalır; tek başına `VERIFIED_COMPLETE` üretemez;
- research sonucu verified memory'ye otomatik commit olamaz; review gerekir.

Görünür Phase 14 smoke:

```bat
.venv\Scripts\python.exe -m luna phase19-smoke
```

Deterministic verifier:

```bat
.venv\Scripts\python.exe scripts\verify_phase14.py
```

## Faz 13 real-model compatibility / controlled rollout sınırları

Faz 13, gerçek model kullanımını scripted test backend'den ayırır ve modelin
runtime otoritesi olmadığını koruyarak kontrollü rollout kapısı ekler.

- compatibility probe dört provider-neutral capability sonucu üretir:
  `TEXT_RESPONSE`, `SINGLE_TOOL_CALL`, `JSON_TOOL_ARGUMENTS`, `USAGE_ACCOUNTING`;
- ilk üç capability rollout için required'dır; usage accounting optional kalır;
- compatibility report SHA-256 fingerprint ile runtime-approved artefakta bağlanır;
- live probe yalnız loopback OpenAI-compatible endpoint'e bağlanır ve rollout yetkisi vermez;
- provider timeout/rate-limit/unavailable/malformed/protocol/rollout failures structured
  `ModelBackendErrorCode` ile normalize edilir;
- retryable backend failure runtime'da `RESOURCE_SUSPENDED` olur; otomatik retry yapılmaz;
- `BLOCKED` ve `SHADOW` authoritative runtime model kararını çalıştıramaz;
- `CANARY` tahsisi `task_id + backend_id` üzerinden deterministic bucket kullanır;
- `ACTIVE` bile compatibility fingerprint ve health tripwire'lardan geçmek zorundadır;
- false-success veya authority-violation tripwire'ı aktif modeli bile bloklar;
- model output rollout stage, compatibility approval veya health authority olamaz;
- controlled backend sessiz fallback yapmaz;
- Phase 12G locked runtime conformance temeli değişmeden korunur.

Görünür deterministic smoke:

```bat
.venv\Scripts\python.exe -m luna phase13-smoke
```

Gerçek yerel model için opsiyonel compatibility probe:

```bat
.venv\Scripts\python.exe -m luna phase13-live-probe --model MODEL_ADI
```

Bu probe yalnız compatibility raporu üretir; `ACTIVE` rollout yetkisi üretmez.

## Faz 12G runtime E2E / behavior conformance sınırları

- suite revision `1.0.0` ve fixture/oracle içeriği canonical SHA-256 ile kilitlidir;
- 11 senaryonun tamamı critical'dır;
- gerçek `LunaRuntime`, durable journal, continuity, evidence ve worktree stack'i çalıştırılır;
- no-evidence, weak/conflicting/stale evidence false completion üretemez;
- multi-action, zero tool budget ve out-of-scope path dispatch öncesi bloklanır;
- `STARTED` side effect restart sonrası kör biçimde replay edilmez;
- HIGH-risk write gerçek Git worktree içinde kalır ve original checkout korunur;
- observation sonraki model turn'üne DATA_ONLY continuity olarak ulaşır;
- conformance executor exception'ı PASS'e çevrilmez, fail-closed `ERROR` olur;
- bağımsız iki run aynı semantic signature üretmelidir;
- kilitli Faz 11 acceptance suite ayrıca 11/11 PASS kalmalıdır.

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
Faz 12A–12G bu suite'i değiştirmez.


## Faz 19 trace/dataset governance ve cognitive quality foundation

Faz 19 iki paralel hattı birlikte kurar:

- **Dataset Governance:** trajectory reconstruction, taxonomy, semantic tool normalization,
  task/repository/trajectory-family grouped leak-free split ve target-only training transformation.
- **Cognitive Quality:** reasoning, planning, tool selection, failure recovery, evidence usage,
  uncertainty calibration ve self-correction için frozen pre-training baseline + karşılaştırma.

Canonical trajectory ham hidden chain-of-thought değildir. Yalnız runtime tarafından gözlemlenebilir
`TASK / PLAN / ACTION / OBSERVATION / REPLAN / EVIDENCE / VERIFICATION / FINAL` olayları, kısa
decision basis ve evidence referansları tutulur. Raw hidden chain-of-thought sözleşme seviyesinde
yasaktır.

Failure taxonomy binary PASS/FAIL yerine intent, context, planning, tool selection, tool argument,
execution, observation interpretation, evidence, verification, uncertainty ve self-correction
hatalarını ayırır.

Confidence evidence-bound'dur: contradictory evidence her zaman STOP üretir. Self-correction yeni
evidence + failed assumption + strategy change + changed dimensions ister; blind retry öğrenme
sayılmaz.

Train/validation/held-out ayrımı training transformation'dan önce yapılır. Explicit held-out task
families train/validation'a giremez ve held-out trajectory training example'a dönüştürülemez.

Bu repository paketi **foundation** uygular; gerçek büyük trace corpus importu, GPU/SFT koşusu ve
post-training held-out ölçümü yapılmış sayılmaz.

Görünür smoke:

```bat
.venv\Scripts\python.exe -m luna phase19-smoke
```

## Faz 19B Evaluation Governance

Faz 19B, Faz 19A'nin cognitive scorecard ve leak-free dataset temeli uzerinde tekrar edilebilir
evaluation governance katmanini kurar:

- held-out ve OOD case kimlikleri semantic revision + SHA-256 ile dondurulur;
- evaluator revision ve implementation fingerprint acikca kaydedilir;
- evaluator candidate artifacts ve training data'dan bagimsiz olmak zorundadir;
- model-judge evaluator candidate modelin kendisi olamaz;
- benchmark contamination exact content, source trajectory ve task/repository/trajectory family
  overlap ile kontrol edilir;
- regression suite zorunlu case inventory ve critical-case subset'i dondurur;
- release snapshot'lari tam ayni case inventory + evaluator fingerprint ile karsilastirilir;
- evaluator/suite drift veya contamination comparison'i BLOCKED yapar;
- comparison per-dimension delta ve regressed case'leri raporlar;
- evaluation katmani promotion authority tasimaz.

Bu faz altyapi/governance uygular. Gercek buyuk benchmark populate edilmis, gercek model baseline
calistirilmis, SFT yapilmis veya model iyilesti diye iddia edilmez.

Gorunur smoke:

```bat
.venv\Scripts\python.exe -m luna phase19b-smoke
```

## Faz 19C Learning Integrity

Faz 19C, merged Faz 19B evaluation governance uzerine learning-integrity kontrollerini ekler:

- learning-integrity policy semantic revision + SHA-256 ile dondurulur;
- train/held-out/OOD gap'leri overfitting riski icin kontrol edilir;
- matched observational shortcut slice gap'leri shortcut-learning riski olarak raporlanir;
- frozen benchmark case identity exposure benchmark gaming olarak bloklanir;
- governed evaluator identity exposure ve independent-evaluator disagreement evaluator gaming olarak bloklanir;
- proxy metric gain governed cognitive regression ile birlikteyse proxy/specification optimization riski
  raporlanir;
- contradictory evidence'in goz ardi edilmesi confirmation bias olarak raporlanir;
- candidate output tek basina independent verification sayilmaz ve self-confirmation olarak bloklanir;
- learning-integrity katmani promotion authority tasimaz.

Shortcut slice kontrolu observational evidence'dir; counterfactual causal proof degildir. Controlled
replay/sandbox counterfactual analysis Faz 19D'ye ertelenmistir. Bu faz gercek training, reward
optimization, trained weights veya measured improvement iddia etmez.

Gorunur smoke:

```bat
.venv\Scripts\python.exe -m luna phase19c-smoke
```

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
[PASS] Luna 0.1 Phase 19F improvement gate passed.
```

## Görünür güncel faz testi

```bat
.venv\Scripts\python.exe -m luna phase19f-smoke
```

Başarılı çıktıda Phase 19F mevcut gerçek candidate yokken `INSUFFICIENT_EVIDENCE` fail-closed boundary görünürdür. Phase 19E için `phase19e-smoke` kullanılabilir.

Phase 19C için ayrıca `phase19c-smoke` kullanılabilir. Başarılı çıktıda frozen learning-integrity policy, shortcut/benchmark/evaluator/overfitting/proxy/
confirmation/self-confirmation probes ve no-promotion-authority boundary görünürdür.

Faz 12F evidence smoke ayrıca kullanılabilir:

```bat
.venv\Scripts\python.exe -m luna phase12f-smoke
```

## Bilinen sınırlar

- Single policy-agent action/observation loop Faz 12E ile uygulanmıştır.
- Deterministic verification/report/evidence finalization Faz 12F ile uygulanmıştır.
- Action/tool candidate policy Faz 12C ile uygulanmıştır.
- Failure taxonomy, minimal-change ve risk-based isolation Faz 12D ile uygulanmıştır.
- Runtime E2E ve behavior conformance Faz 12G ile uygulanmıştır.
- Gerçek-model compatibility ve runtime-owned controlled rollout Faz 13 ile uygulanmıştır.
- Research Gateway ve citation-bound Evidence RAG Faz 14 ile uygulanmıştır.
- Harici cloud-provider adapter/secrets entegrasyonu bu fazda açılmaz; live probe loopback-only kalır.
- Gerçek ağ araştırması ve harici entegrasyonlar kapalıdır.
- GitHub salt-okunur veya diğer dış entegrasyonlar bu fazın kapsamında değildir.
- Ses, Discord, masaüstü ve diğer ürün gateway'leri ayrı faz ister.
- Sabit eval çekirdeği deterministik backend ve yerel dosya fixture'ları kullanır.

## Phase 19D — Controlled Counterfactual Analysis

Phase 19D adds an experimental, non-authoritative counterfactual lab. A proposed alternative plan,
tool selection, evidence path, recovery path, or minimal path is only a hypothesis until it is actually
executed in a controlled replay or sandbox. Like-for-like comparisons require the same case, source
revision, and replay environment. Candidate output cannot serve as independent proof of its own
alternative, and counterfactual analysis cannot authorize release promotion or generalized causal
claims.


## Phase 19E — Small Controlled SFT Governance

Phase 19E adds the controlled boundary between a normalized training corpus and a real external SFT
run. It audits only `train` rows, enforces target-only loss, canonical Luna tool schema, privacy/context
normalization, source derivation, duplicate checks, and conservative initial subset mixing. A passing
corpus can be bound to a revision-locked base model, trainer, corpus digest, seed, and hyperparameter
specification.

The repository does **not** execute a GPU trainer or fabricate weights. A trained candidate is recorded
only when an external execution receipt proves a successful run and binds the resulting artifact to the
frozen spec. Even then the artifact remains `TRAINED_CANDIDATE_UNPROMOTED`; Phase 19F owns the
post-training improvement gate.

Visible smoke:

```bat
.venv\Scripts\python.exe -m luna phase19e-smoke
```

## Phase 19F — Improvement Gate

Phase 19F adds the final evidence boundary for a real trained candidate. It requires the Phase 19E
spec/receipt/artifact chain, frozen held-out/OOD and regression identities, independent evaluator
fingerprints, contamination checks, and Phase 19C learning-integrity status before comparing the
candidate with the frozen baseline.

Non-critical cognitive changes use frozen meaningful-change thresholds plus paired confidence
intervals. Critical regressions remain zero-tolerance. A candidate may receive `PROMOTE`, `REJECT`,
`ROLLBACK`, or `INSUFFICIENT_EVIDENCE`, but the gate itself has no runtime release execution
authority.

The repository currently has no real trained Phase 19E candidate evidence, so the visible smoke
intentionally proves that the correct current decision is `INSUFFICIENT_EVIDENCE` rather than a false
improvement claim.

Visible smoke:

```bat
.venv\Scripts\python.exe -m luna phase19f-smoke
```\n\n## C-002 — Capability Lineage\n\nC-002 adds a read-only canonical capability registry and deterministic impact analysis.\n\n```bat\n.venv\Scripts\python.exe -m luna capability-lineage C-002\n.venv\Scripts\python.exe scripts\verify_c002.py\n```\n\nThe query reports explicit dependencies and downstream blast radius. C-002 cannot mutate the roadmap,\ngrant runtime authority, promote a model, execute workers, start training, or perform self-optimization.\n

<!-- C001_ADAPTIVE_RETRIEVAL_BEGIN -->

## C-001 Adaptive Knowledge Retrieval

C-001 adds deterministic evidence-aware source routing across internal knowledge, observed working
context, verified memory, available project/document RAG, Phase 14 Research Gateway/web, and suitable
structured APIs. Contradictory evidence stops and reinspects; current/high-uncertainty requests require
fresh governed evidence. The router performs no direct network execution and never auto-commits
retrieval results to long-term memory.

<!-- C001_ADAPTIVE_RETRIEVAL_END -->

<!-- C003_EXPERIENCE_DISTILLATION_BEGIN -->

## C-003 Experience Distillation

C-003 converts governed observable experience into reusable **review-required** lesson candidates.

```text
governed TRAIN experience
-> evidence-bound case relation
-> cross-case support check
-> contradiction check
-> bounded generalization
-> review-required candidate
```

A single case is insufficient. At least two independent split groups are required by the default
foundation. Validation and held-out data remain evaluation-only.

Model self-report cannot certify a lesson. Evidence refs must exist in the source trajectory, and cited
traces must already be license-reviewed and PII-reviewed.

C-003 does not execute runtime actions, train models, commit memory, promote candidates, or grant
authority.

Visible smoke:

```bat
.venv\Scripts\python.exe -m luna c003-smoke
```

<!-- C003_EXPERIENCE_DISTILLATION_END -->
