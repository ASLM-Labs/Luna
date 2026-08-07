"""Deterministic Phase 12C action-selection verification."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.actions import (  # noqa: E402
    ActionDenialCode,
    ActionKind,
    ActionProposal,
    ActionProposalBatch,
    ActionResolutionStatus,
    ActionResolver,
    ActionTargetKind,
    ToolFamily,
    ToolSelector,
    build_phase12c_routes,
)
from luna.autonomy import AutonomyLevel  # noqa: E402
from luna.contracts import RiskLevel, TaskContract, TaskScope  # noqa: E402
from luna.contracts.enums import ObservationStatus  # noqa: E402
from luna.tools import ToolCapability, ToolPolicy, build_phase5_registry  # noqa: E402


def _task(*, write_allowed: bool = False) -> TaskContract:
    return TaskContract(
        objective="Verify Phase 12C selection boundaries.",
        required_conditions=("Selection cannot grant runtime authority.",),
        evidence_required=("Structured selection outcome",),
        scope=TaskScope(
            workspace_root=".",
            allowed_paths=("README.md",),
            write_allowed=write_allowed,
        ),
        risk_level=RiskLevel.LOW,
        owner="user",
    )


def _selection_has_no_execution() -> bool:
    forbidden_calls = {"execute", "dispatch"}
    forbidden_modules = {"luna.tools.dispatcher", "luna.tools.builtins"}
    for relative in (
        Path("src/luna/actions/selector.py"),
        Path("src/luna/actions/resolver.py"),
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in forbidden_modules:
                return False
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in forbidden_calls:
                    return False
                if isinstance(func, ast.Name) and func.id in forbidden_calls:
                    return False
    return True


def main() -> int:
    required_files = (
        "src/luna/actions/__init__.py",
        "src/luna/actions/models.py",
        "src/luna/actions/selector.py",
        "src/luna/actions/resolver.py",
        "tests/test_phase12c_action_selection.py",
        "docs/rfcs/RFC-012C_ACTION_PROPOSAL_TOOL_SELECTION.md",
        "docs/PHASE_12C_REPORT.md",
    )
    missing = [relative for relative in required_files if not (ROOT / relative).is_file()]

    registry = build_phase5_registry()
    selector = ToolSelector(registry, build_phase12c_routes())
    resolver = ActionResolver(selector)
    task = _task()

    read = ActionProposal(
        task_id=task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.READ,
        target_kind=ActionTargetKind.FILE,
        summary="Read one observed file.",
        arguments={"path": "README.md"},
        required_capabilities=(ToolCapability.READ,),
    )
    family = selector.select_family(read)
    selected = selector.select_tool(read, family)
    prepared = resolver.resolve(
        proposal=read,
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("filesystem.read_text",)),
    )

    invented = ActionProposal(
        task_id=task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.READ,
        target_kind=ActionTargetKind.FILE,
        summary="Reject an invented model tool name.",
        arguments={"path": "README.md"},
        required_capabilities=(ToolCapability.READ,),
        preferred_tool_name="filesystem.invented_reader",
    )
    invented_resolution = resolver.resolve(
        proposal=invented,
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("filesystem.read_text",)),
    )

    write_task = _task(write_allowed=True)
    preferred_write = ActionProposal(
        task_id=write_task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.WRITE,
        target_kind=ActionTargetKind.FILE,
        summary="Prefer write_text and never substitute after denial.",
        arguments={
            "path": "README.md",
            "content": "phase12c",
            "create_if_missing": False,
        },
        required_capabilities=(ToolCapability.WRITE,),
        preferred_tool_name="filesystem.write_text",
        expectation_id=uuid4(),
    )
    permission_denied = resolver.resolve(
        proposal=preferred_write,
        task_contract=write_task,
        policy=ToolPolicy(
            allowed_tools=("filesystem.replace_text",),
            autonomy_level=AutonomyLevel.LEVEL_2_CONTROLLED,
            max_risk=RiskLevel.MEDIUM,
        ),
    )

    ambiguous = ActionProposal(
        task_id=write_task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.WRITE,
        target_kind=ActionTargetKind.FILE,
        summary="Ambiguous file modification.",
        arguments={"path": "README.md"},
        required_capabilities=(ToolCapability.WRITE,),
        expectation_id=uuid4(),
    )
    ambiguous_selected = selector.select_tool(
        ambiguous,
        selector.select_family(ambiguous),
    )

    multiple_side_effects_blocked = False
    trace_id = uuid4()
    write = ActionProposal(
        task_id=write_task.task_id,
        trace_id=trace_id,
        kind=ActionKind.WRITE,
        target_kind=ActionTargetKind.FILE,
        summary="One write.",
        arguments={
            "path": "README.md",
            "content": "phase12c",
            "create_if_missing": False,
        },
        required_capabilities=(ToolCapability.WRITE,),
        preferred_tool_name="filesystem.write_text",
        expectation_id=uuid4(),
    )
    rollback = ActionProposal(
        task_id=write_task.task_id,
        trace_id=trace_id,
        kind=ActionKind.ROLLBACK,
        target_kind=ActionTargetKind.SNAPSHOT,
        summary="Second side effect in same iteration.",
        arguments={"snapshot_id": str(uuid4())},
        required_capabilities=(ToolCapability.WRITE,),
        preferred_tool_name="workspace.rollback",
        expectation_id=uuid4(),
    )
    try:
        ActionProposalBatch(
            task_id=write_task.task_id,
            trace_id=trace_id,
            proposals=(write, rollback),
        )
    except ValidationError:
        multiple_side_effects_blocked = True

    model_risk_field_rejected = False
    try:
        ActionProposal.model_validate(
            {
                "task_id": str(task.task_id),
                "trace_id": str(uuid4()),
                "kind": "READ",
                "target_kind": "FILE",
                "summary": "Try to lower runtime-owned risk.",
                "arguments": {"path": "README.md"},
                "required_capabilities": ["READ"],
                "risk_level": "LOW",
            }
        )
    except ValidationError:
        model_risk_field_rejected = True

    checks = {
        "required_files_present": not missing,
        "stage_one_family_deterministic": family.family is ToolFamily.FILESYSTEM,
        "stage_two_registered_tool_only": (
            not hasattr(selected, "code")
            and selected.spec.name == "filesystem.read_text"  # type: ignore[union-attr]
        ),
        "prepared_action_not_executed": (
            prepared.status is ActionResolutionStatus.PREPARED
            and prepared.request_id is not None
            and prepared.selected_tool is not None
            and prepared.selected_tool.name == "filesystem.read_text"
        ),
        "invented_tool_denied": (
            invented_resolution.status is ActionResolutionStatus.DENIED
            and invented_resolution.denial is not None
            and invented_resolution.denial.code
            is ActionDenialCode.UNKNOWN_PREFERRED_TOOL
        ),
        "denial_returns_blocked_observation": (
            invented_resolution.observation is not None
            and invented_resolution.observation.status is ObservationStatus.BLOCKED
        ),
        "permission_denial_no_fallback": (
            permission_denied.status is ActionResolutionStatus.DENIED
            and permission_denied.denial is not None
            and permission_denied.denial.code is ActionDenialCode.POLICY_DENIED
            and permission_denied.denial.selected_tool_name == "filesystem.write_text"
        ),
        "ambiguous_selection_denied": (
            hasattr(ambiguous_selected, "code")
            and ambiguous_selected.code is ActionDenialCode.AMBIGUOUS_TOOL  # type: ignore[union-attr]
        ),
        "one_side_effect_per_iteration": multiple_side_effects_blocked,
        "model_cannot_supply_risk": model_risk_field_rejected,
        "selection_has_no_hidden_execution": _selection_has_no_execution(),
        "resolution_round_trip": (
            type(prepared).from_json(prepared.to_json()) == prepared
            and type(invented_resolution).from_json(invented_resolution.to_json())
            == invented_resolution
        ),
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    print(
        json.dumps(
            {
                "phase": "12C",
                "checks": checks,
                "missing_files": missing,
                "status": status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
