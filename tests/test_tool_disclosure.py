from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

import pytest

from luna.conformance.runtime_executor import _build_runtime, _policy, _request
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.modeling import (
    ModelBackendError,
    ModelBackendErrorCode,
    ModelFinishReason,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from luna.runtime import RuntimeOutcome
from luna.tools import (
    ToolDisclosureDecisionStatus,
    ToolDisclosureDenialCode,
    ToolDisclosureProjector,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    build_phase4_registry,
)

_READ_TOOL = "filesystem.read_text"
_DEFERRED_TOOL = "filesystem.list_directory"
_WRITE_TOOL = "filesystem.write_text"


def _tool_names(request: ModelRequest) -> tuple[str, ...]:
    return tuple(spec.name for spec in request.available_tools)


class DisclosureBoundaryBackend:
    """Hold one in-flight request, then let T2 create the next safe boundary."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.first_request_started = Event()
        self.release_first_request = Event()

    @property
    def backend_id(self) -> str:
        return "t3-disclosure-boundary"

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            self.first_request_started.set()
            if not self.release_first_request.wait(timeout=3):
                raise AssertionError("test did not release the first model request")
            raise ModelBackendError(
                code=ModelBackendErrorCode.TIMEOUT,
                backend_id=self.backend_id,
                safe_reason="synthetic transient provider timeout",
                retryable=True,
            )
        return ModelResponse(
            request_id=request.request_id,
            backend_id=self.backend_id,
            text="Use the newly visible authorized directory tool.",
            tool_calls=(
                ModelToolCall(
                    call_id="t3-list-directory",
                    tool_name=_DEFERRED_TOOL,
                    arguments={"path": "."},
                ),
            ),
            finish_reason=ModelFinishReason.TOOL_CALLS,
        )


class RecordingBackend:
    def __init__(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
    ) -> None:
        self._tool_name = tool_name
        self._arguments = arguments
        self.requests: list[ModelRequest] = []

    @property
    def backend_id(self) -> str:
        return "t3-recording"

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            request_id=request.request_id,
            backend_id=self.backend_id,
            text="Propose one tool call.",
            tool_calls=(
                ModelToolCall(
                    call_id=f"t3-call-{len(self.requests)}",
                    tool_name=self._tool_name,
                    arguments=self._arguments,
                ),
            ),
            finish_reason=ModelFinishReason.TOOL_CALLS,
        )


def test_deferred_schema_appears_only_on_next_safe_model_request(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("before", encoding="utf-8")
    backend = DisclosureBoundaryBackend()
    harness = _build_runtime(
        workspace=workspace,
        state_root=tmp_path / "state",
        backend=backend,
    )
    request = _request(
        workspace,
        allowed_tools=(_READ_TOOL, _DEFERRED_TOOL),
        allowed_paths=(".", "note.txt"),
    )
    policy = _policy(allowed_tools=(_READ_TOOL, _DEFERRED_TOOL))
    harness.runtime.configure_tool_disclosure(
        task_id=request.task_id,
        deferred_tools=(_DEFERRED_TOOL,),
    )
    outcomes: list[RuntimeOutcome] = []
    worker = Thread(
        target=lambda: outcomes.append(
            harness.runtime.run(request=request, tool_policy=policy)
        )
    )

    worker.start()
    assert backend.first_request_started.wait(timeout=2)
    assert len(backend.requests) == 1
    first_request = backend.requests[0]
    assert _READ_TOOL in _tool_names(first_request)
    assert _DEFERRED_TOOL not in _tool_names(first_request)

    decision = harness.runtime.request_tool_disclosure(
        task_id=request.task_id,
        tool_names=(_DEFERRED_TOOL,),
    )
    assert decision.status is ToolDisclosureDecisionStatus.PENDING
    assert decision.accepted_pending_tools == (_DEFERRED_TOOL,)
    assert decision.authority_granted is False
    assert _DEFERRED_TOOL not in _tool_names(first_request)

    backend.release_first_request.set()
    worker.join(timeout=4)

    assert not worker.is_alive()
    assert len(outcomes) == 1
    assert len(backend.requests) == 2
    assert _DEFERRED_TOOL in _tool_names(backend.requests[1])
    assert _DEFERRED_TOOL not in _tool_names(first_request)
    assert outcomes[0].usage.model_calls == 2
    assert outcomes[0].usage.tool_calls == 1
    assert len(outcomes[0].usage.provider_retry_evidence) == 1


def test_disclosure_cannot_widen_policy_scope_risk_budget_or_approval(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("before", encoding="utf-8")
    backend = RecordingBackend(
        tool_name=_WRITE_TOOL,
        arguments={
            "path": "note.txt",
            "content": "after",
            "create_if_missing": True,
        },
    )
    harness = _build_runtime(
        workspace=workspace,
        state_root=tmp_path / "state",
        backend=backend,
    )
    request = _request(workspace, allowed_tools=(_READ_TOOL,))
    policy = _policy(allowed_tools=(_READ_TOOL,))
    request_before = request.model_dump(mode="json")
    policy_before = policy.model_dump(mode="json")
    harness.runtime.configure_tool_disclosure(
        task_id=request.task_id,
        deferred_tools=(_WRITE_TOOL,),
    )

    decision = harness.runtime.request_tool_disclosure(
        task_id=request.task_id,
        tool_names=(_WRITE_TOOL,),
    )
    outcome = harness.runtime.run(request=request, tool_policy=policy)

    assert decision.authority_granted is False
    assert _WRITE_TOOL not in _tool_names(backend.requests[0])
    assert outcome.usage.tool_calls == 0
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "before"
    assert request.model_dump(mode="json") == request_before
    assert policy.model_dump(mode="json") == policy_before
    state = harness.runtime.tool_disclosure_state(task_id=request.task_id)
    assert state is not None
    assert state.disclosed_tools == ()
    assert state.pending_tools == ()


def test_invalid_disclosure_request_is_structured_and_non_authoritative() -> None:
    task_id = uuid4()
    projector = ToolDisclosureProjector()
    state = projector.configure(
        task_id=task_id,
        deferred_tools=("core.echo",),
        registered_tools=("core.echo",),
    )

    decision = projector.request(
        state,
        tool_names=("missing.tool",),
        registered_tools=("core.echo",),
    )

    assert decision.status is ToolDisclosureDecisionStatus.REJECTED
    assert decision.authority_granted is False
    assert decision.accepted_pending_tools == ()
    assert decision.denials[0].code is ToolDisclosureDenialCode.UNKNOWN_TOOL
    assert decision.state == state

    with pytest.raises(ValueError, match="bounded tool count"):
        projector.request(
            state,
            tool_names=tuple("missing.tool" for _ in range(33)),
            registered_tools=("core.echo",),
        )
    assert state.pending_tools == ()


def test_reset_and_context_replacement_remove_stale_disclosure() -> None:
    projector = ToolDisclosureProjector()
    state = projector.configure(
        task_id=uuid4(),
        deferred_tools=("core.echo",),
        registered_tools=("core.echo",),
    )
    state, initial = projector.project(
        state,
        basis_fingerprint="a" * 64,
        registered_tools=("core.echo",),
        policy_allowed_tools=("core.echo",),
    )
    assert initial.visible_tools == ()

    decision = projector.request(
        state,
        tool_names=("core.echo",),
        registered_tools=("core.echo",),
    )
    state, disclosed = projector.project(
        decision.state,
        basis_fingerprint="a" * 64,
        registered_tools=("core.echo",),
        policy_allowed_tools=("core.echo",),
    )
    assert disclosed.visible_tools == ("core.echo",)

    state = projector.reset(state)
    state, reset_projection = projector.project(
        state,
        basis_fingerprint="a" * 64,
        registered_tools=("core.echo",),
        policy_allowed_tools=("core.echo",),
    )
    assert reset_projection.visible_tools == ()

    decision = projector.request(
        state,
        tool_names=("core.echo",),
        registered_tools=("core.echo",),
    )
    state, _ = projector.project(
        decision.state,
        basis_fingerprint="a" * 64,
        registered_tools=("core.echo",),
        policy_allowed_tools=("core.echo",),
    )
    state, replaced = projector.project(
        state,
        basis_fingerprint="b" * 64,
        registered_tools=("core.echo",),
        policy_allowed_tools=("core.echo",),
    )
    assert replaced.visible_tools == ()
    assert state.disclosed_tools == ()
    assert state.pending_tools == ()


def test_unavailable_tool_is_pruned_and_requires_redisclosure() -> None:
    registry = build_phase4_registry()
    projector = ToolDisclosureProjector()
    task_id = uuid4()
    state = projector.configure(
        task_id=task_id,
        deferred_tools=("core.echo",),
        registered_tools=tuple(spec.name for spec in registry.specs()),
    )
    decision = projector.request(
        state,
        tool_names=("core.echo",),
        registered_tools=tuple(spec.name for spec in registry.specs()),
    )
    state, visible = projector.project(
        decision.state,
        basis_fingerprint="c" * 64,
        registered_tools=tuple(spec.name for spec in registry.specs()),
        policy_allowed_tools=("core.echo",),
    )
    assert visible.visible_tools == ("core.echo",)

    removed = registry.unregister("core.echo")
    assert removed is not None
    state, unavailable = projector.project(
        state,
        basis_fingerprint="c" * 64,
        registered_tools=tuple(spec.name for spec in registry.specs()),
        policy_allowed_tools=("core.echo",),
    )
    assert unavailable.visible_tools == ()
    assert unavailable.unavailable_tools == ("core.echo",)
    assert state.disclosed_tools == ()

    task = TaskContract(
        task_id=task_id,
        objective="Verify unavailable disclosure safety",
        required_conditions=("Unavailable tool must not execute",),
        evidence_required=("Blocked ToolEvent",),
        scope=TaskScope(workspace_root="."),
        risk_level=RiskLevel.LOW,
    )
    blocked = ToolDispatcher(registry).dispatch(
        request=ToolRequest(
            task_id=task_id,
            trace_id=uuid4(),
            tool_name="core.echo",
            arguments={"message": "must not run"},
        ),
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("core.echo",)),
    )
    assert blocked.result.status is ToolResultStatus.BLOCKED

    registry.register(removed.spec, removed.handler)
    state, restored_but_hidden = projector.project(
        state,
        basis_fingerprint="c" * 64,
        registered_tools=tuple(spec.name for spec in registry.specs()),
        policy_allowed_tools=("core.echo",),
    )
    assert restored_but_hidden.visible_tools == ()

    decision = projector.request(
        state,
        tool_names=("core.echo",),
        registered_tools=tuple(spec.name for spec in registry.specs()),
    )
    _, redisclosed = projector.project(
        decision.state,
        basis_fingerprint="c" * 64,
        registered_tools=tuple(spec.name for spec in registry.specs()),
        policy_allowed_tools=("core.echo",),
    )
    assert redisclosed.visible_tools == ("core.echo",)


def test_runtime_without_disclosure_keeps_direct_execution_compatible(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("before", encoding="utf-8")
    backend = RecordingBackend(tool_name=_READ_TOOL, arguments={"path": "note.txt"})
    harness = _build_runtime(
        workspace=workspace,
        state_root=tmp_path / "state",
        backend=backend,
    )
    request = _request(workspace, allowed_tools=(_READ_TOOL,))

    outcome = harness.runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=(_READ_TOOL,)),
    )

    assert _tool_names(backend.requests[0]) == (_READ_TOOL,)
    assert outcome.usage.tool_calls == 1
    assert not outcome.usage.provider_retry_evidence
