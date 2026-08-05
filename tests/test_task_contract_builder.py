from __future__ import annotations

from uuid import uuid4

import pytest

from luna.contracts import RiskLevel, TaskScope
from luna.intent import DeterministicIntentResolver
from luna.tasking import ContractDraftStatus, TaskContractBuilder


def test_missing_success_and_evidence_are_explicit_blockers() -> None:
    intent = DeterministicIntentResolver().resolve("README.md dosyasını incele")
    draft = TaskContractBuilder().draft(
        intent=intent,
        scope=TaskScope(
            workspace_root="C:/workspace",
            allowed_paths=("README.md",),
        ),
        task_id=uuid4(),
    )

    assert draft.status is ContractDraftStatus.BLOCKED
    assert draft.blocking_unknowns == ("required_conditions", "evidence_required")


def test_complete_draft_finalizes_without_inventing_fields() -> None:
    intent = DeterministicIntentResolver().resolve("README.md dosyasını incele")
    builder = TaskContractBuilder()
    draft = builder.draft(
        intent=intent,
        scope=TaskScope(
            workspace_root="C:/workspace",
            allowed_paths=("README.md",),
        ),
        required_conditions=("README içeriği gözlemlenmiş olmalı",),
        evidence_required=("README içerik hash'i",),
        risk_level=RiskLevel.LOW,
        task_id=uuid4(),
    )

    contract = builder.finalize(draft)

    assert draft.status is ContractDraftStatus.READY
    assert contract.required_conditions == draft.required_conditions
    assert contract.evidence_required == draft.evidence_required
    assert contract.objective == intent.objective


def test_required_and_forbidden_conflict_blocks_finalization() -> None:
    intent = DeterministicIntentResolver().resolve("README.md dosyasını incele")
    builder = TaskContractBuilder()
    draft = builder.draft(
        intent=intent,
        scope=TaskScope(
            workspace_root="C:/workspace",
            allowed_paths=("README.md",),
        ),
        required_conditions=("README değiştirilmeli",),
        forbidden_outcomes=("README değiştirilmeli",),
        evidence_required=("diff",),
        task_id=uuid4(),
    )

    assert draft.status is ContractDraftStatus.BLOCKED
    assert draft.conflicts == ("required_and_forbidden:README değiştirilmeli",)
    with pytest.raises(ValueError, match="blocked"):
        builder.finalize(draft)
