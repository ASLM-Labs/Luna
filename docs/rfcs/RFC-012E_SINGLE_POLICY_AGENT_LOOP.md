# RFC-012E — Single Policy-Agent Runtime Loop

**Status:** ACCEPTED_FOR_PHASE_12E
**Date:** 2026-08-07

## Purpose

Phase 12E turns the Phase 12A–12D contracts and policies into one authoritative Luna
runtime loop. There is one Luna identity, one authoritative `TaskState`, and one
runtime-owned sequence of context → proposal → authorization → action → observation →
reevaluation. Model output remains untrusted proposal data; it never becomes execution
authority.

Phase 12E deliberately stops at `VERIFICATION_PENDING`. Deterministic final verification,
final reporting, evidence-strength reconciliation, memory/learning candidate finalization,
and `verified_complete` remain Phase 12F responsibilities.

## Authoritative loop

```text
RuntimeRequest
→ finalized TaskContract
→ one authoritative TaskState
→ LayeredContextComposer
→ single policy-model turn
→ exactly one ActionProposal
→ Phase 12C ActionResolver
→ runtime policy / risk / budget / minimal-change checks
→ required workspace isolation
→ exactly one ToolDispatcher dispatch
→ durable DispatchOutcome / Observation
→ expected-vs-actual evaluation
→ recovery / continue / safe stop
→ checkpoint
→ next model turn sees prior observations as DATA_ONLY runtime continuity
→ ...
→ VERIFICATION_PENDING
```

There is no role chain, persona chain, hidden subagent, or secondary autonomous model.
The policy model may recommend only the next bounded action. Runtime code owns permissions,
risk ceilings, budgets, isolation, side-effect fencing, cancellation, recovery, task-state
transitions, and completion handoff.

## One action per iteration

A Phase 12E model response may contain either:

- exactly one registered/routed tool call; or
- no tool call, which yields control without execution.

Multiple tool calls are invalid even when every proposed tool is read-only. This is
intentionally stricter than batching because each `DispatchOutcome` must be observed and
reevaluated before another action can be proposed.

## Durable observation continuity

Every completed dispatch, including read-only dispatches, is persisted in the runtime
journal as bounded structured evidence. The next model turn receives recent evidence in
`RUNTIME_CONTINUITY` as `DATA_ONLY` context. Runtime-owned task state remains `CONTROL`;
tool output cannot become control instructions.

Only bounded `ToolResult` and structured `Observation` data are rendered. Tool request
arguments are not copied into model-visible observation context. Existing context secret
redaction remains mandatory before the model sees the entry.

## Side-effect write-ahead fence

Potential side effects use a durable lifecycle:

```text
PREPARED
→ STARTED
→ COMPLETED
→ OBSERVED
→ CHECKPOINTED
```

`ABORTED` is valid only before `STARTED`.

The journal fence is written before `ToolDispatcher.dispatch()`. Resume behavior is
stage-specific:

- `PREPARED`: the handler has not started; runtime may execute it exactly once after a
  fresh safe-control check;
- `STARTED`: execution is ambiguous; automatic replay is forbidden;
- `COMPLETED`: the saved outcome is reconstructed without rerunning the handler;
- `OBSERVED`: runtime checkpoints the already-observed state without rerunning the
  handler;
- `CHECKPOINTED`: no side-effect recovery is pending;
- `ABORTED`: the action will not be executed from that receipt.

Idempotency keys bind task ID + plan step ID + semantic request fingerprint. An identical
side effect in the same step cannot silently obtain a second execution fence. The same
semantic action in a different legitimate step is not incorrectly treated as the same
attempt.

## Safe suspend and cancel

`suspend()` and `cancel()` write durable control records. The loop acknowledges them only
at safe runtime boundaries; it never force-kills an in-flight tool handler.

If interruption evidence says a side effect reached `STARTED`, that ambiguity takes
precedence over a later cancel request: Luna reports interruption instead of pretending
the action did not run. A cancel received while a side effect is still `PREPARED` aborts
the receipt before execution. Safe cancellation also cleans an owned task worktree when
possible.

## Workspace isolation lifecycle

Phase 12D selected isolation strength; Phase 12E performs the lifecycle:

- LOW/MEDIUM mutations use existing snapshot-first execution;
- HIGH/CRITICAL mutations require a real deterministic Git worktree;
- no silent WORKTREE → SNAPSHOT downgrade is allowed;
- after a worktree is established, subsequent task actions, fingerprints, checkpoints,
  and resume guards use that effective isolated root;
- safe cancellation removes the task worktree.

A high-risk task therefore cannot accidentally write the original checkout and then read
or checkpoint a different workspace.

## Runtime budgets

Zero-capacity model, tool, or network budgets disable that capability before dispatch.
Positive hard budgets are checked before each iteration and after model usage is known.
Model token overruns stop before tool execution. Observed file/line changes are charged to
runtime usage and remain subject to the Phase 12D minimal-change policy.

No budget failure grants an automatic retry.

## Recovery boundary

Observed failures are normalized through the Phase 12D classifier and recovery policy.
There is no blind retry loop. Runtime may stop for approval, reinspection, replan,
rollback, suspension, integrity review, or budget review according to structured evidence.

## Completion boundary

Phase 12E may transition the authoritative state to `VERIFYING` only after planned action
observations are complete. Its successful terminal handoff is:

```text
RuntimeStopReason.VERIFICATION_PENDING
```

Phase 12E never manufactures `VERIFIED_COMPLETE`. The Phase 7 deterministic completion
gate remains the only authority allowed to establish verified completion, and Phase 12F
will wire that finalization into the new runtime loop.

## Non-goals

Phase 12E does not add:

- real-model provider rollout;
- autonomous subagents or persona delegation;
- web research, GitHub, MCP/plugin, or other external integrations;
- desktop, Discord, voice, or product-shell gateways;
- final evidence-strength disagreement resolution;
- automatic memory/learning commit from runtime observations;
- uncontrolled self-modification.
