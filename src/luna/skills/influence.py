"""Influence projection for immutable skill versions."""

from __future__ import annotations

from luna.influence import InfluenceSourceClass, InfluenceTrust, single_influence
from luna.skills.models import SkillTrustState, SkillVersion


def skill_version_influence(version: SkillVersion) -> InfluenceTrust:
    """Project host-owned skill admission into authority-negative influence trust."""
    source_class = (
        InfluenceSourceClass.HOST_ADMITTED
        if version.trust_state is SkillTrustState.TRUSTED
        else InfluenceSourceClass.UNKNOWN
    )
    return single_influence(
        source_ref=f"skill://{version.version_id}/sha256/{version.package.package_digest}",
        source_class=source_class,
    )
