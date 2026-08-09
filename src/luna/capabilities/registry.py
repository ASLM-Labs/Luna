"""Deterministic capability registry and blast-radius queries."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from luna.capabilities.models import CapabilityImpact, CapabilityRecord, DependencyKind


class CapabilityRegistry:
    """Validated capability graph with no runtime or promotion authority."""

    def __init__(self, records: Iterable[CapabilityRecord]) -> None:
        materialized = tuple(records)
        by_id: dict[str, CapabilityRecord] = {}
        names: set[str] = set()
        for record in materialized:
            if record.capability_id in by_id:
                raise ValueError(f"duplicate capability ID: {record.capability_id}")
            if record.name in names:
                raise ValueError(f"duplicate capability name: {record.name}")
            by_id[record.capability_id] = record
            names.add(record.name)
        if not by_id:
            raise ValueError("capability registry cannot be empty")
        self._records = tuple(sorted(materialized, key=lambda item: item.capability_id))
        self._by_id = by_id
        self._validate_dependency_references()
        self._validate_acyclic()

    @property
    def records(self) -> tuple[CapabilityRecord, ...]:
        return self._records

    def get(self, capability_id: str) -> CapabilityRecord:
        try:
            return self._by_id[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown capability ID: {capability_id}") from exc

    def dependencies(
        self,
        capability_id: str,
        *,
        kind: DependencyKind | None = None,
    ) -> tuple[str, ...]:
        record = self.get(capability_id)
        if kind is DependencyKind.HARD:
            return record.hard_prerequisites
        if kind is DependencyKind.PREFERRED:
            return record.preferred_prerequisites
        return tuple(sorted((*record.hard_prerequisites, *record.preferred_prerequisites)))

    def direct_dependents(
        self,
        capability_id: str,
        *,
        include_preferred: bool = True,
    ) -> tuple[str, ...]:
        self.get(capability_id)
        matches: list[str] = []
        for record in self._records:
            dependencies = set(record.hard_prerequisites)
            if include_preferred:
                dependencies.update(record.preferred_prerequisites)
            if capability_id in dependencies:
                matches.append(record.capability_id)
        return tuple(sorted(matches))

    def blast_radius(
        self,
        capability_id: str,
        *,
        include_preferred: bool = True,
    ) -> CapabilityImpact:
        self.get(capability_id)
        direct = self.direct_dependents(
            capability_id,
            include_preferred=include_preferred,
        )
        queue: deque[tuple[str, tuple[str, ...]]] = deque(
            (item, (capability_id, item)) for item in direct
        )
        shortest_path: dict[str, tuple[str, ...]] = {item: path for item, path in queue}
        while queue:
            current, path = queue.popleft()
            for dependent in self.direct_dependents(
                current,
                include_preferred=include_preferred,
            ):
                if dependent in shortest_path or dependent == capability_id:
                    continue
                next_path = (*path, dependent)
                shortest_path[dependent] = next_path
                queue.append((dependent, next_path))
        indirect = tuple(sorted(set(shortest_path) - set(direct)))
        paths = tuple(shortest_path[item] for item in sorted(shortest_path))
        return CapabilityImpact(
            capability_id=capability_id,
            direct_dependents=direct,
            indirect_dependents=indirect,
            dependency_paths=paths,
            includes_preferred_edges=include_preferred,
        )

    def _validate_dependency_references(self) -> None:
        known = set(self._by_id)
        for record in self._records:
            for dependency in (*record.hard_prerequisites, *record.preferred_prerequisites):
                if dependency not in known:
                    raise ValueError(
                        f"unknown capability dependency: {record.capability_id} -> {dependency}"
                    )

    def _validate_acyclic(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(capability_id: str) -> None:
            if capability_id in visiting:
                raise ValueError(f"capability dependency cycle detected at {capability_id}")
            if capability_id in visited:
                return
            visiting.add(capability_id)
            for dependency in self.dependencies(capability_id):
                visit(dependency)
            visiting.remove(capability_id)
            visited.add(capability_id)

        for capability_id in sorted(self._by_id):
            visit(capability_id)
