# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 3 — uyarlanabilir plan, eylem öncesi beklenti ve
gözleme göre yeniden planlama** durumundadır.

## Faz 3'te çalışan parçalar

- görev boyutuna göre `SIMPLE`, `STANDARD` veya `COMPLEX` kısa plan;
- sıralı ve doğrulanan plan-adımı yaşam döngüsü;
- yüksek etkili adım öncesi zorunlu `ExpectedObservation`;
- gerçek `Observation` ile deterministik beklenti karşılaştırması;
- başarısız varsayım kaydı;
- aynı eylemi aynı koşullarla yeniden çalıştırmayı engelleyen retry guard;
- yeni kanıt veya değişen stratejiyle sürümlü replan.

## Henüz kapalı yetenekler

- gerçek model backend;
- dosya veya web kaynağını kendiliğinden okuma;
- shell ve Tool Dispatcher;
- workspace yazma;
- verifier, checkpoint ve hafıza depoları;
- zamanlanmış çalışma ve subagent.

## Kurulum

```bat
scripts\bootstrap.bat
```

## Kalite kapısı

```bat
scripts\check.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 3 planning ve replan kapisi gecti.
```

## CLI

```bat
.venv\Scripts\python.exe -m luna --version
.venv\Scripts\python.exe -m luna status
.venv\Scripts\python.exe -m luna resolve-intent "README.md dosyasını incele"
```

Faz 3 planlayıcısı gerçek araç kullanmaz. Araç yürütme Faz 4'e kadar kapalıdır.
