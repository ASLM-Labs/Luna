# Faz 9 Mimari Sınırı

Faz 9, uzun dönem hafızayı doğrudan model çıktısı olarak değil, doğrulanabilir
bir runtime işlemi olarak uygular:

```text
memory candidate → policy check → verification → commit / reject
```

## Var

- Faz 1–8 yetenekleri;
- SQLite WAL memory schema migration v1;
- kaynak, timestamp, confidence, scope, sensitivity, expiry ve supersedes;
- model inference için zorunlu reject;
- tek seferlik tercih için kalıcılık blokajı;
- secret plaintext yerine yalnız opaque secret reference;
- private user, project, repository, research, community ve behavior scope ayrımı;
- aktif kayıt retrieval'i;
- otomatik expiry;
- atomik supersede zinciri;
- kullanıcı kontrollü forget;
- SHA-256 payload bütünlüğü;
- memory candidate/decision/commit/retrieval/forget audit olayları;
- Windows dosya kilidi bırakmayan kısa ömürlü SQLite bağlantıları.

## Yok

- otomatik kullanıcı kimliği veya sabit kişi adı;
- final report composer;
- autonomy level 0–4 runtime enforcement;
- sabit eval suite ve release gate;
- ağ araçları;
- subagent.

Güncel açık kullanıcı talimatı eski hafızadan üstündür. Retrieval yalnız istenen
scope içinden aktif, süresi dolmamış ve güven eşiğini geçen kayıtları döndürür.
