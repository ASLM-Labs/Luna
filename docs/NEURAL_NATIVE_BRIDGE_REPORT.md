# Luna Neural Runtime — Repository-Owned Native Bridge Build Governance

Capability status: **IMPLEMENTED_VERIFIED_FOR_SCOPE**
Repository closure status: **PENDING_FINAL_WINDOWS_GATE_AND_MERGE**
Scope: **LUNA_NATIVE_BRIDGE_BUILD_GOVERNANCE**
Frozen merged-main basis: `ced6089c377151d15b3637cbd5e0f9cf42f63b43`

## Result

The Luna-owned narrow C ABI bridge is now represented by repository-owned C++
source plus a pinned Windows build contract. The repository-owned helper rebuilt
that source successfully, produced a bridge DLL with SHA256
`506D320F0D811E54192B852F81E62330DE9662F26DCEB3C7BEFE788BF9BFADFB`, and kept all compiler/linker output outside the Luna
repository.

The repo-built DLL then passed a real `LunaNativeWorker` full-chain inference
proof with canonical Harmony final-only output.

## Locked invariants

- bridge source SHA256: `6D130A9B53B6014ECBAE91276E15478E4424DE7EA72CCFC35E087D8DDAFA8FF1`;
- external proof-source provenance SHA256: `EE88E17E52565FA0B12634E41CFC1F908F9C2898677B3F67745116B178562804`;
- llama.cpp tag/commit: `b10333` / `08659901c43b51de735740f1cf61bb82fbe0c4e4`;
- exact ABI version: `1`;
- required Luna ABI exports remain exactly the four `luna_nr2b_*` bridge
  functions;
- build output must be outside the repository using a directory-boundary-aware
  containment check;
- object output is build-scoped and must not leak into the repository;
- llama.cpp source, runtime DLLs, and model weights remain external pinned
  dependencies rather than vendored repository payloads.

## Real proof evidence

The receipt
`docs/NEURAL_NATIVE_BRIDGE_REAL_PROOF_RECEIPT.json` locks the uploaded proof by
raw and normalized SHA256. The observed runtime result was
`PASS_REPO_OWNED_BRIDGE_LUNANATIVEWORKER_FULL_CHAIN` with probe exit code `0`.

The proof used CPU-only staging, emitted exactly `TEXT_DELTA` then `FINISH`,
returned the worker to `STOPPED`, did not emit Harmony analysis as canonical
text, and did not require `llama-cli`.

## Scope boundary

No primary-path promotion, persistent residency, persistent KV lifecycle,
GPU-resource enforcement/promotion, live token streaming, SYSTEM/multi-turn
parity, or identity test is claimed here. Neural integration remains an
inference/execution boundary rather than an authority transfer.

## Repository closure

This report intentionally does not pre-claim repository closure. The exact
revision must still pass the full Windows gate and then complete commit/push/PR,
merge containment, and clean-tree verification.
