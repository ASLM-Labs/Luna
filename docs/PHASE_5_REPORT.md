# Faz 5 — Güvenli Shell, Workspace Değişikliği ve Rollback

**Paket hazırlık durumu:** `IMPLEMENTED_UNVERIFIED`

## Uygulananlar

- `ProcessApproval`
- `process.run_argv`
- `SafeProcessRunner`
- `WorkspaceSnapshot`
- `WorkspaceSnapshotStore`
- `WorkspaceMutator`
- `filesystem.write_text`
- `filesystem.replace_text`
- `workspace.rollback`

## Zorunlu davranışlar

- process yalnız exact owner-approved argv ve cwd ile çalışır;
- `shell=False` sabittir; command string kabul edilmez;
- `cmd`, PowerShell, Bash ve benzeri shell/script-host programları reddedilir;
- Python `-c` ve benzeri inline-code yolları reddedilir;
- stdin kapalı, environment sınırlı, timeout ve output budget serttir;
- write için explicit TaskScope ve ExpectedObservation gerekir;
- mevcut dosya overwrite işlemi güncel SHA-256 precondition ister;
- yeni dosya oluşturma ayrıca açıkça onaylanır;
- replace işlemi exact occurrence count ister;
- her write öncesi snapshot kalıcılaştırılır;
- blob ve manifest hash doğrulaması olmadan rollback yapılmaz;
- post-write digest uyuşmazlığında otomatik rollback uygulanır;
- protected descendant, `.luna`, traversal ve symlink hedefleri reddedilir;
- dosya silme ve network araçları kayıtlı değildir.

## Paket üretim ortamı kanıtı

- 77 Python dosyası parse edildi;
- pytest: **94 passed**;
- Faz 1, 2, 3, 4 ve 5 verifier: **PASS**;
- editable install: **PASS**;
- CLI echo, workspace rollback ve exact-argv process smoke: **PASS**;
- Ruff ve mypy: paket üretim ortamında mevcut olmadığından **NOT_RUN**.

Ruff ve mypy strict sonucu hedef Windows makinesindeki `scripts\check.bat` ile kapanır.
Bu nedenle owner makinesindeki tam kalite kapısı görülmeden durum PASS'e yükseltilmez.

## Hedef makinede kapanış

```bat
scripts\bootstrap.bat
scripts\check.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 5 workspace, shell ve rollback kapisi gecti.
```
