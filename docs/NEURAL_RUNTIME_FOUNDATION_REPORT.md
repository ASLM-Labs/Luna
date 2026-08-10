# Luna Neural Runtime Foundation

Status: **IMPLEMENTED_UNVERIFIED**
Scope: **NR-1 Foundation**
Frozen repository basis: `8bc9577ef24ea912c1b951d50f09836601c69ff8`

## Purpose

Create the smallest Luna-owned neural-runtime boundary that can later host native gpt-oss inference without changing Luna's higher-level `ModelBackend` semantics or transferring cognitive/runtime authority into the model engine.

## Frozen architecture decisions

- `ModelBackend` remains the provider-neutral boundary consumed by Luna Runtime / PolicyAgent.
- `NativeModelBackend` adapts Luna Neural Runtime results into existing `ModelResponse` semantics.
- Luna owns neural worker lifecycle, health boundary and resource-policy enforcement.
- GPU/VRAM remains user-owned. The worker receives a budget snapshot; it cannot enlarge the active resource profile.
- Automatic resource changes may reduce authority, but may not enlarge it without explicit user authorization.
- Neural integration is not authority transfer: tool, memory, evidence, continuity, promotion and deployment authority remain outside the neural engine.
- Durable Luna session/continuity state is not the same thing as a neural KV/cache lifetime.
- The target native worker remains Luna-owned and is intended to use private IPC/direct binding rather than preserving an HTTP model-server boundary.
- `LocalOpenAICompatibleBackend` remains available as comparison/fallback until native compatibility, regression and cold-start gates pass.

## Implemented in NR-1

- provider-neutral neural runtime contracts;
- named resource-profile identities and bounded resource budgets;
- non-escalating `NeuralResourcePolicy`;
- private `NeuralWorker` lifecycle protocol;
- `LunaNeuralRuntime` lazy start / resident-or-ephemeral lifecycle;
- request-correlation enforcement;
- provider-neutral runtime failure taxonomy;
- `NativeModelBackend` normalization into existing `ModelResponse`, tool-call and usage contracts;
- deterministic tests and verifier;
- full Windows gate integration.

## Explicitly not implemented or claimed

NR-1 does **not**:

- load gpt-oss;
- bind libllama/llama.cpp;
- start a real child model process;
- implement the final private IPC framing;
- switch the primary model path;
- remove or modify Ollama;
- claim behavioral compatibility of the real native model;
- claim session KV persistence;
- grant tool execution authority to model output;
- grant memory/evidence/training/promotion/self-modification authority;
- claim production-safe GPU allocation.

## Evidence carried into the foundation

The reconciled native proof established llama.cpp b10333 + canonical gpt-oss-20b generation on CUDA without an Ollama inference dependency. The proof measured 80.6 generation tokens/s and showed unrestricted auto-fit reaching 11,676 MiB peak VRAM with only 319 MiB minimum free VRAM. Those numbers establish engine viability and motivate explicit resource policy; they are not a production allocation policy.

## Next gate

After NR-1 passes targeted tests and the full Windows quality gate, the next bounded step is NR-2: implement a Luna-owned native worker transport/binding against the proven llama.cpp path while keeping `ModelBackend`, authority boundaries, resource policy and fallback behavior unchanged.
