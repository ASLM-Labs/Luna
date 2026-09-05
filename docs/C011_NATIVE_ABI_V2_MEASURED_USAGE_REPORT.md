# C-011 S5D-E3 Native ABI v2 Measured-Usage Channel

Status: `C011_NATIVE_ABI_V2_MEASURED_USAGE_CHANNEL_ACCEPTED`

Next gate: `C011_REAL_RUNTIME_CONFIGURATION_CONTRACTS_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`

## VERIFIED

- The Luna bridge reports ABI `2` and exposes exactly six approved exports.
- Legacy v1 entry points and signatures remain available; the versioned create
  entry point adds requested batch and the versioned generate entry point adds
  `uint64_t` input, output and total counters.
- Input tokens are counted after the chat template, output tokens count sampled
  non-EOG tokens, and total tokens equal input plus output. Failures return zero
  counters. The authoritative source label is `ENGINE_NATIVE_COUNTERS`.
- A pinned llama.cpp `b10333` CPU build produced bridge SHA256
  `e3ce30308489d2c1cc75b020afe38a013dd2262b48c4ace0fb07a190ff429466`
  with the exact six-export surface.
- A bounded real model proof passed both the `LunaNativeWorker` path (19 input,
  75 output, 94 total) and the C-011 final-only driver path (72 input, 57
  output, 129 total). Model, bridge, runtime and repository state were stable.
- No Harmony analysis was emitted as canonical output. No hidden
  chain-of-thought access is claimed.

## INFERENCE

The measured channel removes the specific ABI-v1 accounting blocker. It does
not by itself establish equal-compute non-inferiority, production configuration
safety, packaging readiness, or promotion readiness.

## OPEN

- Production runtime configuration and distribution contracts.
- Persistent residency and KV lifecycle.
- GPU resource-policy enforcement.
- Representative equal-compute evidence and independent evaluation.

## Authority boundary

C-011 remains `QUEUED`, default-off and `BLOCKED`. The real call was evidence
collection, not controlled C-011 execution. CANARY, ACTIVE, completion,
user-facing voice and promotion authority remain false.

controlled C-011 execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED

ASLM Research is a separate project and was not evaluated or modified.

Repository acceptance: `PASS_1503_TESTS_1_PLATFORM_SKIP_RUFF_MYPY_315_60_OF_60`
