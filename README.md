# Luna 0.1

**Geliştirici:** Novopic Intelligence

Luna 0.1, tek aktif ajan ve tek devamlı kimlik kullanan yerel bir yapay zekâ
runtime çekirdeğidir.

Repository şu anda **Faz 9 — doğrulanmış hafıza** durumundadır.

## Çalışan zincir

```text
intent → context → contract → plan → expected observation
→ controlled tool use → snapshot/rollback
→ append-only observation/evidence
→ deterministic verification → audited completion
→ SQLite WAL checkpoint → guarded restart/resume
→ memory candidate → policy/verification → commit or reject
→ scoped retrieval → expiry/supersede
```

Luna hafızaya yazmadan önce adayın kaynağını, güvenini, kapsamını,
güncelliğini ve hassasiyetini denetler. Model çıkarımı doğrulanmış gerçek olarak
kaydedilemez. Tek seferlik tercih kalıcı tercih sayılmaz. Sırlar yalnız onaylı
`secret://`, `keyring://` veya `vault://` referansı olarak saklanabilir.

## Kurulum

```bat
scripts\bootstrap.bat
```

## Testler

Windows üzerinde düz `python -m pytest` komutu proje içindeki `.pytest_tmp` klasörünü kullanır; böylece sistem geçici klasöründeki izin sorunlarından etkilenmez.

```bat
python -m pytest
```

## Kalite kapısı

Pencerenin sonuçtan sonra açık kalması için:

```bat
scripts\check_hold.bat
```

Beklenen son satır:

```text
[PASS] Luna 0.1 Faz 9 dogrulanmis hafiza kapisi gecti.
```

## Görünür hafıza testi

```bat
.venv\Scripts\python.exe -m luna memory-smoke
```
