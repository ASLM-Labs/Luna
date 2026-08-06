# Faz 5 Toplu İnceleme ve Düzeltme Raporu

## İncelenen kaynak

Kullanıcının yüklediği `Luna.zip`, Faz 1–5 ana repository kopyası olarak incelendi.

## İlk durum

- Pytest: `93 passed, 1 failed`; başarısızlık eksik `LICENSE` dosyasıydı.
- Faz 1–5 davranış verifier'ları: ilk dört PASS; Faz 5 kodu önceki sürümde PASS veriyordu.
- Repository integrity: manifestte 2 eksik dosya (`LICENSE`, `.editorconfig`) ve 32 hash uyuşmazlığı vardı.
- ZIP içinde `__pycache__`, `.pyc` ve `*.egg-info` üretilmiş dosyaları bulunuyordu.
- Kullanıcının Windows kalite kapısında Ruff geçmiş, mypy 3 dosyada 4 hata göstermişti.

## Bulunan ek güvenlik boşlukları

Toplu inceleme sırasında yalnız tip/format hataları değil, iki gerçek process-boundary açığı da bulundu:

1. `pwsh.exe`, `bash.exe`, `sh.exe`, `zsh.exe`, `fish.exe`, `powershell_ise.exe` ve `command.com` denylist kapsamı dışındaydı.
2. Windows Python launcher `py -c` inline kod çalıştırma yolu engellenmemişti.

Bu yollar yeni regresyon testleriyle kapatıldı.

## Uygulanan düzeltmeler

- Tam Apache License 2.0 metni ve `.editorconfig` eklendi.
- POSIX process-group sonlandırması Windows mypy ile uyumlu, korumalı `getattr` fallback'iyle düzenlendi.
- Numeric tool argument narrowing açık `isinstance` kontrolüyle güvenli hâle getirildi.
- Optional replanner expectation açıkça kontrol edildi.
- Shell executable denylist'i genişletildi ve `py/py.exe -c` engellendi.
- `compileall` yerine bytecode üretmeyen `scripts/verify_syntax.py` eklendi.
- `check.bat`, pytest temp klasörünü başarısızlıkta da temizleyecek biçimde güncellendi.
- CI, yerel kalite kapısıyla aynı syntax ve pytest sınırını kullanacak şekilde güncellendi.
- Cache ve egg-info temizleme aracı eklendi.
- Manifest ile SHA-256 listesi sıfırdan üretildi.

## Bu ortamda tekrar çalıştırılan toplu test

- Syntax: `87 Python files parsed`
- Pytest: `112 passed in 1.22s`
- Faz verifier exit code'ları: `[0, 0, 0, 0, 0]`
- CLI smoke exit code'ları: `[0, 0, 0, 0, 0, 0]`
- Integrity: eksik `0`, hash uyuşmazlığı `0`

## Özellik koruması

- Snapshot-first yazma korunuyor.
- SHA-256 precondition korunuyor.
- Otomatik ve açık rollback doğrulaması korunuyor.
- `shell=False` ve exact-argv onayı korunuyor.
- Testler veya güvenlik eşikleri zayıflatılmadı.
- Denylist genişletildi; yani process sınırı daha sıkı hâle geldi.

## Nihai durum

`IMPLEMENTED_UNVERIFIED`

Bu ortamda Ruff ve mypy paketleri bulunmadığı için nihai Windows PASS ilan edilmedi. Hedef makinede:

```powershell
.\.venv\Scripts\python.exe scripts\clean_generated_artifacts.py
.\scripts\check.bat *> .\phase5_check.log
$LASTEXITCODE
Get-Content .\phase5_check.log -Tail 80
```

Nihai kabul: exit code `0` ve log sonunda `[PASS] Luna 0.1 Faz 5 workspace, shell ve rollback kapisi gecti.`
