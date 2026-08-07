# Changelog

Tüm önemli değişiklikler bu dosyada belgelenir.

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
