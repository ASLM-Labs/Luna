# RFC-012G — Runtime E2E and Behavior Conformance

**Status:** ACCEPTED_FOR_PHASE_12G

## 1. Purpose

Phase 12G validates the Phase 12 runtime foundation as one system instead of as a
collection of isolated components. The goal is to prove that cross-layer behavior
remains correct when context, policy, tools, durable observations, recovery,
isolation, verification, reporting, and continuity interact.

The governing rule is:

> Component-level success is insufficient if the integrated runtime can violate a
> safety, evidence, replay, scope, or completion invariant.

## 2. Locked conformance suite

Phase 12G introduces a revision-locked runtime behavior suite. Case definitions and
expected observable oracles are protected by a canonical SHA-256 digest. Silent
fixture/oracle drift is rejected.

Suite revision: `1.0.0`

Suite SHA-256:

```text
52346f987ad274b02b265c431d309be0dd83e2bc100fb497634474f294ab644e
```

All 11 cases are critical.

## 3. Required behavior domains

The suite covers every Phase 12G conformance domain:

- completion truth;
- evidence discipline;
- policy boundary;
- safe control;
- side-effect replay;
- scope integrity;
- isolation;
- runtime budget enforcement.

## 4. Critical scenarios

The locked suite requires these integrated behaviors:

1. deterministic current evidence is required before verified completion;
2. no evidence cannot become false success;
3. weak evidence remains resumable and inconclusive;
4. conflicting qualifying evidence remains unresolved;
5. multiple model actions are blocked before dispatch;
6. owner cancellation wins at a safe boundary before model/tool execution;
7. ambiguous `STARTED` side effects are not replayed after restart;
8. out-of-scope mutation is denied before dispatcher execution;
9. high-risk writes stay in a real Git worktree and observations reach the next turn;
10. exhausted tool budget blocks before dispatch;
11. stale-revision evidence cannot verify current state.

## 5. Real-runtime execution

`RuntimeBehaviorExecutor` constructs the actual Luna runtime stack with the existing
planner, model boundary, action resolver, dispatcher, recovery policy, durable
runtime journal, worktree manager, continuity store, evidence registry,
`CompletionGate`, report composer, and Phase 12F verification coordinator.

The conformance runner therefore tests observable integrated behavior rather than a
second fake policy implementation.

## 6. Exact oracle comparison

`ConformanceRunner` executes every locked case exactly once and compares normalized
observable values to the locked oracle recursively. Missing keys, changed values,
wrong case IDs, or executor exceptions fail closed.

Executor exceptions are surfaced as `ERROR`; they are not converted into a pass.
Repeated independent runs must produce the same semantic signature.

## 7. Cross-layer scope defect found by Phase 12G

During Phase 12G integration, an out-of-scope file mutation could pass the earlier
dispatcher preflight when write permission was enabled because file-path membership
in `TaskScope.allowed_paths` was not checked at that boundary. A later minimal-change
check still prevented the mutation, but the outcome was an integrity failure rather
than the intended explicit permission/scope denial.

Phase 12G closes that gap in `evaluate_tool_policy()`:

```text
request path
→ canonical workspace path
→ TaskScope.allowed_paths
→ path_scope PASS / FAIL
→ dispatch only after PASS
```

The conformance oracle requires `PERMISSION_DENIED`, zero tool dispatches, no
outside file, and a visible denial observation.

## 8. Isolation and Windows byte integrity

The high-risk scenario uses a real temporary Git repository, enables
`core.autocrlf=true`, writes the baseline fixture as exact bytes, and verifies:

- the original checkout remains unchanged;
- the isolated worktree receives the mutation;
- the next model turn sees the durable observation;
- proposal-only SHA input is not replayed into model-visible continuity;
- cancellation cleanup removes the owned task worktree.

This preserves the Windows byte-exact regression learned in Phase 12E.

The Phase 12G Windows gate additionally found that deriving the worktree location
from the source repository parent can make the combined worktree + snapshot path
inherit arbitrary source depth. HIGH/CRITICAL worktrees therefore use a deterministic
bounded runtime pool keyed by repository path and task ID rather than a sibling path.
The locked `L12G-09` oracle requires this bounded placement.

## 9. Compatibility gate

Phase 12G does not replace the locked Phase 11 acceptance suite. The Phase 12G gate
also runs the existing Phase 11 core acceptance and requires 11/11 PASS with release
status `PASS`.

Phase 1–12F deterministic gates remain part of the full quality gate.

## 10. Non-goals

Phase 12G does not add:

- real external model rollout;
- web/research retrieval;
- GitHub or other external integrations;
- autonomous policy/source rewriting;
- subagents or persona chains;
- desktop, Discord, or voice product gateways.

Those remain later phases. Phase 13 begins real-model compatibility and controlled
rollout only after this runtime behavior foundation is green.

## 11. Acceptance

Phase 12G is accepted only when:

- the locked suite digest validates;
- all 11 critical real-runtime scenarios pass;
- repeated conformance runs have identical semantic signatures;
- out-of-scope paths are denied before dispatcher execution;
- ambiguous side effects are not replayed;
- high-risk worktree isolation and cleanup hold;
- no evidence, weak evidence, conflict, or stale evidence cannot falsely complete;
- the locked Phase 11 acceptance suite remains 11/11 PASS;
- metadata integrity passes;
- the full Windows quality gate, Ruff, and mypy strict pass.
