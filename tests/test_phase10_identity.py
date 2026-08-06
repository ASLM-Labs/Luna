from __future__ import annotations

import pytest
from pydantic import ValidationError

from luna.identity import CommunicationPrinciples, IdentityProfile, UserProfile


def test_identity_profile_is_versioned_and_has_no_hard_coded_user() -> None:
    profile = IdentityProfile()

    assert profile.identity_name == "Luna"
    assert profile.identity_version == "0.1.0"
    assert profile.profile_revision == 1
    assert profile.user_profile is None
    assert profile.preferred_address() == "Kullanıcı"
    assert profile.single_active_identity is True


def test_runtime_user_profile_controls_addressing() -> None:
    profile = IdentityProfile(
        user_profile=UserProfile(
            user_id="owner-1",
            display_name="Display",
            alias="Alias",
            preferred_address="Preferred",
        )
    )

    assert profile.preferred_address() == "Preferred"
    payload = profile.model_dump(mode="json")
    assert payload["user_profile"]["user_id"] == "owner-1"


def test_identity_principles_cannot_be_weakened() -> None:
    with pytest.raises(ValidationError, match="cannot be weakened"):
        CommunicationPrinciples(honest=False)


def test_identity_directives_separate_evidence_and_uncertainty() -> None:
    directives = IdentityProfile().communication_directives()

    assert any("evidence" in item.lower() for item in directives)
    assert any("uncertainty" in item.lower() for item in directives)
    assert any("runtime policy" in item.lower() for item in directives)
