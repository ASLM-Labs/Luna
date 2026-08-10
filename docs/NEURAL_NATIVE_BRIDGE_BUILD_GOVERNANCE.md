# Luna Native Bridge Build Governance

Capability status: **IMPLEMENTED_VERIFIED_FOR_SCOPE**
Repository closure status: **PENDING_FINAL_WINDOWS_GATE_AND_MERGE**
Scope: **LUNA_NATIVE_BRIDGE_BUILD_GOVERNANCE**
Frozen merged-main basis: `ced6089c377151d15b3637cbd5e0f9cf42f63b43`

## Purpose

Make the narrow Luna native C ABI bridge source and its build contract
repository-owned without vendoring llama.cpp, runtime DLLs, or model weights.

The bridge remains an inference boundary only. Tool, memory, evidence,
continuity, training, promotion, deployment, identity, and resource-escalation
authority remain outside the neural engine.

## Proven source and build basis

- repository-owned bridge source SHA256: `6D130A9B53B6014ECBAE91276E15478E4424DE7EA72CCFC35E087D8DDAFA8FF1`;
- external proven source SHA256: `EE88E17E52565FA0B12634E41CFC1F908F9C2898677B3F67745116B178562804`;
- the only source normalization is `append_final_lf_if_missing_only`;
- llama.cpp repository: `https://github.com/ggml-org/llama.cpp.git`;
- exact tag: `b10333`;
- exact commit: `08659901c43b51de735740f1cf61bb82fbe0c4e4`;
- repo-built bridge DLL SHA256: `506D320F0D811E54192B852F81E62330DE9662F26DCEB3C7BEFE788BF9BFADFB`;
- Windows import libraries are reconstructed from the hash-locked runtime DLL
  exports;
- compiler object output is forced into an out-of-repository build directory;
- path containment is directory-boundary-aware, so sibling paths such as
  `LunaNativeProof` are not misclassified as descendants of `Luna`.

## Real Luna full-chain proof

The repository-owned source was rebuilt by the repository-owned build helper,
then the resulting DLL was exercised through:

`NativeModelBackend -> LunaNeuralRuntime -> LunaNativeWorker -> child IPC ->
ctypes -> repo-built Luna bridge -> llama.dll -> gpt-oss`

Observed proof:

- build receipt: `PASS_REPO_OWNED_NATIVE_BRIDGE_BUILD`;
- request correlation: PASS;
- finish reason: `STOP`;
- worker lifecycle: `STOPPED -> inference -> STOPPED`;
- stream event order: `TEXT_DELTA`, then `FINISH`;
- canonical final: `Yes, I'm ready to work today.`;
- raw Harmony analysis was not emitted;
- `llama-cli` was not required;
- exact six-path package contents remained byte-stable during inference;
- unexpected repository byproducts: `0`;
- probe exit code: `0`.

The external proof is hash-locked by
`docs/NEURAL_NATIVE_BRIDGE_REAL_PROOF_RECEIPT.json`. Repository verification
does not assume that a ChatGPT upload is present on the Windows filesystem.

## Explicitly not claimed

This slice does **not** claim:

- primary native-path promotion;
- persistent model residency or persistent neural KV/cache;
- true live token streaming;
- production-safe exact GPU/VRAM budget enforcement;
- zero physical GPU/driver touch;
- GPU-enabled direct-native execution;
- multi-turn or SYSTEM-message parity;
- completion of the deferred Luna identity test;
- final installer/distribution packaging of llama.cpp runtime assets or weights;
- tool, memory, evidence, training, promotion, deployment, or self-modification
  authority for the neural model.

## Closure rule

`IMPLEMENTED_VERIFIED_FOR_SCOPE` describes the bounded bridge capability.
Repository/project workflow becomes closed only after the final Windows gate,
commit/push/PR, merge containment, and clean-tree evidence complete.
