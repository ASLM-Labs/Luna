# Changelog

Tüm önemli değişiklikler bu dosyada belgelenir.

## [0.1.0-phase4] - 2026-08-06

### Added

- Provider-independent `ModelBackend` ve sürümlü model kontratları.
- Deterministik `ScriptedTestBackend`.
- Loopback-only local OpenAI-compatible model adapter.
- Deny-by-default tool registry, policy ve dispatcher.
- ToolSpec, ToolRequest, ToolResult, ToolEvent ve DispatchOutcome.
- Açık argüman şeması, risk, autonomy, scope, timeout, output ve cwd kapıları.
- Model tool-call önerileri için untrusted bridge.
- Hashli/bounded output ve Observation normalizasyonu.
- Read-only `core.echo`, `filesystem.read_text` ve `filesystem.list_directory` araçları.
- Faz 4 birim, integration ve verifier testleri.

## [0.1.0-phase3] - 2026-08-06

### Added

- Kısa ve deterministik adaptive planning baseline'ı.
- Plan lifecycle, expected-observation değerlendirmesi ve replan versioning.
- Failed-assumption kaydı ve blind-retry guard.

## [0.1.0-phase2] - 2026-08-06

### Added

- Deterministik intent resolution, contract draft ve budgeted context collection.

## [0.1.0-phase1] - 2026-08-06

### Added

- Pydantic v2 tabanlı sekiz çekirdek Luna kontratı.

## [0.1.0-phase0] - 2026-08-05

### Added

- Bağımsız Python package iskeleti ve kalite kapısı.
