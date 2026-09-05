# C-011 S5D-E2 Runtime Accounting Contract Report

Date: 2026-09-01
Branch: `capability/c011-single-voice-parallel-cognition`
Baseline: `a86c41510187a95b057c3ea615f79f70dc6bb9cf`
Baseline tree: `bb9149310341700cf6e923ceb691f4277bd7eee7`
Stage: `C011_REAL_EQUAL_COMPUTE_RUNTIME_ACCOUNTING_CONTRACT_ACCEPTED_BLOCKED_ABI_V1`
Decision: `BLOCKED_USAGE_CHANNEL_ABSENT`
Next gate: `C011_NATIVE_ABI_V2_MEASURED_USAGE_CHANNEL_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`

## Outcome

S5D-E2 freezes a passive, content-addressed and fail-closed definition of measured
token accounting. It does not modify the native bridge, native worker process, real
driver or production runtime. It does not execute a provider/model and grants no
runtime or rollout authority.

The current bridge remains ABI v1. The shim computes prompt tokens after applying the
model chat template and advances generation one sampled-token step at a time, but the
ABI returns only generated text and output byte length. No input-token, non-EOG
output-token or total-token counter crosses the ABI boundary. The real driver therefore
still records the historical zero placeholder, which is not measurement evidence.

## Evidence classification

### VERIFIED

- ABI v1 and its exact four exports are frozen by current source and bridge contract.
- The prompt token count is computed inside the shim after chat-template rendering.
- The generation loop samples one token per iteration and stops before rendering EOG.
- ABI v1 exposes no token-usage output fields; Python receives text only.
- The accepted real proof contains no input, output or total token counters.
- Current repository evidence therefore yields `BLOCKED_USAGE_CHANNEL_ABSENT`.

### INFERENCE

- A versioned measured-usage channel is the smallest credible path to authoritative
  equal-compute accounting. The exact ABI v2 binary layout remains an owner-reviewed
  design decision and is not selected by this gate.

### OPEN

- Exact ABI v2 structures, compatibility rules, overflow/error semantics and rebuild
  evidence.
- A real call returning engine-native `input_tokens`, `output_tokens` and
  `total_tokens` under the frozen semantics.
- `SOLO`, `ULTRA_SOLO` and `PARALLEL` equal-compute execution evidence and all remaining
  external attestations from S5D-E1.

## Frozen measurement semantics

- Input tokens are the model tokens actually fed after chat-template application,
  including special/BOS tokens when actually fed.
- Output tokens are sampled non-EOG tokens; terminal EOG is excluded.
- Total tokens equal input plus output tokens.
- Only engine-native counters qualify. Driver declarations, post-hoc text
  re-tokenization, bytes, words, budget ceilings and a zero placeholder do not.

## Why no real model call ran

The owner permits a real model test, but ABI v1 cannot return the required measurement.
Another text-only generation would reproduce the known evidence gap rather than reduce
it. The next information-gaining action is a separately authorized ABI v2
measured-usage implementation and rebuild gate.

## Authority and project boundaries

C-011 remains `QUEUED`, default-off and `BLOCKED`. This checkpoint grants no task-state,
root-context, completion, user-facing voice, CANARY, ACTIVE or promotion authority.
Controlled C-011 execution: NONE. Research Saturation Gate: NOT_READY. Target Spec:
BLOCKED.

ASLM Research is a separate project and was not evaluated or modified. No hidden
chain-of-thought access is claimed.

## Verification

- focused contract and adversarial tests: `PASS_20`
- changed-scope Ruff: `PASS`
- changed-scope strict mypy: `PASS`
- fail-closed verifier: `PASS`
- exact staged repository gate: `PASS_1497_TESTS_1_PLATFORM_SKIP_RUFF_MYPY_315_59_OF_59`
