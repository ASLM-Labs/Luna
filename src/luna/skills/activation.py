"""Exact skill activation admission and authority-negative context projection."""

from __future__ import annotations

from uuid import UUID

from luna.context import (
    ContextInterpretation,
    ContextLayer,
    ContextSource,
    ContextSourceKind,
    LayeredContextCandidate,
)
from luna.skills.models import (
    SkillActivation,
    SkillActivationSource,
    SkillScope,
    SkillTrustState,
)
from luna.skills.registry import SkillRegistry


class SkillActivationError(RuntimeError):
    """Exact version cannot be admitted under current host policy."""


class SkillActivationProjector:
    """Resolve exact trusted versions and project body-only procedural context."""

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def activate(
        self,
        *,
        task_id: UUID,
        version_id: UUID,
        allowed_scopes: tuple[SkillScope, ...],
        activation_source: SkillActivationSource = SkillActivationSource.USER_EXPLICIT,
    ) -> SkillActivation:
        version = self._registry.get_version(version_id)
        if version.trust_state is not SkillTrustState.TRUSTED:
            raise SkillActivationError("quarantined skill version cannot be activated")
        if version.scope not in set(allowed_scopes):
            raise SkillActivationError("skill scope is not allowed for this activation")
        return SkillActivation(
            task_id=task_id,
            skill_id=version.skill_id,
            version_id=version.version_id,
            skill_scope=version.scope,
            activation_source=activation_source,
        )

    def project(self, activation: SkillActivation) -> LayeredContextCandidate:
        version = self._registry.get_version(activation.version_id)
        if version.skill_id != activation.skill_id:
            raise SkillActivationError("skill activation logical identity mismatch")
        if version.scope is not activation.skill_scope:
            raise SkillActivationError("skill activation scope no longer matches exact version")
        if version.trust_state is not SkillTrustState.TRUSTED:
            raise SkillActivationError("skill version is not trusted at projection time")
        package = version.package
        source = ContextSource.from_text(
            kind=ContextSourceKind.DOCUMENT,
            locator=f"skill://{version.version_id}/{package.name}",
            text=package.body,
            verified=False,
            observed_at=activation.activated_at,
            metadata={
                "skill_activation_id": str(activation.activation_id),
                "skill_id": str(version.skill_id),
                "skill_version_id": str(version.version_id),
                "skill_scope": version.scope.value,
                "skill_provenance": version.provenance.value,
                "skill_trust": version.trust_state.value,
                "skill_package_digest": package.package_digest,
                "activation_source": activation.activation_source.value,
            },
        )
        return LayeredContextCandidate(
            layer=ContextLayer.WORKSPACE,
            source=source,
            priority=90,
            required=False,
            interpretation=ContextInterpretation.PROCEDURAL_GUIDANCE,
            relevance_basis=f"activated exact skill version {version.version_id}",
        )
