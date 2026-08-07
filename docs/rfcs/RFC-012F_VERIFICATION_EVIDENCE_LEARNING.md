# RFC-012F — Verification, Evidence, Finalization and Review-Gated Learning

**Status:** ACCEPTED_FOR_PHASE_12F

## 1. Purpose

Phase 12F closes the gap between "an action ran" and "the task is verified". It
connects the Phase 12E single policy-agent loop to deterministic evidence
assessment, completion gating, truthful final reporting, terminal checkpointing,
and review-only learning candidates.

The governing rule is:

> A model assertion, a successful tool return, or a previous task result is not
> sufficient authority for `VERIFIED_COMPLETE`.

## 2. Authoritative flow

```text
VERIFYING TaskState
→ immutable durable evidence registry
→ current revision/environment/freshness checks
→ runtime-owned evidence-strength assessment
→ claim + evidence-requirement assessment
→ disagreement detection
→ deterministic CompletionGate
→ REPORTING TaskState
→ gate-bound FinalReport
→ review-required LearningCandidate batch
→ CLOSED TaskState
→ terminal continuity checkpoint
```

The model is not part of the completion decision.

## 3. Evidence strength

Phase 12F defines four runtime-owned strength classes:

- `WEAK`
- `MODERATE`
- `STRONG`
- `DETERMINISTIC`

Default completion policy requires at least `STRONG` evidence. Source kind,
reproducibility, confidence, revision, environment, and freshness are evaluated by
runtime code. Model prose cannot promote an evidence record to a stronger class.

Default source mapping is intentionally conservative:

- model inference and memory: `WEAK`;
- document and generic tool output: `MODERATE`;
- diff and measurement: `STRONG`;
- reproducible high-confidence test result and hash: `DETERMINISTIC`.

Non-reproducible or low-confidence evidence is downgraded by policy.

## 4. Current-evidence boundary

Evidence is rejected when it belongs to another task, is missing a required
revision/freshness field, refers to a stale revision, does not match the current
environment, is stale, or has a future timestamp outside tolerance.

Old-revision evidence therefore cannot verify a current workspace revision.

## 5. Evidence requirements

Human-readable `TaskContract.evidence_required` values are interpreted only through
explicit deterministic Phase 12F rules. Unknown requirements remain unverified;
they are never guessed or delegated to model judgment.

A generic successful tool output is a useful observation, but by default is only
`MODERATE` and cannot independently produce `VERIFIED_COMPLETE`.

## 6. Disagreement

Current qualifying PASS and FAIL evidence for the same claim creates an explicit
`EvidenceDisagreement`. An unresolved disagreement blocks verified completion and
produces `CONFLICTING_EVIDENCE`.

Disagreement is visible in the verification report and final report rather than
being silently averaged away.

## 7. Durable evidence registry

`SQLiteEvidenceStore` persists evidence using SQLite WAL and canonical JSON SHA-256
integrity metadata. Evidence IDs are immutable:

- writing the same ID with the same payload is idempotent;
- writing the same ID with different payload is rejected;
- integrity can be checked before finalization.

`VerifiedEvidenceRegistry` may additionally emit the existing append-only evidence
audit record. LunaRuntime refuses Phase 12F finalization if registry integrity
fails.

## 8. Completion and reporting

`VerificationCoordinator` joins existing authoritative components rather than
creating a second completion path:

1. `CompletionGate` evaluates evidence and owns completion status;
2. the gate applies that status to the authoritative `TaskState`;
3. `FinalReportComposer` reports exactly the gate-owned status;
4. evidence references expose runtime-assessed strength;
5. unresolved disagreement is surfaced as unverified content.

The runtime maps completion status to an explicit runtime stop reason. Only
`VERIFIED_COMPLETE` becomes `RuntimeStopReason.COMPLETED`.

## 9. Terminal checkpoint

After finalization, `VERIFIED_COMPLETE` and deterministic `FAILED` outcomes may
transition `REPORTING → CLOSED` and write a terminal continuity checkpoint containing
current observations/evidence and current workspace/environment fingerprints. A
terminal checkpoint cannot be resumed.

`UNVERIFIED`, `INCONCLUSIVE`, `BLOCKED`, and `CONFLICTING_EVIDENCE` are deliberately
non-terminal. Luna checkpoints the reporting state with `VERIFYING` as the resume
phase so stronger/current evidence can be collected or disagreement can be reconciled.

If no durable evidence exists, Phase 12F does not fabricate completion. The runtime
stays at the existing safe boundary with `VERIFICATION_PENDING` and a resumable
checkpoint.

## 10. Learning boundary

Phase 12F introduces `LearningCandidate`, not autonomous self-modification.
Candidates may describe:

- failed assumptions;
- evidence conflicts;
- verification gaps;
- recovery patterns after a failed assumption.

Every candidate is contractually locked to:

```text
review_required = true
automatic_commit_allowed = false
```

The builder does not import or invoke memory persistence, process/network access,
or source-code mutation. With audit enabled, candidate payloads are appended to the
audit chain for later human/runtime review.

Phase 12F does not automatically alter policy, prompts, source code, verified
memory, autonomy, or tool permissions.

## 11. Runtime compatibility

Phase 12F services are optional on `RuntimeLoopDependencies` so Phase 12E behavior
remains testable and backward-compatible. Without Phase 12F services the existing
`VERIFICATION_PENDING` handoff is preserved.

With Phase 12F services configured:

```text
run/resume
→ VERIFYING
→ no evidence: VERIFICATION_PENDING
→ durable current evidence recorded
→ resume
→ deterministic gate/report/learning
→ evidence gap/conflict: resumable VERIFYING checkpoint
→ verified/final failure: terminal CLOSED checkpoint
```

## 12. Non-goals

Phase 12F does not add:

- real-model rollout;
- web/research retrieval;
- GitHub or other external integrations;
- autonomous policy/source-code rewriting;
- automatic promotion of learning candidates into verified memory;
- subagents or persona chains;
- product UI, Discord, or voice gateways.

These remain later-phase concerns.

## 13. Acceptance

Phase 12F is accepted only when:

- legacy Phase 1–12E gates remain green;
- strong current evidence can verify a claim;
- generic weak/moderate evidence cannot falsely verify completion;
- old-revision evidence cannot verify the current revision;
- current conflicting qualifying evidence is explicit and blocks success;
- evidence persistence is durable, idempotent, conflict-safe, and integrity-checked;
- final report status remains gate-bound and exposes evidence strength;
- learning candidates require review and reject automatic commit;
- the Phase 12E runtime can remain pending without evidence and finalize after
  current strong evidence is recorded;
- finalization writes a terminal checkpoint;
- metadata integrity and the full quality gate pass.
