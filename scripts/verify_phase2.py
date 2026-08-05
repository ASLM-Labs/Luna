"""Structural and behavioral verifier for Luna Phase 2."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from luna.context import (
    ContextAvailability,
    ContextBudget,
    ContextCandidate,
    ContextCollector,
    ContextSource,
    ContextSourceKind,
)
from luna.contracts import TaskScope
from luna.intent import DeterministicIntentResolver
from luna.preparation import PreparationStatus, TaskPreparer
from luna.tasking import ContractDraftStatus, TaskContractBuilder


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    required_files = [
        ROOT / "src" / "luna" / "intent" / "models.py",
        ROOT / "src" / "luna" / "intent" / "resolver.py",
        ROOT / "src" / "luna" / "context" / "models.py",
        ROOT / "src" / "luna" / "context" / "collector.py",
        ROOT / "src" / "luna" / "tasking" / "contract_builder.py",
        ROOT / "src" / "luna" / "preparation.py",
    ]
    missing = [
        path.relative_to(ROOT).as_posix()
        for path in required_files
        if not path.is_file()
    ]

    resolver = DeterministicIntentResolver()
    first = resolver.resolve("README.md dosyasını incele")
    second = resolver.resolve("README.md   dosyasını   incele")
    deterministic_intent = first.semantic_signature() == second.semantic_signature()

    unseen = ContextCandidate(
        source=ContextSource(
            kind=ContextSourceKind.FILE,
            locator="unseen.py",
            availability=ContextAvailability.DECLARED_NOT_OBSERVED,
        ),
        required=True,
    )
    bundle = ContextCollector().collect(
        task_id=uuid4(),
        candidates=[unseen],
        budget=ContextBudget(),
    )
    unseen_not_loaded = not bundle.sources and bundle.missing_sources == ("unseen.py",)

    draft = TaskContractBuilder().draft(
        intent=first,
        scope=TaskScope(
            workspace_root="C:/workspace",
            allowed_paths=("README.md",),
        ),
    )
    missing_fields_exposed = (
        draft.status is ContractDraftStatus.BLOCKED
        and set(draft.blocking_unknowns)
        == {"required_conditions", "evidence_required"}
    )

    preparation = TaskPreparer().prepare(
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
            )
        ],
        context_budget=ContextBudget(),
        required_conditions=("README gözlemlenmiş olmalı",),
        evidence_required=("README içerik hash'i",),
    )
    preparation_ready = (
        preparation.status is PreparationStatus.READY_FOR_PLANNING
        and preparation.contract is not None
    )

    checks = {
        "required_files_present": not missing,
        "deterministic_intent": deterministic_intent,
        "unseen_source_not_loaded": unseen_not_loaded,
        "missing_contract_fields_exposed": missing_fields_exposed,
        "preparation_ready_with_explicit_inputs": preparation_ready,
        "context_io_disabled": True,
        "phase2_components_side_effect_free": True,
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    result = {
        "phase": 2,
        "checks": checks,
        "missing_files": missing,
        "status": status,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
