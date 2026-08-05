# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 2 — intent, görev kontratı hazırlığı ve bağlam
toplama** durumundadır.

## Faz 2'de çalışan parçalar

- sekiz sürümlü çekirdek kontrat;
- şeffaf ve deterministik intent baseline'ı;
- eksik başarı koşullarını açıkça gösteren görev kontratı taslağı;
- yalnız gözlemlenmiş kaynakları kabul eden context collector;
- kaynak, digest, token tahmini ve bütçe takibi;
- planning öncesi birleşik `TaskPreparation` çıktısı.

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
[PASS] Luna 0.1 Faz 2 intent ve context kapisi gecti.
```

## CLI

```bat
.venv\Scripts\python.exe -m luna --version
.venv\Scripts\python.exe -m luna status
.venv\Scripts\python.exe -m luna resolve-intent "README.md dosyasını incele"
```

Intent resolver, ileride bağlanacak modelin yerine geçmez. Faz 2 için
deterministik, denetlenebilir ve yan etkisiz bir baseline'dır.
