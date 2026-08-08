# RFC-016 — Desktop Product Shell

Status: IMPLEMENTED_UNVERIFIED
Phase: 16
Date: 2026-08-08

## Amaç

Luna'nın Phase 12–15 runtime, evidence, research ve durable operations katmanlarını yerel bir
masaüstü ürün yüzünde birleştirmek; bunu yaparken UI'ı yeni bir authority source haline getirmemek.

## Karar

Phase 16 desktop shell üç ayrı sınırdan oluşur:

1. **Presentation contracts** — queue/runtime state'i insan-dostu kartlara dönüştürür.
2. **Desktop command gateway** — explicit local intent'i bounded `RuntimeRequest` ve `WorkEnvelope`
   haline getirir; tool/model çağrısı yapmaz.
3. **Renderer** — light-first Tk arayüzünü immutable snapshot'lardan üretir.

## Authority

Varsayılan desktop composer `READ_ONLY` çalışır. Controlled write için ayrı `DesktopApproval`
gereklidir ve approval:

- workspace ile birebir eşleşir;
- en az bir relative allowed path taşır;
- changed-file ve line budget taşır;
- network authority vermez.

Gateway sonucu `RequestSource.DESKTOP` olan `RuntimeRequest`, eşlenmiş `ToolPolicy` ve durable queue
item'ıdır. Execution authority Luna runtime/operations katmanında kalır.

## Completion truth

Desktop `Doğrulandı` etiketi yalnızca şu authoritative birleşimde üretilebilir:

- `RuntimeStopReason.COMPLETED`;
- `CompletionStatus.VERIFIED_COMPLETE`;
- non-null `verification_report_id`;
- non-null `final_report_id`.

Queue status, model prose veya UI state tek başına başarı kanıtı değildir.

## UI yönü

Phase 16 referans hissi:

- light-first;
- beyaz ana canvas;
- çok hafif soğuk sidebar;
- graphite text;
- soft gray cards;
- Luna blue yalnız anlamlı accent;
- conversation-first workspace;
- bottom composer;
- progressive-disclosure details drawer.

Theme tokenları renderer'dan ayrıdır; ileride başka renderer kullanılsa bile ürün dili korunur.

## Out of scope

- OS background service;
- installer/update/signing;
- external push;
- Discord/voice;
- browser automation;
- webview dependency;
- direct desktop-to-tool/model execution.

## Acceptance

Phase 16 gate en az şunları doğrular:

- read-only default;
- explicit bounded write approval;
- durable queue routing;
- no false completion label;
- local-only notifications;
- non-authoritative schedule read model;
- locked light-first theme;
- Phase 15 regression;
- metadata integrity.
