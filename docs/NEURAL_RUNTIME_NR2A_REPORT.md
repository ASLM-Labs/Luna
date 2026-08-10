# Luna Neural Runtime NR-2A Native CLI Transport

Status: **IMPLEMENTED_VERIFIED_FOR_SCOPE**
Scope: **NR-2A Native CLI Transport**
Frozen repository basis: `75bc6c390286fc1eb2543e2a80793d009f46d64a`

## Purpose

Bind the Luna-owned Neural Runtime to the proven local llama.cpp/gpt-oss path through a Luna-owned child process and private JSONL IPC, while preserving the existing provider-neutral `ModelBackend`, Luna-owned resource policy, and higher-level authority boundaries.

NR-2A is a transitional native transport. It proves a Luna-owned real-model generation path without turning `llama-cli` into the final persistent neural architecture.

## Implemented and verified in scope

- Luna-owned `LunaCliWorker` child-process lifecycle behind the existing `NeuralWorker` / `LunaNeuralRuntime` boundary.
- Private JSONL IPC; no HTTP model-server boundary is introduced.
- Versioned IPC protocol (`protocol_version = 1`) with a bounded 1 MiB frame contract.
- Exact monotonic generation event sequencing; gaps and duplicates fail closed.
- `READY` is explicitly `TRANSPORT_READY`, not a model-loaded or model-resident claim.
- Ephemeral-only CLI lifecycle; `model_resident=True` is rejected.
- UTF-8 user and system content is transported through temporary prompt files rather than Windows command-line prompt arguments.
- gpt-oss compatibility profile uses embedded/model Jinja, reasoning `auto`, low reasoning effort, temperature `1.0`, and top-p `1.0`.
- Zero model-layer, KV-cache, and host-op GPU offload is requested for this NR-2A profile.
- `llama-cli --output` is treated as a raw one-turn transcript artifact, validated against the exact prompt boundary, and only the final assistant segment is promoted into Luna's canonical model result.
- gpt-oss reasoning markers are removed at the neural boundary and are not promoted into canonical `ModelResponse.text`.
- Raw `llama-cli` stdout/stderr remains diagnostic output and is not treated as Luna model text.
- Deterministic verifier coverage is integrated into the full Windows quality gate.

## Real-model evidence

### Direct changed-basis diagnostic

The initial Luna worker configuration returned unrelated Maven/gpt-oss text even after UTF-8 transport and transcript extraction were repaired. A direct engine diagnostic isolated the invocation profile from the Luna worker/IPC path.

With the same canonical gpt-oss-20b MXFP4 model and llama.cpp b10333, the changed-basis profile used embedded Jinja, reasoning `auto`, low reasoning effort, temperature `1.0`, and top-p `1.0`. The exact Turkish prompt survived and the model returned the contextually correct final answer `Hazırım!`.

This evidence localized the remaining semantic failure to the Luna invocation profile rather than the weights, engine, or UTF-8 prompt-file boundary.

### Luna-owned worker semantic recovery

After the invocation-profile repair, the same neutral Turkish request was executed through:

`LunaNeuralRuntime -> LunaCliWorker -> private JSONL IPC -> Luna child worker -> llama-cli -> gpt-oss`

The canonical Luna worker result was:

`Bugün çalışmaya hazırım.`

with `finish=STOP`, strict UTF-8 output, and no `[Start thinking]` / `[End thinking]` markers in the canonical response.

This verifies real native generation through the Luna-owned child-worker/private-IPC path for the bounded NR-2A scope.

## Failure-chain decisions preserved

The implementation records the changed-basis lessons from the probe sequence:

1. raw `llama-cli` stdout contains engine/UI diagnostics and is not a clean live token stream;
2. Windows direct prompt arguments corrupted Turkish text, so prompt content moved to BOM-less UTF-8 files;
3. `--output` is a transcript artifact rather than automatically canonical assistant-only text;
4. `finish=STOP` is a structural completion signal and cannot establish semantic correctness by itself;
5. the original explicit-template/reasoning-off/temperature-zero invocation produced unrelated output;
6. the direct changed-basis gpt-oss profile recovered semantic behavior;
7. a later CP1254 display failure was a diagnostic harness failure, not a model/worker regression;
8. the final worker retry used strict UTF-8/raw-byte observation and recovered the correct semantic response.

## Resource observation and limits

The successful worker retry sampled the overall GPU state 18 times. Observed total GPU memory use ranged from 1,478 MiB to 1,649 MiB, peak GPU utilization was 25%, and a llama compute application appeared in 16 of 18 samples.

These values are **observation only**. Other desktop GPU users were present, and a CUDA-enabled llama.cpp binary may initialize a GPU/driver context even when model/KV/op offload is disabled.

Therefore NR-2A claims **zero GPU model/KV/op offload requested**, not zero physical GPU touch and not exact production VRAM-budget enforcement.

## Protocol and deterministic verification

Focused NR-2A coverage reached 19 passing tests before closure integration. The deterministic verifier checks:

- protocol version lock;
- bounded frame size;
- protocol-version mismatch rejection;
- sequence-gap rejection;
- transport-only READY semantics;
- working gpt-oss Jinja/reasoning/sampling profile;
- zero model/KV/op GPU offload controls;
- UTF-8 prompt-file transport;
- reasoning-to-final isolation;
- explicit output-artifact request and canonical extraction source;
- absence of an HTTP server boundary.

The full Windows gate was green with 607 tests before the closure verifier was inserted as its own gate step.

## Explicitly not claimed

NR-2A does **not** claim:

- Luna identity behavior or completion of the first identity test;
- true live token streaming;
- persistent model residency or persistent neural KV/cache;
- production-safe exact GPU/VRAM budget enforcement;
- zero GPU/driver touch;
- tool execution authority from model output;
- memory, evidence, continuity, training, promotion, deployment, or self-modification authority for the neural model;
- primary native-path promotion;
- removal of the existing LocalOpenAI/Ollama comparison/fallback path;
- final direct-libllama binding.

## Authority boundary

Neural integration remains an execution/inference boundary only. Tool, memory, evidence, continuity, approval, resource escalation, training, promotion, deployment, and self-modification authority remain owned by higher Luna runtime/governance layers.

## Next bounded step

After repository closure and merge containment for NR-2A, continue toward the direct native/libllama bridge and production resource-policy enforcement. True clean token streaming and persistent model/KV lifecycle belong to that later bridge, not to the transitional CLI adapter.
