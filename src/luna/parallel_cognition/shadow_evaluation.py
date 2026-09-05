"""Non-authoritative S5C shadow evaluation contracts and durable ledger.

The module compares supplied observations. It never executes a provider, mutates task
state, adopts shadow output, speaks for the root, or authorizes promotion.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.evaluation_governance import (
    BenchmarkContaminationReport,
    FrozenEvaluationSuite,
)
from luna.parallel_cognition.models import (
    C011ContractModel,
    Sha256,
    canonical_contract_json,
)

S5C_SHADOW_LEDGER_SCHEMA_VERSION = 1
S5C_METRIC_SCHEMA_REVISION = "1.0.0"
_ZERO_SHA256 = "0" * 64


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _content_identity(
    model: C011ContractModel,
    *,
    identity_field: str,
    prefix: str,
) -> str:
    payload = model.model_dump(mode="json", exclude={identity_field})
    basis = {
        "contract_type": f"{type(model).__module__}.{type(model).__qualname__}",
        "schema_version": model.schema_version,
        "payload": payload,
    }
    return f"{prefix}{sha256(_canonical_json(basis).encode('utf-8')).hexdigest()}"


def _normalized_unique_text(
    values: tuple[str, ...],
    *,
    label: str,
    require_nonempty: bool = False,
) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    if require_nonempty and not normalized:
        raise ValueError(f"{label} must not be empty")
    if any(not value for value in normalized):
        raise ValueError(f"{label} cannot contain blank values")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(normalized))


class ShadowConfiguration(StrEnum):
    SOLO = "SOLO"
    ULTRA_SOLO = "ULTRA_SOLO"
    PARALLEL = "PARALLEL"


_CONFIGURATION_ORDER = (
    ShadowConfiguration.SOLO,
    ShadowConfiguration.ULTRA_SOLO,
    ShadowConfiguration.PARALLEL,
)


class ShadowEvidenceKind(StrEnum):
    DETERMINISTIC_FIXTURE = "DETERMINISTIC_FIXTURE"
    REAL_PROVIDER = "REAL_PROVIDER"


class ShadowComparisonStatus(StrEnum):
    COMPARABLE = "COMPARABLE"
    BLOCKED = "BLOCKED"


class ShadowArtifactKind(StrEnum):
    PLAN = "PLAN"
    OBSERVATION = "OBSERVATION"
    COMPARISON = "COMPARISON"


class EqualComputeBudget(C011ContractModel):
    """One shared total budget ceiling for every compared configuration."""

    max_total_tokens: int = Field(ge=1)
    max_tool_calls: int = Field(ge=0)
    max_compute_units: int = Field(ge=1)
    max_context_bytes: int = Field(ge=1)
    max_wall_time_ms: int = Field(ge=1)


class ShadowArmSpec(C011ContractModel):
    """Exact execution identity for one topology; the label alone has no semantics."""

    configuration: ShadowConfiguration
    execution_configuration_sha256: Sha256
    backend_id: str = Field(min_length=1, max_length=300)
    provider_profile_id: str = Field(min_length=1, max_length=500)
    provider_binding_id: str = Field(min_length=1, max_length=500)
    model_identity: str = Field(min_length=1, max_length=500)
    driver_sha256: Sha256
    runtime_sha256: Sha256
    environment_sha256: Sha256
    sampling_sha256: Sha256
    seed: int = Field(ge=0)
    worker_count: int = Field(ge=0, le=3)
    execution_authority: Literal[False] = False
    task_state_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_worker_count(self) -> Self:
        if self.configuration is ShadowConfiguration.PARALLEL:
            if self.worker_count == 0:
                raise ValueError("PARALLEL arm requires a positive worker count")
        elif self.worker_count != 0:
            raise ValueError("SOLO and ULTRA_SOLO cannot declare workers")
        return self


class ShadowRunSlot(C011ContractModel):
    """One precommitted case/repetition/arm schedule position."""

    slot_id: str = ""
    schedule_index: int = Field(ge=1)
    case_id: str = Field(min_length=1, max_length=300)
    repetition: int = Field(ge=1)
    configuration: ShadowConfiguration

    @model_validator(mode="after")
    def validate_slot(self) -> Self:
        expected = _content_identity(
            self,
            identity_field="slot_id",
            prefix="c011-shadow-slot:sha256:",
        )
        if not self.slot_id:
            object.__setattr__(self, "slot_id", expected)
        elif self.slot_id != expected:
            raise ValueError("shadow run slot ID does not match canonical content")
        return self


class ShadowEvaluationPlan(C011ContractModel):
    """Frozen pre-observation basis for all three configurations."""

    plan_id: str = ""
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    task_contract_sha256: Sha256
    workload_sha256: Sha256
    prompt_sha256: Sha256
    context_manifest_sha256: Sha256
    execution_tree_sha256: Sha256
    compute_accounting_sha256: Sha256
    metric_policy_sha256: Sha256
    contamination_exposure_manifest_sha256: Sha256
    contamination_provenance_complete: bool
    evaluator_independence_evidence_sha256: Sha256
    evaluator_independence_verified: bool
    evaluation_suite: FrozenEvaluationSuite
    contamination_report: BenchmarkContaminationReport
    equal_compute_budget: EqualComputeBudget
    repetitions: int = Field(ge=1, le=100)
    arms: tuple[ShadowArmSpec, ...] = Field(min_length=3, max_length=3)
    run_slots: tuple[ShadowRunSlot, ...] = Field(min_length=3)
    metric_schema_revision: Literal["1.0.0"] = "1.0.0"
    shadow_output_to_task_state: Literal[False] = False
    root_context_adoption_authority: Literal[False] = False
    task_state_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if tuple(item.configuration for item in self.arms) != _CONFIGURATION_ORDER:
            raise ValueError("shadow plan requires canonical SOLO/ULTRA_SOLO/PARALLEL arms")
        stable_fields = (
            "backend_id",
            "provider_profile_id",
            "provider_binding_id",
            "model_identity",
            "driver_sha256",
            "runtime_sha256",
            "environment_sha256",
            "sampling_sha256",
            "seed",
        )
        for field_name in stable_fields:
            if len({getattr(arm, field_name) for arm in self.arms}) != 1:
                raise ValueError(f"shadow arms must share {field_name}")
        for model_identity in {arm.model_identity for arm in self.arms}:
            self.evaluation_suite.evaluator.assert_independent_for_candidate(model_identity)
        case_ids = self.evaluation_suite.case_ids
        expected_slots = {
            (case_id, repetition, configuration)
            for case_id in case_ids
            for repetition in range(1, self.repetitions + 1)
            for configuration in _CONFIGURATION_ORDER
        }
        observed_slots = {
            (item.case_id, item.repetition, item.configuration) for item in self.run_slots
        }
        if observed_slots != expected_slots or len(self.run_slots) != len(expected_slots):
            raise ValueError("shadow run slots must cover the exact suite/repetition/arm grid")
        if tuple(item.schedule_index for item in self.run_slots) != tuple(
            range(1, len(self.run_slots) + 1)
        ):
            raise ValueError("shadow run schedule indices must be contiguous and ordered")
        slot_ids = tuple(item.slot_id for item in self.run_slots)
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("shadow run slot IDs must be unique")
        contamination_case_ids = {
            item.case_id for item in self.contamination_report.findings
        }
        if not contamination_case_ids.issubset(case_ids):
            raise ValueError("contamination findings must reference frozen suite cases")
        expected = _content_identity(
            self,
            identity_field="plan_id",
            prefix="c011-shadow-plan:sha256:",
        )
        if not self.plan_id:
            object.__setattr__(self, "plan_id", expected)
        elif self.plan_id != expected:
            raise ValueError("shadow plan ID does not match canonical content")
        return self


class ShadowMetricObservation(C011ContractModel):
    """Integer-only observed metrics; raw model output is not accepted."""

    quality_score_milli: int = Field(ge=0, le=1000)
    required_evidence_count: int = Field(ge=0)
    verified_required_evidence_count: int = Field(ge=0)
    required_evidence_coverage_milli: int = Field(ge=0, le=1000)
    latency_ms: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    root_compute_units: int = Field(ge=0)
    worker_compute_units: int = Field(ge=0)
    compute_units: int = Field(ge=0)
    context_bytes: int = Field(ge=0)
    duplicate_work_units: int = Field(ge=0)
    stale_rejections: int = Field(ge=0)
    worker_rejections: int = Field(ge=0)
    unnecessary_spawns: int = Field(ge=0)
    changed_basis_respawns: int = Field(ge=0)
    contradictions_detected: int = Field(ge=0)
    contradictions_resolved: int = Field(ge=0)
    user_voice_violations: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        if self.verified_required_evidence_count > self.required_evidence_count:
            raise ValueError("verified required evidence cannot exceed the requirement")
        expected_coverage = (
            1000
            if self.required_evidence_count == 0
            else self.verified_required_evidence_count
            * 1000
            // self.required_evidence_count
        )
        if self.required_evidence_coverage_milli != expected_coverage:
            raise ValueError("required evidence coverage does not match evidence counts")
        if self.contradictions_resolved > self.contradictions_detected:
            raise ValueError("resolved contradictions cannot exceed detected contradictions")
        if self.compute_units != self.root_compute_units + self.worker_compute_units:
            raise ValueError("compute units must equal root plus worker accounting")
        return self

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def unresolved_contradictions(self) -> int:
        return self.contradictions_detected - self.contradictions_resolved


class ShadowEvidenceReference(C011ContractModel):
    locator: str = Field(min_length=1, max_length=2000)
    content_sha256: Sha256


class ShadowRunObservation(C011ContractModel):
    """Hash-only output observation bound to one frozen plan and case."""

    observation_id: str = ""
    plan_id: str = Field(pattern=r"^c011-shadow-plan:sha256:[0-9a-f]{64}$")
    slot_id: str = Field(pattern=r"^c011-shadow-slot:sha256:[0-9a-f]{64}$")
    case_id: str = Field(min_length=1, max_length=300)
    repetition: int = Field(ge=1)
    configuration: ShadowConfiguration
    execution_configuration_sha256: Sha256
    evidence_kind: ShadowEvidenceKind
    result_sha256: Sha256
    evaluator_evidence_refs: tuple[ShadowEvidenceReference, ...] = Field(
        min_length=1,
        max_length=128,
    )
    metrics: ShadowMetricObservation
    raw_output_persisted: Literal[False] = False
    shadow_output_to_task_state: Literal[False] = False
    root_context_adoption_authority: Literal[False] = False
    task_state_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("evaluator_evidence_refs")
    @classmethod
    def normalize_evidence_refs(
        cls,
        values: tuple[ShadowEvidenceReference, ...],
    ) -> tuple[ShadowEvidenceReference, ...]:
        locators = tuple(item.locator for item in values)
        if len(locators) != len(set(locators)):
            raise ValueError("shadow evaluator evidence locators must be unique")
        return tuple(
            sorted(values, key=lambda item: (item.locator, item.content_sha256))
        )

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if (
            self.configuration is not ShadowConfiguration.PARALLEL
            and self.metrics.worker_compute_units != 0
        ):
            raise ValueError("solo observations cannot report worker compute")
        expected = _content_identity(
            self,
            identity_field="observation_id",
            prefix="c011-shadow-observation:sha256:",
        )
        if not self.observation_id:
            object.__setattr__(self, "observation_id", expected)
        elif self.observation_id != expected:
            raise ValueError("shadow observation ID does not match canonical content")
        return self


class ShadowMetricDelta(C011ContractModel):
    """Signed configuration delta relative to SOLO."""

    configuration: ShadowConfiguration
    quality_score_milli: int
    verified_required_evidence_count: int
    required_evidence_coverage_milli: int
    latency_ms: int
    total_tokens: int
    tool_calls: int
    compute_units: int
    context_bytes: int
    duplicate_work_units: int
    stale_rejections: int
    worker_rejections: int
    unnecessary_spawns: int
    changed_basis_respawns: int
    unresolved_contradictions: int
    user_voice_violations: int

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        if self.configuration is ShadowConfiguration.SOLO:
            raise ValueError("SOLO cannot have a delta relative to itself")
        return self


class ShadowEvaluationComparison(C011ContractModel):
    """One case comparison that is permanently non-authoritative in S5C."""

    comparison_id: str = ""
    plan_id: str = Field(pattern=r"^c011-shadow-plan:sha256:[0-9a-f]{64}$")
    case_id: str = Field(min_length=1, max_length=300)
    repetition: int = Field(ge=1)
    observation_ids: tuple[str, ...] = Field(default=(), max_length=128)
    evidence_kinds: tuple[ShadowEvidenceKind, ...] = Field(default=(), max_length=2)
    status: ShadowComparisonStatus
    blocked_reasons: tuple[str, ...] = ()
    deltas_vs_solo: tuple[ShadowMetricDelta, ...] = ()
    equal_compute_budget_shared: Literal[True] = True
    non_inferiority_established: Literal[False] = False
    shadow_output_to_task_state: Literal[False] = False
    root_context_adoption_authority: Literal[False] = False
    task_state_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("observation_ids")
    @classmethod
    def validate_observation_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("shadow comparison observation IDs must be unique")
        if any(
            not value.startswith("c011-shadow-observation:sha256:") for value in values
        ):
            raise ValueError("invalid shadow observation ID")
        return values

    @field_validator("evidence_kinds")
    @classmethod
    def normalize_evidence_kinds(
        cls,
        values: tuple[ShadowEvidenceKind, ...],
    ) -> tuple[ShadowEvidenceKind, ...]:
        if len(values) != len(set(values)):
            raise ValueError("shadow comparison evidence kinds must be unique")
        return tuple(sorted(values, key=lambda item: item.value))

    @field_validator("blocked_reasons")
    @classmethod
    def normalize_blocked_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_unique_text(values, label="shadow comparison blocked reasons")

    @model_validator(mode="after")
    def validate_comparison(self) -> Self:
        if self.status is ShadowComparisonStatus.COMPARABLE:
            if self.blocked_reasons:
                raise ValueError("comparable shadow result cannot have blocked reasons")
            if len(self.observation_ids) != 3 or len(self.deltas_vs_solo) != 2:
                raise ValueError("comparable shadow result requires the complete triplet")
            if tuple(item.configuration for item in self.deltas_vs_solo) != (
                ShadowConfiguration.ULTRA_SOLO,
                ShadowConfiguration.PARALLEL,
            ):
                raise ValueError("shadow deltas must use canonical non-SOLO order")
            if len(self.evidence_kinds) != 1:
                raise ValueError("comparable shadow result cannot mix evidence kinds")
        else:
            if not self.blocked_reasons:
                raise ValueError("blocked shadow result requires a reason")
            if self.deltas_vs_solo:
                raise ValueError("blocked shadow result cannot publish deltas")
        expected = _content_identity(
            self,
            identity_field="comparison_id",
            prefix="c011-shadow-comparison:sha256:",
        )
        if not self.comparison_id:
            object.__setattr__(self, "comparison_id", expected)
        elif self.comparison_id != expected:
            raise ValueError("shadow comparison ID does not match canonical content")
        return self


def _budget_blockers(
    budget: EqualComputeBudget,
    observation: ShadowRunObservation,
) -> tuple[str, ...]:
    metrics = observation.metrics
    prefix = observation.configuration.value
    limits = (
        (metrics.total_tokens, budget.max_total_tokens, "total token"),
        (metrics.tool_calls, budget.max_tool_calls, "tool-call"),
        (metrics.compute_units, budget.max_compute_units, "compute-unit"),
        (metrics.context_bytes, budget.max_context_bytes, "context-byte"),
        (metrics.latency_ms, budget.max_wall_time_ms, "wall-time"),
    )
    return tuple(
        f"{prefix} exceeded {label} budget"
        for actual, ceiling, label in limits
        if actual > ceiling
    )


def _metric_delta(
    configuration: ShadowConfiguration,
    candidate: ShadowMetricObservation,
    solo: ShadowMetricObservation,
) -> ShadowMetricDelta:
    return ShadowMetricDelta(
        configuration=configuration,
        quality_score_milli=candidate.quality_score_milli - solo.quality_score_milli,
        verified_required_evidence_count=(
            candidate.verified_required_evidence_count
            - solo.verified_required_evidence_count
        ),
        required_evidence_coverage_milli=(
            candidate.required_evidence_coverage_milli
            - solo.required_evidence_coverage_milli
        ),
        latency_ms=candidate.latency_ms - solo.latency_ms,
        total_tokens=candidate.total_tokens - solo.total_tokens,
        tool_calls=candidate.tool_calls - solo.tool_calls,
        compute_units=candidate.compute_units - solo.compute_units,
        context_bytes=candidate.context_bytes - solo.context_bytes,
        duplicate_work_units=candidate.duplicate_work_units - solo.duplicate_work_units,
        stale_rejections=candidate.stale_rejections - solo.stale_rejections,
        worker_rejections=candidate.worker_rejections - solo.worker_rejections,
        unnecessary_spawns=candidate.unnecessary_spawns - solo.unnecessary_spawns,
        changed_basis_respawns=(
            candidate.changed_basis_respawns - solo.changed_basis_respawns
        ),
        unresolved_contradictions=(
            candidate.unresolved_contradictions - solo.unresolved_contradictions
        ),
        user_voice_violations=(
            candidate.user_voice_violations - solo.user_voice_violations
        ),
    )


def compare_shadow_observations(
    *,
    plan: ShadowEvaluationPlan,
    case_id: str,
    repetition: int,
    observations: Sequence[ShadowRunObservation],
) -> ShadowEvaluationComparison:
    """Compare supplied observations without executing or authorizing anything."""

    current_plan = ShadowEvaluationPlan.model_validate(plan.model_dump(mode="json"))
    current = tuple(
        ShadowRunObservation.model_validate(item.model_dump(mode="json"))
        for item in observations
    )
    expected_case_id = case_id.strip()
    if not expected_case_id:
        raise ValueError("shadow comparison case ID cannot be blank")
    if repetition < 1:
        raise ValueError("shadow comparison repetition must be positive")

    reasons: list[str] = []
    if expected_case_id not in current_plan.evaluation_suite.case_ids:
        reasons.append("case is not part of the frozen evaluation suite")
    if len(current) != 3:
        reasons.append("comparison requires exactly three observations")
    if any(item.plan_id != current_plan.plan_id for item in current):
        reasons.append("observation plan binding mismatch")
    if any(item.case_id != expected_case_id for item in current):
        reasons.append("observation case binding mismatch")
    if any(item.repetition != repetition for item in current):
        reasons.append("observation repetition binding mismatch")

    by_configuration: dict[ShadowConfiguration, ShadowRunObservation] = {}
    slots = {
        (slot.case_id, slot.repetition, slot.configuration): slot
        for slot in current_plan.run_slots
    }
    arms = {arm.configuration: arm for arm in current_plan.arms}
    for observation in current:
        if observation.configuration in by_configuration:
            reasons.append("comparison contains a duplicate configuration")
        else:
            by_configuration[observation.configuration] = observation
        slot = slots.get(
            (observation.case_id, observation.repetition, observation.configuration)
        )
        if slot is None or observation.slot_id != slot.slot_id:
            reasons.append("observation run-slot binding mismatch")
        arm = arms[observation.configuration]
        if (
            observation.execution_configuration_sha256
            != arm.execution_configuration_sha256
        ):
            reasons.append("observation arm configuration binding mismatch")
        reasons.extend(_budget_blockers(current_plan.equal_compute_budget, observation))
    if set(by_configuration) != set(_CONFIGURATION_ORDER):
        reasons.append("comparison requires SOLO, ULTRA_SOLO and PARALLEL")
    if current_plan.contamination_report.contaminated:
        reasons.append("frozen evaluation suite has contamination findings")
    if not current_plan.contamination_provenance_complete:
        reasons.append("contamination provenance is incomplete")
    if not current_plan.evaluator_independence_verified:
        reasons.append("evaluator independence evidence is incomplete")

    evidence_kinds = tuple(
        sorted({item.evidence_kind for item in current}, key=lambda item: item.value)
    )
    if len(evidence_kinds) > 1:
        reasons.append("comparison cannot mix fixture and real-provider evidence")
    if len({item.metrics.compute_units for item in current}) > 1:
        reasons.append("normalized whole-arm compute totals are not equal")

    ordered = tuple(
        sorted(
            current,
            key=lambda item: (
                _CONFIGURATION_ORDER.index(item.configuration),
                item.observation_id,
            ),
        )
    )
    ordered_observation_ids = tuple(
        dict.fromkeys(item.observation_id for item in ordered)
    )
    blocked_reasons = tuple(sorted(set(reasons)))
    if blocked_reasons:
        return ShadowEvaluationComparison(
            plan_id=current_plan.plan_id,
            case_id=expected_case_id,
            repetition=repetition,
            observation_ids=ordered_observation_ids,
            evidence_kinds=evidence_kinds,
            status=ShadowComparisonStatus.BLOCKED,
            blocked_reasons=blocked_reasons,
        )

    solo = by_configuration[ShadowConfiguration.SOLO].metrics
    deltas = tuple(
        _metric_delta(configuration, by_configuration[configuration].metrics, solo)
        for configuration in (
            ShadowConfiguration.ULTRA_SOLO,
            ShadowConfiguration.PARALLEL,
        )
    )
    return ShadowEvaluationComparison(
        plan_id=current_plan.plan_id,
        case_id=expected_case_id,
        repetition=repetition,
        observation_ids=ordered_observation_ids,
        evidence_kinds=evidence_kinds,
        status=ShadowComparisonStatus.COMPARABLE,
        deltas_vs_solo=deltas,
    )


class ShadowLedgerError(RuntimeError):
    pass


class ShadowLedgerConflictError(ShadowLedgerError):
    pass


class ShadowLedgerIntegrityError(ShadowLedgerError):
    pass


ShadowArtifact = ShadowEvaluationPlan | ShadowRunObservation | ShadowEvaluationComparison

_SCHEMA = """
CREATE TABLE shadow_entries (
    sequence INTEGER PRIMARY KEY,
    artifact_kind TEXT NOT NULL CHECK (artifact_kind IN ('PLAN', 'OBSERVATION', 'COMPARISON')),
    artifact_id TEXT NOT NULL UNIQUE,
    artifact_json TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    previous_entry_sha256 TEXT NOT NULL,
    entry_sha256 TEXT NOT NULL UNIQUE
);
"""


def _artifact_kind(artifact: ShadowArtifact) -> ShadowArtifactKind:
    if isinstance(artifact, ShadowEvaluationPlan):
        return ShadowArtifactKind.PLAN
    if isinstance(artifact, ShadowRunObservation):
        return ShadowArtifactKind.OBSERVATION
    return ShadowArtifactKind.COMPARISON


def _artifact_id(artifact: ShadowArtifact) -> str:
    if isinstance(artifact, ShadowEvaluationPlan):
        return artifact.plan_id
    if isinstance(artifact, ShadowRunObservation):
        return artifact.observation_id
    return artifact.comparison_id


def _parse_artifact(kind: ShadowArtifactKind, payload: str) -> ShadowArtifact:
    if kind is ShadowArtifactKind.PLAN:
        return ShadowEvaluationPlan.model_validate_json(payload)
    if kind is ShadowArtifactKind.OBSERVATION:
        return ShadowRunObservation.model_validate_json(payload)
    return ShadowEvaluationComparison.model_validate_json(payload)


def _entry_sha256(
    *,
    sequence: int,
    artifact_kind: ShadowArtifactKind,
    artifact_id: str,
    artifact_sha256: str,
    previous_entry_sha256: str,
) -> str:
    return sha256(
        _canonical_json(
            {
                "sequence": sequence,
                "artifact_kind": artifact_kind.value,
                "artifact_id": artifact_id,
                "artifact_sha256": artifact_sha256,
                "previous_entry_sha256": previous_entry_sha256,
            }
        ).encode("utf-8")
    ).hexdigest()


class SQLiteShadowEvaluationLedger:
    """Append-only hash-chained S5C ledger with no runtime integration surface."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path).resolve()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ShadowLedgerError("failed to create S5C ledger directory") from exc
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA busy_timeout = 5000")
            row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
            if row is None or str(row[0]).casefold() != "wal":
                raise ShadowLedgerError("S5C ledger did not enable WAL")
            return connection
        except ShadowLedgerError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            raise ShadowLedgerError("failed to open S5C ledger") from exc

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        except ShadowLedgerError:
            raise
        except sqlite3.DatabaseError as exc:
            raise ShadowLedgerError("S5C ledger read failed") from exc
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._read_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._verify_connection(connection)
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize(self) -> None:
        with self._read_connection() as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
            if row is None:
                raise ShadowLedgerError("S5C ledger version is unavailable")
            version = int(row[0])
            tables = frozenset(
                str(item[0])
                for item in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            )
            if version == 0:
                if tables:
                    raise ShadowLedgerError("unversioned S5C ledger contains tables")
                connection.executescript(_SCHEMA)
                connection.execute(
                    f"PRAGMA user_version = {S5C_SHADOW_LEDGER_SCHEMA_VERSION}"
                )
            elif version != S5C_SHADOW_LEDGER_SCHEMA_VERSION or tables != {
                "shadow_entries"
            }:
                raise ShadowLedgerError(
                    f"unsupported S5C ledger schema: version={version}, tables={tables}"
                )
            connection.commit()
            self._verify_connection(connection)

    @staticmethod
    def _row_artifact(row: sqlite3.Row) -> ShadowArtifact:
        try:
            return _parse_artifact(
                ShadowArtifactKind(str(row["artifact_kind"])),
                str(row["artifact_json"]),
            )
        except (TypeError, ValueError) as exc:
            raise ShadowLedgerIntegrityError("invalid S5C artifact row") from exc

    @staticmethod
    def _lookup_artifact(
        connection: sqlite3.Connection,
        artifact_id: str,
    ) -> ShadowArtifact | None:
        row = connection.execute(
            "SELECT * FROM shadow_entries WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        return None if row is None else SQLiteShadowEvaluationLedger._row_artifact(row)

    def _verify_connection(self, connection: sqlite3.Connection) -> None:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or str(integrity[0]).casefold() != "ok":
            raise ShadowLedgerIntegrityError("SQLite integrity check failed")
        rows = tuple(
            connection.execute("SELECT * FROM shadow_entries ORDER BY sequence")
        )
        plans: dict[str, ShadowEvaluationPlan] = {}
        observations: dict[str, ShadowRunObservation] = {}
        observation_slots: dict[tuple[str, str], str] = {}
        referenced_observations: set[str] = set()
        comparison_keys: set[tuple[str, str, int]] = set()
        previous = _ZERO_SHA256
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            if sequence != expected_sequence:
                raise ShadowLedgerIntegrityError("S5C ledger sequence is not contiguous")
            artifact_json = str(row["artifact_json"])
            artifact = self._row_artifact(row)
            kind = _artifact_kind(artifact)
            identity = _artifact_id(artifact)
            digest = sha256(artifact_json.encode("utf-8")).hexdigest()
            if str(row["artifact_kind"]) != kind.value:
                raise ShadowLedgerIntegrityError("S5C artifact kind mismatch")
            if str(row["artifact_id"]) != identity:
                raise ShadowLedgerIntegrityError("S5C artifact identity mismatch")
            if str(row["artifact_sha256"]) != digest:
                raise ShadowLedgerIntegrityError("S5C artifact digest mismatch")
            if str(row["previous_entry_sha256"]) != previous:
                raise ShadowLedgerIntegrityError("S5C ledger hash chain is broken")
            expected_entry = _entry_sha256(
                sequence=sequence,
                artifact_kind=kind,
                artifact_id=identity,
                artifact_sha256=digest,
                previous_entry_sha256=previous,
            )
            if str(row["entry_sha256"]) != expected_entry:
                raise ShadowLedgerIntegrityError("S5C ledger entry digest mismatch")

            if isinstance(artifact, ShadowEvaluationPlan):
                plans[artifact.plan_id] = artifact
            elif isinstance(artifact, ShadowRunObservation):
                plan = plans.get(artifact.plan_id)
                if plan is None or artifact.case_id not in plan.evaluation_suite.case_ids:
                    raise ShadowLedgerIntegrityError(
                        "S5C observation lacks prior frozen plan provenance"
                    )
                previous_observation = observation_slots.setdefault(
                    (artifact.plan_id, artifact.slot_id),
                    artifact.observation_id,
                )
                if previous_observation != artifact.observation_id:
                    raise ShadowLedgerIntegrityError(
                        "S5C run slot contains conflicting observations"
                    )
                observations[artifact.observation_id] = artifact
            else:
                comparison_key = (
                    artifact.plan_id,
                    artifact.case_id,
                    artifact.repetition,
                )
                if comparison_key in comparison_keys:
                    raise ShadowLedgerIntegrityError("duplicate S5C comparison run key")
                comparison_keys.add(comparison_key)
                plan = plans.get(artifact.plan_id)
                selected = tuple(
                    observations.get(observation_id)
                    for observation_id in artifact.observation_ids
                )
                if (
                    plan is None
                    or len(selected) != 3
                    or any(item is None for item in selected)
                ):
                    raise ShadowLedgerIntegrityError(
                        "S5C comparison lacks one complete observation triplet"
                    )
                complete = cast(tuple[ShadowRunObservation, ...], selected)
                if {item.configuration for item in complete} != set(
                    _CONFIGURATION_ORDER
                ):
                    raise ShadowLedgerIntegrityError(
                        "S5C comparison does not bind the three required arms"
                    )
                rebuilt = compare_shadow_observations(
                    plan=plan,
                    case_id=artifact.case_id,
                    repetition=artifact.repetition,
                    observations=complete,
                )
                if canonical_contract_json(rebuilt) != canonical_contract_json(artifact):
                    raise ShadowLedgerIntegrityError(
                        "S5C comparison does not match stored observations"
                    )
                referenced_observations.update(artifact.observation_ids)
            previous = expected_entry
        if set(observations) != referenced_observations:
            raise ShadowLedgerIntegrityError(
                "S5C ledger contains an incomplete observation triplet"
            )

    def verify_integrity(self) -> None:
        with self._read_connection() as connection:
            self._verify_connection(connection)

    @staticmethod
    def _append_in_connection(
        connection: sqlite3.Connection,
        artifact: ShadowArtifact,
    ) -> ShadowArtifact:
        validated = _parse_artifact(
            _artifact_kind(artifact),
            canonical_contract_json(artifact),
        )
        identity = _artifact_id(validated)
        kind = _artifact_kind(validated)
        artifact_json = canonical_contract_json(validated)
        artifact_digest = sha256(artifact_json.encode("utf-8")).hexdigest()
        existing = connection.execute(
            "SELECT artifact_json FROM shadow_entries WHERE artifact_id = ?",
            (identity,),
        ).fetchone()
        if existing is not None:
            if str(existing["artifact_json"]) != artifact_json:
                raise ShadowLedgerConflictError("S5C artifact identity conflict")
            return validated
        tail = connection.execute(
            "SELECT sequence, entry_sha256 FROM shadow_entries "
            "ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = 1 if tail is None else int(tail["sequence"]) + 1
        previous = _ZERO_SHA256 if tail is None else str(tail["entry_sha256"])
        entry_digest = _entry_sha256(
            sequence=sequence,
            artifact_kind=kind,
            artifact_id=identity,
            artifact_sha256=artifact_digest,
            previous_entry_sha256=previous,
        )
        connection.execute(
            "INSERT INTO shadow_entries "
            "(sequence, artifact_kind, artifact_id, artifact_json, artifact_sha256, "
            "previous_entry_sha256, entry_sha256) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sequence,
                kind.value,
                identity,
                artifact_json,
                artifact_digest,
                previous,
                entry_digest,
            ),
        )
        return validated

    def _append(self, artifact: ShadowArtifact) -> ShadowArtifact:
        with self._transaction() as connection:
            validated = self._append_in_connection(connection, artifact)
            self._verify_connection(connection)
        return validated

    def append_plan(self, plan: ShadowEvaluationPlan) -> ShadowEvaluationPlan:
        return cast(ShadowEvaluationPlan, self._append(plan))

    def append_completed_run(
        self,
        *,
        plan: ShadowEvaluationPlan,
        observations: Sequence[ShadowRunObservation],
        comparison: ShadowEvaluationComparison,
    ) -> ShadowEvaluationComparison:
        current_plan = ShadowEvaluationPlan.model_validate(plan.model_dump(mode="json"))
        current_observations = tuple(
            ShadowRunObservation.model_validate(item.model_dump(mode="json"))
            for item in observations
        )
        if len(current_observations) != 3 or {
            item.configuration for item in current_observations
        } != set(_CONFIGURATION_ORDER):
            raise ShadowLedgerConflictError(
                "S5C completed run requires exactly one observation per arm"
            )
        current = ShadowEvaluationComparison.model_validate(
            comparison.model_dump(mode="json")
        )
        rebuilt = compare_shadow_observations(
            plan=current_plan,
            case_id=current.case_id,
            repetition=current.repetition,
            observations=current_observations,
        )
        if canonical_contract_json(rebuilt) != canonical_contract_json(current):
            raise ShadowLedgerConflictError(
                "S5C comparison does not match supplied observations"
            )
        with self._transaction() as connection:
            self._append_in_connection(connection, current_plan)
            existing_rows = tuple(
                connection.execute(
                    "SELECT * FROM shadow_entries WHERE artifact_kind = 'COMPARISON'"
                )
            )
            for row in existing_rows:
                existing = cast(ShadowEvaluationComparison, self._row_artifact(row))
                if (
                    existing.plan_id == current.plan_id
                    and existing.case_id == current.case_id
                    and existing.repetition == current.repetition
                    and existing.comparison_id != current.comparison_id
                ):
                    raise ShadowLedgerConflictError("conflicting S5C comparison run key")
            existing_observations = tuple(
                cast(ShadowRunObservation, self._row_artifact(row))
                for row in connection.execute(
                    "SELECT * FROM shadow_entries WHERE artifact_kind = 'OBSERVATION'"
                )
            )
            by_slot = {
                (item.plan_id, item.slot_id): item.observation_id
                for item in existing_observations
            }
            for observation in current_observations:
                prior = by_slot.get((observation.plan_id, observation.slot_id))
                if prior is not None and prior != observation.observation_id:
                    raise ShadowLedgerConflictError("conflicting S5C run-slot replay")
            for observation in sorted(
                current_observations,
                key=lambda item: _CONFIGURATION_ORDER.index(item.configuration),
            ):
                self._append_in_connection(connection, observation)
            validated = self._append_in_connection(connection, current)
            self._verify_connection(connection)
        return cast(ShadowEvaluationComparison, validated)

    def entry_count(self) -> int:
        with self._read_connection() as connection:
            self._verify_connection(connection)
            row = connection.execute("SELECT COUNT(*) FROM shadow_entries").fetchone()
            if row is None:
                raise ShadowLedgerIntegrityError("S5C ledger count is unavailable")
            return int(row[0])

    def observations(
        self,
        *,
        plan_id: str,
        case_id: str,
        repetition: int,
    ) -> tuple[ShadowRunObservation, ...]:
        with self._read_connection() as connection:
            self._verify_connection(connection)
            rows = tuple(
                connection.execute(
                    "SELECT * FROM shadow_entries WHERE artifact_kind = 'OBSERVATION' "
                    "ORDER BY sequence"
                )
            )
        selected = tuple(
            cast(ShadowRunObservation, self._row_artifact(row)) for row in rows
        )
        return tuple(
            sorted(
                (
                    item
                    for item in selected
                    if item.plan_id == plan_id and item.case_id == case_id
                    and item.repetition == repetition
                ),
                key=lambda item: _CONFIGURATION_ORDER.index(item.configuration),
            )
        )


__all__ = [
    "S5C_METRIC_SCHEMA_REVISION",
    "S5C_SHADOW_LEDGER_SCHEMA_VERSION",
    "EqualComputeBudget",
    "SQLiteShadowEvaluationLedger",
    "ShadowArmSpec",
    "ShadowArtifactKind",
    "ShadowComparisonStatus",
    "ShadowConfiguration",
    "ShadowEvaluationComparison",
    "ShadowEvaluationPlan",
    "ShadowEvidenceKind",
    "ShadowEvidenceReference",
    "ShadowLedgerConflictError",
    "ShadowLedgerError",
    "ShadowLedgerIntegrityError",
    "ShadowMetricDelta",
    "ShadowMetricObservation",
    "ShadowRunObservation",
    "ShadowRunSlot",
    "compare_shadow_observations",
]
