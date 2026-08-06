# Faz 8 Windows SQLite Dosya Kilidi Hotfix

Windows üzerinde `checkpoint-smoke` tamamlandıktan sonra `TemporaryDirectory`
temizliği `WinError 32` ile `runtime.sqlite3` dosyasını silemiyordu.

Kök neden, `sqlite3.Connection` nesnesinin `with connection:` kullanımında
transaction'ı sonlandırması fakat bağlantıyı kapatmamasıydı.

Düzeltme:

- salt-okuma bağlantıları `_read_connection()` context manager üzerinden açılır;
- her kod yolunda `connection.close()` garanti edilir;
- schema, WAL, load, list ve integrity çağrılarından sonra çalışma klasörünün
  silinebildiğini doğrulayan Windows regresyon testi eklenir.
