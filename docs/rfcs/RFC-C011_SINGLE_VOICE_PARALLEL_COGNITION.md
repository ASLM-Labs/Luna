# RFC-C011 — Single-Voice Parallel Cognition

Status: `IMPLEMENTED_S5D_E3_NATIVE_ABI_V2_ACCEPTED`

Owner direction accepted: 2026-08-23

Separate S1 owner authorization accepted: 2026-08-24

Separate S2 owner authorization accepted: 2026-08-24

Separate S3 owner authorization accepted: 2026-08-28

Separate S4 owner authorization accepted: 2026-08-28

Separate post-S4/S5 owner authorization accepted: 2026-08-29

Separate S5D owner authorization accepted: 2026-09-01

Separate real equal-compute evidence-test authorization accepted: 2026-09-01

Separate runtime-accounting contract authorization accepted: 2026-09-01

Separate native ABI v2 measured-usage authorization accepted: 2026-09-03

Capability status: `QUEUED`

Current Luna-local gate: `C011_NATIVE_ABI_V2_MEASURED_USAGE_CHANNEL_ACCEPTED`

Historical S1 gate: `C011_S1_CONTRACTS_ACCEPTED`

Next code gate: `C011_REAL_RUNTIME_CONFIGURATION_CONTRACTS_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`

First bounded vertical: `C-011A — Read-Only Parallel Evidence Handoff`

## Purpose

C-011 adds selective parallel cognition without creating multiple Luna identities,
multiple task owners, or multiple completion authorities.

The governing rule is:

> One mind. Many hands. One voice.

Temporary workers may prepare bounded evidence and proposals. Main Luna remains the
only user-facing voice, the only owner of authoritative `TaskState`, the only component
that may adopt worker output, and the only component that may request whole-task
completion.

This RFC adopts a staged implementation plan. S1-S3 remain isolated control packages.
S4 adds a default-off, local live-capable worker boundary and generic root-context
extension, but does not enable a real model provider, controlled production C-011, or
promote the capability beyond `QUEUED`.

## Authority and repository basis

This RFC is bound to the following verified baseline:

```text
repository: C:\Users\istem\Projects\Luna
baseline branch: main
baseline commit: 0154390581e6f145eb8b912fe91595cdd54496af
baseline tree: 4b378b54a0add0c17b0207308ee4426f331078c4
live origin/main at S0 start: 0154390581e6f145eb8b912fe91595cdd54496af
implementation branch: capability/c011-single-voice-parallel-cognition
baseline working tree/index: clean
accepted ASLM owner-floor commit: 8036ca918f937f2cfc40c9c6f13381191b0ced6a
reverified ASLM source branch: research/asia-frontier-deep-recon-v0-1
reverified ASLM source HEAD at S0: 78d2f43afb21a93927f14ccb377730032447cb6d
```

The owner explicitly directed Luna to advance Ultra plus temporary autonomous
subagents in bounded stages, while allowing unfinished later stages to remain durably
checkpointed. That direction supplies the separate authority and narrow gate transition
for S0 governance artifacts only. It does not authorize S1 code or any live C-011
execution. Each later stage requires its own owner authorization after current-state
reverification. The resulting sequence change is recorded in
`docs/C011_OWNER_DIRECTED_SEQUENCE_DELTA_REVIEW.md`.

After S0 acceptance at commit `09a5dcc2855edec5625fe9b8845da9f7745dae6f`, the owner
separately authorized S1 on 2026-08-24. Current Git, the clean worktree/index, and live
`main` identity were reverified before implementation. S1 was accepted at commit
`8c82cab7eebafd04fdd6a7990115ac1019176ad1`. The owner then separately authorized S2
on 2026-08-24 after another current-state reconciliation. S2 authority is limited to
the durable event/recovery core, deterministic fake backend, and local verification;
it does not authorize live workers, production wiring, or capability promotion. S2 was
accepted at commit `5620d8e428f003b1ca5c8a6392e64e213145132a`. The owner separately
authorized S3 on 2026-08-28 after current branch, HEAD and main identity were reverified.

ASLM Research is a separate project. Luna S3 neither evaluates nor modifies its research
gates; historical ASLM references in earlier checkpoints are not S3 acceptance evidence.

## Relationship to the Luna 0.1 constitution

The frozen Luna 0.1 core remains a single-policy-agent system. C-011 is an optional,
default-off capability extension behind an explicit dependency and feature boundary.

This RFC satisfies the constitution's requirement for a separate numbered RFC before
subagent or multi-agent behavior enters the core. It does not make C-011 a Luna 0.1
release requirement and does not weaken any existing Luna 0.1 gate.

When C-011 is disabled, unavailable, denied admission, cancelled, or rolled back, the
existing solo `LunaRuntime` path must remain behaviorally unchanged.

## Current verified foundation

The repository already contains C7 coordination contracts, deterministic topology
selection, a caller-concurrency-limited in-memory runtime scaffold, result contracts,
reconciliation, and authority-negative fields. The current C7 foundation is not
production C-011 because:

- no production `LunaRuntime` call site constructs or invokes it;
- runtime plan admission does not revalidate current root state, contract, policy, or
  provenance;
- assignment identity does not cover the complete current semantic basis;
- evidence and observation identifiers are not resolved against current authoritative
  stores before reconciliation;
- per-worker and overall deadlines are absent;
- thread/object separation is not process, context, credential, or backend isolation;
- coordination lifecycle, cleanup, and adoption receipts are not durable;
- active or hung workers cannot be reliably terminated.

Existing C7 code is reusable scaffolding. Its presence is not C-011 completion evidence.

## First vertical: C-011A

C-011A proves one narrow behavior:

```text
current root task/state/policy
-> deterministic delegation admission
-> zero to three independent read-only assignments
-> isolated temporary execution attempts
-> runtime-authored receipts
-> evidence and freshness resolution
-> deterministic reconciliation
-> quarantined distilled handoff
-> root verification/adoption decision
-> one root response
```

C-011A is opt-in and default-off. Ultra effort and delegation topology are separate
axes: selecting Ultra may make delegation available, but it must not force worker
creation when the work is not independent or expected benefit does not exceed
orchestration cost.

## Frozen C-011A invariants

1. There is exactly one authoritative Luna identity, root task owner, `TaskState`
   writer, final report, and completion gate.
2. A worker is a temporary execution attempt, not a persistent persona or task owner.
3. The root may admit at most three live workers in the reference C-011A profile.
4. Delegation depth is exactly one. Workers cannot spawn descendants.
5. Workers receive no write, network, process, external-action, memory-commit,
   permission-escalation, state-mutation, or completion authority.
6. C-011A workers consume only a runtime-brokered read-only context manifest. They do
   not invoke tools directly in the first vertical.
7. Runtime admission is rebuilt from current authoritative inputs. A caller-supplied
   prebuilt plan is never sufficient execution authority.
8. Assignment semantic identity and execution-attempt identity are distinct.
9. Every admitted attempt has explicit per-worker and overall deadlines. Missing or
   unbounded deadlines deny admission.
10. Cancellation, deadline, root lease, authority, and freshness are rechecked before
    creation, before execution, before result admission, and before state adoption.
11. Late, stale, cancelled, timed-out, unbound, or tampered results remain quarantined.
12. Evidence and observations must resolve through current authoritative stores.
    Non-empty identifiers alone are never evidence qualification.
13. Majority vote is not truth. Contradiction produces `CONFLICT` or `VERIFY`.
14. Reconciliation `ACCEPT` means eligible for root consideration only. It never means
    task completion or automatic state adoption.
15. Only a distilled handoff may enter root context. Raw scratch work, hidden reasoning,
    role framing, credentials, and unverified intermediate claims do not.
16. Every create/start/result/cancel/timeout/cleanup/reconcile/adopt/reject transition is
    represented by durable runtime-authored evidence before live enablement.
17. Existing solo behavior is the rollback path and remains covered by locked tests.
18. No hidden chain-of-thought access, persistence, reconstruction, or claim is part of
    C-011.

## Contract freeze for S1

If separately authorized, S1 must introduce immutable, versioned contracts whose
resulting C-011 runtime behavior performs no model calls, tool calls, network access,
worker processes, repository writes, or live-worker execution. Normal repository edits,
local tests, and development tooling used to implement and verify S1 are not C-011
runtime evidence.

### `AssignmentSemanticSpec`

The canonical semantic basis must include:

- task ID and current task revision;
- complete current task-contract fingerprint;
- complete source-step semantics and dependencies;
- acceptance-basis and target references;
- context-manifest fingerprint;
- current autonomy and tool-policy fingerprint;
- requested worker role and bounded objective;
- granted read-only source references;
- capability-selection basis;
- root coordination epoch;
- budget and deadline envelope;
- schema version.

The assignment ID is derived from this complete canonical payload. Any material change
creates a new assignment identity.

### `AgentExecutionAttempt`

An execution attempt binds one semantic assignment to:

- a unique attempt ID;
- runtime-issued session ID;
- backend and profile IDs;
- root coordination epoch;
- cancellation epoch;
- created/start/deadline timestamps;
- process/session/context isolation references;
- lifecycle state.

A display name is presentation metadata and never identity or authority.

### `ReadOnlyContextManifest`

The manifest contains only explicit source references, canonical digests, freshness,
task/revision binding, redaction state, and size accounting. It cannot contain secrets,
write grants, tool grants, or inherited worker memory.

### `AgentPayload`

The payload is untrusted worker output. It may contain:

- result summary;
- claims;
- cited source/evidence/observation references;
- assumptions;
- uncertainty;
- conflicts;
- recommended next action.

It cannot authoritatively report runtime usage, cancellation, cleanup, isolation,
freshness, permissions, or completion.

### `AgentExecutionReceipt`

The runtime-authored receipt binds the untrusted payload to the admitted assignment and
attempt and records observed lifecycle, backend/session identity, budgets, deadlines,
cancellation, cleanup, payload digest, and terminal state.

### `ClaimRecord` and `DistilledHandoff`

Each claim carries an explicit support disposition, resolved evidence lineage,
freshness, contradiction state, and qualification reason. The distilled handoff contains
only qualified claim records plus bounded assumptions, uncertainty, conflicts, and next
action.

### `AdoptionReceipt`

The root-owned receipt records exactly which qualified claims were adopted, rejected, or
sent for verification, the current root state revision, the resulting state revision if
any, and the authoritative evidence basis. It carries no completion authority.

## Authority algebra

Worker capability is always an intersection, never a union:

```text
effective worker capability
= root task scope
∩ current autonomy policy
∩ current tool policy
∩ C-011A read-only ceiling
∩ assignment grant
∩ live resource/deadline/cancellation state
```

No prompt, payload, follow-up, backend response, worker profile, or previous successful
attempt can widen this intersection.

## Lifecycle state

Required attempt states:

```text
PROPOSED
ADMITTED | DENIED
CREATED
STARTED
RESULT_RECEIVED | CANCEL_REQUESTED | TIMED_OUT | FAILED
CANCELLED | TERMINATED
CLEANUP_COMPLETE | CLEANUP_FAILED
RECONCILED
ADOPTED | REJECTED | VERIFY_REQUIRED
CLOSED
```

Transitions are monotonic, append-only, idempotent, and bound to a root coordination
epoch. Root restart or split-brain detection must fail closed.

## Retention and privacy

- Raw worker scratch and hidden reasoning are neither required nor persisted.
- Distilled payloads and runtime receipts follow the parent task's governed retention.
- Context manifests store source references and digests rather than copied secrets.
- Existing redaction, deletion, audit, and user-data rules remain authoritative.
- Worker-specific long-term memory and persistent persona history are prohibited.

## Staged implementation

### S0 — RFC and evidence freeze

- this numbered RFC;
- owner-directed sequence Delta Review;
- exact durable handoff;
- current-source threat/gap reconciliation;
- C7 baseline tests;
- no production behavior change.

### S1 — Contract/state package

- implement the frozen contracts above;
- canonical serialization, hashing, reconstruction, and validation;
- authority-negative and tamper-rejection tests;
- no live execution.

### S2 — Durable event and recovery core

- coordination event store;
- root lease and monotonic coordination epoch;
- idempotent fake backend;
- receipt and crash/recovery tests;
- no live execution.

### S3 — Admission and hierarchical controls

- current-state admission;
- total/concurrent/depth/result/context/deadline budgets;
- cancellation and late-result fences;
- authoritative evidence/observation resolution;
- deterministic fake-agent fixtures.

### S4 — Narrow live read-only workers

- interruptible backend only;
- focused context broker;
- zero-to-three read-only attempts;
- feature flag and kill switch;
- root context adoption and one-voice integration;
- existing solo path unchanged.

Later RFC stages may add follow-up, adversarial review, root-only mutation from worker
proposals, or isolated child-write experiments. None is part of C-011A.

## Required deterministic acceptance fixtures

At minimum the C-011A package must prove:

- current contract/state/policy/plan-seal admission;
- zero workers when delegation has no independent value;
- root plus three independent read-only lanes when resources allow;
- hard total, concurrent, depth, deadline, result, and context ceilings;
- cancellation before creation and after creation/before execution;
- termination and late-result fencing for in-flight cancellation/timeout;
- denial of a backend that cannot guarantee bounded driver calls and root liveness;
- distinct runtime-issued attempt/session/context identities;
- unknown, cross-task, stale, digest-changed, or fabricated evidence rejection;
- tamper and wrong-assignment/backend/session rejection;
- deterministic reconciliation independent of arrival order;
- conflict without majority-vote truth;
- durable receipt restart without blind replay;
- distilled handoff only in root context;
- no worker mutation of `TaskState` or decision state;
- reconciliation acceptance without task completion;
- exactly one root final report and no worker user-facing voice;
- unchanged locked solo conformance.

## Evaluation and promotion

Worker count is not the success metric. C-011 must compare solo, Ultra-solo, and
parallel configurations on representative work and measure quality, required evidence,
latency, token/tool/compute cost, context growth, duplicate work, stale rejection,
worker rejection, contradiction handling, and user-voice consistency.

C-011 cannot become `IMPLEMENTED_UNVERIFIED` until the entire declared bounded
capability has production wiring, deterministic verification, an evidence revision, and
truthful known limitations. `VERIFIED` additionally requires current independent
evidence under existing capability governance.

## Explicitly open after S1

- first live worker backend and model/profile routing;
- user-facing Ultra/delegation configuration and lifecycle UI;
- target hardware, GPU/KV accounting, and numeric workload thresholds;
- follow-up/resume semantics for a live worker session;
- child worktree/write isolation;
- equal-compute non-inferiority and promotion thresholds.

These open decisions did not block the separately authorized S1 contract stage. They do
block unsupported durable-runtime, live-worker, or whole-capability claims. S2 and every
later stage remain blocked pending their own owner authorization and current-state
reverification.

## S0 acceptance

S0 is accepted when:

- this RFC and the Delta Review are committed on the dedicated feature branch;
- the handoff records the exact baseline, completed work, open work, evidence, risks,
  and next action;
- existing C7 targeted tests remain green;
- repository integrity and full local gates remain green after metadata refresh;
- C-011 remains `QUEUED` and production remains solo/default-off.

Completion of S0 does not transition the S1 gate. The next governed action is to seek or
record separate S1 owner authorization against current Git, then implement only the
immutable contract/state package if that authorization is granted.

## S1 authorization and acceptance

Separate S1 owner authorization was recorded on 2026-08-24 against S0 commit
`09a5dcc2855edec5625fe9b8845da9f7745dae6f`. S1 introduces only frozen, versioned,
content-integrity and cross-binding contracts under `luna.parallel_cognition`, plus
deterministic tests and a verifier. It does not modify legacy C7 semantics or any
production `LunaRuntime` call site.

The focused contract suite, combined C7/solo regression suite, repository integrity,
Ruff, strict mypy, every verifier, and CLI smoke passed on the exact staged tree. S1 is
therefore accepted for the declared immutable contract/state scope. The next gate remains
`C011_S2_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`.

The broader gates remain unchanged:

```text
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
controlled execution: NONE
```

## S2 authorization and acceptance

Separate S2 owner authorization was recorded on 2026-08-24 against accepted S1 commit
`8c82cab7eebafd04fdd6a7990115ac1019176ad1`. The bounded implementation adds a
task-scoped durable event chain, root lease and monotonic coordination epoch, legal
attempt-transition snapshots, a deterministic in-process fake backend, store-authored
execution receipts, and fail-closed crash/recovery decisions. It does not modify legacy
C7 behavior or wire any production `LunaRuntime` call site.

The focused S2 suite passes `19` tests; the combined S2/S1/C7/solo/continuity/audit/
metadata regression set passes `195` tests. The exact accepted staged-tree full local gate
passes `1339` tests with one recorded Windows symlink-platform skip, repository-wide Ruff
and strict mypy pass, and the complete verifier/CLI chain passes `49/49`. S2 is therefore
`C011_S2_DURABLE_RECOVERY_ACCEPTED` for this declared isolated scope. The next code gate
remains closed as `C011_S3_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`; S2 acceptance
does not authorize S3, production wiring, live workers, or capability promotion.

S2 establishes local store-mediated event provenance and fencing, not cryptographic
human or OS-process authentication. A complete internally valid database rollback or
full-chain rewrite still requires an external anchor or MAC to detect. Current-state
admission, authoritative evidence resolution, cancellation/late-result policy, real
backend isolation, and live workers remain outside S2.

## S3 authorization and acceptance

Separate S3 owner authorization was recorded on 2026-08-28 against accepted S2 commit
`5620d8e428f003b1ca5c8a6392e64e213145132a` and tree
`64ab6a54d168d43286f68043cbd9ab27ec9df935`. S3 adds current-authoritative-state
admission, explicit hierarchical budgets, four runtime-owned currentness fences,
durable denial/quarantine receipts, typed authoritative reference resolution and
deterministic exact reconciliation. It remains an isolated fake-only control plane.

The focused S3 suite passes `24` tests and the combined S1/S2/S3 suite passes `72`
tests. The exact staged-tree full local gate passes `1364` tests with one recorded
Windows symlink-platform skip; repository-wide Ruff, strict mypy, every verifier and CLI
smoke pass the complete `50/50` chain. S3 is therefore
`C011_S3_ADMISSION_CONTROLS_ACCEPTED`. The next code gate remains closed as
`C011_S4_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`. No live worker, production
runtime call site, task-state adoption, capability promotion or controlled C-011
execution is authorized.

## S4 owner authorization and kickoff

The owner separately authorized S4 on 2026-08-28. Current Git reconciliation fixed the
S4 baseline at accepted S3 commit `d7e18459016bdeba3feb17369dee46c006e01110`
and tree `1ad4f38b067e9cee183bcfd33d48491123406c64`; local `main` and
`origin/main` remained `0154390581e6f145eb8b912fe91595cdd54496af`.

The durable kickoff is `C011_S4_OWNER_AUTHORIZED_RECON_COMPLETE`. It authorizes the
bounded S4 engineering sequence recorded in `docs/C011_S4_KICKOFF_CHECKPOINT.md`,
beginning with an interruptible backend and termination/cleanup proof. It does not claim
that a live backend, focused context broker, feature flag, kill switch, root-context
adoption or production Ultra path exists. C-011 remains `QUEUED`, controlled execution
remains `NONE`, and the existing solo `LunaRuntime` path remains unchanged.

The historical S3 next-gate marker
`C011_S4_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION` was satisfied by the explicit
2026-08-28 owner authorization; it remains in the S3 acceptance record as historical
provenance, not the current S4 state.

## S4 implementation and final-gate readiness

S4 implementation is based on kickoff commit
`144c2d1bf7fef6a71d1246761f50086cb9868e34` and tree
`aa0b4446fc98d8e776846f30694ab14b5516bb37`. The bounded implementation adds:

- a shell-free, absolute-executable subprocess driver with explicit environment,
  bounded file output, cooperative cancellation, terminate/kill escalation and
  ephemeral scratch cleanup;
- exact focused-context materialization with root-side redaction and no worker tools,
  credentials, inherited memory, network or write authority;
- root-owned S3 admission and currentness fences around zero-to-three attempts;
- a separate durable S4 reservation/result/handoff journal with fail-closed no-replay
  recovery and append-only current-state evidence for handoff reuse;
- a generic optional root-context extension. `luna.runtime` imports no C-011 package;
  the missing or disabled provider path remains the existing solo path;
- qualified distilled handoffs and root consideration receipts only. Raw worker output,
  hidden reasoning and worker voice never enter the root context.

Deterministic local subprocess fixtures prove the process lifecycle and three-lane
integration. They are not real-model execution or controlled production rollout. The
focused S4 suite passes `10` cases and the combined C-011 plus solo-boundary targeted
suite passes `84`. The exact staged-tree full gate passes `1377` tests with one recorded
Windows symlink-platform skip; repository-wide Ruff, strict mypy, every verifier and
CLI smoke pass the complete `51/51` chain. S4 is therefore
`C011_S4_LIVE_WORKERS_ACCEPTED` for this declared bounded, default-off scope.

The broader states remain unchanged:

```text
C-011 capability: QUEUED
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
controlled execution: NONE
live model execution: NONE
default enabled: false
```

## S5 owner authorization and kickoff

The owner separately authorized the next post-S4 step on 2026-08-29. Current Git
reconciliation fixed its baseline at accepted S4 commit
`030d8488d8882d41e8d3f25cd1ef9f2e108019dc` and tree
`461c53034d7f1bafe36ac917acd9187ec076a4a4`; local `main` and `origin/main`
remained `0154390581e6f145eb8b912fe91595cdd54496af` and the tree/index were clean.

The durable kickoff is `C011_S5_OWNER_AUTHORIZED_RECON_COMPLETE`. The bounded sequence
is recorded in `docs/C011_S5_KICKOFF_CHECKPOINT.md`; it begins with a content-addressed,
deny-by-default provider/profile control plane. S5A performs no provider call, grants no
runtime or promotion authority and does not change S4's disabled solo-default behavior.

Real provider assets, host resource ceilings, identity evidence, equal-compute
non-inferiority, OS containment and any `CANARY`/`ACTIVE` transition remain external
evidence gates. C-011 remains `QUEUED`; Research Saturation Gate remains `NOT_READY`,
Target Spec remains `BLOCKED`, and controlled execution remains `NONE`.

## S5A implementation and final-gate readiness

S5A is implemented against kickoff commit
`4374d7e78bdb67e87dfebdeef24288520c44eb8f` and tree
`967a99a21c45460cb612ec10012752d466c8dc01`. It adds immutable,
content-addressed provider profiles and a pure fail-closed registry that binds exact
backend/model/driver identity, current Phase 13 compatibility fingerprint, neural
resource budget, assignment capacity and permitted worker roles.

Default and kill-switch policy states deny. `CANARY` and `ACTIVE` are structurally
rejected. Exact matches produce only non-executable `SHADOW_ELIGIBLE` evidence with no
provider call, root-context adoption, task-state, completion, worker-voice or promotion
authority. The module has no provider/process/filesystem/network/runtime I/O boundary.

The focused suite passes `17` cases. The exact staged-tree full local gate passes `1395`
tests with one recorded Windows symlink-platform skip; repository-wide Ruff, strict
mypy, every verifier and CLI smoke pass the complete `52/52` chain. S5A is therefore
`C011_S5A_PROVIDER_PROFILE_CONTROL_PLANE_ACCEPTED` for this non-executable scope. The
next code gate is `C011_S5B_LOCAL_NATIVE_DRIVER_ADAPTER_PENDING_IMPLEMENTATION`. C-011
remains `QUEUED`, Research Saturation Gate remains `NOT_READY`, Target Spec remains
`BLOCKED`, and controlled execution remains `NONE`.

## S5B fixture-first local-native driver adapter

S5B is implemented against accepted S5A commit
`3d302c1ace97d65c612cd4c040c5d54f3c5bec00` and tree
`bca0ae37a9e57e1f7c71782cad44aef656382171`. It composes current S5A exact-profile
selection with S4's existing interruptible subprocess backend. The S5B binding fixes the
profile/backend, canonical executable/driver/model paths and hashes, exact explicit child
environment digest and protocol version. This first slice structurally admits only
deterministic `fixture:*` NR-2B Slice 1 profiles.

The current provider policy, compatibility fingerprint, resource budget, request profile
and all artifact hashes are revalidated immediately before execution; artifact hashes are
checked again after cleanup. S4 retains shell-free process creation, bounded output,
cooperative cancellation, terminate/kill escalation and ephemeral cleanup. S4 result
identities are not changed: a distinct S5B result subtype binds the exact provider binding
ID and retains zero adoption, state, completion, voice and promotion authority.

The focused suite passes `13` cases. The exact staged-tree full local gate passes `1409`
tests with one recorded Windows symlink-platform skip; repository-wide Ruff, strict
mypy, every verifier and CLI smoke pass the complete `53/53` chain. Only deterministic
temporary fixture child processes executed. No real provider/model, credential, network
call or production runtime route was added. S5B is
`C011_S5B_LOCAL_NATIVE_DRIVER_ADAPTER_ACCEPTED`.

Real deployment assets and provenance, current host numeric budgets, real compatibility,
race-free OS containment, external journal anchoring and equal-compute evidence remain
open. The next evidence gate is
`C011_S5B_REAL_LOCAL_NATIVE_EXECUTION_BLOCKED_PENDING_EXTERNAL_EVIDENCE`; S5C has not
started. C-011 remains `QUEUED`, Research Saturation Gate remains `NOT_READY`, Target
Spec remains `BLOCKED`, and controlled execution remains `NONE`.

## S5B current real local-native evidence

The external-evidence prerequisite was re-run against accepted S5B commit
`d5d995baf36277a51cf332599aa2fb9153ecade0`. Current absolute asset paths, sizes and
hashes were captured for the 12,109,566,624-byte gpt-oss model blob, the accepted ABI-1
repo-owned bridge, the proof driver and all 18 CPU runtime files. Current host CPU,
memory, GPU identity and driver observations were recorded; WMI adapter RAM is not
accepted as authoritative GPU capacity.

One bounded current-HEAD `LunaNativeWorker` proof executed with eight CPU threads, one
generation, 512 context tokens, at most 256 output tokens, zero GPU/VRAM authority and
ephemeral residency. It passed request correlation, `STOP`, `STOPPED -> STOPPED`, exact
`TEXT_DELTA -> FINISH`, final-only output and exit zero. Model, bridge and runtime hashes
matched after execution.

This evidence is `C011_S5B_REAL_LOCAL_NATIVE_EVIDENCE_ACCEPTED`; it is not a real
`LocalNativeDriverAdapter` invocation. The adapter remains deterministic-fixture-only,
default-off and outside production runtime wiring. The next code gate is
`C011_S5B_REAL_ADAPTER_EXECUTION_PENDING_IMPLEMENTATION`. C-011 remains `QUEUED`,
Research Saturation Gate: NOT_READY, Target Spec: BLOCKED, and controlled execution:
NONE.

## S5B real adapter execution checkpoint

Status: `C011_S5B_REAL_ADAPTER_EXECUTION_ACCEPTED`

One separately authorized, bounded CPU-only execution passed through the default-off
`LocalNativeDriverAdapter`. A single S4-supervised child owned the accepted NR-2B ABI
shim in-process; the exact model, bridge, Python executable, repository driver,
environment and 18-file CPU runtime allowlist matched before and after execution. The
result remained an unverified read-only draft with zero claims and no task-state,
completion, user-voice, tool, memory, network, delegation, persistence or promotion
authority.

The exact staged tree passed 1419 tests, one Windows platform skip, Ruff, strict mypy
across 311 source files and the complete 55/55 verifier/CLI chain. The next code gate
is `C011_S5C_SHADOW_EVALUATION_PENDING_IMPLEMENTATION`; S5C has not started. C-011
remains `QUEUED`, default-off and outside production runtime wiring.

```text
repository acceptance: PASS_1419_TESTS_1_PLATFORM_SKIP_RUFF_MYPY_311_55_OF_55
controlled C-011 execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
```

## S5C shadow evaluation ledger checkpoint

Status: `C011_S5C_SHADOW_EVALUATION_LEDGER_ACCEPTED`

S5C adds passive content-addressed plans, observations and comparisons plus an atomic
hash-chained SQLite ledger. It compares supplied `SOLO`, `ULTRA_SOLO` and `PARALLEL`
observations without executing a provider or feeding shadow output into authoritative
task state. The deterministic fixture proves contract, comparison, replay and tamper
behavior only; real equal-compute non-inferiority remains open.

The next gate is owner-frozen as
`C011_S5D_EXTERNAL_EVIDENCE_AND_PROMOTION_DECISION_BLOCKED_PENDING_OWNER_DECISION`.
C-011 remains `QUEUED`, default-off and outside production runtime wiring.

```text
repository acceptance: PASS_1440_TESTS_1_PLATFORM_SKIP_RUFF_MYPY_312_56_OF_56
real provider execution: NONE
controlled C-011 execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
```

## S5D external-evidence promotion decision checkpoint

Status: `C011_S5D_EXTERNAL_EVIDENCE_PROMOTION_DECISION_ACCEPTED_NOT_PROMOTED`

Decision: `BLOCKED_INSUFFICIENT_EVIDENCE` / `NOT_PROMOTED`

The owner separately authorized the bounded S5D decision slice on 2026-09-01. S5D
evaluates supplied, content-addressed evidence only. It made no provider/model call,
added no production runtime wiring and cannot apply or authorize CANARY or ACTIVE.

Current evidence verifies one prior S5B real-provider observation and S5C local-ledger
integrity. Hardware-resource and safety-containment evidence is partial. Representative
real equal-compute non-inferiority, independent evaluator attestation, contamination
provenance and an external immutable ledger anchor are open. C-011 therefore remains
`QUEUED`, default-off and `BLOCKED`.

The next gate is
`C011_REAL_EQUAL_COMPUTE_EXTERNAL_EVIDENCE_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`.

```text
repository acceptance: PASS_1459_TESTS_1_PLATFORM_SKIP_RUFF_MYPY_313_57_OF_57
provider/model execution during S5D: NONE
controlled C-011 execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
```

ASLM Research is a separate project and was not evaluated or modified. No hidden
chain-of-thought access is claimed.

## S5D-E1 real equal-compute execution preflight

Status: `C011_REAL_EQUAL_COMPUTE_EXTERNAL_EVIDENCE_PREFLIGHT_ACCEPTED_BLOCKED`

Decision: `BLOCKED_REJECTED_BASIS` / `NOT_EXECUTED_BLOCKED`

The owner separately authorized a bounded real equal-compute evidence test on
2026-09-01. This permission is recorded as provenance; it does not grant runtime,
rollout or promotion authority. The preflight requires frozen `SOLO`, `ULTRA_SOLO` and
`PARALLEL` contracts, at least two parallel workers, measured token accounting and the
complete external evidence inventory.

Current source and accepted receipts reject measured-token accounting and the parallel
runtime basis: token usage is hard-coded/reported as zero, and the accepted real harness
permits only one total and concurrent worker. A model run now could not establish a fair
equal-compute triplet, so no provider/model call was attempted. Other runtime contracts,
representative evidence and independent attestations remain open or partial.

The next gate is
`C011_REAL_EQUAL_COMPUTE_RUNTIME_ACCOUNTING_CONTRACT_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`.

```text
repository acceptance: PASS_1476_TESTS_1_PLATFORM_SKIP_RUFF_MYPY_314_58_OF_58
provider/model execution during preflight: NONE
controlled C-011 execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
```

C-011 remains `QUEUED`, default-off and `BLOCKED`. The preflight grants no task-state,
root-context, completion, user-facing voice, CANARY, ACTIVE or promotion authority.
ASLM Research is a separate project and no hidden chain-of-thought access is claimed.

## S5D-E2 runtime accounting contract checkpoint

Status: `C011_REAL_EQUAL_COMPUTE_RUNTIME_ACCOUNTING_CONTRACT_ACCEPTED_BLOCKED_ABI_V1`

Decision: `BLOCKED_USAGE_CHANNEL_ABSENT`

The owner separately authorized this bounded contract gate on 2026-09-01. S5D-E2
defines input usage as post-chat-template model tokens actually fed, including actual
special/BOS tokens; output usage as sampled non-EOG tokens; and total usage as their
sum. Only engine-native counters are accepted. A driver declaration, text
re-tokenization, byte/word estimate, budget ceiling or zero placeholder cannot satisfy
the contract.

Current source proves that ABI v1 calculates the prompt token count and samples one
token per generation step internally. Its exact four exports return generated bytes and
byte length only; neither the Python native worker nor the accepted proof receives
input, output or total token counters. The fail-closed decision is therefore
`BLOCKED_USAGE_CHANNEL_ABSENT`.

No provider/model call ran because another ABI-v1 result would add no authoritative
usage evidence. This gate adds no production runtime wiring and changes no native
bridge, native worker or real-driver source. The next gate is
`C011_NATIVE_ABI_V2_MEASURED_USAGE_CHANNEL_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`.

```text
repository acceptance: PASS_1497_TESTS_1_PLATFORM_SKIP_RUFF_MYPY_315_59_OF_59
provider/model execution during S5D-E2: NONE
controlled C-011 execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
```

C-011 remains `QUEUED`, default-off and `BLOCKED`. This checkpoint grants no runtime,
task-state, root-context, completion, user-facing voice, CANARY, ACTIVE or promotion
authority. ASLM Research is a separate project and no hidden chain-of-thought access is
claimed.

## S5D-E3 native ABI v2 measured-usage checkpoint

Status: `C011_NATIVE_ABI_V2_MEASURED_USAGE_CHANNEL_ACCEPTED`

The separately authorized ABI v2 keeps all legacy v1 exports/signatures and adds
versioned create and generate calls. The new generate result carries
`ENGINE_NATIVE_COUNTERS`: post-template input tokens, sampled non-EOG output tokens
and their exact total. Failure counters are zeroed.

The pinned CPU bridge rebuild exposed exactly six approved symbols. A bounded real
`LunaNativeWorker` path and C-011 final-only driver path both returned valid native
usage while preserving model, bridge, runtime and repository integrity.

This is an accounting-channel proof, not equal-compute non-inferiority or runtime
promotion. C-011 remains `QUEUED`, default-off and `BLOCKED`. The next gate is
`C011_REAL_RUNTIME_CONFIGURATION_CONTRACTS_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION`.

```text
repository acceptance: PASS_1503_TESTS_1_PLATFORM_SKIP_RUFF_MYPY_315_60_OF_60
controlled C-011 execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
```

ASLM Research is a separate project and was not evaluated or modified. No hidden
chain-of-thought access is claimed.

## S5D-E4 real runtime configuration checkpoint

Status: `C011_REAL_RUNTIME_CONFIGURATION_CONTRACTS_ACCEPTED`

The owner-authorized E4 package turns the previously open runtime definitions
into three immutable, content-addressed contracts:

- `SOLO`: one standard root-only final pass;
- `ULTRA_SOLO`: one Ultra root draft followed by one root-only verification and
  finalization pass;
- `PARALLEL`: two or three concurrent read-only final-only worker passes followed
  by one Ultra root verification and synthesis pass.

All arms bind the same exact model, ABI v2 bridge, driver, runtime bundle,
environment, sampling protocol, seed, generated-output ceiling, and normalized
compute budget. Intermediate payloads are final-only; raw analysis is not
persisted or exposed. Workers cannot mutate task state or acquire completion,
root-context, user-facing voice, or promotion authority.

The E4 change also closes an ABI v2 provenance gap: native input/output/total
counters now survive the S4 subprocess and S5B adapter result boundary. The
assignment `max_tokens` ceiling continues to govern generated output, while the
full native total remains separately available for equal-compute accounting.

A bounded real proof ran two distinct one-shot CPU model children concurrently.
Both returned `READY.` with 76 input, 24 output, and 100 total engine-native
tokens. Maximum observed concurrency was two; neither adapter could be replayed;
model, bridge, runtime, and repository evidence remained unchanged.

This proof exercises the parallel worker basis only. It is not the frozen
representative `SOLO` / `ULTRA_SOLO` / `PARALLEL` evaluation and cannot establish
non-inferiority or promotion. The next gate is
`C011_REAL_EQUAL_COMPUTE_RUNNER_AND_FROZEN_SUITE_PENDING_IMPLEMENTATION`.

```text
repository acceptance: PASS_1521_TESTS_1_PLATFORM_SKIP_RUFF_MYPY_317_61_OF_61
controlled C-011 execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
```

C-011 remains `QUEUED`, default-off and `BLOCKED`. ASLM Research is a separate
project and was not evaluated or modified. No hidden chain-of-thought access is
claimed.

## S5D-E5 real equal-compute runner and frozen-suite checkpoint

Status: `C011_REAL_EQUAL_COMPUTE_RUNNER_AND_FROZEN_SUITE_ACCEPTED_BLOCKED_EXTERNAL_EVIDENCE`

E5 implements the repository-controlled part of the full comparison gate. A
content-addressed six-case suite freezes three `HELD_OUT` and three `OOD` cases
across evidence grounding, contradiction resolution, authority boundaries,
stale-state reconciliation, changed-basis failure classification, and
cross-review synthesis. The scope is bounded and does not claim statistical
representativeness.

The runner accepts only the E4 `SOLO`, `ULTRA_SOLO`, and `PARALLEL` topology
contracts. It revalidates copied inputs, requires a ready E1 preflight, binds the
asset, arm, suite, and executor identities, enforces equal-compute budgets, and
never retries a provider call. Parallel workers expose final-only drafts to one
root synthesis call. Raw model output and hidden reasoning are not persisted;
hash-only receipts preserve native input/output/total counters and timing.

Deterministic test-double execution proves the exact 36-call two-worker and
42-call three-worker schedules and their concurrency boundaries. This cannot
falsify or replace real-model quality evidence. The authoritative current
preflight remains blocked because three external attestations are absent and two
are partial; therefore no full real triplet was run.

The next material gate is
`C011_REAL_EQUAL_COMPUTE_EXTERNAL_ATTESTATIONS_AND_EXECUTION_BLOCKED`.

```text
repository acceptance: PASS_1539_TESTS_1_PLATFORM_SKIP_RUFF_MYPY_318_62_OF_62
controlled C-011 execution: NONE
Research Saturation Gate: NOT_READY
Target Spec: BLOCKED
```

C-011 remains `QUEUED`, default-off and `BLOCKED`. No production runtime,
task-state, root-context, completion, user-facing voice, CANARY, ACTIVE, or
promotion authority is granted. ASLM Research is a separate project and was not
evaluated or modified. No hidden chain-of-thought access is requested or claimed.
