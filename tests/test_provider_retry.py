from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Event, Thread
from urllib.error import HTTPError
from uuid import UUID, uuid4

import pytest

from luna.conformance.runtime_executor import _build_runtime, _policy, _request
from luna.modeling import (
    MessageRole,
    ModelBackendError,
    ModelBackendErrorCode,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    ModelUsage,
    ProviderRetryBasisKind,
    ProviderRetryCoordinator,
)
from luna.planning import RetryReason
from luna.runtime import (
    ProviderRetryScheduleStage,
    RuntimeBudget,
    RuntimeControlCommand,
    RuntimeJournalConflictError,
    RuntimeMode,
    RuntimeOutcome,
    RuntimeStopReason,
    SQLiteRuntimeJournal,
)


class SequencedProviderBackend:
    def __init__(
        self,
        failures: tuple[tuple[ModelBackendErrorCode, bool, float | None], ...],
        *,
        tool_name: str = "filesystem.read_text",
        arguments: dict[str, object] | None = None,
    ) -> None:
        self._failures = failures
        self._tool_name = tool_name
        self._arguments = arguments or {"path": "note.txt"}
        self.calls = 0
        self.requests: list[ModelRequest] = []
        self.first_call = Event()

    @property
    def backend_id(self) -> str:
        return "t2-sequenced-provider"

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        self.calls += 1
        self.first_call.set()
        if self.calls <= len(self._failures):
            code, retryable, retry_after = self._failures[self.calls - 1]
            raise ModelBackendError(
                code=code,
                backend_id=self.backend_id,
                safe_reason=f"synthetic {code.value} provider failure",
                retryable=retryable,
                retry_after_seconds=retry_after,
            )
        return ModelResponse(
            request_id=request.request_id,
            backend_id=self.backend_id,
            text="Execute exactly one authorized tool call.",
            tool_calls=(
                ModelToolCall(
                    call_id=f"provider-call-{self.calls}",
                    tool_name=self._tool_name,
                    arguments=self._arguments,
                ),
            ),
            finish_reason=ModelFinishReason.TOOL_CALLS,
            usage=ModelUsage(input_tokens=8, output_tokens=3),
        )


class RaisingTransport:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> dict[str, object]:
        del url, payload, timeout_seconds, max_response_bytes
        raise self._error


def _run_case(
    tmp_path: Path,
    backend: SequencedProviderBackend,
    *,
    runtime_budget: RuntimeBudget | None = None,
    write: bool = False,
) -> tuple[RuntimeOutcome, object]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("before", encoding="utf-8")
    tool_name = "filesystem.write_text" if write else "filesystem.read_text"
    harness = _build_runtime(
        workspace=workspace,
        state_root=tmp_path / "state",
        backend=backend,
    )
    outcome = harness.runtime.run(
        request=_request(
            workspace,
            allowed_tools=(tool_name,),
            write=write,
            runtime_budget=runtime_budget,
        ),
        tool_policy=_policy(allowed_tools=(tool_name,), write=write),
    )
    return outcome, harness


def test_rate_limit_retry_after_is_evidence_bound_then_succeeds(tmp_path: Path) -> None:
    backend = SequencedProviderBackend(
        ((ModelBackendErrorCode.RATE_LIMITED, True, 0.01),)
    )

    outcome, harness = _run_case(tmp_path, backend)

    assert backend.calls == 2
    assert outcome.usage.model_calls == 2
    assert outcome.usage.tool_calls == 1
    assert len(outcome.usage.provider_retry_evidence) == 1
    evidence = outcome.usage.provider_retry_evidence[0]
    assert evidence.basis_kind is ProviderRetryBasisKind.RETRY_AFTER
    assert evidence.delay_seconds == 0.01
    assert evidence.retry_reason is RetryReason.CHANGED_BASIS
    assert "evidence" in evidence.changed_dimensions

    schedules = (
        harness.runtime._deps.runtime_journal
        .list_provider_retry_schedules(outcome.task_id)
    )
    assert len(schedules) == 1

    schedule = schedules[0]
    assert schedule.stage is ProviderRetryScheduleStage.RESOLVED
    assert schedule.evidence == evidence
    assert schedule.started_model_request_id == backend.requests[1].request_id
    assert (
        schedule.started_model_request_fingerprint
        == backend.requests[1].fingerprint()
        == evidence.request_fingerprint
    )
    assert schedule.started_at is not None
    assert schedule.resolved_at is not None


def test_transient_timeout_uses_exponential_backoff_then_succeeds(tmp_path: Path) -> None:
    backend = SequencedProviderBackend(((ModelBackendErrorCode.TIMEOUT, True, None),))

    outcome, _ = _run_case(tmp_path, backend)

    assert backend.calls == 2
    assert outcome.usage.model_calls == 2
    assert outcome.usage.provider_retry_evidence[0].basis_kind is (
        ProviderRetryBasisKind.EXPONENTIAL_BACKOFF
    )


def test_transient_unavailable_retries_then_succeeds(tmp_path: Path) -> None:
    backend = SequencedProviderBackend(((ModelBackendErrorCode.UNAVAILABLE, True, None),))

    outcome, _ = _run_case(tmp_path, backend)

    assert backend.calls == 2
    assert outcome.usage.model_calls == 2
    assert outcome.usage.tool_calls == 1


def test_authentication_failure_never_retries_even_if_adapter_marks_retryable(
    tmp_path: Path,
) -> None:
    backend = SequencedProviderBackend(
        ((ModelBackendErrorCode.AUTHENTICATION, True, None),)
    )

    outcome, _ = _run_case(tmp_path, backend)

    assert backend.calls == 1
    assert outcome.usage.model_calls == 1
    assert outcome.usage.tool_calls == 0
    assert not outcome.usage.provider_retry_evidence
    assert outcome.stop_reason is RuntimeStopReason.BLOCKED
    assert any("semantic failure classification" in reason for reason in outcome.reasons)


def test_cancellation_during_backoff_stops_before_another_provider_call(
    tmp_path: Path,
) -> None:
    backend = SequencedProviderBackend(
        ((ModelBackendErrorCode.RATE_LIMITED, True, 5.0),)
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("before", encoding="utf-8")
    harness = _build_runtime(
        workspace=workspace,
        state_root=tmp_path / "state",
        backend=backend,
    )
    request = _request(workspace, allowed_tools=("filesystem.read_text",))
    result: list[RuntimeOutcome] = []

    worker = Thread(
        target=lambda: result.append(
            harness.runtime.run(
                request=request,
                tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
            )
        )
    )
    worker.start()
    assert backend.first_call.wait(timeout=1)
    harness.runtime.cancel(task_id=request.task_id, reason="cancel provider backoff")
    worker.join(timeout=10)

    assert not worker.is_alive()
    assert backend.calls == 1
    assert len(result) == 1
    assert result[0].stop_reason is RuntimeStopReason.CANCELLED
    assert result[0].usage.model_calls == 1
    assert result[0].usage.tool_calls == 0

    schedules = (
        harness.runtime._deps.runtime_journal
        .list_provider_retry_schedules(request.task_id)
    )
    assert len(schedules) == 1
    assert schedules[0].stage is ProviderRetryScheduleStage.CANCELLED
    assert schedules[0].started_model_request_id is None
    assert schedules[0].started_model_request_fingerprint is None


def test_max_attempts_exhaust_to_deterministic_provider_failure(tmp_path: Path) -> None:
    failure = (ModelBackendErrorCode.TIMEOUT, True, None)
    backend = SequencedProviderBackend((failure, failure, failure))

    outcome, _ = _run_case(tmp_path, backend)

    assert backend.calls == 3
    assert outcome.stop_reason is RuntimeStopReason.RESOURCE_SUSPENDED
    assert outcome.usage.model_calls == 3
    assert len(outcome.usage.provider_retry_evidence) == 2
    assert any("provider retry attempts exhausted: 3/3" in reason for reason in outcome.reasons)
    assert any("model_backend:TIMEOUT" in reason for reason in outcome.reasons)


def test_retry_attempts_consume_existing_model_call_budget(tmp_path: Path) -> None:
    failure = (ModelBackendErrorCode.TIMEOUT, True, None)
    backend = SequencedProviderBackend((failure, failure, failure))

    outcome, _ = _run_case(
        tmp_path,
        backend,
        runtime_budget=RuntimeBudget(max_model_calls=2),
    )

    assert backend.calls == 2
    assert outcome.stop_reason is RuntimeStopReason.BUDGET_EXHAUSTED
    assert outcome.usage.model_calls == 2
    assert len(outcome.usage.provider_retry_evidence) == 1
    assert any("model_calls" in reason for reason in outcome.reasons)


def test_retry_after_never_waits_past_runtime_elapsed_budget(tmp_path: Path) -> None:
    backend = SequencedProviderBackend(
        ((ModelBackendErrorCode.RATE_LIMITED, True, 5.0),)
    )

    outcome, _ = _run_case(
        tmp_path,
        backend,
        runtime_budget=RuntimeBudget(max_elapsed_seconds=1),
    )

    assert backend.calls == 1
    assert outcome.stop_reason is RuntimeStopReason.RESOURCE_SUSPENDED
    assert not outcome.usage.provider_retry_evidence
    assert any("remaining runtime elapsed budget" in reason for reason in outcome.reasons)


def test_same_provider_failure_evidence_cannot_authorize_same_basis_twice() -> None:
    coordinator = ProviderRetryCoordinator()
    task_id = uuid4()
    step_id = uuid4()
    failure_ref = uuid4()
    basis = coordinator.initial_basis(
        backend_id="same-basis-provider",
        request_fingerprint="a" * 64,
        scope_fingerprint="b" * 64,
        assumption_revision=0,
    )
    first = coordinator.plan(
        task_id=task_id,
        step_id=step_id,
        attempt_number=1,
        code=ModelBackendErrorCode.RATE_LIMITED,
        backend_id="same-basis-provider",
        request_fingerprint="a" * 64,
        retry_after_seconds=0.0,
        failure_ref=failure_ref,
        current_basis=basis,
        history=(),
    )
    assert first.evidence is not None

    repeated = coordinator.plan(
        task_id=task_id,
        step_id=step_id,
        attempt_number=2,
        code=ModelBackendErrorCode.RATE_LIMITED,
        backend_id="same-basis-provider",
        request_fingerprint="a" * 64,
        retry_after_seconds=0.0,
        failure_ref=failure_ref,
        current_basis=first.candidate_basis,
        history=(first.failed_attempt,),
    )

    assert repeated.evidence is None
    assert repeated.decision.reason is RetryReason.BLIND_RETRY_BLOCKED


def test_successful_side_effect_tool_call_is_not_provider_or_tool_replayed(
    tmp_path: Path,
) -> None:
    backend = SequencedProviderBackend(
        (),
        tool_name="filesystem.write_text",
        arguments={
            "path": "note.txt",
            "content": "after",
            "create_if_missing": True,
        },
    )

    outcome, harness = _run_case(tmp_path, backend, write=True)

    assert backend.calls == 1
    assert outcome.usage.model_calls == 1
    assert outcome.usage.tool_calls == 1
    assert not outcome.usage.provider_retry_evidence
    receipts = harness.runtime._deps.runtime_journal.list_for_task(outcome.task_id)
    assert len(receipts) == 1


def test_local_adapter_preserves_valid_retry_after_without_raw_header() -> None:
    from luna.modeling import LocalOpenAICompatibleBackend

    backend = LocalOpenAICompatibleBackend(
        endpoint="http://127.0.0.1:1234/v1/chat/completions",
        model="local-test",
        transport=RaisingTransport(
            HTTPError(
                url="http://127.0.0.1:1234/v1/chat/completions",
                code=429,
                msg="rate limited",
                hdrs={"Retry-After": "2"},
                fp=None,
            )
        ),
    )
    request = ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="hello"),),
    )

    try:
        backend.generate(request)
    except ModelBackendError as exc:
        assert exc.retry_after_seconds == 2.0
        assert "Retry-After" not in str(exc)
    else:
        raise AssertionError("429 transport must raise ModelBackendError")


def _journal_retry_plan(
    *,
    delay_seconds: float = 0.0,
) -> tuple[UUID, UUID, UUID, object]:
    coordinator = ProviderRetryCoordinator()
    task_id = uuid4()
    trace_id = uuid4()
    step_id = uuid4()
    basis = coordinator.initial_basis(
        backend_id="durable-provider",
        request_fingerprint="a" * 64,
        scope_fingerprint="b" * 64,
        assumption_revision=0,
    )
    plan = coordinator.plan(
        task_id=task_id,
        step_id=step_id,
        attempt_number=1,
        code=ModelBackendErrorCode.RATE_LIMITED,
        backend_id="durable-provider",
        request_fingerprint="a" * 64,
        retry_after_seconds=delay_seconds,
        failure_ref=uuid4(),
        current_basis=basis,
        history=(),
    )
    assert plan.evidence is not None
    return task_id, trace_id, step_id, plan


def test_provider_retry_schedule_is_durable_before_wait(
    tmp_path: Path,
) -> None:
    task_id, trace_id, step_id, plan = _journal_retry_plan(
        delay_seconds=60.0
    )
    journal_path = tmp_path / "journal.sqlite3"
    journal = SQLiteRuntimeJournal(journal_path)

    scheduled = journal.schedule_provider_retry(
        task_id=task_id,
        trace_id=trace_id,
        step_id=step_id,
        failed_attempt=plan.failed_attempt,
        candidate_basis=plan.candidate_basis,
        evidence=plan.evidence,
    )

    assert scheduled.stage is ProviderRetryScheduleStage.SCHEDULED
    assert scheduled.eligible_at > scheduled.scheduled_at
    assert journal.latest_recoverable_provider_retry(task_id) == scheduled

    repeated = journal.schedule_provider_retry(
        task_id=task_id,
        trace_id=trace_id,
        step_id=step_id,
        failed_attempt=plan.failed_attempt,
        candidate_basis=plan.candidate_basis,
        evidence=plan.evidence,
    )
    assert repeated == scheduled

    reopened = SQLiteRuntimeJournal(journal_path)
    assert reopened.schema_version() == 4
    assert reopened.list_provider_retry_schedules(task_id) == (scheduled,)
    assert reopened.latest_recoverable_provider_retry(task_id) == scheduled
    assert reopened.verify_integrity()


def test_provider_retry_schedule_start_and_resolution_are_fenced(
    tmp_path: Path,
) -> None:
    task_id, trace_id, step_id, plan = _journal_retry_plan()
    journal = SQLiteRuntimeJournal(tmp_path / "journal.sqlite3")

    scheduled = journal.schedule_provider_retry(
        task_id=task_id,
        trace_id=trace_id,
        step_id=step_id,
        failed_attempt=plan.failed_attempt,
        candidate_basis=plan.candidate_basis,
        evidence=plan.evidence,
    )

    started_request_id = uuid4()
    started = journal.mark_provider_retry_started(
        schedule_id=scheduled.schedule_id,
        model_request_id=started_request_id,
        model_request_fingerprint=plan.evidence.request_fingerprint,
    )
    assert started.stage is ProviderRetryScheduleStage.STARTED
    assert started.started_at is not None
    assert started.started_model_request_id == started_request_id
    assert (
        journal.mark_provider_retry_started(
            schedule_id=scheduled.schedule_id,
            model_request_id=started_request_id,
            model_request_fingerprint=plan.evidence.request_fingerprint,
        )
        == started
    )

    resolved = journal.resolve_provider_retry(scheduled.schedule_id)
    assert resolved.stage is ProviderRetryScheduleStage.RESOLVED
    assert resolved.resolved_at is not None
    assert journal.resolve_provider_retry(scheduled.schedule_id) == resolved
    assert journal.latest_recoverable_provider_retry(task_id) is None

    with pytest.raises(
        RuntimeJournalConflictError,
        match="cancelled only before it starts",
    ):
        journal.cancel_provider_retry(
            schedule_id=scheduled.schedule_id,
            reason="too late",
        )

    assert journal.verify_integrity()


def test_provider_retry_schedule_can_cancel_only_before_start(
    tmp_path: Path,
) -> None:
    task_id, trace_id, step_id, plan = _journal_retry_plan(
        delay_seconds=60.0
    )
    journal = SQLiteRuntimeJournal(tmp_path / "journal.sqlite3")

    scheduled = journal.schedule_provider_retry(
        task_id=task_id,
        trace_id=trace_id,
        step_id=step_id,
        failed_attempt=plan.failed_attempt,
        candidate_basis=plan.candidate_basis,
        evidence=plan.evidence,
    )

    cancelled = journal.cancel_provider_retry(
        schedule_id=scheduled.schedule_id,
        reason="owner cancelled provider backoff",
    )
    assert cancelled.stage is ProviderRetryScheduleStage.CANCELLED
    assert cancelled.cancelled_at is not None
    assert journal.latest_recoverable_provider_retry(task_id) is None

    assert (
        journal.cancel_provider_retry(
            schedule_id=scheduled.schedule_id,
            reason="owner cancelled provider backoff",
        )
        == cancelled
    )

    with pytest.raises(
        RuntimeJournalConflictError,
        match="start only from SCHEDULED",
    ):
        journal.mark_provider_retry_started(
            schedule_id=scheduled.schedule_id,
            model_request_id=uuid4(),
            model_request_fingerprint=plan.evidence.request_fingerprint,
        )


def test_provider_retry_schedule_row_binding_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    task_id, trace_id, step_id, plan = _journal_retry_plan(
        delay_seconds=60.0
    )
    journal_path = tmp_path / "journal.sqlite3"
    journal = SQLiteRuntimeJournal(journal_path)

    scheduled = journal.schedule_provider_retry(
        task_id=task_id,
        trace_id=trace_id,
        step_id=step_id,
        failed_attempt=plan.failed_attempt,
        candidate_basis=plan.candidate_basis,
        evidence=plan.evidence,
    )
    assert journal.verify_integrity()

    with sqlite3.connect(journal_path) as connection:
        connection.execute(
            """
            UPDATE provider_retry_schedules
            SET stage = 'STARTED'
            WHERE schedule_id = ?
            """,
            (str(scheduled.schedule_id),),
        )
        connection.commit()

    assert not journal.verify_integrity()


def test_runtime_journal_migrates_v3_to_v4_without_losing_control(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "journal.sqlite3"
    initial = SQLiteRuntimeJournal(journal_path)
    assert initial.schema_version() == 4

    task_id = uuid4()
    control = initial.request_control(
        task_id=task_id,
        command=RuntimeControlCommand.CANCEL,
        reason="preserve across v3 to v4 migration",
    )

    with sqlite3.connect(journal_path) as connection:
        connection.execute("DROP TABLE provider_retry_schedules")
        connection.execute(
            """
            DELETE FROM journal_schema
            WHERE version = 4
            """
        )
        connection.commit()

    reopened = SQLiteRuntimeJournal(journal_path)

    assert reopened.schema_version() == 4
    assert reopened.latest_control(task_id) == control
    assert reopened.list_provider_retry_schedules(task_id) == ()
    assert reopened.verify_integrity()


def test_provider_retry_start_binds_changed_safe_boundary_request_fingerprint(
    tmp_path: Path,
) -> None:
    task_id, trace_id, step_id, plan = _journal_retry_plan()
    journal = SQLiteRuntimeJournal(tmp_path / "journal.sqlite3")

    scheduled = journal.schedule_provider_retry(
        task_id=task_id,
        trace_id=trace_id,
        step_id=step_id,
        failed_attempt=plan.failed_attempt,
        candidate_basis=plan.candidate_basis,
        evidence=plan.evidence,
    )

    started_request_id = uuid4()
    started_request_fingerprint = "f" * 64

    assert (
        started_request_fingerprint
        != plan.evidence.request_fingerprint
    )

    started = journal.mark_provider_retry_started(
        schedule_id=scheduled.schedule_id,
        model_request_id=started_request_id,
        model_request_fingerprint=started_request_fingerprint,
    )

    assert started.stage is ProviderRetryScheduleStage.STARTED
    assert (
        started.evidence.request_fingerprint
        == plan.evidence.request_fingerprint
    )
    assert started.started_model_request_id == started_request_id
    assert (
        started.started_model_request_fingerprint
        == started_request_fingerprint
    )
    assert (
        journal.load_provider_retry_schedule(
            scheduled.schedule_id
        )
        == started
    )


class _SyntheticProviderCrash(BaseException):
    """Synthetic process-loss boundary that bypasses Exception handlers."""


class _CrashOnSecondProviderBackend(SequencedProviderBackend):
    """Crash after retry STARTED is durable and backend execution begins."""

    def generate(self, request: ModelRequest) -> ModelResponse:
        if self.calls == 1:
            self.requests.append(request)
            self.calls += 1
            raise _SyntheticProviderCrash(
                "synthetic crash inside started provider retry"
            )
        return super().generate(request)


def test_cold_resume_of_scheduled_provider_retry_never_replays_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("before", encoding="utf-8")

    state_root = tmp_path / "state"
    backend = SequencedProviderBackend(
        ((ModelBackendErrorCode.RATE_LIMITED, True, 5.0),)
    )
    harness = _build_runtime(
        workspace=workspace,
        state_root=state_root,
        backend=backend,
    )
    request = _request(
        workspace,
        allowed_tools=("filesystem.read_text",),
    )
    policy = _policy(
        allowed_tools=("filesystem.read_text",)
    )

    def crash_wait(
        delay_seconds: float,
        *,
        cancellation_probe: object,
    ) -> None:
        del delay_seconds, cancellation_probe
        raise _SyntheticProviderCrash(
            "synthetic crash after retry schedule persistence"
        )

    monkeypatch.setattr(
        harness.runtime._provider_retry,
        "wait",
        crash_wait,
    )

    with pytest.raises(
        _SyntheticProviderCrash,
        match="after retry schedule persistence",
    ):
        harness.runtime.run(
            request=request,
            tool_policy=policy,
        )

    scheduled = (
        harness.runtime._deps.runtime_journal
        .latest_recoverable_provider_retry(
            request.task_id
        )
    )
    assert scheduled is not None
    assert scheduled.stage is ProviderRetryScheduleStage.SCHEDULED
    assert scheduled.pre_retry_state is not None
    assert backend.calls == 1

    resume_backend = SequencedProviderBackend(())
    resumed_harness = _build_runtime(
        workspace=workspace,
        state_root=state_root,
        backend=resume_backend,
    )
    resume_request = _request(
        workspace,
        task_id=request.task_id,
        allowed_tools=("filesystem.read_text",),
        mode=RuntimeMode.RESUME,
    )

    resumed = resumed_harness.runtime.resume(
        request=resume_request,
        tool_policy=policy,
    )

    assert resumed.stop_reason is RuntimeStopReason.INTERRUPTED
    assert resumed.usage.model_calls == 0
    assert resumed.usage.tool_calls == 0
    assert resume_backend.calls == 0
    assert (
        "automatic provider replay is forbidden"
        in " ".join(resumed.reasons)
    )

    still_scheduled = (
        resumed_harness.runtime._deps.runtime_journal
        .latest_recoverable_provider_retry(
            request.task_id
        )
    )
    assert still_scheduled == scheduled


def test_cold_resume_of_started_provider_retry_never_replays_backend(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("before", encoding="utf-8")

    state_root = tmp_path / "state"
    backend = _CrashOnSecondProviderBackend(
        ((ModelBackendErrorCode.RATE_LIMITED, True, 0.0),)
    )
    harness = _build_runtime(
        workspace=workspace,
        state_root=state_root,
        backend=backend,
    )
    request = _request(
        workspace,
        allowed_tools=("filesystem.read_text",),
    )
    policy = _policy(
        allowed_tools=("filesystem.read_text",)
    )

    with pytest.raises(
        _SyntheticProviderCrash,
        match="inside started provider retry",
    ):
        harness.runtime.run(
            request=request,
            tool_policy=policy,
        )

    started = (
        harness.runtime._deps.runtime_journal
        .latest_recoverable_provider_retry(
            request.task_id
        )
    )
    assert started is not None
    assert started.stage is ProviderRetryScheduleStage.STARTED
    assert started.pre_retry_state is not None
    assert started.started_model_request_id is not None
    assert started.started_model_request_fingerprint is not None
    assert backend.calls == 2

    resume_backend = SequencedProviderBackend(())
    resumed_harness = _build_runtime(
        workspace=workspace,
        state_root=state_root,
        backend=resume_backend,
    )
    resume_request = _request(
        workspace,
        task_id=request.task_id,
        allowed_tools=("filesystem.read_text",),
        mode=RuntimeMode.RESUME,
    )

    first = resumed_harness.runtime.resume(
        request=resume_request,
        tool_policy=policy,
    )
    second = resumed_harness.runtime.resume(
        request=resume_request,
        tool_policy=policy,
    )

    for resumed in (first, second):
        assert resumed.stop_reason is RuntimeStopReason.INTERRUPTED
        assert resumed.usage.model_calls == 0
        assert resumed.usage.tool_calls == 0
        assert (
            "automatic provider replay is forbidden"
            in " ".join(resumed.reasons)
        )

    assert resume_backend.calls == 0

    still_started = (
        resumed_harness.runtime._deps.runtime_journal
        .latest_recoverable_provider_retry(
            request.task_id
        )
    )
    assert still_started == started
    assert still_started.stage is ProviderRetryScheduleStage.STARTED
