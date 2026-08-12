from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.tools import (
    AutonomyLevel,
    ProcessApproval,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    build_phase5_registry,
)


def _read_only_process_contract(root: Path) -> TaskContract:
    return TaskContract(
        objective="CD-01 process write-scope regression",
        required_conditions=("Process execution must respect write scope.",),
        evidence_required=("ToolResult", "ToolEvent", "Observation", "filesystem state"),
        scope=TaskScope(
            workspace_root=str(root),
            allowed_paths=("notes.txt",),
            write_allowed=False,
            process_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
    )


def test_exact_approved_process_cannot_mutate_write_disabled_workspace(
    tmp_path: Path,
) -> None:
    git_exe = shutil.which("git")
    assert git_exe is not None

    contract = _read_only_process_contract(tmp_path)
    argv = (git_exe, "init", "--quiet")
    outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=ToolRequest(
            task_id=contract.task_id,
            trace_id=uuid4(),
            tool_name="process.run_argv",
            arguments={"argv": list(argv)},
            working_directory=".",
            expectation_id=uuid4(),
        ),
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=("process.run_argv",),
            owner_approved_tools=("process.run_argv",),
            process_approvals=(ProcessApproval(argv=argv, working_directory="."),),
            autonomy_level=AutonomyLevel.OWNER_APPROVED,
            max_risk=RiskLevel.HIGH,
        ),
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert "write" in outcome.event.reason.lower()
    assert not (tmp_path / ".git").exists()
    assert outcome.observation.changed_files == ()

def test_explicit_read_only_process_can_run_in_write_disabled_workspace(
    tmp_path: Path,
) -> None:
    git_exe = shutil.which("git")
    assert git_exe is not None

    contract = _read_only_process_contract(tmp_path)
    argv = (git_exe, "--version")

    outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=ToolRequest(
            task_id=contract.task_id,
            trace_id=uuid4(),
            tool_name="process.run_argv",
            arguments={"argv": list(argv)},
            working_directory=".",
            expectation_id=uuid4(),
        ),
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=("process.run_argv",),
            owner_approved_tools=("process.run_argv",),
            process_approvals=(
                ProcessApproval(
                    argv=argv,
                    working_directory=".",
                    may_write_workspace=False,
                ),
            ),
            autonomy_level=AutonomyLevel.OWNER_APPROVED,
            max_risk=RiskLevel.HIGH,
        ),
    )

    assert outcome.result.status is ToolResultStatus.SUCCESS
    assert not (tmp_path / ".git").exists()
