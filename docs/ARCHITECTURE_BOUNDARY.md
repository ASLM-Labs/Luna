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
