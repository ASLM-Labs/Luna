# Faz 2 — Intent, Görev Kontratı Hazırlığı ve Bağlam

**Paket hazırlık durumu:** `IMPLEMENTED_UNVERIFIED`

## Uygulananlar

- `IntentResolution`
- `DeterministicIntentResolver`
- `TaskContractDraft`
- `TaskContractBuilder`
- `ContextSource`
- `ContextBudget`
- `ContextBundle`
- `ContextCollector`
- `TaskPreparation`

## Tasarım sınırı

Resolver şeffaf kural baseline'ıdır; gerçek model reasoning'i olarak sunulmaz.
Collector hiçbir dosyayı veya URL'yi kendiliğinden açmaz. Yalnız çağıran
katmanın gözlemlenmiş içerik olarak verdiği kaynakları bütçe içinde seçer.

## Kabul kanıtları

- aynı normalize edilmiş istek aynı semantik çözümü üretir;
- yazma isteğinde eksik target scope açık unknown olur;
- required condition ve evidence eksikliği açık blocker olur;
- çelişkili required/forbidden koşulları finalization'ı engeller;
- gözlemlenmemiş kaynak active context'e alınmaz;
- context seçimi priority ve hard budget ile deterministiktir;
- tam açık girdiler planning'e hazır bir TaskPreparation üretir.

## Hedef makinede kapanış

```bat
scripts\bootstrap.bat
scripts\check.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 2 intent ve context kapisi gecti.
```
