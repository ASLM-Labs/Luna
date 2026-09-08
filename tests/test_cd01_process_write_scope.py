from __future__ import annotations

import shutil
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

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

    request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="process.run_argv",
        arguments={"argv": list(argv)},
        working_directory=".",
        expectation_id=uuid4(),
    )
    approval_basis = sha256(b"cd01-read-only-process-basis").hexdigest()
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
                    evidence_ref="cd01:test:read-only-process-approval",
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
        ),
        approval_basis_fingerprint=approval_basis,
    )

    assert outcome.result.status is ToolResultStatus.SUCCESS
    assert "process_effects:READ" in outcome.event.policy_checks
    assert "process_effect_rule:git:version" in outcome.event.policy_checks
    assert "process_effect:PASS" in outcome.event.policy_checks
    assert not (tmp_path / ".git").exists()


def _effect_contract(
    root: Path,
    *,
    write_allowed: bool,
    network_allowed: bool,
) -> TaskContract:
    return TaskContract(
        objective="Process effect classifier policy integration",
        required_conditions=("Inferred process effects must strengthen scope.",),
        evidence_required=("ToolResult", "ToolEvent", "Observation"),
        scope=TaskScope(
            workspace_root=str(root),
            allowed_paths=("notes.txt",),
            write_allowed=write_allowed,
            network_allowed=network_allowed,
            process_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
    )


def _exact_process_policy(
    request: ToolRequest,
    argv: tuple[str, ...],
    *,
    may_write_workspace: bool,
    basis: str,
) -> ToolPolicy:
    return ToolPolicy(
        allowed_tools=("process.run_argv",),
        owner_approved_tools=("process.run_argv",),
        exact_call_approvals=(
            ExactCallApproval.bind(
                request,
                basis_fingerprint=basis,
                approved_by="owner:test",
                evidence_ref="process-effect:test:exact-approval",
            ),
        ),
        process_approvals=(
            ProcessApproval(
                argv=argv,
                working_directory=".",
                may_write_workspace=may_write_workspace,
            ),
        ),
        autonomy_level=AutonomyLevel.OWNER_APPROVED,
        max_risk=RiskLevel.HIGH,
    )


def test_inferred_write_blocks_understated_process_approval(
    tmp_path: Path,
) -> None:
    git_exe = shutil.which("git")
    assert git_exe is not None

    contract = _effect_contract(
        tmp_path,
        write_allowed=False,
        network_allowed=False,
    )
    argv = (git_exe, "init", "--quiet")
    request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="process.run_argv",
        arguments={"argv": list(argv)},
        working_directory=".",
        expectation_id=uuid4(),
    )
    basis = sha256(b"process-effect-inferred-write").hexdigest()

    outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=request,
        task_contract=contract,
        policy=_exact_process_policy(
            request,
            argv,
            may_write_workspace=False,
            basis=basis,
        ),
        approval_basis_fingerprint=basis,
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert "write" in outcome.event.reason.lower()
    assert "process_effects:WRITE" in outcome.event.policy_checks
    assert not (tmp_path / ".git").exists()


def test_declared_write_requirement_survives_inferred_read(
    tmp_path: Path,
) -> None:
    git_exe = shutil.which("git")
    assert git_exe is not None

    contract = _effect_contract(
        tmp_path,
        write_allowed=False,
        network_allowed=False,
    )
    argv = (git_exe, "--version")
    request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="process.run_argv",
        arguments={"argv": list(argv)},
        working_directory=".",
        expectation_id=uuid4(),
    )
    basis = sha256(b"process-effect-declared-write").hexdigest()

    outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=request,
        task_contract=contract,
        policy=_exact_process_policy(
            request,
            argv,
            may_write_workspace=True,
            basis=basis,
        ),
        approval_basis_fingerprint=basis,
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert "write" in outcome.event.reason.lower()
    assert "process_effects:READ" in outcome.event.policy_checks


def test_inferred_network_requires_network_scope(tmp_path: Path) -> None:
    contract = _effect_contract(
        tmp_path,
        write_allowed=False,
        network_allowed=False,
    )
    argv = ("curl", "https://example.invalid/")
    request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="process.run_argv",
        arguments={"argv": list(argv)},
        working_directory=".",
        expectation_id=uuid4(),
    )
    basis = sha256(b"process-effect-network").hexdigest()

    outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=request,
        task_contract=contract,
        policy=_exact_process_policy(
            request,
            argv,
            may_write_workspace=False,
            basis=basis,
        ),
        approval_basis_fingerprint=basis,
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert "network" in outcome.event.reason.lower()
    assert "process_effects:NETWORK" in outcome.event.policy_checks


def test_opaque_executable_requires_network_scope(tmp_path: Path) -> None:
    contract = _effect_contract(
        tmp_path,
        write_allowed=True,
        network_allowed=False,
    )
    argv = ("opaque-tool", "--arg")
    request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="process.run_argv",
        arguments={"argv": list(argv)},
        working_directory=".",
        expectation_id=uuid4(),
    )
    basis = sha256(b"process-effect-opaque").hexdigest()

    outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=request,
        task_contract=contract,
        policy=_exact_process_policy(
            request,
            argv,
            may_write_workspace=True,
            basis=basis,
        ),
        approval_basis_fingerprint=basis,
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert "network" in outcome.event.reason.lower()
    assert "process_effects:WRITE,NETWORK" in outcome.event.policy_checks


def test_git_clone_requires_write_and_network_scope(tmp_path: Path) -> None:
    argv = ("git", "clone", "https://example.invalid/repo.git")

    write_blocked_contract = _effect_contract(
        tmp_path,
        write_allowed=False,
        network_allowed=True,
    )
    write_request = ToolRequest(
        task_id=write_blocked_contract.task_id,
        trace_id=uuid4(),
        tool_name="process.run_argv",
        arguments={"argv": list(argv)},
        working_directory=".",
        expectation_id=uuid4(),
    )
    write_basis = sha256(b"process-effect-clone-write").hexdigest()
    write_outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=write_request,
        task_contract=write_blocked_contract,
        policy=_exact_process_policy(
            write_request,
            argv,
            may_write_workspace=False,
            basis=write_basis,
        ),
        approval_basis_fingerprint=write_basis,
    )

    assert write_outcome.result.status is ToolResultStatus.BLOCKED
    assert "write" in write_outcome.event.reason.lower()

    network_blocked_contract = _effect_contract(
        tmp_path,
        write_allowed=True,
        network_allowed=False,
    )
    network_request = ToolRequest(
        task_id=network_blocked_contract.task_id,
        trace_id=uuid4(),
        tool_name="process.run_argv",
        arguments={"argv": list(argv)},
        working_directory=".",
        expectation_id=uuid4(),
    )
    network_basis = sha256(b"process-effect-clone-network").hexdigest()
    network_outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=network_request,
        task_contract=network_blocked_contract,
        policy=_exact_process_policy(
            network_request,
            argv,
            may_write_workspace=True,
            basis=network_basis,
        ),
        approval_basis_fingerprint=network_basis,
    )

    assert network_outcome.result.status is ToolResultStatus.BLOCKED
    assert "network" in network_outcome.event.reason.lower()
    assert "process_effects:WRITE,NETWORK" in network_outcome.event.policy_checks


@pytest.mark.parametrize(
    ("argv", "reason_fragment", "effect_check"),
    (
        (
            ("winget", "install", "pkg"),
            "install",
            "process_effects:INSTALL",
        ),
        (
            ("shutdown", "/s"),
            "destructive",
            "process_effects:DESTRUCTIVE",
        ),
    ),
)
def test_unsupported_process_effects_block_even_with_broad_scope(
    tmp_path: Path,
    argv: tuple[str, ...],
    reason_fragment: str,
    effect_check: str,
) -> None:
    contract = _effect_contract(
        tmp_path,
        write_allowed=True,
        network_allowed=True,
    )
    request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="process.run_argv",
        arguments={"argv": list(argv)},
        working_directory=".",
        expectation_id=uuid4(),
    )
    basis = sha256(("process-effect-" + reason_fragment).encode()).hexdigest()

    outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=request,
        task_contract=contract,
        policy=_exact_process_policy(
            request,
            argv,
            may_write_workspace=True,
            basis=basis,
        ),
        approval_basis_fingerprint=basis,
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert reason_fragment in outcome.event.reason.lower()
    assert effect_check in outcome.event.policy_checks
