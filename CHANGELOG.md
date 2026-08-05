# Changelog

Tüm önemli değişiklikler bu dosyada belgelenir.

## [0.1.0-phase3] - 2026-08-06

### Added

- Görev boyutuna göre kısa plan üreten adaptive planner baseline'ı.
- Versioned TaskPlan ve doğrulanan plan-step lifecycle.
- Yüksek etkili adımlar için expected-observation kapısı.
- Observation ile deterministic expectation assessment.
- Explicit failed-assumption records.
- Aynı action basis'iyle blind retry engeli.
- Değişen evidence veya strategy ile versioned replan.
- Faz 3 unit, integration ve verifier testleri.

## [0.1.0-phase2] - 2026-08-06

### Added

- Deterministik ve şeffaf intent resolver baseline'ı.
- Intent türü, istenen eylem, resource, unknown ve risk sinyali modelleri.
- Eksik başarı kriterlerini uydurmak yerine blocker olarak gösteren contract draft.
- Kaynak digest'i, availability, context bütçesi ve exclusion kayıtları.
- Gözlemlenmemiş kaynağı active context'e almayan collector.
- Planning öncesi TaskPreparation bütünleştirme akışı.
- Faz 2 birim, entegrasyon ve verifier testleri.
- CLI `resolve-intent` komutu.

### Changed

- Proje geliştiricisi Novopic Intelligence olarak güncellendi.
- LICENSE tam Apache-2.0 metniyle değiştirildi.
- CLI status ve kalite kapısı Faz 2'yi gösterir.
- GitHub Actions Faz 1 ve Faz 2 verifier'larını çalıştırır.

## [0.1.0-phase1] - 2026-08-06

### Added

- Pydantic v2 tabanlı sekiz çekirdek Luna kontratı.
- Sıkı şema sürümü, UTC zaman ve ekstra alan reddi.
- Görev yaşam döngüsü ve kontrollü state transition kuralları.
- Model çıkarımının PASS kanıtı olmasını engelleyen Evidence doğrulaması.
- Checkpoint tutarlılığı ve yeniden başlatma için gerekli alanlar.
- JSON round-trip, şema, geçersiz durum ve transition testleri.
- Faz 1 yapısal doğrulama komutu.

## [0.1.0-phase0] - 2026-08-05

### Added

- Bağımsız Python package iskeleti.
- Windows bootstrap ve kalite kontrol komutları.
- pytest, Ruff ve mypy strict yapılandırması.
- Minimal `luna` CLI.
- CI kalite iş akışı.
- Onaylı Luna 0.1 Teknik Anayasası.
