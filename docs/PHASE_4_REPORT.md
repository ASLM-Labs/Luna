# Faz 4 — Model Backend Sınırı ve Kontrollü Araçlar

**Paket hazırlık durumu:** `IMPLEMENTED_UNVERIFIED`

## Uygulananlar

- `ModelBackend`
- `ModelRequest` / `ModelResponse`
- `ScriptedTestBackend`
- `LocalOpenAICompatibleBackend`
- `ToolSpec`
- `ToolRequest`
- `ToolResult`
- `ToolEvent`
- `ToolPolicy`
- `ToolRegistry`
- `ToolDispatcher`
- `core.echo`
- `filesystem.read_text`
- `filesystem.list_directory`

## Zorunlu davranışlar

- çekirdek testler model sunucusu olmadan çalışır;
- local adapter dış internet endpoint'ini kabul etmez;
- kayıtlı olmayan araç handler'a ulaşmaz;
- boş allowlist bütün araçları reddeder;
- model origin'i izin kazandırmaz;
- unknown veya yanlış tipte argüman reddedilir;
- write/network/process kabiliyeti expectation_id olmadan çalışmaz;
- timeout ve output bütçesi çalıştırmadan önce kontrol edilir;
- read araçları canonical workspace ve allowed_paths sınırındadır;
- her deneme result, event ve observation ile trace edilir;
- stdout/stderr tam içerik yerine bounded excerpt ve SHA-256 referansı taşır.

## Bilinçli olarak kapalı

Shell, process, file write, network tools, rollback ve kalıcı audit bu fazda açılmaz.

## Hedef makinede kapanış

```bat
scriptsootstrap.bat
scripts\check.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 4 model ve tool kapisi gecti.
```
