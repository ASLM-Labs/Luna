# Faz 19 Trace/Dataset Governance + Cognitive Quality Mimari Sınırı

Faz 19, Luna'nın runtime güvenliğini model/dataset geliştirme hattına taşır. Bu katman runtime
yetkisi vermez; geçmiş ve yeni trajectory'leri denetlenebilir eğitim/eval verisine dönüştürür ve
model değişikliklerini frozen baseline'a karşı ölçer.

```text
observable source rows
→ reconstruction (missing rows invent edilmez)
→ taxonomy + failure labels
→ semantic tool normalization (no executable authority)
→ grouped leak-free split
   ├─ TRAIN
   ├─ VALIDATION
   └─ HELD_OUT unseen task families
→ target-only training transformation

pre-training held-out scorecards
→ frozen cognitive baseline
→ candidate held-out scorecards
→ dimension deltas + contamination/regression gate
```

## Zorlanan kurallar

- canonical trace raw hidden chain-of-thought içermez;
- observable decision basis, action, observation ve evidence refs tutulabilir;
- eksik source event uydurulmaz; repair/drop gerekir;
- binary FAILED yerine multi-axis failure taxonomy kullanılır;
- wrapper tool adı Luna runtime authority değildir; normalization sadece dataset semantiğidir;
- split row bazlı değil task/repository/trajectory family bazlıdır;
- explicit held-out task family train/validation'a sızamaz;
- held-out trajectory training transformation tarafından reddedilir;
- license ve PII review olmadan training example üretilemez;
- confidence evidence ile bağlıdır; contradictory evidence STOP üretir;
- self-correction changed-basis ister; blind retry/pseudo-learning kabul edilmez;
- model improvement generic iddia değildir; dimension-specific frozen-baseline delta ister;
- critical regression veya held-out contamination candidate'i reddeder.

## Foundation kapsamında olmayanlar

- gerçek büyük trace corpus importu;
- gerçek GPU/SFT training run;
- trained weight publication;
- post-training acceptance claim;
- hidden chain-of-thought toplama/eğitme.

---

# Faz 18 Mimari Sınırı

Faz 18, Phase 16 desktop permission UX ve Phase 17 gateway disiplininin ustune yerel Voice
Gateway ekler. Ses transkripsiyonu data'dir; role, autonomy veya tool authority degildir.

## Var

- provider-neutral STT/TTS adapter kontratlari;
- verified local session + configured speaker identity;
- wake-word / push-to-talk capture metadata;
- session-bound transcript view;
- chat/command ayrimi;
- read-only command icin direct confirmation;
- high-impact istek icin iki transcript-bound confirmation;
- double confirmation sonrasi read-only approval-review queue;
- `RequestSource.VOICE`, Level 1 read-only runtime envelope;
- model-unavailable durable queue;
- interruption/cancel pre-dispatch safe-control;
- raw transcript/audio icermeyen append-only audit digest kaydi.

## Zorlanan kurallar

- spoken text owner identity olusturamaz veya autonomy yukseltemez;
- bir transcript write/delete/deploy/external action calistiramaz;
- high-impact iki onaydan sonra bile ayri non-voice bounded approval olmadan side effect alamaz;
- Voice Gateway filesystem/shell/network/tool dispatcher'i dogrudan cagiramaz;
- TTS provider veya final Luna voice profile Phase 18'de kilitlenmez;
- interruption dispatch fence'i gecmis work'u blind cancel/replay yapmaz.

## Yok

- production microphone driver;
- wake-word engine implementation;
- real STT/TTS provider veya secret;
- Luna'nin final kadin sesi, ton/pitch/accent/persona voice profili;
- speaker biometric enrollment;
- direct voice write/process/network/deploy/external action.

---

# Faz 17 Mimari Sınırı (Baseline)

Faz 17, Phase 16 ürün yüzünün yanına external Discord ingress boundary ekler. Gateway yalnız
doğrulanmış transport metadata'sını runtime kontratlarına çevirir; Discord mesajı yetki değildir.

```text
verified Discord transport event
→ configured guild/channel allowlist
→ configured user/role mapping
→ RuntimeActor(GATEWAY_ROLE)
→ fixed moderation + rate-limit boundary
→ RuntimeRequest(source=DISCORD, Level 1 read-only)
→ WorkEnvelope
→ durable queue
→ append-only audit decision
→ ingress-bound reply route
```

## Var

- transport-neutral Discord contracts;
- configured channel purposes `UPDATES / CHAT / AION_QA / MAINTENANCE / FEEDBACK`;
- owner/trusted/community/guest role resolution;
- verified `GATEWAY_ROLE` runtime actor;
- role-bound rate limiter;
- ingress-only bot/webhook/mass-mention moderation;
- model unavailable durable queue acknowledgement;
- deterministic duplicate-delivery idempotency;
- append-only content-digest audit;
- ingress-channel-bound reply route;
- deterministic verifier, tests and CLI smoke.

## Zorlanan kurallar

- message text/familiarity cannot become role authority;
- Discord cannot raise autonomy;
- Discord project write is disabled;
- Discord process/terminal is disabled;
- Discord network authority is disabled;
- unknown guild/channel fails closed;
- community/guest cannot publish through UPDATES ingress;
- gateway does not call a model/tool directly;
- gateway does not send, delete, ban or perform another external Discord action;
- audit does not persist raw community message content.

## Yok

- Discord token/secret manager;
- live `discord.py` client or network transport;
- automatic external moderation;
- Discord-driven project write/terminal;
- Discord-driven network/autonomy escalation;
- private owner memory exposure to community.

## Sonraki kapılar

```text
18 voice gateway
→ 19 trace/dataset governance
→ 20 final conformance / RC
```

---

# Faz 16 Mimari Sınırı

Faz 16, Phase 15 durable operations çekirdeğinin üzerine local desktop product shell ekler.
Desktop shell presentation ve command-routing katmanıdır; runtime authority değildir.

```text
local user session
→ DesktopComposerDraft
→ explicit desktop access boundary
→ RuntimeRequest(source=DESKTOP)
→ WorkEnvelope
→ durable queue
→ Luna runtime / operations
→ authoritative RuntimeOutcome
→ evidence-aware desktop read model
```

## Var

- light-first local Tk desktop renderer;
- conversation-first workspace, sidebar, composer ve details drawer;
- read-only default desktop request factory;
- explicit bounded controlled-write approval;
- durable queue, schedules, resources ve local notification read-model;
- RuntimeOutcome-bound task state labels;
- headless deterministic verifier ve CLI smoke.

## Zorlanan kurallar

- UI tool/model dispatch yapamaz;
- UI completion veya evidence authority üretemez;
- `VERIFIED_COMPLETE` yalnız authoritative runtime outcome + verification/final-report IDs ile görünür;
- write authority raw composer metninden türemez;
- desktop network authority üretmez;
- local notification external-delivery claim taşımaz.

## Yok

- OS background service;
- auto-updater;
- installer/signing;
- external desktop push transport;
- Discord/voice gateway;
- browser/webview dependency;
- model-generated UI authority.

## Sonraki kapılar

```text
17 Discord
→ 18 voice
→ 19 trace/dataset governance
→ 20 final conformance / RC
```

---

# Faz 15 Mimari Sınırı

Faz 15, Faz 14 araştırma sınırının üzerine Luna'nın uzun süre yaşayan yerel operasyon
katmanını ekler. Queue, scheduler, resource manager ve notification outbox koordinasyon
yapar; hiçbiri runtime otoritesinin yerine geçmez.

```text
authorized RuntimeRequest + ToolPolicy
→ durable queue
→ UTC scheduler eligibility
→ resource-capacity lease
→ pre-runtime DISPATCHED fence
→ LunaRuntime.run/resume
→ authoritative RuntimeOutcome
→ atomic queue finalization + resource release + local outbox
```

## Var

- shared SQLite WAL operations store ve canonical JSON SHA-256 integrity;
- idempotent durable queue, priority + eligible-time ordering;
- `LEASED` ve `DISPATCHED` arasında may-have-executed replay fence;
- expired pre-dispatch lease için safe requeue;
- expired/failed post-dispatch ambiguity için `RECOVERY_REQUIRED`;
- `ACTIVE / STALE / RELEASED` resource leases;
- worker/model/network capacity admission;
- UTC `ONE_SHOT` ve `FIXED_INTERVAL` schedules;
- bounded catch-up materialization;
- recurrence başına fresh deterministic request/task/trace IDs;
- recurring Level 4 task-bound FREE_RESEARCH grant clone rejection;
- one-runtime-invocation-per-dispatch coordinator;
- RuntimeOutcome-bound local notification outbox;
- verified-complete notification için verification + final-report evidence;
- Phase 15 verifier, tests, CLI smoke ve quality-gate integration.

## Zorlanan kurallar

- scheduler sadece işi eligible/materialized yapar; execution authority değildir;
- queue priority permission/risk/autonomy artırmaz;
- resource slot tahsisi network/write/process/tool yetkisi vermez;
- ambiguous `DISPATCHED` item otomatik replay edilmez;
- stale resource lease kapasiteden sessizce düşmez;
- runtime exception blind retry üretmez;
- queue payload'daki ToolPolicy RuntimeRequest authority'sini aşamaz;
- `TASK_VERIFIED_COMPLETE` model metninden üretilemez;
- Phase 15 notification external transport içermez;
- queued cancel yalnız dispatch öncesinde doğrudan yapılır; in-flight control LunaRuntime'a aittir.

## Yok

- email/webhook/Discord/SMS/desktop push transport;
- distributed multi-node scheduler;
- OS background service hosting;
- webhook event triggers;
- automatic replay of ambiguous runtime execution;
- recurring FREE_RESEARCH authority cloning;
- external account mutation;
- desktop, Discord veya voice product gateway.

## Sonraki kapılar

```text
16 desktop product shell
→ 17 Discord
→ 18 voice
→ 19 trace/dataset governance
```

---

# Faz 14 Mimari Sınırı

Faz 14, Faz 13 controlled model sınırının üzerine runtime-owned read-only Research
Gateway ve citation-bound Evidence RAG katmanı ekler.

```text
RuntimeRequest network authority
+ explicit ResearchPolicy
+ domain / Level 4 contract / budget preflight
→ read-only ResearchBackend GET
→ provenance-bound ResearchSource
→ prompt-injection scan (DATA_ONLY)
→ citation-bound claim assessment
→ optional MODERATE DOCUMENT evidence
```

## Var

- network-closed-by-default research policy;
- runtime scope ve `RuntimeBudget.max_network_requests` authority binding;
- deny-first explicit domain allowlist/denylist;
- Level 4 `FREE_RESEARCH` domain/request/duration boundary;
- request, elapsed-time, source-size ve admitted-token budgets;
- read-only provider-neutral backend protocol ve standard-library GET backend;
- automatic redirect refusal ve final-URL policy recheck;
- URL, publisher, source-family, retrieval/publication time ve SHA-256 provenance;
- conservative prompt-injection signals with structural `DATA_ONLY` semantics;
- exact excerpt + digest + publisher + retrieval-time bound citations;
- source-family-aware citation selection;
- Phase 12F `DOCUMENT` evidence bridge;
- deterministic Phase 14 verifier, tests, CLI smoke ve quality-gate integration.

## Zorlanan kurallar

- network access model veya web content tarafından açılamaz;
- out-of-domain target backend dispatch'a ulaşamaz;
- backend response başka domaine kaçarsa source admission olmaz;
- web content runtime policy, autonomy veya tool authority olamaz;
- external research action GET dışında genişletilemez;
- sourceless current claim publishable olamaz;
- citation/source digest/URL/publisher/retrieval-time mismatch kabul edilmez;
- same-source-family sayfa çoğaltımı bağımsız corroboration gibi sunulmaz;
- research result verified memory'ye otomatik commit olamaz;
- DOCUMENT evidence default strong completion threshold'ünü tek başına geçemez;
- backend failure implicit retry oluşturamaz.

## Yok

- autonomous web-search discovery veya research scheduling;
- browser automation ve external account actions;
- automatic persistent research memory;
- cloud credential distribution;
- GitHub veya diğer harici integrations;
- subagent/persona chain;
- desktop, Discord veya voice gateway.

## Sonraki kapılar

```text
15 resource manager / queue / scheduler / notifications
→ 16 desktop product shell
→ 17 Discord
```

---

# Faz 13 Mimari Sınırı

Faz 13, Faz 12'nin integrated runtime foundation'ı üzerine gerçek-model
compatibility ve runtime-owned controlled rollout kapısı ekler.

```text
real/local model adapter
→ provider-neutral ModelRequest
→ compatibility probe
→ required capability PASS
→ compatibility fingerprint
→ runtime-owned rollout policy + health snapshot
→ BLOCKED / SHADOW / CANARY / ACTIVE
→ ModelPolicyAgent
→ existing Phase 12 runtime authorization / tool / evidence / verification chain
```

## Var

- provider-neutral structured model backend failure taxonomy;
- timeout, rate limit, auth, unavailable, malformed response, response-too-large,
  protocol ve rollout-blocked kategorileri;
- live compatibility probe ve immutable result report;
- required text/single-tool/JSON-argument capability gate;
- optional usage-accounting capability;
- deterministic compatibility fingerprint;
- runtime-owned `ModelRolloutPolicy`, `ModelRolloutHealth`, `ModelRolloutGate`;
- `BLOCKED / SHADOW / CANARY / ACTIVE` rollout stage'leri;
- deterministic task-based canary bucket;
- false-success, authority violation, backend failure ve invalid-turn tripwire'ları;
- rollout-gated `ControlledModelBackend`;
- retryable backend failure için resumable `RESOURCE_SUSPENDED`, no blind retry;
- non-retryable / rollout-blocked backend failure için fail-closed `BLOCKED`;
- loopback-only OpenAI-compatible live probe;
- Phase 13 verifier, tests, CLI smoke ve quality-gate integration.

## Zorlanan kurallar

- compatibility PASS tek başına rollout stage yükseltemez;
- model kendi compatibility fingerprint'ini onaylayamaz;
- model rollout stage veya health snapshot yazamaz;
- SHADOW output authoritative runtime kararı olamaz;
- CANARY tahsisi model seçimine bırakılamaz;
- critical false-success veya authority violation ACTIVE rollout'u bile bloklar;
- retryable provider error aynı call'u otomatik tekrar çalıştıramaz;
- provider raw error detail'i runtime-visible safe reason olmak zorunda değildir;
- controlled backend denied olduğunda inner model sessizce çağrılmaz;
- live probe rollout authority vermez;
- cloud secret/provider entegrasyonu bu fazda otomatik açılmaz.

## Yok

- autonomous rollout stage promotion;
- provider credential store / secret distribution;
- external cloud provider-specific production adapter;
- network research veya evidence RAG;
- GitHub veya diğer harici integrations;
- subagent/persona chain;
- desktop, Discord veya voice gateway.

## Sonraki kapılar

```text
14 research gateway / evidence RAG
→ 15 resource manager / queue / scheduler / notifications
→ 16 desktop product shell
```

---

# Faz 12G Mimari Sınırı

Faz 12G, Faz 12A–12F runtime temelini tek sistem olarak locked real-runtime E2E
behavior conformance ile doğrular. Component PASS, integrated invariant ihlalini
gizleyemez.

```text
locked scenario + oracle
→ real LunaRuntime stack
→ model/action/policy/tool boundary
→ durable observation / recovery / continuity
→ verification / report / checkpoint
→ normalized observable result
→ exact oracle comparison
→ PASS / FAIL / ERROR
```

## Var

- revision `1.0.0` locked conformance suite ve canonical SHA-256 fixture/oracle digest;
- 8 cross-layer domain ve 11 critical runtime scenario;
- actual LunaRuntime + journal + continuity + evidence + worktree execution;
- exact fail-closed oracle comparison;
- independent run semantic-repeatability check;
- no/weak/conflicting/stale evidence false-completion regressions;
- multi-action, cancel, budget ve STARTED-side-effect replay regressions;
- HIGH-risk real Git worktree isolation/cleanup regression;
- dispatcher preflight `path` → `TaskScope.allowed_paths` scope enforcement;
- locked Faz 11 core acceptance compatibility 11/11 gate;
- Faz 12G verifier, tests, CLI smoke ve quality-gate integration.

## Zorlanan kurallar

- component-level PASS integrated behavior PASS yerine geçmez;
- conformance fixture/oracle hash/revision değiştirilmeden sessizce değişemez;
- executor exception'ı success'e çevrilemez;
- no evidence `COMPLETED` olamaz;
- out-of-scope mutation dispatcher'a ulaşamaz;
- ambiguous `STARTED` side effect restart sonrası otomatik replay edilemez;
- HIGH-risk write original checkout'a sızamaz;
- stale revision evidence current state'i doğrulayamaz;
- Phase 11 locked acceptance Phase 12G eklenince bozulamaz.

## Yok

- gerçek harici model rollout;
- network research veya external integration;
- autonomous self-modification;
- desktop, Discord veya voice gateway;
- subagent/persona chain.

## Sonraki kapılar

```text
13 real-model compatibility + controlled rollout
→ 14 research gateway / evidence RAG
→ 15 resource manager / queue / scheduler / notifications
```

---

# Faz 12F Mimari Sınırı

Faz 12F, Faz 12E single policy-agent loop'un `VERIFYING` sınırını deterministic
evidence, completion, reporting, terminal continuity ve review-only learning ile
kapatır.

```text
VERIFYING TaskState
→ durable current evidence registry
→ revision / environment / freshness validation
→ runtime-owned evidence strength
→ claim + evidence requirement assessment
→ explicit disagreement detection
→ deterministic CompletionGate
→ REPORTING
→ gate-bound FinalReport
→ review-required LearningCandidate batch
→ evidence gap/conflict: CHECKPOINTED → VERIFYING resume
→ terminal completion/failure: CLOSED → terminal checkpoint
```

## Var

- `WEAK / MODERATE / STRONG / DETERMINISTIC` evidence-strength taxonomy;
- default minimum `STRONG` completion evidence threshold;
- direct, reproducible, confidence-aware qualification;
- stale/wrong-revision/wrong-environment evidence rejection;
- unresolved qualifying PASS/FAIL disagreement and `CONFLICTING_EVIDENCE`;
- SQLite WAL immutable evidence store with canonical JSON SHA-256 integrity;
- `VerificationCoordinator` binding gate, final report, authoritative state, and learning;
- explicit `record_evidence()` runtime boundary;
- `VERIFICATION_PENDING` when durable evidence is absent;
- evidence gap/conflict için non-terminal `REPORTING → CHECKPOINTED → VERIFYING`;
- terminal completion/failure için `REPORTING → CLOSED` ve terminal continuity checkpoint;
- review-only failed-assumption/conflict/gap/recovery learning candidates;
- append-only `LEARNING_CANDIDATE` audit event;
- Phase 12F verifier, tests, CLI smoke and quality-gate integration.

## Zorlanan kurallar

- model evidence strength veya completion authority değildir;
- generic successful tool output default policy altında verified completion sağlayamaz;
- old-revision evidence current revision'ı doğrulayamaz;
- unresolved qualifying evidence disagreement gizlenemez;
- evidence ID farklı payload ile overwrite edilemez;
- evidence-store integrity bozuksa runtime finalization durur;
- final report completion gate ile çelişemez;
- learning candidate `review_required=false` olamaz;
- learning candidate `automatic_commit_allowed=true` olamaz;
- learning builder memory, process, network veya source mutation yapmaz;
- terminal task checkpoint resume edilemez.

## Yok

- learning candidate'ın verified memory/policy/source'a otomatik promotion'ı;
- autonomous self-modification;
- real-model rollout;
- network research, GitHub, MCP/plugin veya diğer harici entegrasyonlar;
- desktop, Discord veya voice gateway;
- subagent veya persona chain.

## Sonraki kapılar

```text
12G runtime E2E + behavior conformance
→ 13 real-model compatibility + controlled rollout
→ 14 research gateway / evidence RAG
```

---

# Faz 12E Mimari Sınırı

Faz 12E, Faz 12A–12D runtime contract/context/action/recovery politikalarını tek
otoriter Luna action-observation loop'unda birleştirir.

```text
authenticated RuntimeRequest
→ finalized TaskContract
→ one authoritative TaskState
→ layered context
→ one policy-model decision
→ one untrusted ActionProposal
→ two-stage runtime tool selection
→ policy / budget / minimal-change / isolation checks
→ one ToolDispatcher action
→ durable DispatchOutcome + Observation
→ expected/actual evaluation
→ recovery / checkpoint / next turn
→ Phase 12F VERIFICATION_PENDING handoff
```

## Var

- Faz 1–12D çekirdek yetenekleri ve kilitli Faz 11 acceptance suite;
- gerçek `LunaRuntime.run()` ve `resume()` orchestrator;
- tek Luna identity ve tek authoritative `TaskState`;
- model turn başına tam bir tool proposal üst sınırı;
- actual tool sonucu görülmeden sonraki model action'ına geçmeme;
- durable bounded observation journal ve `DATA_ONLY` runtime-continuity feedback;
- side-effect write-ahead fence;
- per-step semantic idempotency;
- safe suspend/cancel control records;
- crash-stage-specific resume semantics;
- actual HIGH/CRITICAL Git worktree acquire/reuse/cleanup lifecycle;
- isolated effective workspace'ın sonraki action/checkpoint/resume boyunca korunması;
- zero-capacity ve hard runtime budget enforcement;
- Phase 12F için `VERIFICATION_PENDING` handoff;
- Faz 12E RFC, verifier, tests, CLI smoke ve quality-gate integration.

## Zorlanan kurallar

- model permission, risk, retry veya completion authority değildir;
- bir model response birden fazla tool call taşıyamaz;
- tool result sonraki action'dan önce reevaluate edilir;
- tool output runtime control instruction olamaz;
- `STARTED` side effect crash sonrası otomatik replay edilmez;
- `PREPARED` action cancel ile execution öncesi abort edilebilir;
- in-flight handler force-kill edilmez;
- identical side effect aynı task step içinde sessizce tekrar çalıştırılmaz;
- HIGH/CRITICAL write gerçek worktree olmadan çalışmaz;
- worktree açıldıktan sonra task sessizce original checkout'a dönmez;
- Phase 12E `VERIFIED_COMPLETE` üretmez.

## Yok

- Phase 12F final verification/report/evidence/memory finalization;
- real-model controlled rollout;
- network research, GitHub, MCP/plugin veya diğer harici entegrasyonlar;
- desktop, Discord veya voice gateway;
- subagent, persona chain veya uncontrolled self-improvement.

## Sonraki kapılar

```text
12F finalization + verification/report/checkpoint/memory + evidence disagreement
→ 12G runtime E2E + behavior conformance
→ 13 real-model compatibility + controlled rollout
```


---

# Faz 19B Evaluation Governance Mimari Siniri

Faz 19B, Faz 19A'nin observable trace ve cognitive-quality altyapisini degistirmeden evaluation
identity, contamination, evaluator independence ve release comparison governance katmanini ekler.

```text
frozen HELD_OUT/OOD case inventory
→ versioned independent evaluator
→ training-exposure contamination check
→ frozen regression inventory
→ exact-case release snapshot
→ like-for-like comparison
→ COMPARABLE / REGRESSION_DETECTED / BLOCKED
```

## Var

- semantic-revision + SHA-256 ile kilitli held-out/OOD evaluation suite;
- task/repository/trajectory family grouping;
- exact content, source trajectory ve family-overlap contamination detection;
- evaluator semantic revision + implementation fingerprint;
- candidate/training-data independence zorunlulugu;
- model-judge self-judging engeli;
- frozen required-case + critical-case regression inventory;
- evaluator/suite/case drift fail-closed comparison;
- cognitive-dimension delta ve regressed-case raporu;
- Faz 19A verifier regression guard.

## Yetki siniri

Evaluation Governance observe/freeze/compare/report yapabilir. Runtime authority, tool dispatch,
training-data mutation veya candidate promotion yapamaz. `promotion_authorized` bu katmanda false
kalir. Promotion threshold/confidence-interval ve rollback karari Faz 19F'ye aittir.

## Yok

- real large benchmark execution;
- real-model pre-training baseline run;
- GPU/SFT training;
- trained weights;
- post-training improvement claim;
- autonomous promotion.

## Sonraki kapi

```text
19B Evaluation Governance
→ 19C Learning Integrity
→ 19D experimental counterfactual analysis
→ 19E small controlled SFT
→ 19F improvement gate
```


---

# Faz 19C Learning Integrity Mimari Siniri

Faz 19C, Faz 19B'nin frozen evaluation identities ve release comparison sonucunu kullanarak gorunen
"iyilesme" sinyallerinin shortcut, gaming, proxy optimization, confirmation bias, self-confirmation
veya overfitting ile aciklanabildigi durumlari fail-closed bicimde gorunur yapar.

```text
frozen Phase 19B evaluation identities
→ frozen learning-integrity policy
→ generalization / shortcut / evaluator probes
→ benchmark + evaluator exposure accounting
→ proxy-vs-governed-result comparison
→ evidence independence + contradiction accounting
→ CLEAN / REVIEW_REQUIRED / REJECT_CANDIDATE
→ promotion authority: NONE
```

## Var

- semantic-revision + SHA-256 ile kilitli learning-integrity policy;
- train/held-out/OOD generalization gap kontrolleri;
- matched observational shortcut-slice dependency sinyali;
- frozen benchmark case identity exposure detection;
- governed evaluator identity exposure detection;
- distinct independent evaluator disagreement kontrolu;
- proxy gain ile governed regression ayrismasi;
- critical governed regression icin zero-tolerance integrity handling;
- explicit evidence origin + candidate-independence kaydi;
- ignored contradictory evidence icin confirmation-bias detection;
- candidate self-output icin independent-support zorunlulugu;
- Faz 19B verifier regression guard.

## Yetki siniri

Learning Integrity observe/compare/classify/report yapabilir ve learning-lab seviyesinde candidate'i
`REJECT_CANDIDATE` olarak isaretleyebilir. Runtime authority, tool dispatch, data mutation veya release
promotion yapamaz. `promotion_authorized` bu katmanda false kalir. Final statistical promotion ve
rollback Faz 19F'ye aittir.

## Counterfactual siniri

Matched shortcut slices observational evidence'dir. Faz 19C bunlardan causal counterfactual sonuc
uretemez. "Shortcut kaldirilsa kesin daha iyi olurdu" gibi iddialar controlled replay/sandbox evidence
olmadan kabul edilmez. Bu deneysel alan Faz 19D'ye ertelenmistir.

## Yok

- real large-corpus import;
- GPU/SFT training;
- reward optimization;
- trained weights;
- real counterfactual replay;
- measured post-training improvement claim;
- autonomous promotion.

## Sonraki kapi

```text
19C Learning Integrity
→ 19D experimental counterfactual analysis
→ 19E small controlled SFT
→ 19F improvement gate
```

## Phase 19D Counterfactual Analysis Boundary

The Phase 19D counterfactual package is a learning/evaluation-lab component. It receives already
observed controlled replay/sandbox outcomes and compares them deterministically. It does not dispatch
runtime tools, acquire network authority, mutate runtime permissions, or promote a model candidate.

Unexecuted alternatives remain hypotheses. An observed sandbox/replay advantage is scoped to the
specific controlled conditions and cannot become a generalized causal claim without later evidence.
