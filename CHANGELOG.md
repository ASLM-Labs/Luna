# Changelog

Tüm önemli değişiklikler bu dosyada belgelenir.

## [0.1.0-phase17] - 2026-08-08

### Added

- Transport-neutral Discord gateway contracts and bootstrap over the existing durable queue and audit ledger.
- Runtime-owned guild/channel bindings plus owner/trusted/community/guest role resolution from verified Discord metadata.
- Role-bound fixed-window ingress rate limiting and local bot/webhook/mass-mention moderation guard.
- Model-unavailable durable queue acknowledgements, deterministic Discord delivery idempotency, and ingress-bound reply routes.
- Phase 17 deterministic verifier, CLI smoke, regression tests, and quality-gate integration.

### Security

- Discord message text, familiarity, or self-asserted identity cannot raise actor role or autonomy.
- Discord-originated tasks remain Level 1 read-only with project write, terminal/process, and network authority disabled.
- Unknown guild/channel input fails closed and updates-channel ingress is restricted to owner/trusted roles.
- Append-only audit records message content digests rather than raw community message text.
- Gateway performs no external Discord moderation action and no direct network send.

## [0.1.0-phase16] - 2026-08-08

### Added

- Local light-first desktop product shell with conversation workspace, sidebar, composer, and details drawer.
- Runtime-bound desktop command gateway using `RequestSource.DESKTOP` and the durable Phase 15 queue.
- Read-only default desktop authority and explicit bounded controlled-write approval contracts.
- Evidence-aware task cards, schedule cards, resource summary, and local notification presentation.
- Lazy-loaded Tk renderer plus deterministic Phase 16 headless verifier and CLI smoke.

### Changed

- Phase 15 metadata verifier is forward-compatible with later numeric phases.
- Operations store exposes read-only schedule listing for desktop presentation.

### Security

- Desktop UI cannot call tools or models directly.
- UI state cannot manufacture runtime authority or `VERIFIED_COMPLETE`.
- Controlled writes require explicit local approval, approved paths, and file/line budgets.
- Desktop notifications remain local-only; no external transport is added.

## [0.1.0-phase15] - 2026-08-08

### Added

- Shared SQLite WAL operations store for queue, schedules, resource leases, and local outbox events.
- Idempotent durable queue with deterministic priority/eligibility ordering.
- Worker/model/network resource admission with ACTIVE/STALE/RELEASED leases.
- UTC one-shot and fixed-interval scheduler with bounded catch-up and fresh recurring task IDs.
- Pre-runtime DISPATCHED replay fence and RECOVERY_REQUIRED ambiguity handling.
- Runtime coordinator with one invocation per dispatch and atomic outcome/resource/outbox finalization.
- RuntimeOutcome-bound local notification events with no external transport.
- Phase 15 verifier, tests, CLI smoke, RFC, report, metadata, and CI integration.

### Changed

- Phase 14 metadata verifier is forward-compatible with later numeric phases while retaining
  canonical manifest/SHA integrity checks.

### Security

- Queue priority, scheduler eligibility, and resource capacity cannot grant runtime authority.
- Expired DISPATCHED work is never blindly replayed.
- STALE resource reservations continue to consume capacity until reconciled.
- Recurring schedules cannot clone task-bound Level 4 FREE_RESEARCH authority.
- Verified-complete notifications require authoritative verification and final-report evidence.
- Phase 15 provides no email, webhook, Discord, desktop-push, or other external notification transport.

## [0.1.0-phase14] - 2026-08-08

### Added

- Runtime-owned read-only Research Gateway and provider-neutral research backend boundary.
- Explicit domain allow/deny policy with request, elapsed-time, source-size, and token budgets.
- URL, publisher, source-family, retrieval-time, publication-time, and SHA-256 provenance.
- Prompt-injection risk labeling with structural `DATA_ONLY` interpretation.
- Citation-bound current-claim assessments and source-family citation discipline.
- Phase 12F `DOCUMENT` evidence adapter that remains moderate/non-terminal by default.
- Phase 14 verifier, tests, CLI smoke, RFC, report, metadata, and CI integration.

### Changed

- Phase 13 metadata verification is forward-compatible with later numeric phases while retaining
  canonical manifest/SHA integrity checks.

### Security

- Research network access remains closed unless both runtime authority and explicit research
  policy permit it.
- Out-of-domain and Level 4 contract violations are blocked before backend dispatch.
- Retrieved content cannot mutate runtime policy, invoke external actions, or auto-commit memory.
- Sourceless current claims are not publishable and citation/source mismatch is rejected.
- Research document evidence cannot manufacture `VERIFIED_COMPLETE` under the default gate.

## [0.1.0-phase13] - 2026-08-08

### Added

- Provider-neutral structured model-backend failure taxonomy.
- Real-model compatibility probe for text, single-tool-call, exact JSON arguments, and usage reporting.
- Stable compatibility-report SHA-256 fingerprint for runtime approval.
- Runtime-owned `BLOCKED`, `SHADOW`, `CANARY`, and `ACTIVE` rollout policy.
- Deterministic task-based canary allocation and explicit health tripwires.
- Rollout-gated model backend wrapper and loopback-only live compatibility probe.
- Phase 13 verifier, tests, CLI smoke, RFC, report, metadata, and quality-gate integration.

### Changed

- Model policy-agent backend failures are normalized instead of crashing the runtime boundary.
- Retryable provider failures return `RESOURCE_SUSPENDED` without blind retry.
- Phase 12G runtime harness accepts the generic `ModelBackend` protocol for compatibility testing.

### Security

- Compatibility success cannot grant rollout authority.
- `SHADOW` output cannot drive authoritative runtime actions.
- Critical false-success or authority-violation health signals block even `ACTIVE` rollout.
- Denied rollout never silently falls back to another model.
- Live compatibility probing remains loopback-only and grants no rollout authority.

## [0.1.0-phase12g] - 2026-08-07

### Added

- Revision-locked Phase 12 runtime behavior-conformance suite with 11 critical real-runtime cases.
- Cross-layer completion, evidence, policy, control, replay, scope, isolation and budget oracles.
- Exact fail-closed conformance runner and repeated-run semantic signature checks.
- Real LunaRuntime conformance executor using durable journal, continuity, evidence and worktree services.
- Phase 12G verifier, CLI smoke, RFC, report and quality-gate integration.

### Fixed

- Dispatcher preflight now validates schema-backed file `path` against `TaskScope.allowed_paths`.
- Out-of-scope mutation is denied as an explicit permission/scope decision before tool dispatch.

### Security

- No/weak/conflicting/stale evidence cannot falsely become verified completion.
- Ambiguous STARTED side effects cannot be blindly replayed after restart.
- Multi-action and exhausted tool-budget cases remain blocked before dispatch.
- HIGH-risk mutation remains isolated in a real Git worktree with cleanup verification.
- The locked Phase 11 core acceptance suite must remain 11/11 PASS.

## [0.1.0-phase12f] - 2026-08-07

### Added

- Runtime-owned WEAK/MODERATE/STRONG/DETERMINISTIC evidence-strength assessment.
- Current revision/environment/freshness qualification and explicit evidence rejection.
- Unresolved evidence disagreement records that block false verified completion.
- SQLite WAL immutable evidence store with canonical payload SHA-256 integrity.
- VerificationCoordinator joining deterministic gate, final report, TaskState and learning.
- Review-required learning candidates for failed assumptions, conflicts and verification gaps.
- LunaRuntime evidence recording, verified finalization and terminal continuity checkpoint.
- Phase 12F RFC, verifier, tests, CLI smoke and quality-gate integration.

### Security

- Model inference cannot promote itself into completion evidence.
- Generic tool output alone cannot satisfy the default strong-evidence completion threshold.
- Stale revision/environment evidence cannot verify current state.
- Conflicting qualifying PASS/FAIL evidence cannot be silently collapsed into success.
- Evidence IDs cannot be overwritten with a different payload.
- Final report remains bound to CompletionGate status.
- Learning candidates always require review and cannot auto-commit to policy or memory.

## [0.1.0-phase12e] - 2026-08-07

### Added

- Authoritative `LunaRuntime.run()` / `resume()` single policy-agent loop.
- Exactly-one-action model boundary with runtime-owned authorization and execution.
- Durable SQLite write-ahead side-effect receipts and structured observation journal.
- Tool observations fed into later model turns as DATA_ONLY runtime continuity.
- Safe suspend/cancel control and crash-stage-specific resume reconciliation.
- Actual HIGH/CRITICAL Git worktree lifecycle with effective-workspace continuity.
- Phase 12F completion handoff through `VERIFICATION_PENDING`.
- RFC-012E, verifier, behavior tests, CLI smoke, and quality-gate integration.

### Security

- Ambiguous STARTED side effects are never automatically replayed.
- Multiple model tool calls are rejected before dispatch.
- Tool output cannot become runtime control authority.
- HIGH/CRITICAL writes cannot silently downgrade from worktree isolation.
- Safe cancellation can abort PREPARED work and clean an owned task worktree.
- Phase 12E cannot manufacture `VERIFIED_COMPLETE`.

## [0.1.0-phase12d] - 2026-08-07

### Added

- Stable runtime-owned failure taxonomy and structured recovery decisions.
- Exact transient-error allowlist; model prose cannot grant retry authority.
- Changed-basis-only transient retry policy with deterministic replan fallback.
- Minimal-change path/file/line budgets and observed scope-creep detection.
- Risk-based NONE/SNAPSHOT/WORKTREE isolation planning.
- RFC-012D, verifier, unit tests, CLI smoke, and quality-gate integration.

### Security

- Permission/scope denial never blind-retries.
- Stale state requires reinspection and verification failure can require rollback.
- Integrity failure and hard budget exhaustion stop safely.
- HIGH/CRITICAL worktree requirement cannot silently downgrade to snapshot-only execution.
- Recovery policy performs no hidden tool, rollback, process, network, or Git execution.

## [0.1.0-phase12c] - 2026-08-07

### Added

- Untrusted `ActionProposal` and one-side-effect-per-iteration batch contract.
- Runtime-owned Stage 1 tool-family and Stage 2 registered ToolSpec selection.
- Explicit `ToolRoute` metadata for built-in Phase 5 tools.
- Strict argument validation and deterministic dispatcher-policy preflight.
- Structured denial codes/stages/checks normalized into BLOCKED observations.
- `ActionResolution` PREPARED/DENIED boundary and explicit dispatcher handoff.
- RFC-012C, verifier, unit tests, CLI smoke, and quality-gate integration.

### Security

- Model proposals cannot set runtime risk or create tool authority.
- Invented and route-incompatible tool names are denied.
- Ambiguous tool matches are denied rather than guessed.
- Permission denial never triggers silent fallback to a different tool.
- Selector/resolver never execute handlers; ToolDispatcher remains the execution authority.
- Multiple side-effect proposals in one iteration are rejected.

## [0.1.0-phase12b] - 2026-08-07

### Added

- Canonical `ACTIVE`, `TASK`, `RUNTIME_CONTINUITY`, `WORKSPACE`, and
  `VERIFIED_MEMORY` context layers.
- Runtime-owned `LayeredContextComposer` with deterministic ordering and hard
  per-layer plus overall budgets.
- `CONTROL` versus `DATA_ONLY` interpretation boundary.
- Explicit freshness windows, future/stale rejection, required-context gap tracking,
  and deterministic bundle fingerprinting.
- Verified-memory relevance requirement and compatibility bridge from Phase 2
  `ContextCandidate`.
- Secret-safe model rendering using the existing deterministic redactor.
- RFC-012B, Phase 12B verifier, unit tests, CLI smoke, and quality-gate integration.

### Security

- Unseen or content-unavailable sources cannot enter model context.
- Workspace and memory content cannot be promoted to runtime control instructions.
- Unverified memory blocking and secret redaction cannot be disabled.
- Secret-classified candidates are excluded before model rendering.
- Future/stale sources can be rejected before model use.
- Bulk workspace/memory context cannot crowd out active/task/runtime control context.
- The composer performs no hidden filesystem, process, database, or network I/O.

## [0.1.0-phase12a] - 2026-08-06

### Added

- Runtime-owned request source and verified actor/role contracts.
- Read-only-by-default `RuntimeBudget` and explicit bounded-write budgets.
- `RuntimeRequest` with task/trace identity, scope, autonomy, context, constraints,
  priority, mode, and resume coherence.
- Deterministic SHA-256 task fingerprint excluding transient IDs.
- Explicit runtime dependency injection manifest.
- `RuntimeUsage`, explicit stop reasons, and TaskState-bound `RuntimeOutcome`.
- RFC-012A, Phase 11 source baseline, L01–L21 evidence map, Phase 12A verifier,
  tests, and CLI smoke.

### Security

- Privileged actor roles without runtime verification are rejected.
- Read-only scope cannot carry write or network budgets.
- Write scope requires explicit change budgets; dry-run cannot authorize writes.
- Resume target mismatch is rejected before execution.
- `COMPLETED` cannot be emitted without closed state, `VERIFIED_COMPLETE`, and a
  final-report reference.
- Future orchestrator dependencies cannot silently resolve from global state.

## [0.1.0-phase11] - 2026-08-06

### Added

- Revision ve SHA-256 ile kilitlenen 11 vakalık sabit Luna core eval suite.
- Fixture/oracle bütünlüğünü doğrulayan `LockedEvalSuite`.
- Gerçek çekirdek bileşenlerini çalıştıran `CoreAcceptanceExecutor`.
- Deterministik `RegressionRunner`, `EvalMetrics` ve `EvalReport`.
- Karşılaştırılabilir görev başarısı, yanlış başarı, scope, retry, rollback,
  resume, hafıza ve rapor doğruluğu metrikleri.
- Runtime-owned `ReleaseGate`, açık eşikler ve bilinen sınırlama zorunluluğu.
- Faz 11 verifier, unit/integration/acceptance testleri ve `phase11-smoke`.

### Security

- Sabit eval fixture veya oracle içeriğinin hash güncellenmeden değiştirilmesi
  engellendi.
- Model veya rapor beyanının release yetkisi vermesi engellendi.
- Kritik yanlış `VERIFIED_COMPLETE`, protected-path ihlali ve blind retry için
  release eşiği sıfıra kilitlendi.
- Kritik vaka, rollback, restart/resume, memory cleanliness, scope ve final report
  doğruluğu geçmeden release PASS verilmesi engellendi.
- Bilinen sınırlamalar yayınlanmadan release PASS verilmesi engellendi.


## [0.1.0-phase10] - 2026-08-06

### Added

- Versioned `IdentityProfile`, `UserProfile` ve kilitli iletişim ilkeleri.
- Kullanıcıya ait adlandırma alanlarının runtime profilinden çözülmesi; sabit kişi adı yok.
- Gate-owned `FinalReportComposer` ve yapılan/değişen/doğrulanan/doğrulanamayan/risk ayrımı.
- Append-only `FINAL_REPORT` audit olayı.
- Runtime-enforced autonomy Level 0–4 ve Phase 4/5 adları için uyumluluk alias'ları.
- Ayrı, süreli, domain/tool/bütçe sınırlı `FREE_RESEARCH` kontratı.
- Dispatcher içinde Level 4 istek bütçesi ve oturum süresi muhasebesi.
- Faz 10 unit, integration, verifier ve CLI smoke testleri.

### Security

- Modelin yetki kaynağı olarak kabul edilmesi engellendi.
- Level 0 araç yürütmesi, Level 1 yazma ve Level 2 ağ erişimi runtime'da engellendi.
- Level 4 için kontratsız, süresi geçmiş, bütçesi tükenmiş veya domain dışı çağrı engellendi.
- `FREE_RESEARCH` ile workspace yazma yetkisi verilmesi engellendi.
- Nihai raporun completion gate ve verification report ile çelişmesi engellendi.

## [0.1.0-phase9] - 2026-08-06

### Added

- SQLite WAL tabanlı, scope ayrımlı verified-memory store.
- `MemoryCandidate → policy/verification → commit/reject` akışı.
- Kaynak, zaman, güven, scope, sensitivity, expiry ve supersedes metaverileri.
- Deterministik scope/type/term/confidence retrieval.
- Atomik supersede zinciri, expiry ve kullanıcı kontrollü forget işlemi.
- Append-only memory candidate, decision, commit, retrieval ve forget audit olayları.
- Faz 9 unit, integration, verifier ve CLI memory smoke testleri.
- Sonuç penceresini açık tutan `scripts/check_hold.bat`.

### Security

- Model inference kaynağının doğrulanmış gerçek olarak commit edilmesi engellendi.
- Tek seferlik tercihin açık kalıcılık isteği veya tekrar olmadan saklanması engellendi.
- Düz metin sırların normal hafızaya yazılması engellendi.
- Secret kayıtlarında yalnız onaylı opaque reference ve sabit placeholder saklanır.
- Private user, project, repository, research, community ve behavior scope'ları
  retrieval sırasında birbirinden ayrıldı.

## [0.1.0-phase8] - 2026-08-06

### Added

- SQLite WAL tabanlı atomic TaskState ve checkpoint persistence.
- Schema migration v1 ve SHA-256 payload integrity.
- Immutable checkpoint chain ve optimistic revision guard.
- Runtime revision, workspace ve environment restart doğrulaması.
- Persist edilmiş AttemptRecord geçmişiyle restart sonrası blind-retry guard.
- Append-only CHECKPOINT_CREATED ve RESUME_DECISION audit olayları.
- Faz 8 unit, integration, verifier ve CLI restart smoke testleri.

### Fixed

- Windows `checkpoint-smoke` sonrasında açık kalan SQLite read bağlantılarının
  `runtime.sqlite3` üzerinde `WinError 32` dosya kilidi oluşturması giderildi.

### Security

- Aktifken kesilmiş eylemin observation reconciliation olmadan tekrar
  çalıştırılması engellendi.
- Terminal görev checkpoint'inin değiştirilmesi engellendi.
- Aynı checkpoint'in ikinci kez resume edilmesi engellendi.

## [0.1.0-phase7] - 2026-08-06

### Added

- Kontrattan SHA-256 tabanlı required ve forbidden-absence claim kimlikleri.
- Revision, environment, freshness ve clock-tolerance evidence filtreleri.
- Deterministik requirement→evidence verifier.
- Evidence requirement kelime haritası ve açık UNVERIFIED fallback.
- Claim conflict ve altı resmi completion status kararı.
- Append-only VerificationReport ve CompletionDecision audit olayları.
- VERIFYING → REPORTING completion status uygulaması.
- Faz 7 birim, entegrasyon, verifier ve CLI smoke testleri.

### Security

- Model beyanının completion gate'i atlaması engellendi.
- Eski revision veya yanlış environment kanıtının VERIFIED_COMPLETE üretmesi engellendi.
- Audit bütünlüğü bozukken completion kararı üretilmesi engellendi.

## [0.1.0-phase6] - 2026-08-06

### Added

- Append-only SHA-256 zincirli audit ledger.
- Redacted content-addressed output store.
- Observation ve Evidence audit bağlantısı.
