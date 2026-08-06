# Faz 10 Mimari Sınırı

Faz 10, kimliği model davranışına bırakmaz; yetkiyi model beyanından ayırır ve
nihai raporu completion gate'e bağlar:

```text
versioned identity profile + verified memory + runtime rules
→ runtime-owned autonomy policy
→ controlled tool execution
→ deterministic verification/completion
→ gate-bound final report
```

## Var

- Faz 1–9 yetenekleri;
- tek aktif `IdentityProfile` ve version/revision alanları;
- runtime `UserProfile`: `user_id`, `display_name`, `alias`, `preferred_address`;
- doğal, sıcak, açık ve dürüst iletişim ilkeleri;
- bilinç, duygu ve kanıtsız kesinlik iddiası blokajı;
- yapılan, değişen, doğrulanan, doğrulanamayan, risk ve completion status ayrımı;
- `FinalReportComposer` ile verification report ve completion decision bağlantısı;
- append-only `FINAL_REPORT` audit olayı;
- autonomy Level 0–4;
- Level 0 araç blokajı, Level 1 salt-okunur sınırı, Level 2 ağ blokajı;
- Level 3 yüksek-risk owner approval ve mevcut exact-argv korumaları;
- Level 4 için ayrı `FREE_RESEARCH` kontratı;
- Level 4 tool/domain/expiry/duration/request-budget enforcement;
- modelin yetki kaynağı olamaması;
- Phase 4/5 autonomy adları için geriye uyumlu parse alias'ları.

## Yok

- sabit kişi adı veya model ağırlığına gömülü kullanıcı profili;
- gerçek ağ aracı veya otomatik web araştırması;
- Level 4'ün varsayılan olarak açılması;
- zamanlayıcı;
- subagent;
- sabit eval suite ve release gate;
- masaüstü, ses veya Discord ürün entegrasyonu.

Açık kullanıcı talimatı, doğrulanmış hafıza ve runtime policy sırasıyla ele alınır;
model önerisi hiçbir zaman izin veya completion kararı değildir.
