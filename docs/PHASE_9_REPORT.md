# Faz 9 — Doğrulanmış Hafıza

**Paket hazırlık durumu:** `IMPLEMENTED_UNVERIFIED`

## Uygulananlar

- `MemoryCandidate`
- `MemoryRecord`
- `MemoryPolicy`
- `MemoryPolicyEvaluator`
- `SQLiteMemoryStore`
- `VerifiedMemoryService`
- `MemoryQuery`
- `MemoryRetrieval`
- `MemoryIntegrity`

## Zorunlu davranışlar

- hafıza yalnız candidate → policy/verification → commit/reject akışıyla yazılır;
- model inference kaynağı doğrulanmış gerçek olarak commit edilemez;
- güven eşiğinin altındaki aday reddedilir;
- tek seferlik tercih, açık kalıcılık talebi veya tekrar olmadan saklanmaz;
- değişebilir araştırma bilgisi expiry olmadan commit edilemez;
- SECRET kayıt düz metin statement taşımaz;
- sır yalnız onaylı `secret://`, `keyring://` veya `vault://` referansıyla saklanır;
- source, source_ref, observed/verified time, confidence ve scope korunur;
- retrieval scope sınırını aşamaz;
- supersede atomik olarak yeni kaydı aktif, eski kaydı pasif yapar;
- süresi dolan kayıt retrieval'den çıkarılır ve EXPIRED yapılır;
- kullanıcı forget işlemiyle kaydı retrieval'den kaldırabilir;
- SQLite WAL, FULL synchronous, foreign key, secure_delete ve busy timeout kullanılır;
- payload SHA-256 bütünlüğü ve supersession bağlantıları doğrulanır;
- SQLite bağlantıları her işlem sonunda kapatılır;
- adayın statement veya secret_ref değeri audit ledger'a yazılmaz;
- memory candidate, decision, commit, retrieval ve forget işlemleri audit edilir.

## Paket ortamındaki doğrulama

```text
Python syntax       124 dosya PASS
Pytest              170 passed
Faz 1–9 verifier    PASS
memory-smoke        PASS
```

Ruff ve mypy strict, hedef Windows `.venv` ortamındaki tam kalite kapısında
çalıştırılmalıdır. Bu nedenle nihai durum yerel Windows sonucu görülene kadar
`IMPLEMENTED_UNVERIFIED` kalır.

## Hedef makinede kapanış

```bat
scripts\check_hold.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 9 dogrulanmis hafiza kapisi gecti.
```

## Bilinçli sınır

Kimlik profili, final report composer ve autonomy level 0–4 Faz 10'a aittir.
