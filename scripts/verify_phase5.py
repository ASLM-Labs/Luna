"""Structural and behavioral verifier for Luna Phase 5."""

from __future__ import annotations

import json
import os
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.shell import SafeProcessError, validate_safe_argv
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
from luna.workspace import WorkspaceMutationError, WorkspaceMutator

ROOT = Path(__file__).resolve().parents[1]


def _contract(
    workspace: Path,
    *,
    write_allowed: bool = False,
    process_allowed: bool = False,
) -> TaskContract:
    return TaskContract(
        objective="Phase 5 verification",
        required_conditions=("Side effects remain scoped and reversible",),
        evidence_required=("ToolResult, Observation, snapshot and digest",),
        scope=TaskScope(
            workspace_root=str(workspace),
            allowed_paths=("sample.txt",),
            write_allowed=write_allowed,
            process_allowed=process_allowed,
        ),
        risk_level=RiskLevel.HIGH,
    )


def main() -> int:
    required_files = [
        ROOT / "src" / "luna" / "workspace" / "models.py",
        ROOT / "src" / "luna" / "workspace" / "store.py",
        ROOT / "src" / "luna" / "workspace" / "mutator.py",
        ROOT / "src" / "luna" / "workspace" / "tools.py",
        ROOT / "src" / "luna" / "shell" / "runner.py",
        ROOT / "src" / "luna" / "shell" / "tool.py",
    ]
    missing = [path.relative_to(ROOT).as_posix() for path in required_files if not path.is_file()]

    registry = build_phase5_registry()
    dispatcher = ToolDispatcher(registry)
    with TemporaryDirectory(prefix="luna-phase5-verify-") as directory:
        workspace = Path(directory)
        task = _contract(workspace, write_allowed=True, process_allowed=True)
        write = dispatcher.dispatch(
            request=ToolRequest(
                task_id=task.task_id,
                trace_id=uuid4(),
                tool_name="filesystem.write_text",
                arguments={
                    "path": "sample.txt",
                    "content": "phase5",
                    "create_if_missing": True,
                },
                expectation_id=uuid4(),
            ),
            task_contract=task,
            policy=ToolPolicy(
                allowed_tools=("filesystem.write_text",),
                autonomy_level=AutonomyLevel.BOUNDED,
                max_risk=RiskLevel.MEDIUM,
            ),
        )
        snapshot_value = write.result.metadata.get("snapshot_id")
        snapshot_id = UUID(snapshot_value) if isinstance(snapshot_value, str) else None
        write_snapshot_ok = (
            write.result.status is ToolResultStatus.SUCCESS
            and snapshot_id is not None
            and (workspace / "sample.txt").read_text(encoding="utf-8") == "phase5"
            and (workspace / ".luna" / "snapshots" / str(snapshot_id) / "manifest.json").is_file()
        )

        rollback_ok = False
        if snapshot_id is not None:
            rollback_request = ToolRequest(
                task_id=task.task_id,
                trace_id=uuid4(),
                tool_name="workspace.rollback",
                arguments={"snapshot_id": str(snapshot_id)},
                expectation_id=uuid4(),
            )
            rollback_basis = sha256(b"phase5-rollback-basis").hexdigest()
            rollback = dispatcher.dispatch(
                request=rollback_request,
                task_contract=task,
                policy=ToolPolicy(
                    allowed_tools=("workspace.rollback",),
                    owner_approved_tools=("workspace.rollback",),
                    exact_call_approvals=(
                        ExactCallApproval.bind(
                            rollback_request,
                            basis_fingerprint=rollback_basis,
                            approved_by="owner:phase5-verifier",
                            evidence_ref="phase5:verifier:rollback-approval",
                        ),
                    ),
                    autonomy_level=AutonomyLevel.OWNER_APPROVED,
                    max_risk=RiskLevel.HIGH,
                ),
                approval_basis_fingerprint=rollback_basis,
            )
            rollback_ok = (
                rollback.result.status is ToolResultStatus.SUCCESS
                and rollback.result.metadata.get("verified") is True
                and not (workspace / "sample.txt").exists()
            )

        stale_target = workspace / "sample.txt"
        stale_target.write_text("current", encoding="utf-8")
        stale = dispatcher.dispatch(
            request=ToolRequest(
                task_id=task.task_id,
                trace_id=uuid4(),
                tool_name="filesystem.write_text",
                arguments={
                    "path": "sample.txt",
                    "content": "should-not-write",
                    "expected_sha256": "0" * 64,
                    "create_if_missing": False,
                },
                expectation_id=uuid4(),
            ),
            task_contract=task,
            policy=ToolPolicy(
                allowed_tools=("filesystem.write_text",),
                autonomy_level=AutonomyLevel.BOUNDED,
                max_risk=RiskLevel.MEDIUM,
            ),
        )
        stale_precondition_ok = (
            stale.result.status is ToolResultStatus.BLOCKED
            and stale_target.read_text(encoding="utf-8") == "current"
        )

        argv = (sys.executable, "--version")
        process_request = ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="process.run_argv",
            arguments={"argv": list(argv)},
            working_directory=".",
            expectation_id=uuid4(),
        )
        process_basis = sha256(b"phase5-process-basis").hexdigest()
        process_policy = ToolPolicy(
            allowed_tools=("process.run_argv",),
            owner_approved_tools=("process.run_argv",),
            process_approvals=(ProcessApproval(argv=argv),),
            exact_call_approvals=(
                ExactCallApproval.bind(
                    process_request,
                    basis_fingerprint=process_basis,
                    approved_by="owner:phase5-verifier",
                    evidence_ref="phase5:verifier:process-approval",
                ),
            ),
            autonomy_level=AutonomyLevel.OWNER_APPROVED,
            max_risk=RiskLevel.HIGH,
        )
        process = dispatcher.dispatch(
            request=process_request,
            task_contract=task,
            policy=process_policy,
            approval_basis_fingerprint=process_basis,
        )
        exact_process_ok = (
            process.result.status is ToolResultStatus.SUCCESS
            and process.result.metadata.get("shell") is False
        )
        mismatch = dispatcher.dispatch(
            request=ToolRequest(
                task_id=task.task_id,
                trace_id=uuid4(),
                tool_name="process.run_argv",
                arguments={"argv": [sys.executable, "-V"]},
                working_directory=".",
                expectation_id=uuid4(),
            ),
            task_contract=task,
            policy=process_policy,
            approval_basis_fingerprint=process_basis,
        )
        exact_approval_ok = mismatch.result.status is ToolResultStatus.BLOCKED

        original = "stable"
        stale_target.write_text(original, encoding="utf-8")
        mutator = WorkspaceMutator(
            workspace_root=str(workspace),
            task_id=task.task_id,
            allowed_paths=("sample.txt",),
            protected_paths=(),
        )

        if os.name == "nt":

            def injected_bound_failure(
                *,
                observation: object,
                expected_content: bytes,
                source: object,
            ) -> int:
                del observation, expected_content, source
                raise WorkspaceMutationError("injected verification failure")

            mutator._verify_bound_publication = (  # type: ignore[method-assign]
                injected_bound_failure
            )
        else:

            def injected_failure(path: Path, expected_digest: str) -> None:
                del path, expected_digest
                raise WorkspaceMutationError("injected verification failure")

            mutator._verify_after_write = injected_failure  # type: ignore[method-assign]

        automatic_rollback_ok = False
        try:
            mutator.write_text(
                relative_path="sample.txt",
                content="unstable",
                expected_sha256=sha256(original.encode("utf-8")).hexdigest(),
                create_if_missing=False,
            )
        except WorkspaceMutationError as exc:
            automatic_rollback_ok = (
                exc.rollback is not None
                and exc.rollback.verified
                and stale_target.read_text(encoding="utf-8") == original
            )

    capabilities = {
        spec.name: {capability.value for capability in spec.capabilities}
        for spec in registry.specs()
    }
    shell_aliases_blocked = True
    for executable in ("bash.exe", "pwsh.exe", "sh.exe", "zsh.exe"):
        try:
            validate_safe_argv((executable, "--version"))
        except SafeProcessError:
            continue
        shell_aliases_blocked = False
        break

    inline_py_launcher_blocked = False
    try:
        validate_safe_argv(("py", "-c", "print('blocked')"))
    except SafeProcessError:
        inline_py_launcher_blocked = True

    checks = {
        "required_files_present": not missing,
        "seven_tools_registered": len(registry.specs()) == 7,
        "snapshot_before_write": write_snapshot_ok,
        "verified_explicit_rollback": rollback_ok,
        "stale_hash_blocks_write": stale_precondition_ok,
        "automatic_rollback_on_verification_failure": automatic_rollback_ok,
        "exact_argv_process_executes": exact_process_ok,
        "unapproved_argv_is_blocked": exact_approval_ok,
        "shell_parsing_disabled": process.result.metadata.get("shell") is False,
        "shell_aliases_disabled": shell_aliases_blocked,
        "inline_py_launcher_disabled": inline_py_launcher_blocked,
        "license_present": (ROOT / "LICENSE").is_file(),
        "network_tools_disabled": all("NETWORK" not in values for values in capabilities.values()),
        "file_delete_tool_absent": "filesystem.delete" not in capabilities,
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    result = {"phase": 5, "checks": checks, "missing_files": missing, "status": status}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
