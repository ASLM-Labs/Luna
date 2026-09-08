"""Thread-safe registry for immutable Luna skill versions."""

from __future__ import annotations

from threading import RLock
from uuid import UUID, uuid4, uuid5

from luna.skills.models import (
    SkillPackage,
    SkillProvenance,
    SkillScope,
    SkillTrustState,
    SkillVersion,
)


class SkillRegistryError(RuntimeError):
    """Base registry failure."""


class SkillVersionNotFoundError(SkillRegistryError):
    """Requested immutable version is not registered."""


class SkillRegistryIntegrityError(SkillRegistryError):
    """Same immutable identity was presented with conflicting host state."""


class SkillRegistry:
    """Registry-owned lifecycle identity without runtime/tool authority."""

    def __init__(self) -> None:
        self._versions: dict[UUID, SkillVersion] = {}
        self._lock = RLock()

    def install(
        self,
        package: SkillPackage,
        *,
        scope: SkillScope,
        provenance: SkillProvenance,
        trust_state: SkillTrustState = SkillTrustState.QUARANTINED,
        skill_id: UUID | None = None,
    ) -> SkillVersion:
        logical_id = skill_id or uuid4()
        version_id = uuid5(logical_id, package.package_digest)
        with self._lock:
            existing = self._versions.get(version_id)
            if existing is not None:
                if (
                    existing.skill_id == logical_id
                    and existing.package == package
                    and existing.scope is scope
                    and existing.provenance is provenance
                    and existing.trust_state is trust_state
                ):
                    return existing.model_copy(deep=True)
                raise SkillRegistryIntegrityError(
                    "immutable skill version identity conflicts with registered state"
                )
            version = SkillVersion(
                skill_id=logical_id,
                version_id=version_id,
                package=package.model_copy(deep=True),
                scope=scope,
                provenance=provenance,
                trust_state=trust_state,
            )
            self._versions[version_id] = version
            return version.model_copy(deep=True)

    def get_version(self, version_id: UUID) -> SkillVersion:
        with self._lock:
            version = self._versions.get(version_id)
            if version is None:
                raise SkillVersionNotFoundError(f"skill version is not registered: {version_id}")
            return version.model_copy(deep=True)

    def versions(self) -> tuple[SkillVersion, ...]:
        with self._lock:
            return tuple(
                item.model_copy(deep=True)
                for item in sorted(
                    self._versions.values(),
                    key=lambda value: (
                        value.package.name,
                        str(value.skill_id),
                        str(value.version_id),
                    ),
                )
            )
