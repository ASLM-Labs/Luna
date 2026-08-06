# Changelog

Tüm önemli değişiklikler bu dosyada belgelenir.


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
