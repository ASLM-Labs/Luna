from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from luna.applied_changes.models import (
    AppliedChangeOperation,
    AppliedChangeState,
)
from luna.contracts import (
    RiskLevel,
    TaskContract,
    TaskScope,
)
from luna.tools.dispatcher import (
    _lifecycle_failure_output,
)
from luna.tools.lifecycle import (
    ExecutionLifecycleController,
    ExecutionStop,
    ExecutionStopKind,
)
from luna.tools.registry import (
    ToolExecutionContext,
)
from luna.workspace.mutator import (
    WorkspaceMutationError,
    WorkspaceMutator,
)
from luna.workspace.tools import (
    ReplaceTextTool,
    WriteTextTool,
    _mutator,
)


def _digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def _contract(
    root: Path,
) -> TaskContract:
    return TaskContract(
        objective=(
            "Exercise typed workspace "
            "applied-change handoff."
        ),
        required_conditions=(
            "Mutation authority remains unchanged.",
        ),
        evidence_required=(
            "Typed applied-change candidate.",
        ),
        scope=TaskScope(
            workspace_root=str(root),
            allowed_paths=(
                "src",
                "new.txt",
            ),
        ),
        risk_level=RiskLevel.LOW,
    )


def _context(
    contract: TaskContract,
) -> ToolExecutionContext:
    controller = (
        ExecutionLifecycleController.start(
            execution_id=uuid4(),
            timeout_ms=1000,
        )
    )

    return ToolExecutionContext(
        task_contract=contract,
        timeout_ms=1000,
        max_output_chars=16000,
        working_directory=None,
        lifecycle=controller.lifecycle,
    )


def test_workspace_mutator_handoff_preserves_execution_identity(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    request_id = uuid4()
    runtime_receipt_id = uuid4()

    controller = ExecutionLifecycleController.start(
        execution_id=request_id,
        timeout_ms=1000,
    )

    context = ToolExecutionContext(
        task_contract=contract,
        timeout_ms=1000,
        max_output_chars=16000,
        working_directory=None,
        lifecycle=controller.lifecycle,
        runtime_receipt_id=runtime_receipt_id,
    )

    mutator = _mutator(context)

    assert mutator.task_id == contract.task_id
    assert mutator.request_id == request_id
    assert (
        mutator.runtime_receipt_id
        == runtime_receipt_id
    )


def test_workspace_mutator_rejects_runtime_receipt_without_request_identity(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        WorkspaceMutationError,
        match="runtime_receipt_id requires request_id",
    ):
        WorkspaceMutator(
            workspace_root=str(tmp_path),
            task_id=uuid4(),
            allowed_paths=("note.txt",),
            protected_paths=(),
            runtime_receipt_id=uuid4(),
        )



def test_write_tool_hands_off_committed_applied_change(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"

    before = b"before\n"
    after = b"after\n"

    target.write_bytes(before)

    contract = _contract(tmp_path)

    output = WriteTextTool().execute(
        {
            "path": "src/module.py",
            "content": after.decode("utf-8"),
            "expected_sha256": _digest(before),
            "create_if_missing": False,
        },
        _context(contract),
    )

    assert target.read_bytes() == after
    assert len(output.applied_changes) == 1

    candidate = output.applied_changes[0]

    assert candidate.task_id == contract.task_id
    assert (
        candidate.operation
        is AppliedChangeOperation.WRITE_TEXT
    )
    assert (
        candidate.state
        is AppliedChangeState.COMPLETE
    )
    assert (
        candidate.relative_path
        == "src/module.py"
    )


def test_replace_tool_hands_off_replace_candidate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"

    before = b"name = 'Luna'\n"
    after = b"name = 'Sol'\n"

    target.write_bytes(before)

    contract = _contract(tmp_path)

    output = ReplaceTextTool().execute(
        {
            "path": "src/module.py",
            "old_text": "Luna",
            "new_text": "Sol",
            "expected_sha256": _digest(before),
            "expected_occurrences": 1,
        },
        _context(contract),
    )

    assert target.read_bytes() == after
    assert len(output.applied_changes) == 1

    candidate = output.applied_changes[0]

    assert (
        candidate.operation
        is AppliedChangeOperation.REPLACE_TEXT
    )
    assert (
        candidate.state
        is AppliedChangeState.COMPLETE
    )


def test_lifecycle_failure_rewrite_preserves_applied_change_handoff(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"

    before = b"before\n"
    after = b"after\n"

    target.write_bytes(before)

    contract = _contract(tmp_path)

    output = WriteTextTool().execute(
        {
            "path": "src/module.py",
            "content": after.decode("utf-8"),
            "expected_sha256": _digest(before),
            "create_if_missing": False,
        },
        _context(contract),
    )

    rewritten = _lifecycle_failure_output(
        ExecutionStop(
            kind=(
                ExecutionStopKind
                .DEADLINE_EXCEEDED
            ),
            reason=(
                "injected post-handler deadline"
            ),
        ),
        ambiguous=True,
        output=output,
    )

    assert (
        rewritten.applied_changes
        == output.applied_changes
    )

    assert (
        rewritten.changed_files
        == output.changed_files
    )

    assert (
        rewritten.metadata[
            "execution_lifecycle"
        ]
        == "DEADLINE_EXCEEDED"
    )

    assert (
        rewritten.metadata[
            "execution_may_have_occurred"
        ]
        is True
    )
