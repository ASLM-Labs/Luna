# RFC-017 — Discord Gateway

Status: IMPLEMENTED_UNVERIFIED
Phase: 17
Date: 2026-08-08

## Amaç

Luna'nın Discord yüzünü mevcut runtime-owned identity, authority, durable queue ve append-only audit
sınırlarının üzerine eklemek; Discord mesajını yeni bir yetki kaynağına dönüştürmemek.

## Karar

Phase 17, canlı Discord SDK'sına bağımlı olmayan transport-neutral bir gateway sözleşmesi uygular.
Gerçek Discord transport adapter'ı yalnız doğrulanmış guild/channel/user/role metadata'sını gateway'e
iletir. Gateway'in kendisi ağ çağrısı, model çağrısı, tool dispatch veya Discord moderasyon işlemi
yapmaz.

## Doğrulanmış kaynak

- Guild ve kanal amacı runtime-owned `DiscordAuthorityConfig` içinden çözülür.
- Owner kimliği yalnız configured Discord user ID eşleşmesinden gelir.
- Trusted/community rolleri yalnız doğrulanmış Discord role ID eşleşmesinden gelir.
- Eşleşmeyen doğrulanmış kullanıcı `GUEST` olur.
- Mesaj metni, samimiyet, takma ad veya "ben sahibim" iddiası rol değiştiremez.
- Runtime actor `ActorVerificationSource.GATEWAY_ROLE` ile kaydedilir.

## Authority sınırı

Phase 17'de Discord-originated her accepted task:

- `RequestSource.DISCORD` kullanır;
- `LEVEL_1_READ_ONLY` ile başlar;
- workspace write kapalıdır;
- process/terminal kapalıdır;
- network authority kapalıdır;
- write ve network budget sıfırdır;
- yalnız read-only tool allowlist taşır.

Owner rolü bile Discord mesajı üzerinden bu sınırı yükseltemez. Daha yüksek yetki gerekiyorsa ayrı,
runtime-owned onay akışı gerekir; Phase 17 bu akışı üretmez.

## Kanal politikası

Referans kanal amaçları:

- `UPDATES`
- `CHAT`
- `AION_QA`
- `MAINTENANCE`
- `FEEDBACK`

`UPDATES` yalnız owner/trusted ingress kabul eder. Diğer configured kanallar owner, trusted,
community ve guest için dar mesaj alma yüzüdür. Unknown channel fail-closed olur.

## Model kapalıyken queue

Gateway kabul edilen mesajı doğrudan `DurableTaskQueue` içine yazar. Queue item model slotu ister,
network slotu istemez. Ana model kullanılamıyorsa mesaj yine `QUEUED` kalır ve transport'a
`QUEUED_FOR_MODEL` acknowledgement döner. Gateway ana modelin cevabını taklit etmez.

Discord message ID, guild ve channel ile deterministic idempotency key ve runtime UUID'leri türetilir.
Aynı transport event yeniden teslim edilirse ikinci task üretilmez.

## Rate limit ve moderation boundary

- Rate limit doğrulanmış runtime rolüne göre sabit pencere uygular.
- Duplicate transport delivery ek rate-limit slotu tüketmez.
- Bot, webhook ve mass-mention ingress dar moderation guard tarafından kuyruğa alınmaz.
- Gateway mesaj silme, kullanıcı banlama veya Discord tarafında external moderation action yapmaz.

## Audit trail

Her allow/deny kararı mevcut append-only SHA-256 audit ledger'a `OBSERVATION` olarak yazılır.
Audit payload raw Discord mesajını saklamaz; yalnız content SHA-256, karakter sayısı ve routing/
decision metadata'sı taşır.

## Reply routing

Gateway dış gönderim yapmaz. Sonuç yalnız ingress channel ID + source message ID ile
`DiscordReplyRoute` üretir. Böylece gelecekteki transport adapter cevabı başka kanala sessizce
yönlendiremez.

## Out of scope

- Discord token/secret yönetimi;
- `discord.py` veya başka canlı network client bağımlılığı;
- otomatik ban/delete/moderation action;
- Discord üzerinden project write veya terminal;
- Discord üzerinden autonomy/network escalation;
- özel owner memory'sinin community retrieval'a açılması;
- model yokken karmaşık cevabı Luna üretmiş gibi gösterme.

## Acceptance

Phase 17 gate en az şunları doğrular:

- verified guild/channel/role source;
- owner/trusted/community/guest policy;
- role-bound rate limit;
- ingress-only moderation boundary;
- model unavailable durable queue;
- duplicate delivery idempotency;
- no autonomy escalation from Discord text;
- project write/process/network default-off;
- append-only audit with content digest, no raw message;
- ingress-bound reply route;
- Phase 16 regression;
- metadata integrity.
