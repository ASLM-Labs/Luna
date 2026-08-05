# Faz 0 Doğrulama Raporu

**Durum:** `IMPLEMENTED_UNVERIFIED`

## Geçen kontroller

- Python compileall: `PASS`
- pytest: `PASS` — 6 test geçti
- Standard-library structural verifier: `PASS`
- Doğrudan CLI version smoke: `PASS`
- Doğrudan CLI status smoke: `PASS`

## Hedef makinede bekleyen kontroller

Artifact üretim ortamında temiz venv içinde `setuptools.build_meta`, Ruff ve mypy erişilebilir değildi. Bu nedenle temiz editable install, Ruff ve mypy sonuçları üretilmiş gibi gösterilmedi.

Windows hedef makinede:

```bat
scripts\bootstrap.bat
scripts\check.bat
```

İkinci komut exit code `0` vermeden Faz 0 `PASS` sayılmaz ve Faz 1 başlamaz.
