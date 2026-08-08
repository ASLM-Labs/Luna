# Phase 17 Report — Discord Gateway

## Sonuç

Phase 17, Luna'ya transport-neutral Discord ingress gateway'i ekler. Discord yüzü mevcut runtime
identity, autonomy, durable operations ve append-only audit truth'una bağlanır; yeni bir authority
veya completion sistemi oluşturmaz.

## Uygulanan bileşenler

- `luna.discord.models`: verified transport, configured channel/role ve reply-route kontratları.
- `luna.discord.policy`: owner/trusted/community/guest çözümlemesi ve channel policy.
- `luna.discord.rate_limit`: role-bound fixed-window ingress limiti.
- `luna.discord.moderation`: bot/webhook/mass-mention local ingress boundary.
- `luna.discord.gateway`: `DISCORD → RuntimeActor → RuntimeRequest → WorkEnvelope → durable queue`.
- `luna.discord.bootstrap`: mevcut operations store + append-only audit ile local construction.
- `phase17-smoke`: model unavailable durable-queue ve authority regression smoke.

## Güvenlik sonucu

- Discord message text rol veya autonomy üretemez;
- configured owner bile Discord üzerinden write/process/network authority alamaz;
- unknown guild/channel fail-closed;
- model kapalıyken accepted work durable queue'da kalır;
- duplicate delivery yeni task üretmez;
- audit raw community message'ını saklamaz;
- gateway dış Discord moderation veya network send yapmaz.

## Bilinen sınırlamalar

Phase 17 gerçek Discord SDK/token transport'unu bağlamaz. Bu bilinçli olarak network secret ve
external action yüzünü gateway authority katmanından ayrı tutar. Canlı adapter eklendiğinde aynı
verified transport envelope ve reply-route kontratlarını kullanmalıdır.

## Sonraki faz

Phase 18 Voice Gateway, desktop permission UX ve runtime authority sınırlarını sesli komutlara taşır.
