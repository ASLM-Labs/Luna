from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from luna.actions import (
    ActionKind,
    ActionTargetKind,
    build_phase12c_routes,
)
from luna.contracts import (
    RiskLevel,
    TaskContract,
    TaskScope,
)
from luna.tools import (
    AutonomyLevel,
    ExactCallApproval,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    build_phase5_registry,
)
from luna.workspace import (
    WorkspaceMutationError,
    WorkspaceMutator,
)
from luna.workspace.store import (
    WorkspaceSnapshotStore,
)


def _contract(root: Path) -> TaskContract:
    return TaskContract(
        objective="W3-E explicit safe-undo tool migration",
        required_conditions=(
            "Explicit undo never clobbers foreign state",
        ),
        evidence_required=(
            "Conditional safe-undo result",
        ),
        scope=TaskScope(
            workspace_root=str(root),
            allowed_paths=("notes.txt",),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
    )


def _mutator(
    root: Path,
    *,
    task_id: UUID,
) -> WorkspaceMutator:
    return WorkspaceMutator(
        workspace_root=str(root),
        task_id=task_id,
        allowed_paths=("notes.txt",),
        protected_paths=(),
    )


def _dispatch_undo(
    *,
    dispatcher: ToolDispatcher,
    contract: TaskContract,
    tool_name: str,
    snapshot_id: UUID,
):
    request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name=tool_name,
        arguments={
            "snapshot_id": str(snapshot_id),
        },
        expectation_id=uuid4(),
    )
    basis = sha256(
        f"w3-e:{tool_name}".encode()
    ).hexdigest()
    policy = ToolPolicy(
        allowed_tools=(tool_name,),
        owner_approved_tools=(tool_name,),
        exact_call_approvals=(
            ExactCallApproval.bind(
                request,
                basis_fingerprint=basis,
                approved_by="owner:w3-e-test",
                evidence_ref=(
                    "w3-e:explicit-undo:"
                    f"{tool_name}"
                ),
            ),
        ),
        autonomy_level=(
            AutonomyLevel.OWNER_APPROVED
        ),
        max_risk=RiskLevel.HIGH,
    )
    return dispatcher.dispatch(
        request=request,
        task_contract=contract,
        policy=policy,
        approval_basis_fingerprint=basis,
    )


def _forbid_legacy_restore(
    *_args: object,
    **_kwargs: object,
) -> object:
    raise AssertionError(
        "explicit undo must not call "
        "WorkspaceSnapshotStore.restore"
    )


def test_registry_and_selector_use_canonical_safe_undo() -> None:
    registry = build_phase5_registry()
    specs = {
        spec.name: spec
        for spec in registry.specs()
    }

    assert "workspace.safe_undo" in specs
    assert "workspace.rollback" in specs
    assert (
        specs["workspace.safe_undo"].risk_level
        is RiskLevel.HIGH
    )
    assert (
        specs["workspace.rollback"].risk_level
        is RiskLevel.HIGH
    )
    assert (
        specs["workspace.safe_undo"].capabilities
        == specs["workspace.rollback"].capabilities
    )

    undo_routes = tuple(
        route
        for route in build_phase12c_routes()
        if (
            ActionKind.ROLLBACK
            in route.action_kinds
            and ActionTargetKind.SNAPSHOT
            in route.target_kinds
        )
    )

    assert tuple(
        route.tool_name
        for route in undo_routes
    ) == (
        "workspace.safe_undo",
        "workspace.rollback",
    )

    assert tuple(
        route.tool_name
        for route in undo_routes
        if route.default_for_shape
    ) == (
        "workspace.safe_undo",
    )

    rollback_route = next(
        route
        for route in undo_routes
        if (
            route.tool_name
            == "workspace.rollback"
        )
    )

    assert (
        rollback_route.default_for_shape
        is False
    )


@pytest.mark.skipif(
    os.name != "nt",
    reason="strong explicit safe undo is Windows-only",
)
@pytest.mark.parametrize(
    "tool_name",
    (
        "workspace.safe_undo",
        "workspace.rollback",
    ),
)
def test_explicit_undo_tool_names_share_safe_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    contract = _contract(tmp_path)
    mutator = _mutator(
        tmp_path,
        task_id=contract.task_id,
    )
    mutation = mutator.write_text(
        relative_path="notes.txt",
        content="temporary",
        expected_sha256=None,
        create_if_missing=True,
    )

    monkeypatch.setattr(
        WorkspaceSnapshotStore,
        "restore",
        _forbid_legacy_restore,
    )

    outcome = _dispatch_undo(
        dispatcher=ToolDispatcher(
            build_phase5_registry()
        ),
        contract=contract,
        tool_name=tool_name,
        snapshot_id=(
            mutation.snapshot.snapshot_id
        ),
    )

    assert (
        outcome.result.status
        is ToolResultStatus.SUCCESS
    )
    assert outcome.result.metadata["verified"] is True
    assert (
        outcome.result.metadata["operation"]
        == "safe_undo"
    )
    assert not (tmp_path / "notes.txt").exists()


@pytest.mark.skipif(
    os.name != "nt",
    reason="strong explicit safe undo is Windows-only",
)
def test_mutator_rollback_is_safe_undo_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    mutator = _mutator(
        tmp_path,
        task_id=contract.task_id,
    )
    mutation = mutator.write_text(
        relative_path="notes.txt",
        content="temporary",
        expected_sha256=None,
        create_if_missing=True,
    )

    monkeypatch.setattr(
        WorkspaceSnapshotStore,
        "restore",
        _forbid_legacy_restore,
    )

    result = mutator.rollback(
        mutation.snapshot.snapshot_id
    )

    assert result.verified
    assert not (tmp_path / "notes.txt").exists()


@pytest.mark.skipif(
    os.name == "nt",
    reason="non-Windows fail-closed contract",
)
@pytest.mark.parametrize(
    "tool_name",
    (
        "workspace.safe_undo",
        "workspace.rollback",
    ),
)
def test_explicit_undo_tools_fail_closed_off_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    contract = _contract(tmp_path)
    mutator = _mutator(
        tmp_path,
        task_id=contract.task_id,
    )
    mutation = mutator.write_text(
        relative_path="notes.txt",
        content="temporary",
        expected_sha256=None,
        create_if_missing=True,
    )

    monkeypatch.setattr(
        WorkspaceSnapshotStore,
        "restore",
        _forbid_legacy_restore,
    )

    outcome = _dispatch_undo(
        dispatcher=ToolDispatcher(
            build_phase5_registry()
        ),
        contract=contract,
        tool_name=tool_name,
        snapshot_id=(
            mutation.snapshot.snapshot_id
        ),
    )

    assert (
        outcome.result.status
        is ToolResultStatus.BLOCKED
    )
    assert (
        outcome.result.error_class
        == "ToolExecutionDenied"
    )
    assert (
        tmp_path / "notes.txt"
    ).read_text(encoding="utf-8") == "temporary"


@pytest.mark.skipif(
    os.name == "nt",
    reason="non-Windows fail-closed contract",
)
def test_mutator_rollback_alias_fails_closed_off_windows(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    mutator = _mutator(
        tmp_path,
        task_id=contract.task_id,
    )
    mutation = mutator.write_text(
        relative_path="notes.txt",
        content="temporary",
        expected_sha256=None,
        create_if_missing=True,
    )

    with pytest.raises(
        WorkspaceMutationError,
        match="supported only on Windows",
    ):
        mutator.rollback(
            mutation.snapshot.snapshot_id
        )

    assert (
        tmp_path / "notes.txt"
    ).read_text(encoding="utf-8") == "temporary"
