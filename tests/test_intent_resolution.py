from __future__ import annotations

import pytest
from pydantic import ValidationError

from luna.intent import (
    DeterministicIntentResolver,
    IntentKind,
    IntentResolution,
    RequestedAction,
)


def test_same_request_has_same_semantic_resolution() -> None:
    resolver = DeterministicIntentResolver()
    request = "src/luna/cli.py dosyasını incele ve hatayı düzelt"

    first = resolver.resolve(request)
    second = resolver.resolve(request)

    assert first.semantic_signature() == second.semantic_signature()
    assert first.kind is IntentKind.CODE_CHANGE
    assert RequestedAction.INSPECT in first.actions
    assert RequestedAction.MODIFY in first.actions
    assert first.referenced_resources == ("src/luna/cli.py",)
    assert not first.requires_clarification


def test_write_request_without_target_exposes_unknown() -> None:
    resolution = DeterministicIntentResolver().resolve("kodu düzelt")

    assert resolution.kind is IntentKind.CODE_CHANGE
    assert "target_scope" in resolution.unknowns
    assert resolution.requires_clarification


def test_research_request_is_explicit() -> None:
    resolution = DeterministicIntentResolver().resolve(
        "GitHub üzerinde checkpoint mimarilerini araştır"
    )

    assert resolution.kind is IntentKind.RESEARCH
    assert resolution.actions == (RequestedAction.RESEARCH,)


def test_fingerprint_is_validated() -> None:
    resolution = DeterministicIntentResolver().resolve("Bu nedir?")

    with pytest.raises(ValidationError):
        IntentResolution.model_validate(
            {
                **resolution.model_dump(),
                "request_fingerprint": "0" * 64,
            }
        )
