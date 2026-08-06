# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 5 — güvenli process çalıştırma, kontrollü dosya değişikliği,
snapshot ve rollback** durumundadır.

## Faz 5'te çalışan parçalar

- Faz 1–4 kontrat, intent, context, planning, model ve dispatcher katmanları;
- `shell=False` kullanan exact-argv process runner;
- her komut için tam argv ve çalışma klasörü owner approval kontrolü;
- shell/script-host ve inline interpreter kaçışlarının reddi;
- timeout, stdin kapatma, sınırlı environment ve bounded stdout/stderr;
- SHA-256 precondition gerektiren atomik UTF-8 dosya yazımı;
- exact occurrence sayısına bağlı minimal text replacement;
- her write işleminden önce kalıcı snapshot manifesti ve content blob'u;
- snapshot ve blob bütünlüğü için SHA-256 doğrulaması;
- post-write doğrulama başarısızsa otomatik rollback;
- owner-approved açık rollback aracı;
- protected path descendant ve symlink bileşeni engeli.

## Bilinçli olarak kapalı yetenekler

- command string, `cmd /c`, PowerShell, Bash veya `shell=True`;
- keyfî environment/stdio injection;
- dosya silme ve dizin ağacı değişikliği;
- internet/web araçları;
- append-only kalıcı audit, checkpoint ve hafıza;
- deterministic completion verifier;
- subagent.

## Kurulum ve kalite kapısı

```bat
scripts\bootstrap.bat
scripts\check.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 5 workspace, shell ve rollback kapisi gecti.
```

## CLI

```bat
.venv\Scripts\python.exe -m luna status
.venv\Scripts\python.exe -m luna list-tools
.venv\Scripts\python.exe -m luna workspace-smoke
.venv\Scripts\python.exe -m luna process-smoke
```

Process aracı yalnız runtime sahibi tarafından **tam olarak onaylanmış argv** ile
çalışır. Modelin komut önermesi izin değildir. Dosya yazımı da önce snapshot alır;
başarı sonrası hash doğrulanmadan değişiklik committed sayılmaz.
