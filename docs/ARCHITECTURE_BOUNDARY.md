# Faz 6 Mimari Sınırı

Faz 6, kontrollü araç akışının gözlemlerini kalıcı, redakte edilmiş ve
değişiklik tespit edilebilir bir audit/evidence katmanına bağlar.

## Var

- Faz 1–5 kontrat, planning, dispatcher, safe process ve workspace katmanları;
- append-only JSONL audit ledger;
- sıralı SHA-256 event chain ve replay doğrulaması;
- task/tool/observation/evidence için ortak `trace_id`;
- hassas değerleri persistence öncesinde redakte eden sınır;
- content-addressed tam stdout/stderr artifact deposu;
- bounded excerpt ve hash reference kullanan Observation;
- current Observation → Evidence oluşturma;
- correction-as-new-event davranışı;
- owner task audit inspection API/CLI.

## Yok

- requirement→evidence completion verifier;
- `VERIFIED_COMPLETE` kararı;
- conflicting-evidence resolution;
- SQLite task/checkpoint/memory state;
- network/web araçları;
- subagent.

Audit log bir reasoning/chain-of-thought günlüğü değildir. Yalnız karar için
gerekli observable olay, policy, result, observation ve evidence kayıtlarını tutar.
