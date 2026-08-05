from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from luna.contracts import RiskLevel, TaskContract, TaskScope


def make_scope(*, write_allowed: bool = False) -> TaskScope:
    return TaskScope(
        workspace_root="C:/workspace/luna",
        allowed_paths=("src",) if write_allowed else (),
        protected_paths=("docs/governance",),
        write_allowed=write_allowed,
    )


def test_task_contract_round_trip() -> None:
    contract = TaskContract(
        objective="Implement the contract layer",
        required_conditions=("Eight contracts exist",),
        forbidden_outcomes=("Runtime tools become active",),
        evidence_required=("Unit tests pass",),
        scope=make_scope(write_allowed=True),
        risk_level=RiskLevel.MEDIUM,
    )

    restored = TaskContract.from_json(contract.to_json())
    assert restored == contract
    assert restored.created_at.tzinfo is not None


def test_task_contract_rejects_conflicting_conditions() -> None:
    with pytest.raises(ValidationError, match="conflict"):
        TaskContract(
            objective="Contradictory task",
            required_conditions=("Do not change files",),
            forbidden_outcomes=("Do not change files",),
            evidence_required=("A result exists",),
            scope=make_scope(),
        )


def test_task_contract_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        TaskContract(
            objective="Bad timestamp",
            required_conditions=("One",),
            evidence_required=("One",),
            scope=make_scope(),
            created_at=datetime(2026, 8, 6),
        )


def test_scope_rejects_parent_escape() -> None:
    with pytest.raises(ValidationError, match="relative paths"):
        TaskScope(
            workspace_root="C:/workspace/luna",
            allowed_paths=("../outside",),
            write_allowed=True,
        )


def test_task_contract_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        TaskContract.model_validate(
            {
                "objective": "Strict model",
                "required_conditions": ["One"],
                "evidence_required": ["One"],
                "scope": {"workspace_root": "C:/workspace/luna"},
                "unexpected": True,
            }
        )
