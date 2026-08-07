# RFC-012C — Action Proposal, Two-Stage Tool Selection, Structured Denial

**Status:** ACCEPTED_FOR_PHASE_12C
**Date:** 2026-08-07

## 1. Amaç

Faz 12C, tek policy-agent loop kurulmadan önce model niyeti ile gerçek tool execution
arasına açık ve test edilebilir bir seçim sınırı koyar.

```text
model/runtime intent
→ ActionProposal (untrusted)
→ Stage 1: ToolFamily selection
→ Stage 2: registered ToolSpec selection
→ argument validation
→ deterministic policy preflight
→ PREPARED ToolRequest id
   veya
→ Structured ActionDenial + BLOCKED Observation
→ future ToolDispatcher execution
```

## 2. Temel ilke

`ActionProposal` yetki değildir. Model tool adı, risk, permission veya completion kararı
üzerinde otorite kazanmaz. Runtime-owned registry, routes, policy ve dispatcher son
otoritedir.

## 3. ActionProposal

Proposal yalnız niyeti ve ihtiyaç duyulan action shape'i taşır:

- task / trace identity;
- action kind;
- target kind;
- bounded summary;
- arguments;
- required tool capabilities;
- optional preferred registered tool name;
- timeout/output/cwd isteği;
- high-impact action için expectation reference;
- origin metadata.

Proposal içinde runtime risk seviyesi yoktur. Risk `ToolSpec` ve runtime policy'den gelir.

## 4. Stage 1 — Tool family

Stage 1 semantik action kind'i runtime-owned family'ye map eder:

- `READ` / `WRITE` → `FILESYSTEM`;
- `ROLLBACK` → `WORKSPACE`;
- `PROCESS` → `PROCESS`;
- `UTILITY` → `CORE`.

Bu katman tool çalıştırmaz ve permission kararı vermez.

## 5. Stage 2 — Concrete tool

Stage 2 yalnız runtime-owned `ToolRoute` ve kayıtlı `ToolSpec` üzerinden seçim yapar.

- Unregistered preferred tool reddedilir.
- Route/capability uyuşmazlığı reddedilir.
- Birden fazla compatible tool varsa sessiz tahmin yapılmaz; `AMBIGUOUS_TOOL` döner.
- Explicit preferred tool seçilmişse policy reddinden sonra başka tool'a fallback yapılmaz.

Bu, blind substitution/retry davranışını engeller.

## 6. Argument ve policy preflight

Concrete tool seçildikten sonra:

1. mevcut strict tool argument schema çalışır;
2. mevcut deterministic tool policy execution öncesi preflight edilir.

Preflight PASS gerçek execution yetkisi değildir. `ToolDispatcher` execution anında policy'yi
yeniden uygular.

## 7. Structured denial

Selection veya preflight başarısız olduğunda `ActionDenial` üretilir:

- stage;
- stable denial code;
- reason;
- deterministic checks;
- selected family/tool varsa provenance;
- retryable / requires_replan flags.

Denial ayrıca `ObservationStatus.BLOCKED` olan yapılandırılmış bir `Observation` üretir.
Bu observation future policy-agent loop'a model-visible feedback olarak verilebilir.

## 8. Side-effect sınırı

Bir `ActionProposalBatch` iteration başına en fazla bir side-effect proposal kabul eder.
Side-effect capability kümesi:

- `WRITE`;
- `NETWORK`;
- `PROCESS`.

Bir iteration içinde iki side-effect proposal schema seviyesinde reddedilir.

## 9. Execution ayrımı

Faz 12C selector/resolver katmanı:

- handler çalıştırmaz;
- `ToolDispatcher.dispatch()` çağırmaz;
- filesystem/process/network I/O yapmaz;
- completion kararı üretmez.

`PREPARED`, yalnız dispatcher'a verilebilecek doğrulanmış request shape anlamına gelir.

## 10. Bilinçli sınırlar

Bu faz şunları yapmaz:

- failure taxonomy;
- minimal-change budget enforcement;
- worktree isolation;
- `LunaRuntime.run()` / resume loop;
- model rollout;
- harici network/MCP/GitHub entegrasyonu.

Bunlar sırasıyla sonraki Faz 12D+ kapılarındadır.
