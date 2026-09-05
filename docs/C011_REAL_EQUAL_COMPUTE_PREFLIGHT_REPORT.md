# C-011 Real Equal-Compute Execution Preflight

Status: `C011_REAL_EQUAL_COMPUTE_EXTERNAL_EVIDENCE_PREFLIGHT_ACCEPTED_BLOCKED`

Decision: `BLOCKED_REJECTED_BASIS`

Outcome: `NOT_EXECUTED_BLOCKED`

Next gate: `C011_REAL_EQUAL_COMPUTE_RUNTIME_ACCOUNTING_CONTRACT_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`

## Outcome

The owner authorized a bounded real equal-compute evidence test. The preflight records
that authorization without converting it into runtime, rollout or promotion authority.
It freezes the required `SOLO`, `ULTRA_SOLO` and `PARALLEL` configurations, requires at
least two parallel workers and requires measured token accounting.

The current measurement basis fails before provider execution. The real driver records
zero tokens, the accepted real receipt also reports zero tokens, and the accepted real
harness permits only one total and concurrent worker. A provider call on this basis could
produce another real output, but it could not establish a valid equal-compute triplet.
Accordingly, no provider/model call was attempted. C-011 remains `QUEUED`, default-off
and `BLOCKED`.

Repository acceptance: 1476 tests passed with one Windows platform skip, Ruff passed,
strict mypy passed across 314 source files, and the complete 58/58 verifier/CLI chain
passed on the exact staged tree with a short isolated Windows temp path.

## Evidence classification

### VERIFIED

- The preflight is frozen to branch
  `capability/c011-single-voice-parallel-cognition`, commit
  `dcc0c25e1e34d7ce4ea8bcb2c77bfa17e7ca64ff` and tree
  `ce68639c9e593b30ee4b3d8405377359d7bfa867`.
- Current content-addressed source assigns `tokens=0`; the accepted S5B real result
  reports zero tokens.
- The accepted real harness and receipt permit one parallel generation, one total worker
  and one concurrent worker.
- The accepted S5C receipt states that its triplet is deterministic fixture evidence,
  no real provider ran, and equal-compute non-inferiority was not established.

### INFERENCE

- Running a model now would verify only another bounded provider observation. With no
  measured-token basis and no multi-worker parallel contract, it would not be fair
  real equal-compute evidence.
- Repository-declared process budgets support partial confidence but are not independent
  enforceable hardware or containment attestations.

### OPEN

- a measured-token accounting contract and evidence;
- frozen real `SOLO` and `ULTRA_SOLO` runtime contracts;
- a real parallel runtime contract with at least two workers;
- a representative frozen real suite and current triplet asset binding;
- independent evaluator, contamination-provenance, hardware-resource,
  safety-containment and external-ledger attestations.

## Provenance and authority boundary

The policy, eleven-item evidence snapshot, every evidence item and the decision have
canonical SHA-256 content identities recorded in
`c011_real_equal_compute_preflight_verification.json`. Target drift, inventory drift,
evidence-class laundering, identity tampering or incomplete external attestation fails
closed.

The preflight imports no provider driver, makes no network or subprocess call, wires no
production runtime and cannot mutate task state. It grants no task-state, root-context,
completion, user-facing voice, CANARY, ACTIVE or promotion authority. No hidden
chain-of-thought access is claimed, requested or stored.

ASLM Research is a separate project. Its Research Saturation Gate remains `NOT_READY`,
Target Spec remains `BLOCKED`, and controlled execution remains `NONE`.

controlled C-011 execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
