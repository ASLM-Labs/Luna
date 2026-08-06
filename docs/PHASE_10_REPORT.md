# Faz 10 — Kimlik, Raporlama ve Özerklik

**Paket hazırlık durumu:** `IMPLEMENTED_UNVERIFIED`

## Uygulananlar

- `CommunicationPrinciples`
- `UserProfile`
- `IdentityProfile`
- `ReportRisk`
- `FinalReport`
- `FinalReportComposer`
- `AutonomyLevel` 0–4
- `AutonomyGrantSource`
- `AutonomyPolicy`
- `FreeResearchContract`
- dispatcher içi Level 4 kullanım muhasebesi
- `FINAL_REPORT` audit olayı

## Zorunlu davranışlar

- tek aktif kimlik versioned profile ile temsil edilir;
- mimari veya varsayılan profil sabit kullanıcı adı taşımaz;
- runtime profil alanları kullanıcıya hitabı belirler;
- iletişim ilkeleri runtime'da zayıflatılamaz;
- nihai rapor completion gate statüsüyle çelişemez;
- yapılan, değişen, doğrulanan, doğrulanamayan ve risk ayrı alanlardır;
- rapor özel iç muhakeme günlüğü taşımaz;
- model bir autonomy grant kaynağı değildir;
- Level 0 araç çalıştıramaz;
- Level 1 salt-okunur sınırını aşamaz;
- Level 2 ağ yetkisi kullanamaz;
- Level 3 mevcut allowlist, scope, risk ve owner-approval kurallarına tabidir;
- Level 4 ayrı `FREE_RESEARCH` kontratı olmadan oluşturulamaz;
- kontrat tool, domain, expiry, süre ve istek bütçesiyle sınırlıdır;
- `FREE_RESEARCH` workspace yazma yetkisi vermez;
- dispatcher Level 4 request budget'ını runtime içinde tüketir.

## Paket ortamındaki doğrulama

```text
Python syntax       135 dosya PASS
Pytest              186 passed
Faz 1–10 verifier   PASS
phase10-smoke       PASS
```

Ruff ve mypy strict, hedef Windows `.venv` ortamındaki tam kalite kapısında
çalıştırılmalıdır. Bu nedenle nihai durum yerel Windows sonucu görülene kadar
`IMPLEMENTED_UNVERIFIED` kalır.

## Hedef makinede kapanış

```bat
scripts\check_hold.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 10 kimlik, raporlama ve ozerklik kapisi gecti.
```

## Bilinçli sınır

Sabit eval seti, regression runner ve release gate Faz 11'e aittir. Gerçek web
araştırması ve ürün entegrasyonları Faz 12 sonrası ayrı RFC gerektirir.
