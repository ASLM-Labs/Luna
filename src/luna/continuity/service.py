"""Checkpoint creation, restart validation, and blind-retry continuity."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from luna.audit.models import AuditEventKind
from luna.audit.session import AuditSession
from luna.continuity.models import (
    CheckpointEnvelope,
    ResumeDecision,
    ResumePolicy,
    ResumeStatus,
    StoredCheckpoint,
)
from luna.continuity.store import (
    CheckpointNotFoundError,
    ContinuityConflictError,
    SQLiteContinuityStore,
)
from luna.contracts.base import stable_payload
from luna.contracts.checkpoint import Checkpoint
from luna.contracts.enums import PlanStepStatus, TaskPhase
from luna.contracts.state import ALLOWED_TRANSITIONS, TaskState
from luna.planning.models import (
    AttemptBasis,
    AttemptRecord,
    RetryDecision,
)
from luna.planning.retry import RetryGuard


_SAFE_RESUME_PHASES = frozenset(
    {
        TaskPhase.CONTEXT_READY,
        TaskPhase.PLANNED,
        TaskPhase.VERIFYING,
        TaskPhase.REPORTING,
    }
)


_DEFAULT_RESUME_PHASE: dict[TaskPhase, TaskPhase] = {
    TaskPhase.CONTRACTED: TaskPhase.CONTEXT_READY,
    TaskPhase.CONTEXT_READY: TaskPhase.CONTEXT_READY,
    TaskPhase.PLANNED: TaskPhase.PLANNED,
    TaskPhase.ACTING: TaskPhase.PLANNED,
    TaskPhase.OBSERVING: TaskPhase.VERIFYING,
    TaskPhase.REPLANNING: TaskPhase.PLANNED,
    TaskPhase.VERIFYING: TaskPhase.VERIFYING,
    TaskPhase.REPORTING: TaskPhase.REPORTING,
}


class ContinuityService:
    """Coordinate immutable checkpoints with optional append-only audit."""

    def __init__(
        self,
        store: SQLiteContinuityStore,
        audit: AuditSession | None = None,
    ) -> None:
        self.store = store
        self.audit = audit

    @staticmethod
    def _step_sets(state: TaskState) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
        completed = tuple(
            step.step_id
            for step in state.plan
            if step.status in {
                PlanStepStatus.COMPLETE,
                PlanStepStatus.SKIPPED_WITH_REASON,
            }
        )
        open_steps = tuple(
            step.step_id
            for step in state.plan
            if step.status not in {
                PlanStepStatus.COMPLETE,
                PlanStepStatus.SKIPPED_WITH_REASON,
            }
        )
        return completed, open_steps

    def create_checkpoint(
        self,
        *,
        state: TaskState,
        workspace_fingerprint: str,
        environment_fingerprint: str,
        runtime_revision: str,
        next_step: str | None,
        risks: Iterable[str] = (),
        attempts: Iterable[AttemptRecord] = (),
        resume_phase: TaskPhase | None = None,
        trace_id: UUID | None = None,
    ) -> StoredCheckpoint:
        if self.audit is not None and trace_id is None:
            raise ValueError("audited checkpoint requires trace_id")

        latest: StoredCheckpoint | None
        try:
            latest = self.store.load_latest(state.task_id)
        except CheckpointNotFoundError:
            latest = None

        completed, open_steps = self._step_sets(state)
        terminal = state.phase is TaskPhase.CLOSED

        if terminal:
            if next_step is not None:
                raise ValueError("closed task checkpoint cannot define next_step")
            checkpoint = Checkpoint(
                task_id=state.task_id,
                workspace_fingerprint=workspace_fingerprint,
                environment_fingerprint=environment_fingerprint,
                last_verified_phase=TaskPhase.CLOSED,
                completed_step_ids=completed,
                open_step_ids=open_steps,
                failed_assumptions=state.failed_assumptions,
                observation_ids=state.observation_ids,
                evidence_ids=state.evidence_ids,
                next_step=None,
                risks=tuple(risks),
            )
            persisted_state = state
            target_phase = None
        else:
            if state.phase is TaskPhase.CHECKPOINTED:
                raise ValueError("state is already checkpointed")
            if TaskPhase.CHECKPOINTED not in ALLOWED_TRANSITIONS[state.phase]:
                raise ValueError(
                    f"task phase {state.phase.value} cannot be checkpointed"
                )
            if not next_step:
                raise ValueError("non-terminal checkpoint requires next_step")
            target_phase = resume_phase or _DEFAULT_RESUME_PHASE.get(state.phase)
            if target_phase is None:
                raise ValueError(
                    f"no safe resume phase for {state.phase.value}"
                )
            if target_phase not in ALLOWED_TRANSITIONS[TaskPhase.CHECKPOINTED]:
                raise ValueError(
                    "resume phase is not reachable from CHECKPOINTED"
                )
            checkpoint = Checkpoint(
                task_id=state.task_id,
                workspace_fingerprint=workspace_fingerprint,
                environment_fingerprint=environment_fingerprint,
                last_verified_phase=state.phase,
                completed_step_ids=completed,
                open_step_ids=open_steps,
                failed_assumptions=state.failed_assumptions,
                observation_ids=state.observation_ids,
                evidence_ids=state.evidence_ids,
                next_step=next_step,
                risks=tuple(risks),
            )
            persisted_state = state.transition_to(
                TaskPhase.CHECKPOINTED,
                completion_status=state.completion_status,
                checkpoint_id=checkpoint.checkpoint_id,
            )

        envelope = CheckpointEnvelope(
            checkpoint=checkpoint,
            state=persisted_state,
            runtime_revision=runtime_revision,
            resume_phase=target_phase,
            previous_checkpoint_id=(
                latest.envelope.checkpoint.checkpoint_id
                if latest is not None
                else None
            ),
            attempt_records=tuple(attempts),
            terminal=terminal,
        )
        stored = self.store.save_checkpoint(envelope)

        if self.audit is not None:
            assert trace_id is not None
            self.audit.ledger.append(
                kind=AuditEventKind.CHECKPOINT_CREATED,
                task_id=state.task_id,
                trace_id=trace_id,
                subject_id=str(checkpoint.checkpoint_id),
                payload={
                    "checkpoint": stable_payload(checkpoint),
                    "runtime_revision": runtime_revision,
                    "resume_phase": (
                        target_phase.value if target_phase is not None else None
                    ),
                    "previous_checkpoint_id": (
                        str(envelope.previous_checkpoint_id)
                        if envelope.previous_checkpoint_id is not None
                        else None
                    ),
                    "payload_sha256": stored.payload_sha256,
                    "terminal": terminal,
                },
            )
        return stored

    def resume_latest(
        self,
        *,
        task_id: UUID,
        policy: ResumePolicy,
        trace_id: UUID | None = None,
    ) -> ResumeDecision:
        if self.audit is not None and trace_id is None:
            raise ValueError("audited resume requires trace_id")
        stored = self.store.load_latest(task_id)
        envelope = stored.envelope
        checkpoint = envelope.checkpoint

        replay_prohibited = tuple(
            dict.fromkeys(
                (
                    *checkpoint.completed_step_ids,
                    *(
                        attempt.step_id
                        for attempt in envelope.attempt_records
                    ),
                )
            )
        )

        if envelope.terminal:
            decision = ResumeDecision(
                task_id=task_id,
                checkpoint_id=checkpoint.checkpoint_id,
                status=ResumeStatus.TERMINAL,
                reasons=("terminal checkpoint cannot resume",),
                policy=policy,
                replay_prohibited_step_ids=replay_prohibited,
            )
            self._record_resume(decision=decision, trace_id=trace_id)
            return decision

        reasons: list[str] = []
        if envelope.runtime_revision != policy.runtime_revision:
            reasons.append("runtime revision mismatch")
        if checkpoint.workspace_fingerprint != policy.workspace_fingerprint:
            reasons.append("workspace fingerprint mismatch")
        if (
            checkpoint.environment_fingerprint
            != policy.environment_fingerprint
        ):
            reasons.append("environment fingerprint mismatch")

        current_state = self.store.load_task_state(task_id)
        if (
            current_state.revision != envelope.state.revision
            or current_state.phase is not TaskPhase.CHECKPOINTED
            or current_state.checkpoint_id != checkpoint.checkpoint_id
        ):
            reasons.append("checkpoint is stale or has already resumed")

        active_steps = tuple(
            step.step_id
            for step in envelope.state.plan
            if step.status is PlanStepStatus.ACTIVE
        )
        if active_steps or checkpoint.last_verified_phase is TaskPhase.ACTING:
            reasons.append(
                "interrupted action requires observation reconciliation before resume"
            )
            replay_prohibited = tuple(
                dict.fromkeys((*replay_prohibited, *active_steps))
            )

        if reasons:
            decision = ResumeDecision(
                task_id=task_id,
                checkpoint_id=checkpoint.checkpoint_id,
                status=ResumeStatus.BLOCKED,
                reasons=tuple(dict.fromkeys(reasons)),
                policy=policy,
                resume_phase=envelope.resume_phase,
                replay_prohibited_step_ids=replay_prohibited,
            )
            self._record_resume(decision=decision, trace_id=trace_id)
            return decision

        if envelope.resume_phase is None:
            raise ContinuityConflictError(
                "non-terminal checkpoint lost resume_phase"
            )
        resumed_state = envelope.state.transition_to(
            envelope.resume_phase,
            completion_status=envelope.state.completion_status,
        )
        self.store.resume_checkpoint(
            stored=stored,
            resumed_state=resumed_state,
        )
        decision = ResumeDecision(
            task_id=task_id,
            checkpoint_id=checkpoint.checkpoint_id,
            status=ResumeStatus.READY,
            reasons=(
                "revision, workspace, and environment fingerprints match",
                "persisted task state resumed without replaying completed actions",
            ),
            policy=policy,
            resume_phase=envelope.resume_phase,
            resumed_state=resumed_state,
            replay_prohibited_step_ids=replay_prohibited,
        )
        self._record_resume(decision=decision, trace_id=trace_id)
        return decision

    def evaluate_retry(
        self,
        *,
        checkpoint_id: UUID,
        candidate: AttemptBasis,
    ) -> RetryDecision:
        """Apply blind-retry protection to attempt history after restart."""
        stored = self.store.load_checkpoint(checkpoint_id)
        return RetryGuard().evaluate(
            candidate,
            stored.envelope.attempt_records,
        )

    def _record_resume(
        self,
        *,
        decision: ResumeDecision,
        trace_id: UUID | None,
    ) -> None:
        if self.audit is None:
            return
        if trace_id is None:
            raise ValueError("audited resume requires trace_id")
        self.audit.ledger.append(
            kind=AuditEventKind.RESUME_DECISION,
            task_id=decision.task_id,
            trace_id=trace_id,
            subject_id=str(decision.decision_id),
            payload=stable_payload(decision),
        )
