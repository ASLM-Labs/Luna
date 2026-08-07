"""Explicit dependency-injection boundary for the future runtime orchestrator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum
from types import MappingProxyType

from pydantic import field_validator, model_validator

from luna.actions import ActionResolver
from luna.context import LayeredContextComposer
from luna.continuity import ContinuityService
from luna.contracts.base import LunaContractModel
from luna.memory import VerifiedMemoryService
from luna.modeling import ModelBackend
from luna.planning import AdaptivePlanner
from luna.preparation import TaskPreparer
from luna.recovery import (
    FailureClassifier,
    MinimalChangePolicy,
    RecoveryPolicy,
    WorkspaceIsolationPolicy,
)
from luna.reporting import FinalReportComposer
from luna.runtime.change_inspector import WorkspaceChangeInspector
from luna.runtime.environment import RuntimeFingerprintProvider
from luna.runtime.isolation import WorkspaceIsolationManager
from luna.runtime.journal import SQLiteRuntimeJournal
from luna.tools import ToolDispatcher
from luna.verification import CompletionGate


class RuntimeDependencyName(StrEnum):
    """Stable names of Phase 12A orchestrator dependencies."""

    TASK_PREPARER = "TASK_PREPARER"
    PLANNER = "PLANNER"
    MODEL_BACKEND = "MODEL_BACKEND"
    TOOL_DISPATCHER = "TOOL_DISPATCHER"
    COMPLETION_GATE = "COMPLETION_GATE"
    REPORT_COMPOSER = "REPORT_COMPOSER"
    CONTINUITY_SERVICE = "CONTINUITY_SERVICE"
    MEMORY_SERVICE = "MEMORY_SERVICE"


_REQUIRED_DEPENDENCIES = tuple(RuntimeDependencyName)


class RuntimeDependencyManifest(LunaContractModel):
    """Serializable proof that explicit runtime dependencies were supplied."""

    required: tuple[RuntimeDependencyName, ...] = _REQUIRED_DEPENDENCIES
    available: tuple[RuntimeDependencyName, ...]

    @field_validator("required", "available")
    @classmethod
    def validate_unique(
        cls,
        values: tuple[RuntimeDependencyName, ...],
    ) -> tuple[RuntimeDependencyName, ...]:
        if len(values) != len(set(values)):
            raise ValueError("runtime dependency names must be unique")
        return values

    @model_validator(mode="after")
    def validate_readiness(self) -> RuntimeDependencyManifest:
        missing = set(self.required) - set(self.available)
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"runtime dependencies are incomplete: {names}")
        return self

    @property
    def ready(self) -> bool:
        return set(self.required).issubset(self.available)


@dataclass(frozen=True, slots=True)
class RuntimeDependencies:
    """Concrete injected services; no module-global fallback is permitted."""

    task_preparer: TaskPreparer
    planner: AdaptivePlanner
    model_backend: ModelBackend
    tool_dispatcher: ToolDispatcher
    completion_gate: CompletionGate
    report_composer: FinalReportComposer
    continuity_service: ContinuityService
    memory_service: VerifiedMemoryService

    def __post_init__(self) -> None:
        for item in fields(self):
            if getattr(self, item.name) is None:
                raise ValueError(f"runtime dependency cannot be None: {item.name}")

    def as_mapping(self) -> Mapping[RuntimeDependencyName, object]:
        """Return a read-only dependency map for orchestrator construction."""
        return MappingProxyType(
            {
                RuntimeDependencyName.TASK_PREPARER: self.task_preparer,
                RuntimeDependencyName.PLANNER: self.planner,
                RuntimeDependencyName.MODEL_BACKEND: self.model_backend,
                RuntimeDependencyName.TOOL_DISPATCHER: self.tool_dispatcher,
                RuntimeDependencyName.COMPLETION_GATE: self.completion_gate,
                RuntimeDependencyName.REPORT_COMPOSER: self.report_composer,
                RuntimeDependencyName.CONTINUITY_SERVICE: self.continuity_service,
                RuntimeDependencyName.MEMORY_SERVICE: self.memory_service,
            }
        )

    def manifest(self) -> RuntimeDependencyManifest:
        """Build the serializable readiness manifest."""
        return RuntimeDependencyManifest(available=tuple(self.as_mapping()))


@dataclass(frozen=True, slots=True)
class RuntimeLoopDependencies:
    """Phase 12E services required by the single policy-agent loop."""

    core: RuntimeDependencies
    context_composer: LayeredContextComposer
    action_resolver: ActionResolver
    failure_classifier: FailureClassifier
    recovery_policy: RecoveryPolicy
    minimal_change_policy: MinimalChangePolicy
    isolation_policy: WorkspaceIsolationPolicy
    change_inspector: WorkspaceChangeInspector
    runtime_journal: SQLiteRuntimeJournal
    isolation_manager: WorkspaceIsolationManager
    fingerprint_provider: RuntimeFingerprintProvider

    def __post_init__(self) -> None:
        for item in fields(self):
            if getattr(self, item.name) is None:
                raise ValueError(f"runtime loop dependency cannot be None: {item.name}")
