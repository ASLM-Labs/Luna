from __future__ import annotations

import os
import sys
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.tools import (
    AutonomyLevel,
    ExactCallApproval,
    ProcessApproval,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    build_phase5_registry,
)


def _contract(
    root: Path,
    *,
    write_allowed: bool = False,
    process_allowed: bool = False,
) -> TaskContract:
    return TaskContract(
        objective="Phase 5 controlled execution test",
        required_conditions=("All side effects remain inside explicit scope",),
        evidence_required=("ToolResult and Observation",),
        scope=TaskScope(
            workspace_root=str(root),
            allowed_paths=("notes.txt",),
            write_allowed=write_allowed,
            process_allowed=process_allowed,
        ),
        risk_level=RiskLevel.HIGH,
    )


@pytest.mark.skipif(
    os.name != "nt",
    reason="explicit conditional undo is Windows-only",
)
def test_write_tool_creates_snapshot_and_explicit_rollback_removes_file(
    tmp_path: Path,
) -> None:
    registry = build_phase5_registry()
    dispatcher = ToolDispatcher(registry)
    contract = _contract(tmp_path, write_allowed=True)
    expectation_id = uuid4()
    write = dispatcher.dispatch(
        request=ToolRequest(
            task_id=contract.task_id,
            trace_id=uuid4(),
            tool_name="filesystem.write_text",
            arguments={
                "path": "notes.txt",
                "content": "phase5",
                "create_if_missing": True,
            },
            timeout_ms=15000,
            expectation_id=expectation_id,
        ),
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=("filesystem.write_text",),
            autonomy_level=AutonomyLevel.BOUNDED,
            max_risk=RiskLevel.MEDIUM,
        ),
    )

    assert write.result.status is ToolResultStatus.SUCCESS
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "phase5"
    snapshot_id = UUID(str(write.result.metadata["snapshot_id"]))

    rollback_request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="workspace.rollback",
        arguments={"snapshot_id": str(snapshot_id)},
        expectation_id=uuid4(),
    )
    rollback_basis = sha256(b"phase5-rollback-basis").hexdigest()
    rollback = dispatcher.dispatch(
        request=rollback_request,
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=("workspace.rollback",),
            owner_approved_tools=("workspace.rollback",),
            exact_call_approvals=(
                ExactCallApproval.bind(
                    rollback_request,
                    basis_fingerprint=rollback_basis,
                    approved_by="owner:test",
                    evidence_ref="phase5:test:rollback-approval",
                ),
            ),
            autonomy_level=AutonomyLevel.OWNER_APPROVED,
            max_risk=RiskLevel.HIGH,
        ),
        approval_basis_fingerprint=rollback_basis,
    )

    assert rollback.result.status is ToolResultStatus.SUCCESS
    assert not (tmp_path / "notes.txt").exists()
    assert rollback.result.metadata["verified"] is True


def test_write_tool_is_blocked_when_task_scope_is_read_only(tmp_path: Path) -> None:
    contract = _contract(tmp_path, write_allowed=False)
    outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=ToolRequest(
            task_id=contract.task_id,
            trace_id=uuid4(),
            tool_name="filesystem.write_text",
            arguments={
                "path": "notes.txt",
                "content": "blocked",
                "create_if_missing": True,
            },
            expectation_id=uuid4(),
        ),
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=("filesystem.write_text",),
            autonomy_level=AutonomyLevel.BOUNDED,
            max_risk=RiskLevel.MEDIUM,
        ),
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert "does not allow writes" in outcome.event.reason
    assert not (tmp_path / "notes.txt").exists()


def test_process_tool_requires_exact_argv_and_cwd_approval(tmp_path: Path) -> None:
    contract = _contract(tmp_path, process_allowed=True)
    argv = (sys.executable, "--version")
    dispatcher = ToolDispatcher(build_phase5_registry())
    approved_request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="process.run_argv",
        arguments={"argv": list(argv)},
        working_directory=".",
        expectation_id=uuid4(),
    )
    approval_basis = sha256(b"phase5-process-basis").hexdigest()
    policy = ToolPolicy(
        allowed_tools=("process.run_argv",),
        owner_approved_tools=("process.run_argv",),
        exact_call_approvals=(
            ExactCallApproval.bind(
                approved_request,
                basis_fingerprint=approval_basis,
                approved_by="owner:test",
                evidence_ref="phase5:test:process-approval",
            ),
        ),
        process_approvals=(
            ProcessApproval(
                argv=argv,
                working_directory=".",
                may_write_workspace=False,
            ),
        ),
        autonomy_level=AutonomyLevel.OWNER_APPROVED,
        max_risk=RiskLevel.HIGH,
    )

    approved = dispatcher.dispatch(
        request=approved_request,
        task_contract=contract,
        policy=policy,
        approval_basis_fingerprint=approval_basis,
    )
    unapproved = dispatcher.dispatch(
        request=ToolRequest(
            task_id=contract.task_id,
            trace_id=uuid4(),
            tool_name="process.run_argv",
            arguments={"argv": [sys.executable, "-V"]},
            working_directory=".",
            expectation_id=uuid4(),
        ),
        task_contract=contract,
        policy=policy,
        approval_basis_fingerprint=approval_basis,
    )

    assert approved.result.status is ToolResultStatus.SUCCESS
    assert "Python" in approved.result.stdout_excerpt + approved.result.stderr_excerpt
    assert approved.result.metadata["shell"] is False
    assert unapproved.result.status is ToolResultStatus.BLOCKED
    assert "exact argv" in unapproved.event.reason


def test_banned_shell_is_blocked_even_when_exactly_approved(tmp_path: Path) -> None:
    contract = _contract(tmp_path, process_allowed=True)
    argv = ("cmd.exe", "/c", "echo", "unsafe")
    request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="process.run_argv",
        arguments={"argv": list(argv)},
        working_directory=".",
        expectation_id=uuid4(),
    )
    approval_basis = sha256(b"phase5-banned-shell-basis").hexdigest()
    outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=request,
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=("process.run_argv",),
            owner_approved_tools=("process.run_argv",),
            exact_call_approvals=(
                ExactCallApproval.bind(
                    request,
                    basis_fingerprint=approval_basis,
                    approved_by="owner:test",
                    evidence_ref="phase5:test:banned-shell-approval",
                ),
            ),
            process_approvals=(ProcessApproval(argv=argv, may_write_workspace=False),),
            autonomy_level=AutonomyLevel.OWNER_APPROVED,
            max_risk=RiskLevel.HIGH,
        ),
        approval_basis_fingerprint=approval_basis,
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert "shell" in outcome.event.reason


def test_existing_write_hash_is_visible_in_tool_evidence(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("before", encoding="utf-8")
    before = sha256(b"before").hexdigest()
    contract = _contract(tmp_path, write_allowed=True)
    outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=ToolRequest(
            task_id=contract.task_id,
            trace_id=uuid4(),
            tool_name="filesystem.write_text",
            arguments={
                "path": "notes.txt",
                "content": "after",
                "expected_sha256": before,
                "create_if_missing": False,
            },
            expectation_id=uuid4(),
        ),
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=("filesystem.write_text",),
            autonomy_level=AutonomyLevel.BOUNDED,
            max_risk=RiskLevel.MEDIUM,
        ),
    )

    assert outcome.result.status is ToolResultStatus.SUCCESS
    assert outcome.result.metadata["before_sha256"] == before
    assert outcome.observation.changed_files == ("notes.txt",)


def test_tool_failure_reports_verified_automatic_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    from luna.workspace import (
        WorkspaceMutationError,
        WorkspaceMutator,
    )

    target = tmp_path / "notes.txt"
    target.write_text(
        "stable",
        encoding="utf-8",
    )
    before = sha256(b"stable").hexdigest()

    if os.name == "nt":

        def fail_bound_verification(
            *,
            observation: object,
            expected_content: bytes,
            source: object,
        ) -> int:
            del observation, expected_content, source

            raise WorkspaceMutationError(
                "injected verification failure"
            )

        monkeypatch.setattr(
            WorkspaceMutator,
            "_verify_bound_publication",
            staticmethod(fail_bound_verification),
        )

    else:

        def fail_verification(
            path: Path,
            expected_digest: str,
        ) -> None:
            del path, expected_digest

            raise WorkspaceMutationError(
                "injected verification failure"
            )

        monkeypatch.setattr(
            WorkspaceMutator,
            "_verify_after_write",
            staticmethod(fail_verification),
        )

    contract = _contract(
        tmp_path,
        write_allowed=True,
    )

    outcome = ToolDispatcher(
        build_phase5_registry()
    ).dispatch(
        request=ToolRequest(
            task_id=contract.task_id,
            trace_id=uuid4(),
            tool_name="filesystem.write_text",
            arguments={
                "path": "notes.txt",
                "content": "unstable",
                "expected_sha256": before,
                "create_if_missing": False,
            },
            expectation_id=uuid4(),
        ),
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=("filesystem.write_text",),
            autonomy_level=AutonomyLevel.BOUNDED,
            max_risk=RiskLevel.MEDIUM,
        ),
    )

    assert (
        outcome.result.status
        is ToolResultStatus.FAILURE
    )
    assert (
        outcome.result.metadata["rollback_verified"]
        is True
    )
    assert target.read_text(
        encoding="utf-8"
    ) == "stable"

def test_existing_write_mode_is_visible_in_tool_evidence(
    tmp_path: Path,
) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("before", encoding="utf-8")
    before = sha256(b"before").hexdigest()

    contract = _contract(tmp_path, write_allowed=True)

    outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=ToolRequest(
            task_id=contract.task_id,
            trace_id=uuid4(),
            tool_name="filesystem.write_text",
            arguments={
                "path": "notes.txt",
                "content": "after",
                "expected_sha256": before,
                "create_if_missing": False,
            },
            expectation_id=uuid4(),
        ),
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=("filesystem.write_text",),
            autonomy_level=AutonomyLevel.BOUNDED,
            max_risk=RiskLevel.MEDIUM,
        ),
    )

    assert outcome.result.status is ToolResultStatus.SUCCESS
    assert outcome.result.metadata["after_mode"] == (
        target.stat().st_mode & 0o7777
    )
