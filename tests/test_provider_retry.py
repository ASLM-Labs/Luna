from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from urllib.error import HTTPError
from uuid import uuid4

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
from luna.runtime import RuntimeBudget, RuntimeOutcome, RuntimeStopReason


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
        self.first_call = Event()

    @property
    def backend_id(self) -> str:
        return "t2-sequenced-provider"

    def generate(self, request: ModelRequest) -> ModelResponse:
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

    outcome, _ = _run_case(tmp_path, backend)

    assert backend.calls == 2
    assert outcome.usage.model_calls == 2
    assert outcome.usage.tool_calls == 1
    assert len(outcome.usage.provider_retry_evidence) == 1
    evidence = outcome.usage.provider_retry_evidence[0]
    assert evidence.basis_kind is ProviderRetryBasisKind.RETRY_AFTER
    assert evidence.delay_seconds == 0.01
    assert evidence.retry_reason is RetryReason.CHANGED_BASIS
    assert "evidence" in evidence.changed_dimensions


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
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert backend.calls == 1
    assert len(result) == 1
    assert result[0].stop_reason is RuntimeStopReason.CANCELLED
    assert result[0].usage.model_calls == 1
    assert result[0].usage.tool_calls == 0


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
