# C-011 S5B Real Adapter Execution Report

Status: `C011_S5B_REAL_ADAPTER_EXECUTION_ACCEPTED`

Evidence date: 2026-08-30

Baseline: `9b2667838df9ed5e127e1db54e1428062716a18c`

## Outcome

The default-off `LocalNativeDriverAdapter` completed one accepted CPU-only real-model
evidence call through a single S4-supervised child that owns the accepted NR-2B ABI shim
in-process. The accepted result was `RESULT_RECEIVED`, cleanup was
`CLEANUP_COMPLETE`, no hard termination was used, all bound artifacts matched before
and after execution, and the canonical final was `Yes, I'm ready to work today.`

The model authored no claims. Its final is stored only as an unverified read-only worker
draft; root validation, task state, completion and user-facing voice authority remain
absent. Raw Harmony analysis was not emitted.

Two earlier authorized attempts were rejected rather than promoted. The first returned
safe driver code `20`; its loader-working-directory diagnosis remains an **INFERENCE**.
The second was **VERIFIED** terminated when native diagnostics exceeded the S4 stderr
ceiling. Changed-basis fixes aligned the working directory and stderr boundary with the
accepted NR-2B child. The third separately authorized attempt passed.

The exact staged tree passed 1419 tests with one Windows symlink-platform skip,
repository-wide Ruff, strict mypy across 311 source files, every verifier and CLI smoke
in the complete 55/55 chain. The final acceptance tree is independently rerun below.

## Evidence classification

### VERIFIED

- Exact model SHA256 `27cd6c43…5901`, bridge SHA256 `506d320f…adfb`, ABI 1,
  Python executable, repo driver, explicit environment and all 18 CPU-runtime files
  were bound by the accepted adapter binding.
- Real mode is structurally separate as `REAL_EVIDENCE_ONESHOT`; default policy remains
  disabled and kill-switched, exact binding approval is required, and each adapter
  instance consumes at most one real attempt.
- The real child receives only a single USER prompt, no tools, credentials, memory,
  network, write, delegation, state, completion or voice authority.
- Result-file reads are capped before allocation; late oversized output fails closed.
- Focused fixture/adversarial coverage passed 31 tests; changed-scope Ruff and strict
  mypy passed.
- One final real adapter result passed with 263 raw result bytes, zero claims and
  16,922 ms child runtime.

### INFERENCE

- The first safe driver-code failure was caused by the CPU runtime not being the child
  working directory. The correction is consistent with the accepted NR-2B loader and
  the subsequent changed failure basis, but the original generic code did not identify
  its internal phase.
- The single-child ABI shape materially reduces the nested-grandchild orphan risk that
  would have existed if the adapter had wrapped `LunaNativeWorker`.

### OPEN

- Final durable commit and post-commit identity acceptance.
- Race-free artifact containment across hash-to-load, OS sandbox/credential attestation,
  externally enforceable RAM/GPU ceilings and an external journal integrity anchor.
- Durable live-runtime replay identity including `binding_id`, and subtype-preserving
  journal round-trip for `LocalNativeDriverResult`.
- Equal-compute solo, Ultra-solo and parallel evaluation; S5C shadow ledger evidence;
  every canary, active or promotion decision.

```text
C-011 capability: QUEUED
S5B real adapter proof: PASS
repository acceptance: PASS_1419_TESTS_1_PLATFORM_SKIP_RUFF_MYPY_311_55_OF_55
default enabled: false
successful real adapter result: ONE
controlled C-011 execution: NONE
production runtime wiring: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
next gate after acceptance: C011_S5C_SHADOW_EVALUATION_PENDING_IMPLEMENTATION
```

ASLM Research is a separate project and was not evaluated or modified. No hidden
chain-of-thought access, persistence, reconstruction or claim is made.
