# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 4 — model backend sınırı ve kontrollü araç çalıştırma**
durumundadır.

## Faz 4'te çalışan parçalar

- sağlayıcıdan bağımsız `ModelBackend` arayüzü;
- model erişimi gerektirmeyen deterministik `ScriptedTestBackend`;
- yalnız loopback adreslerine bağlanan yerel OpenAI-compatible adapter;
- `ToolSpec`, `ToolRequest`, `ToolResult` ve `ToolEvent` kontratları;
- kayıtlı olmayan aracı çalıştırmayan deny-by-default registry/dispatcher;
- açık izin, risk, özerklik, scope, argüman, timeout, çıktı ve cwd kontrolleri;
- model tool-call önerilerini sıradan ve yetkisiz request olarak ele alan trust boundary;
- hashli ve sınırlı output ile yapılandırılmış `Observation` üretimi;
- yan etkisiz `core.echo` ve scope kontrollü iki read-only filesystem aracı.

## Henüz kapalı yetenekler

- shell ve process çalıştırma;
- dosya yazma, snapshot ve rollback;
- internet/web araçları;
- kalıcı audit, checkpoint ve hafıza;
- deterministic completion verifier;
- subagent.

## Kurulum ve kalite kapısı

```bat
scriptsootstrap.bat
scripts\check.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 4 model ve tool kapisi gecti.
```

## CLI

```bat
.venv\Scripts\python.exe -m luna status
.venv\Scripts\python.exe -m luna list-tools
.venv\Scripts\python.exe -m luna tool-smoke "merhaba"
```

Model bir araç çağrısı önerebilir; izni model vermez. Son karar her zaman runtime
tarafındaki `ToolDispatcher` tarafından verilir.
