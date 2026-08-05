# Faz 4 Mimari Sınırı

Faz 4, model ile runtime arasındaki güven sınırını ve read-only kontrollü araç
çalıştırmayı kanıtlar.

## Var

- Faz 1 çekirdek kontratları;
- Faz 2 intent, contract draft ve context hazırlığı;
- Faz 3 adaptive planning, expectation ve retry guard;
- provider-independent `ModelBackend`;
- deterministik `ScriptedTestBackend`;
- loopback-only local OpenAI-compatible adapter;
- deny-by-default `ToolRegistry` ve `ToolDispatcher`;
- explicit tool allowlist, risk, autonomy, scope, schema, timeout, output ve cwd kontrolü;
- her denemede `ToolResult`, `ToolEvent` ve `Observation`;
- bounded output excerpt ve SHA-256 log referansı;
- `core.echo`, `filesystem.read_text`, `filesystem.list_directory`.

## Yok

- shell/process tool;
- write-capable tool;
- network tool;
- snapshot ve rollback;
- append-only kalıcı audit deposu;
- completion verifier;
- kalıcı checkpoint veya hafıza;
- subagent.

Yerel model adapter'ının endpoint'i yalnız `localhost`, `127.0.0.1` veya `::1`
olabilir. Bir model tool-call ürettiğinde bu yalnız öneridir; permission, scope veya
risk kararı değildir.
