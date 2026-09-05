# C-011 S1 Contract/State Package Report

Date: 2026-08-24

Status: `C011_S1_CONTRACTS_ACCEPTED`

Capability status: `QUEUED`

Current Luna-local gate: `C011_S1_CONTRACTS_ACCEPTED`

Next code gate: `C011_S2_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`

## Authorization and verified baseline

The owner separately authorized S1 after the S0 checkpoint and current-state
reverification. The implementation started only after the following baseline was
reconfirmed:

```text
branch: capability/c011-single-voice-parallel-cognition
HEAD: 09a5dcc2855edec5625fe9b8845da9f7745dae6f
tree: 8c7c0e72fbe7660357164e37cbb5cd31951def1c
parent/main/origin-main/live-main: 0154390581e6f145eb8b912fe91595cdd54496af
working tree/index before S1: clean
```

Three independent read-only reviews covered contract architecture, adversarial
identity/provenance risks, and acceptance/metadata discipline. Those reviews were
development-process evidence, not Luna/C-011 runtime execution.

## Implemented S1 boundary

The isolated `luna.parallel_cognition` package now defines the eight frozen RFC models:

- `AssignmentSemanticSpec`
- `AgentExecutionAttempt`
- `ReadOnlyContextManifest`
- `AgentPayload`
- `AgentExecutionReceipt`
- `ClaimRecord`
- `DistilledHandoff`
- `AdoptionReceipt`

Supporting records encode read-only context references, complete source-step semantics,
integer budget/deadline envelopes, isolation references, proposed claims, observed usage,
resolved evidence lineage, lifecycle state, and exhaustive adoption decisions.

Canonical serialization uses validated JSON-mode values, UTF-8, sorted keys, compact
separators, finite numbers, and domain-separated SHA-256 identities. Reconstruction
revalidates the serialized payload, so an old identity cannot survive content tampering
and an unvalidated Pydantic copy cannot bypass the public canonical/integrity helpers.

Assignment identity includes task/revision, full task-contract digest, complete step
semantics and dependencies, acceptance basis/targets, exact context digest, autonomy and
tool-policy digests, role/objective, granted sources, capability-selection basis, root
epoch, depth-one ceiling, budget/deadline envelope, authority negatives, and schema
version.

## Authority and provenance limits

Worker-facing contracts grant no write, network, process-spawn, tool, external-action,
delegation, memory-commit, state-mutation, completion, or user-facing voice authority.
`AgentPayload` is explicitly untrusted and structurally cannot carry authoritative
runtime usage, cancellation, cleanup, isolation, freshness, permission, mutation,
completion, scratch, or hidden-reasoning fields.

The receipt, lineage, and adoption schemas provide deterministic content integrity and
cross-artifact binding. They do **not** prove who issued an artifact. A malicious producer
that can rewrite an entire internally consistent chain can recompute SHA-256 values.
Durable issuer authority and append-only event provenance remain S2; current-state
admission and authoritative evidence resolution remain S3; live worker isolation remains
S4.

No hidden chain-of-thought access, persistence, reconstruction, or claim was added.

## Current verification evidence

```text
new S1 contract tests: 29 passed
combined S1 + C7 + solo Phase 12E/12G + metadata suite: 156 passed
Ruff changed scope: PASS
strict mypy S1 package: PASS
full exact staged-tree scripts/check.bat: 1319 passed, 1 platform skip
full exact staged-tree Ruff: PASS
full exact staged-tree strict mypy: PASS
verifier and CLI chain: PASS 48/48
```

The combined suite preserves the legacy C7 fixtures and the unchanged solo runtime path.
The exact staged tree passed the full 48-stage local gate from a short Windows path.

The first full-chain candidate run reached stage 46 before exposing a metadata-only
dependency: the existing NR-2B and native-bridge scoped manifests pin the canonical hash
of `scripts/check.bat`. S1 adds a 48th gate stage, so those two scoped manifest entries
were rebound to the new check-chain hash. Their frozen scope, status, source/proof hashes,
and authority boundaries were not changed. The truthful S1 scope is therefore 16 files.

## Unchanged gates

```text
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
controlled execution: NONE
C-011 capability: QUEUED
production Ultra/subagents: NOT IMPLEMENTED
production coordination call sites: NONE
live C-011 execution: NONE
```

S1 is accepted for its declared immutable contract/state scope only. S2, production
wiring, live workers, task-state mutation, and capability promotion are not authorized by
this checkpoint.
