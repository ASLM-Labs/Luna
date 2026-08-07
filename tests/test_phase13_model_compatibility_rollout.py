from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from luna.conformance.runtime_executor import _build_runtime, _policy, _request
from luna.modeling import (
    ControlledModelBackend,
    LocalOpenAICompatibleBackend,
    MessageRole,
    ModelBackendError,
    ModelBackendErrorCode,
    ModelCompatibilityProbe,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRolloutGate,
    ModelRolloutHealth,
    ModelRolloutPolicy,
    ModelRolloutStage,
    ModelToolCall,
    ModelUsage,
)
from luna.runtime import RuntimeStopReason


class CompatibleBackend:
    def __init__(self, backend_id: str = "phase13-compatible") -> None:
        self._backend_id = backend_id
        self.calls = 0

    @property
    def backend_id(self) -> str:
        return self._backend_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if request.available_tools:
            return ModelResponse(
                request_id=request.request_id,
                backend_id=self.backend_id,
                tool_calls=(
                    ModelToolCall(
                        call_id="compat-call",
                        tool_name="compat.echo",
                        arguments={"message": "LUNA_TOOL_OK"},
                    ),
                ),
                finish_reason=ModelFinishReason.TOOL_CALLS,
                usage=ModelUsage(input_tokens=20, output_tokens=5),
            )
        return ModelResponse(
            request_id=request.request_id,
            backend_id=self.backend_id,
            text="LUNA_COMPAT_OK",
            finish_reason=ModelFinishReason.STOP,
            usage=ModelUsage(input_tokens=10, output_tokens=3),
        )


class FailingBackend:
    def __init__(
        self,
        *,
        code: ModelBackendErrorCode,
        retryable: bool,
        backend_id: str = "phase13-failing",
    ) -> None:
        self._code = code
        self._retryable = retryable
        self._backend_id = backend_id
        self.calls = 0

    @property
    def backend_id(self) -> str:
        return self._backend_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        del request
        self.calls += 1
        raise ModelBackendError(
            code=self._code,
            backend_id=self.backend_id,
            safe_reason="synthetic model backend failure",
            retryable=self._retryable,
        )


def _compatible_report(backend: CompatibleBackend):
    report = ModelCompatibilityProbe().run(backend)
    assert report.eligible_for_rollout
    return report


def test_live_compatibility_probe_requires_text_tool_and_json_arguments() -> None:
    backend = CompatibleBackend()

    report = ModelCompatibilityProbe().run(backend)

    assert report.eligible_for_rollout
    assert report.required_passed
    assert len(report.results) == 4
    assert backend.calls == 2
    assert all(item.status.value == "PASS" for item in report.results)
    assert len(report.fingerprint()) == 64


def test_compatibility_fingerprint_is_stable_across_probe_ids_and_time() -> None:
    first = ModelCompatibilityProbe().run(CompatibleBackend())
    second = ModelCompatibilityProbe().run(CompatibleBackend())

    assert first.report_id != second.report_id
    assert first.fingerprint() == second.fingerprint()


def test_rollout_shadow_never_authorizes_authoritative_model_output() -> None:
    backend = CompatibleBackend()
    report = _compatible_report(backend)
    policy = ModelRolloutPolicy(
        backend_id=backend.backend_id,
        approved_compatibility_fingerprint=report.fingerprint(),
        stage=ModelRolloutStage.SHADOW,
    )

    decision = ModelRolloutGate().decide(
        task_id=uuid4(),
        policy=policy,
        compatibility=report,
        health=ModelRolloutHealth(),
    )

    assert not decision.authorized
    assert "SHADOW" in decision.reasons[0]


def test_canary_allocation_is_deterministic_per_task() -> None:
    backend = CompatibleBackend()
    report = _compatible_report(backend)
    policy = ModelRolloutPolicy(
        backend_id=backend.backend_id,
        approved_compatibility_fingerprint=report.fingerprint(),
        stage=ModelRolloutStage.CANARY,
        canary_percent=25,
    )
    task_id = uuid4()
    gate = ModelRolloutGate()

    first = gate.decide(
        task_id=task_id,
        policy=policy,
        compatibility=report,
        health=ModelRolloutHealth(),
    )
    second = gate.decide(
        task_id=task_id,
        policy=policy,
        compatibility=report,
        health=ModelRolloutHealth(),
    )

    assert first == second
    assert first.canary_bucket is not None
    assert first.authorized is (first.canary_bucket < 25)


def test_rollout_tripwire_blocks_even_active_backend() -> None:
    backend = CompatibleBackend()
    report = _compatible_report(backend)
    policy = ModelRolloutPolicy(
        backend_id=backend.backend_id,
        approved_compatibility_fingerprint=report.fingerprint(),
        stage=ModelRolloutStage.ACTIVE,
    )

    decision = ModelRolloutGate().decide(
        task_id=uuid4(),
        policy=policy,
        compatibility=report,
        health=ModelRolloutHealth(false_successes=1),
    )

    assert not decision.authorized
    assert any("false-success" in reason for reason in decision.reasons)


def test_controlled_backend_blocks_shadow_without_calling_inner_model() -> None:
    backend = CompatibleBackend()
    report = _compatible_report(backend)
    calls_before = backend.calls
    controlled = ControlledModelBackend(
        backend=backend,
        compatibility=report,
        policy=ModelRolloutPolicy(
            backend_id=backend.backend_id,
            approved_compatibility_fingerprint=report.fingerprint(),
            stage=ModelRolloutStage.SHADOW,
        ),
    )

    request = ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="hello"),),
    )

    with pytest.raises(ModelBackendError) as exc_info:
        controlled.generate(request)

    assert exc_info.value.code is ModelBackendErrorCode.ROLLOUT_BLOCKED
    assert backend.calls == calls_before


def test_controlled_backend_active_forwards_after_approved_compatibility() -> None:
    backend = CompatibleBackend()
    report = _compatible_report(backend)
    calls_before = backend.calls
    controlled = ControlledModelBackend(
        backend=backend,
        compatibility=report,
        policy=ModelRolloutPolicy(
            backend_id=backend.backend_id,
            approved_compatibility_fingerprint=report.fingerprint(),
            stage=ModelRolloutStage.ACTIVE,
        ),
    )
    request = ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="hello"),),
    )

    response = controlled.generate(request)

    assert response.request_id == request.request_id
    assert backend.calls == calls_before + 1


def test_retryable_model_backend_failure_suspends_runtime_without_blind_retry(
    tmp_path: Path,
) -> None:
    backend = FailingBackend(
        code=ModelBackendErrorCode.TIMEOUT,
        retryable=True,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    harness = _build_runtime(
        workspace=workspace,
        state_root=tmp_path / "state",
        backend=backend,
    )
    request = _request(
        workspace,
        allowed_tools=("filesystem.read_text",),
    )

    outcome = harness.runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.RESOURCE_SUSPENDED
    assert outcome.usage.model_calls == 1
    assert outcome.usage.tool_calls == 0
    assert backend.calls == 1
    assert any("never blindly retried" in reason for reason in outcome.reasons)


def test_rollout_block_is_runtime_block_not_fallback_or_tool_dispatch(tmp_path: Path) -> None:
    inner = CompatibleBackend()
    report = _compatible_report(inner)
    controlled = ControlledModelBackend(
        backend=inner,
        compatibility=report,
        policy=ModelRolloutPolicy(
            backend_id=inner.backend_id,
            approved_compatibility_fingerprint=report.fingerprint(),
            stage=ModelRolloutStage.SHADOW,
        ),
    )
    calls_before = inner.calls
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    harness = _build_runtime(
        workspace=workspace,
        state_root=tmp_path / "state",
        backend=controlled,
    )
    request = _request(
        workspace,
        allowed_tools=("filesystem.read_text",),
    )

    outcome = harness.runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.BLOCKED
    assert outcome.usage.model_calls == 1
    assert outcome.usage.tool_calls == 0
    assert inner.calls == calls_before
    assert any("ROLLOUT_BLOCKED" in reason for reason in outcome.reasons)


class RaisingTransport:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> dict[str, object]:
        del url, payload, timeout_seconds, max_response_bytes
        raise self.error


class StaticTransport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> dict[str, object]:
        del url, payload, timeout_seconds, max_response_bytes
        return self.payload


def test_local_adapter_maps_timeout_without_leaking_raw_exception() -> None:
    backend = LocalOpenAICompatibleBackend(
        endpoint="http://127.0.0.1:1234/v1/chat/completions",
        model="local-test",
        transport=RaisingTransport(TimeoutError("secret provider detail")),
    )
    request = ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="hello"),),
    )

    with pytest.raises(ModelBackendError) as exc_info:
        backend.generate(request)

    assert exc_info.value.code is ModelBackendErrorCode.TIMEOUT
    assert exc_info.value.retryable
    assert "secret provider detail" not in str(exc_info.value)


def test_local_adapter_maps_rate_limit_to_retryable_structured_error() -> None:
    http_error = HTTPError(
        url="http://127.0.0.1:1234/v1/chat/completions",
        code=429,
        msg="rate limited",
        hdrs=None,
        fp=None,
    )
    backend = LocalOpenAICompatibleBackend(
        endpoint="http://127.0.0.1:1234/v1/chat/completions",
        model="local-test",
        transport=RaisingTransport(http_error),
    )
    request = ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="hello"),),
    )

    with pytest.raises(ModelBackendError) as exc_info:
        backend.generate(request)

    assert exc_info.value.code is ModelBackendErrorCode.RATE_LIMITED
    assert exc_info.value.retryable


def test_local_adapter_maps_malformed_provider_payload_fail_closed() -> None:
    backend = LocalOpenAICompatibleBackend(
        endpoint="http://127.0.0.1:1234/v1/chat/completions",
        model="local-test",
        transport=StaticTransport({"choices": "not-a-list"}),
    )
    request = ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="hello"),),
    )

    with pytest.raises(ModelBackendError) as exc_info:
        backend.generate(request)

    assert exc_info.value.code is ModelBackendErrorCode.MALFORMED_RESPONSE
    assert not exc_info.value.retryable
