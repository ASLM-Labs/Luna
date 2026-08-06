# Faz 5 Mimari Sınırı

Faz 5, Luna'nın proje üzerinde sınırlı ve geri alınabilir yan etki üretmesini
kanıtlar. Model hâlâ karar yetkisine sahip değildir; izin, scope ve onay runtime
katmanındadır.

## Var

- Faz 1 çekirdek kontratları;
- Faz 2 intent, contract draft ve context hazırlığı;
- Faz 3 adaptive planning, expectation ve retry guard;
- Faz 4 model backend sınırı ve deny-by-default dispatcher;
- `process.run_argv` için exact argv + cwd approval;
- `shell=False`, kapalı stdin, hard timeout ve bounded output;
- shell/script-host ve inline-code reddi;
- `filesystem.write_text` ve `filesystem.replace_text`;
- write öncesi snapshot, content-addressed blob ve SHA-256 manifest;
- atomic replace, post-write digest doğrulaması ve otomatik rollback;
- owner-approved `workspace.rollback`;
- protected descendant, path traversal, workspace escape ve symlink engeli;
- her işlemde `ToolResult`, `ToolEvent`, `Observation` ve change hash evidence.

## Yok

- command string veya genel amaçlı interactive shell;
- dosya/dizin silme aracı;
- network tool;
- append-only kalıcı audit deposu;
- deterministic completion verifier;
- kalıcı checkpoint veya memory;
- subagent.

Snapshot verileri workspace içindeki runtime-owned `.luna/snapshots` alanında tutulur
ve `.gitignore` tarafından dışlanır. Task araçları `.luna` altını hedefleyemez.
Rollback yalnız aynı workspace ve aynı `task_id` için geçerlidir; manifest veya blob
hash'i uyuşmazsa restore başlamadan reddedilir.
