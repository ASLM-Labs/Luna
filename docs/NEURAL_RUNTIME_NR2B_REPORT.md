# Luna Neural Runtime NR-2B Direct Native Worker — Slice 1

Capability status: **IMPLEMENTED_VERIFIED_FOR_SCOPE**
Repository closure status: **PENDING_FINAL_WINDOWS_GATE_AND_MERGE**
Scope: **NR-2B Direct Native Worker Slice 1**
Frozen merged-main basis: `639bb5ddead055eec9b04d868370364218496cba`

## Purpose

Integrate the proven Luna-owned narrow native C ABI shim into the existing
`NativeModelBackend -> LunaNeuralRuntime -> NeuralWorker` architecture without
preserving `llama-cli` as a required inference hop.

This slice is deliberately bounded. It proves Luna-owned direct-native execution
and canonical Harmony final-channel isolation while keeping resource, tool,
memory, evidence, training, promotion, and deployment authority outside the
neural engine.

## Verified runtime path

The real full-chain proof executed:

`NativeModelBackend -> LunaNeuralRuntime -> LunaNativeWorker -> Luna child process
-> private JSONL IPC -> ctypes -> Luna narrow C ABI shim -> llama.dll -> gpt-oss`

Observed proof result:

- request correlation: PASS;
- finish reason: `STOP`;
- ephemeral lifecycle returned the worker to `STOPPED`;
- observable event order: `TEXT_DELTA`, then `FINISH`;
- canonical final text: `Yes, I'm ready to work today.`;
- Harmony analysis content was not emitted as canonical Luna output;
- `llama-cli` was not required by this direct-native path;
- proof exit code: `0`.

The exact externally captured proof artifact is hash-locked by
`docs/NEURAL_RUNTIME_NR2B_REAL_PROOF_RECEIPT.json`. The closure script does
not assume that a ChatGPT upload also exists on the Windows Desktop or in
Downloads.

## Implemented in Slice 1

- `LunaNativeWorker` behind the existing `NeuralWorker` protocol;
- Luna-private bounded/versioned JSONL IPC, reusing the established framing and
  exact sequence discipline;
- child-process isolation for the ctypes/native boundary;
- explicit model-ready semantics: `MODEL_READY_DIRECT_NATIVE`;
- direct ctypes binding to the proven Luna narrow C ABI shim;
- canonical Harmony `final` extraction inside the child process;
- raw Harmony analysis text is not promoted into `NeuralGenerationResult.text`;
- one canonical final `TEXT_DELTA` followed by `FINISH`;
- CPU-only staging guard rejects `ggml-cuda.dll` and cuBLAS in this slice;
- resource budget rejects non-zero GPU/VRAM authority;
- ephemeral-only lifecycle; `model_resident=True` is rejected;
- one USER turn only;
- output bound capped at 256 tokens;
- startup changed-basis fix launches the child with `cwd=runtime_dir`, matching
  the proven CPU backend discovery environment.

## Startup failure-chain lesson

The first repo full-chain attempt reached `LunaNativeWorker.start()` but did not
receive model-ready acknowledgement. The direct shim proof had run from the
CPU runtime staging directory, while the repo child inherited the Luna repository
working directory.

The repair changed the child working directory to the staged CPU runtime. The
same full Luna runtime chain then passed real inference. This is preserved as a
backend-discovery regression invariant rather than treated as a model failure.

## Deterministic verification

The bounded Slice 1 test suite covers:

- absolute-path config requirements;
- fixed Slice 1 readiness and output bounds;
- exactly-one-USER request rendering;
- rejection of system/multi-turn input;
- rejection above the 256-token bound;
- final-only Harmony extraction;
- rejection of analysis-only output;
- rejection of persistent residency;
- rejection of GPU budgets;
- rejection of CUDA runtime staging.

The deterministic verifier additionally locks the direct-child architecture,
absence of a `llama-cli` subprocess in the direct child, child runtime working
directory, final-only boundary, real-proof receipt, scoped metadata, and
authority/non-claim boundaries.

## External native asset boundary

Slice 1 does not vendor or package the proof shim, llama.cpp runtime DLLs, or
gpt-oss weights into the Luna repository. The real proof used externally staged,
hash-identified native assets. This verifies the Luna runtime integration
boundary, not final distribution/installer packaging.

## Explicitly not claimed

NR-2B Slice 1 does **not** claim:

- primary native-path promotion;
- removal of the existing LocalOpenAI/Ollama comparison or fallback path;
- persistent model residency;
- persistent neural KV/cache across requests;
- true live token streaming;
- production-safe exact GPU/VRAM budget enforcement;
- zero physical GPU/driver touch;
- GPU-enabled direct-native execution;
- multi-turn or SYSTEM-message parity;
- model-proposed tool execution authority;
- memory, evidence, continuity, training, promotion, deployment, or
  self-modification authority for the neural model;
- final production packaging of the Luna C ABI shim/runtime assets;
- completion of the deferred Luna identity test.

## Authority boundary

Neural integration remains an inference/execution boundary. Higher Luna layers
retain tool, memory, evidence, continuity, approval, resource escalation,
training, promotion, deployment, and self-modification authority.

## Next bounded work after repository closure

After the exact Slice 1 revision passes the full Windows gate and merge
containment, later work may address production shim packaging/build governance,
GPU resource-policy enforcement, persistent model residency, KV lifecycle,
multi-turn/system compatibility, and true live streaming. Those remain separate
gates and are not implied by this Slice 1 closure.
