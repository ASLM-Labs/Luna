# C-011 S5D-E4 Real Runtime Configuration Contracts

Status: `C011_REAL_RUNTIME_CONFIGURATION_CONTRACTS_ACCEPTED`

Next gate: `C011_REAL_EQUAL_COMPUTE_RUNNER_AND_FROZEN_SUITE_PENDING_IMPLEMENTATION`

## VERIFIED

- `SOLO`, `ULTRA_SOLO`, and `PARALLEL` now have distinct, content-addressed
  runtime contracts over one exact model, ABI v2 bridge, driver, runtime bundle,
  environment, sampling protocol, seed, output ceiling, and normalized compute
  budget.
- `SOLO` is one standard root-only final pass. `ULTRA_SOLO` is two sequential
  Ultra root-only final passes. `PARALLEL` is one Ultra root synthesis pass plus
  two or three concurrent, read-only, final-only worker passes.
- Every arm has the same 256 generated-output-token ceiling and 1000 normalized
  compute units. Engine-native input/output/total counters remain mandatory.
- The S4/S5B boundary now preserves ABI v2 native usage through the admitted
  result. Generated-output budget accounting remains separate from the full
  engine-native input/output/total measurement.
- A bounded pool admits exactly two or three distinct one-shot adapters, exposes
  all members concurrently, consumes failed members, and forbids replay.
- A real CPU-only proof ran two independent ABI v2 model children concurrently.
  Both returned `READY.`, each measured 76 input + 24 output = 100 total tokens,
  maximum observed concurrency was two, and model/bridge/runtime/repository
  evidence remained stable.
- No Harmony analysis was emitted as canonical output. No hidden
  chain-of-thought access is claimed.

## INFERENCE

The contracts and two-lane proof remove the local runtime-definition and
single-adapter concurrency blockers. They make a real three-arm evaluation
implementable; they do not establish representative quality, non-inferiority,
independent evaluation, or promotion readiness.

## OPEN

- Execute the frozen `SOLO` / `ULTRA_SOLO` / `PARALLEL` runner across a
  representative, contamination-controlled suite.
- Obtain independent evaluator, hardware/resource, safety-containment, and
  external-ledger attestations where the preflight requires external provenance.
- Decide promotion only from complete S5D evidence; no missing prerequisite may
  be inferred from this local proof.

## Authority boundary

C-011 remains `QUEUED`, default-off and `BLOCKED`. The two model calls were
evidence collection, not controlled C-011 execution. No production route was
wired. Runtime, task-state, root-context adoption, completion, user-facing voice,
CANARY, ACTIVE, and promotion authority remain false.

controlled C-011 execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED

ASLM Research is a separate project and was not evaluated or modified.

Repository acceptance: `PASS_1521_TESTS_1_PLATFORM_SKIP_RUFF_MYPY_317_61_OF_61`
