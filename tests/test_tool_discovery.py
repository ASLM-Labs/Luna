from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

import pytest

from luna.conformance.runtime_executor import _build_runtime, _policy, _request
from luna.modeling import (
    ModelBackendError,
    ModelBackendErrorCode,
    ModelFinishReason,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    ScriptedTestBackend,
)
from luna.runtime import RuntimeOutcome
from luna.tools import (
    ToolCapability,
    ToolDisclosureDecisionStatus,
    ToolDisclosureDenialCode,
    ToolDisclosureProjector,
    ToolDiscoveryIndex,
    ToolSpec,
    build_phase4_registry,
)


def _spec(
    name: str,
    description: str,
    *,
    capabilities: tuple[ToolCapability, ...] = (),
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        capabilities=capabilities,
    )


def _names(result) -> tuple[str, ...]:
    return tuple(candidate.tool_name for candidate in result.candidates)


def test_discovery_ranking_is_deterministic_and_name_first() -> None:
    index = ToolDiscoveryIndex()
    specs = (
        _spec(
            "filesystem.read_text",
            "Read text from a file",
            capabilities=(ToolCapability.READ,),
        ),
        _spec(
            "filesystem.read_lines",
            "Read selected lines",
            capabilities=(ToolCapability.READ,),
        ),
        _spec(
            "workspace.inspect",
            "Inspect and read workspace text",
            capabilities=(ToolCapability.READ,),
        ),
    )

    exact = index.search(
        task_id=uuid4(),
        query="filesystem.read_text",
        disclosure_state_revision=0,
        deferred_tools=tuple(spec.name for spec in specs),
        specs=specs,
        policy_allowed_tools=tuple(spec.name for spec in specs),
    )
    assert _names(exact)[0] == "filesystem.read_text"

    tied = index.search(
        task_id=uuid4(),
        query="read",
        disclosure_state_revision=0,
        deferred_tools=tuple(spec.name for spec in specs),
        specs=specs,
        policy_allowed_tools=tuple(spec.name for spec in specs),
    )
    assert _names(tied)[:2] == (
        "filesystem.read_lines",
        "filesystem.read_text",
    )


def test_discovery_filters_to_deferred_registered_and_policy_allowed() -> None:
    index = ToolDiscoveryIndex()
    specs = (
        _spec("filesystem.read_text", "Read text from a file"),
        _spec("filesystem.list_directory", "List directory entries"),
        _spec("filesystem.write_text", "Write text to a file"),
    )
    result = index.search(
        task_id=uuid4(),
        query="file directory write read",
        disclosure_state_revision=2,
        deferred_tools=(
            "filesystem.list_directory",
            "filesystem.write_text",
            "missing.tool",
        ),
        specs=specs,
        policy_allowed_tools=("filesystem.list_directory",),
        limit=16,
    )

    assert _names(result) == ("filesystem.list_directory",)
    assert result.disclosure_state_revision == 2
    assert result.authority_granted is False


def test_discovery_candidate_is_metadata_only_and_non_authoritative() -> None:
    result = ToolDiscoveryIndex().search(
        task_id=uuid4(),
        query="read text",
        disclosure_state_revision=0,
        deferred_tools=("filesystem.read_text",),
        specs=(
            ToolSpec(
                name="filesystem.read_text",
                description="Read text from a file",
                capabilities=(ToolCapability.READ,),
                argument_schema={},
            ),
        ),
        policy_allowed_tools=("filesystem.read_text",),
    )

    candidate = result.candidates[0]
    payload = candidate.model_dump(mode="json")
    assert "argument_schema" not in payload
    assert "handler" not in payload
    assert candidate.authority_granted is False
    assert result.authority_granted is False


def test_discovery_rejects_unbounded_or_catalog_fallback_queries() -> None:
    index = ToolDiscoveryIndex()
    kwargs = dict(
        task_id=uuid4(),
        disclosure_state_revision=0,
        deferred_tools=("core.echo",),
        specs=(_spec("core.echo", "Echo one message"),),
        policy_allowed_tools=("core.echo",),
    )
    with pytest.raises(ValueError, match="must not be blank"):
        index.search(query="   ", **kwargs)
    with pytest.raises(ValueError, match="512"):
        index.search(query="x" * 513, **kwargs)
    with pytest.raises(ValueError, match="between 1 and 16"):
        index.search(query="echo", limit=17, **kwargs)

    no_match = index.search(query="unrelated", **kwargs)
    assert no_match.candidates == ()


def test_stale_discovery_candidate_must_pass_current_disclosure_state() -> None:
    registry = build_phase4_registry()
    projector = ToolDisclosureProjector()
    task_id = uuid4()
    state = projector.configure(
        task_id=task_id,
        deferred_tools=("core.echo",),
        registered_tools=tuple(spec.name for spec in registry.specs()),
    )
    result = ToolDiscoveryIndex().search(
        task_id=task_id,
        query="echo",
        disclosure_state_revision=state.revision,
        deferred_tools=state.deferred_tools,
        specs=registry.specs(),
        policy_allowed_tools=("core.echo",),
    )
    assert _names(result) == ("core.echo",)

    removed = registry.unregister("core.echo")
    assert removed is not None
    decision = projector.request(
        state,
        tool_names=("core.echo",),
        registered_tools=tuple(spec.name for spec in registry.specs()),
    )
    assert decision.status is ToolDisclosureDecisionStatus.REJECTED
    assert decision.denials[0].code is ToolDisclosureDenialCode.UNAVAILABLE

    registry.register(removed.spec, removed.handler)
    rediscovered = ToolDiscoveryIndex().search(
        task_id=task_id,
        query="echo",
        disclosure_state_revision=state.revision,
        deferred_tools=state.deferred_tools,
        specs=registry.specs(),
        policy_allowed_tools=("core.echo",),
    )
    assert _names(rediscovered) == ("core.echo",)

    _, hidden = projector.project(
        state,
        basis_fingerprint="a" * 64,
        registered_tools=tuple(spec.name for spec in registry.specs()),
        policy_allowed_tools=("core.echo",),
    )
    assert hidden.visible_tools == ()


def test_runtime_discovery_does_not_mutate_disclosure_or_policy(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    harness = _build_runtime(
        workspace=workspace,
        state_root=tmp_path / "state",
        backend=ScriptedTestBackend(turns=()),
    )
    request = _request(
        workspace,
        allowed_tools=("filesystem.read_text", "filesystem.list_directory"),
    )
    policy = _policy(
        allowed_tools=("filesystem.read_text", "filesystem.list_directory"),
    )
    harness.runtime.configure_tool_disclosure(
        task_id=request.task_id,
        deferred_tools=("filesystem.list_directory",),
    )
    state_before = harness.runtime.tool_disclosure_state(task_id=request.task_id)
    policy_before = policy.model_dump(mode="json")

    result = harness.runtime.discover_deferred_tools(
        task_id=request.task_id,
        query="list directory",
        policy=policy,
    )

    state_after = harness.runtime.tool_disclosure_state(task_id=request.task_id)
    assert _names(result) == ("filesystem.list_directory",)
    assert state_after == state_before
    assert policy.model_dump(mode="json") == policy_before

    decision = harness.runtime.request_tool_disclosure(
        task_id=request.task_id,
        tool_names=(result.candidates[0].tool_name,),
    )
    assert decision.status is ToolDisclosureDecisionStatus.PENDING
    assert decision.authority_granted is False


class _BoundaryBackend:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.first_started = Event()
        self.release_first = Event()

    @property
    def backend_id(self) -> str:
        return "tool-discovery-boundary"

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            self.first_started.set()
            if not self.release_first.wait(timeout=3):
                raise AssertionError("test did not release first model request")
            raise ModelBackendError(
                code=ModelBackendErrorCode.TIMEOUT,
                backend_id=self.backend_id,
                safe_reason="synthetic transient timeout",
                retryable=True,
            )
        return ModelResponse(
            request_id=request.request_id,
            backend_id=self.backend_id,
            text="Use the disclosed directory tool.",
            tool_calls=(
                ModelToolCall(
                    call_id="tool-discovery-list",
                    tool_name="filesystem.list_directory",
                    arguments={"path": "."},
                ),
            ),
            finish_reason=ModelFinishReason.TOOL_CALLS,
        )


def test_discovery_requires_explicit_disclosure_and_next_safe_boundary(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backend = _BoundaryBackend()
    harness = _build_runtime(
        workspace=workspace,
        state_root=tmp_path / "state",
        backend=backend,
    )
    request = _request(
        workspace,
        allowed_tools=("filesystem.read_text", "filesystem.list_directory"),
        allowed_paths=(".",),
    )
    policy = _policy(
        allowed_tools=("filesystem.read_text", "filesystem.list_directory"),
    )
    harness.runtime.configure_tool_disclosure(
        task_id=request.task_id,
        deferred_tools=("filesystem.list_directory",),
    )

    outcomes: list[RuntimeOutcome] = []
    worker = Thread(
        target=lambda: outcomes.append(
            harness.runtime.run(request=request, tool_policy=policy)
        )
    )
    worker.start()
    assert backend.first_started.wait(timeout=2)
    assert len(backend.requests) == 1
    first_request = backend.requests[0]
    first_names = tuple(spec.name for spec in first_request.available_tools)
    assert "filesystem.list_directory" not in first_names

    result = harness.runtime.discover_deferred_tools(
        task_id=request.task_id,
        query="list directory",
        policy=policy,
    )
    assert _names(result) == ("filesystem.list_directory",)
    assert "filesystem.list_directory" not in tuple(
        spec.name for spec in first_request.available_tools
    )

    decision = harness.runtime.request_tool_disclosure(
        task_id=request.task_id,
        tool_names=("filesystem.list_directory",),
    )
    assert decision.status is ToolDisclosureDecisionStatus.PENDING

    backend.release_first.set()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert len(outcomes) == 1
    assert len(backend.requests) == 2
    second_names = tuple(spec.name for spec in backend.requests[1].available_tools)
    assert "filesystem.list_directory" in second_names
    assert outcomes[0].usage.tool_calls == 1
