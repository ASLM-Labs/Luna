# Luna 0.1

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ runtime çekirdeğidir.

Bu repository şu anda **Faz 0 — repository ve kalite iskeleti** durumundadır. Model, araç yürütme, hafıza, shell, web ve dosya değiştirme yetenekleri henüz aktif değildir.

## Gereksinimler
- Windows 11
- Python 3.12 veya 3.13
- Git

## Kurulum
```bat
scripts\bootstrap.bat
```

## Kalite kontrolleri
```bat
scripts\check.bat
```

## CLI
```bat
.venv\Scripts\python.exe -m luna --version
.venv\Scripts\python.exe -m luna status
```

Beklenen Faz 0 durumu:
```text
phase: 0
status: SCAFFOLD_READY
runtime_capabilities: disabled
```

## Yönetişim
Onaylı teknik anayasa: `docs/governance/Luna_0.1_Teknik_Anayasa_v0.1.md`

Faz 1 başlamadan önce Faz 0 doğrulama raporu `PASS` olmalıdır.
