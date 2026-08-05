from __future__ import annotations

from uuid import uuid4

from luna.context import ContextBudget, ContextCandidate, ContextSource, ContextSourceKind
from luna.contracts import TaskScope
from luna.preparation import PreparationStatus, TaskPreparer


def test_preparation_reaches_ready_for_planning_with_explicit_inputs() -> None:
    task_id = uuid4()
    preparation = TaskPreparer().prepare(
        task_id=task_id,
        request="README.md dosyasını incele",
        scope=TaskScope(
            workspace_root="C:/workspace",
            allowed_paths=("README.md",),
        ),
        context_candidates=[
            ContextCandidate(
                source=ContextSource.from_text(
                    kind=ContextSourceKind.FILE,
                    locator="README.md",
                    text="# Luna",
                    verified=True,
                ),
                required=True,
                priority=100,
            )
        ],
        context_budget=ContextBudget(),
        required_conditions=("README gözlemlenmiş olmalı",),
        evidence_required=("README içerik hash'i",),
    )

    assert preparation.status is PreparationStatus.READY_FOR_PLANNING
    assert preparation.contract is not None
    assert preparation.task_id == task_id


def test_preparation_stops_for_ambiguous_write_request() -> None:
    preparation = TaskPreparer().prepare(
        request="kodu düzelt",
        scope=TaskScope(workspace_root="C:/workspace"),
        context_candidates=[],
        context_budget=ContextBudget(),
        required_conditions=("hata düzelmeli",),
        evidence_required=("test sonucu",),
    )

    assert preparation.status is PreparationStatus.NEEDS_CLARIFICATION
    assert preparation.contract is None
    assert "write_scope" in preparation.reasons
