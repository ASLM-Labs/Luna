# Faz 8 Mimari Sınırı

Faz 8, görev durumunu ve checkpoint zincirini SQLite WAL içinde atomik ve
restart-safe biçimde saklar.

## Var

- Faz 1–7 yetenekleri;
- SQLite schema migration v1;
- task state + checkpoint atomik transaction;
- immutable checkpoint zinciri;
- SHA-256 payload bütünlüğü;
- optimistic revision kontrolü;
- terminal checkpoint değişmezliği;
- runtime revision, workspace ve environment resume guard;
- aktif eylem reconciliation blokajı;
- persist edilmiş blind-retry geçmişi;
- checkpoint/resume audit olayları;
- gerçek restart simülasyonu.

## Yok

- doğrulanmış uzun dönem hafıza;
- kullanıcı profili yönetimi;
- final kimlik ve kullanıcı raporu;
- sabit eval suite ve release gate;
- ağ araçları;
- subagent.

Resume bir önceki eylemi otomatik tekrarlamaz. Kesilmiş aktif adım varsa
görev BLOCKED kalır ve yeni gözlem/reconciliation gerekir.
