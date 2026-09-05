# C-011 Owner-Directed Sequence Delta Review

Date: 2026-08-23

Status: `ACCEPTED_FOR_STAGED_C011_WORK`

Current Luna-local gate: `C011_S0_GOVERNANCE_AUTHORIZED`

Next code gate: `C011_S1_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`

## Trigger

The previously recorded preferred capability sequence placed C-011 after C-005,
C-010, C-008, C-009, C-006, and C-004. The owner has now explicitly prioritized an
Ultra-class, temporary-subagent capability and directed work to continue in bounded
stages, with unfinished stages preserved in the repository.

This is a material sequence change and must not be inferred silently from conversation
memory.

## Verified baseline

```text
main: 0154390581e6f145eb8b912fe91595cdd54496af
origin/main at review start: 0154390581e6f145eb8b912fe91595cdd54496af
tree: 4b378b54a0add0c17b0207308ee4426f331078c4
working tree/index before branch creation: clean
feature branch: capability/c011-single-voice-parallel-cognition
C-011 capability status: QUEUED
production coordination call sites: NONE
accepted ASLM owner-floor commit: 8036ca918f2cfc40c9c6f13381191b0ced6a
reverified ASLM source branch: research/asia-frontier-deep-recon-v0-1
reverified ASLM source HEAD at S0: 78d2f43afb21a93927f14ccb377730032447cb6d
```

## Decision

C-011 is advanced for immediate staged work as an owner-directed exception to the
previous preferred sequence.

The first bounded target is:

> C-011A — Read-Only Parallel Evidence Handoff

The sequence decision and the owner's current direction authorize S0 governance
artifacts on the dedicated branch. They preserve the selected direction for subsequent
stages, but each code or live-execution stage requires separate owner authorization and
current-state revalidation. This decision does not:

- reject, cancel, or demote C-005, C-010, C-008, C-009, C-006, or C-004;
- convert preferred dependency edges into hard prerequisites;
- promote C-011 beyond `QUEUED`;
- claim a Luna 0.1 release requirement;
- enable live subagents, worker writes, network, external actions, memory commit,
  training, deployment, or self-promotion;
- change ASLM Research Saturation or Target Spec gates.

The narrow Luna-local S0 gate above is the separate authority transition that supersedes
the earlier `implementation authorization: NONE` only for governance/checkpoint work.
It does not supersede or weaken the broader ASLM states:

```text
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
controlled execution: NONE
```

## Why this reordering is coherent

The current main branch already contains the preferred C-011 foundations C-002,
C-001, and C-003, plus C7 coordination scaffolding and C-007. Their existence does not
prove C-011, but it makes a contracts-first C-011A vertical possible without pretending
that later inheritance/flywheel capabilities are already complete.

The owner-selected priority is implemented conservatively:

1. preserve the existing solo path;
2. freeze authority, identity, evidence, lifecycle, and rollback contracts;
3. test deterministic contracts and recovery before live agents;
4. introduce read-only workers before any mutation authority;
5. retain all skipped capability work in the roadmap.

## Risk controls

- Dedicated feature branch; no direct main mutation.
- Optional/default-off integration only.
- One root Luna state and voice.
- Maximum reference profile of three temporary workers; depth one.
- Root-only authority and completion.
- Read-only first vertical; no worker tool execution.
- Full provenance, freshness, cancellation, cleanup, and adoption evidence before live
  enablement.
- C-011 status changes only through the canonical capability governance rules.

## Rollback

Before merge, rollback is branch deletion with no main behavior change. After a future
merge, disabling or removing the optional coordination dependency must restore the
unchanged solo path. No durable worker persona or worker-owned state may survive
rollback.

## Next governed action

Complete RFC-C011 S0 and its durable handoff, then verify and commit the exact S0 scope.
After a separate S1 owner authorization is recorded against current Git, implement and
verify only the S1 contract/state package. Do not jump directly to live or write-capable
workers.
