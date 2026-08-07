# Faz 12C Mimari Sınırı

Faz 12C, Faz 12B'nin layered context sınırının üstüne model intent ile gerçek tool
execution arasındaki action-selection katmanını ekler.

```text
authenticated RuntimeRequest
→ LayeredContextBundle
→ ActionProposal (untrusted)
→ Stage 1 ToolFamily
→ Stage 2 registered ToolSpec
→ argument validation
→ deterministic policy preflight
→ PREPARED request veya StructuredDenial + BLOCKED Observation
→ future ToolDispatcher execution in single policy-agent loop
```

## Var

- Faz 1–12B çekirdek yetenekleri ve kilitli Faz 11 acceptance suite;
- `ActionProposal`, action kind/target/capability contract;
- iteration başına en fazla bir side-effect proposal;
- runtime-owned `ToolFamily` ve `ToolRoute`;
- iki aşamalı deterministic tool selection;
- strict argument-schema preflight;
- mevcut runtime tool policy'nin execution öncesi deterministic preflight'i;
- ambiguous/invented/incompatible tool için structured denial;
- permission denial sonrası silent fallback yasağı;
- denial → `ObservationStatus.BLOCKED` normalization;
- `PREPARED` result ile ToolDispatcher arasında açık execution boundary;
- Faz 12C RFC, verifier, unit test ve CLI smoke.

## Zorlanan kurallar

- model proposal permission veya risk veremez;
- proposal runtime-owned risk alanı taşımaz;
- route yalnız registered tool'a işaret edebilir;
- birden fazla compatible tool varsa runtime tahmin yapmaz;
- preferred tool reddedilirse başka tool sessizce denenmez;
- high-impact expectation ve scope/autonomy/risk policy preflight'te kontrol edilir;
- denied action executable request'e dönüştürülemez;
- selector/resolver handler execute veya dispatcher dispatch çağrısı yapamaz;
- bir iteration'da birden fazla WRITE/NETWORK/PROCESS proposal olamaz.

## Yok

- ortak failure taxonomy ve retry sınıflandırması;
- minimal-change enforcement ve worktree isolation;
- `LunaRuntime.run()` / `resume()` orchestrator;
- gerçek model rollout;
- ağ, GitHub, MCP/plugin, masaüstü, Discord veya ses entegrasyonu;
- subagent veya kontrolsüz self-improvement.

## Sonraki kapılar

```text
12D failure taxonomy + minimal change + risk-based worktree
→ 12E single policy-agent loop
→ 12F finalization
→ 12G E2E + behavior acceptance
```
