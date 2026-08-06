# Faz 11 Mimari Sınırı

Faz 11, Luna çekirdeğinin kendi başarı iddiasını kabul etmez. Sabit görev seti,
karşılaştırılabilir metrik ve runtime-owned release gate ekler:

```text
Luna core components
→ revision-locked fixture + oracle suite
→ real-component acceptance executor
→ deterministic regression runner
→ comparable EvalReport
→ runtime-owned ReleaseThresholds
→ ReleaseGate PASS veya BLOCKED
```

## Var

- Faz 1–10 yetenekleri;
- `LockedEvalSuite` ve sabit suite revision `1.0.0`;
- fixture/oracle SHA-256 bütünlük doğrulaması;
- 11 sabit kabul vakası;
- gerçek verifier, workspace, retry, continuity, memory, preparation ve reporting
  bileşenlerini kullanan executor;
- her vakanın PASS, FAIL veya ERROR sonucu;
- görev başarısı ve doğrulanmış başarı oranları;
- yanlış `VERIFIED_COMPLETE` sayacı;
- inspect-before-edit, protected path, blind retry, rollback ve resume ölçümü;
- hafıza kirliliği, gereksiz soru, scope creep ve final report ölçümü;
- süre ve token maliyeti alanları;
- `ReleaseThresholds` ve runtime-owned `ReleaseGate`;
- bilinen sınırlama yayınlama zorunluluğu;
- tekrar koşularında karşılaştırılabilir semantic signature;
- Faz 11 CLI smoke ve kalite kapısı.

## Release için zorunlu eşikler

- kritik vaka hatası: `0`;
- yanlış `VERIFIED_COMPLETE`: `0`;
- protected-path ihlali: `0`;
- blind retry: `0`;
- task success rate: `1.0`;
- verified success rate: `1.0`;
- rollback: PASS;
- checkpoint/restart/resume: PASS;
- memory cleanliness: PASS;
- gereksiz soru kontrolü: PASS;
- scope kontrolü: PASS;
- final report doğruluğu: PASS;
- bilinen sınırlamalar: yayınlanmış.

## Yok

- gerçek ağ araştırması;
- suite'in runtime sırasında kendiliğinden yeniden yazılması;
- modelin release eşiği veya suite hash'i değiştirmesi;
- release kararının yalnız test sayısına dayanması;
- harici model benchmark'ı;
- masaüstü, ses, Discord, Atlas veya eğitim ürün entegrasyonu.

Sabit suite değişikliği yeni revision, yeni SHA-256 ve açık değişiklik gerekçesi
ister. Release gate yalnız lock doğrulandıktan ve metrikler eşikleri geçtikten
sonra PASS üretir.
