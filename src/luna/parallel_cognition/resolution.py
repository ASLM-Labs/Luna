"""Authoritative, fail-closed S3 resolution of typed worker citations.

Provider records contain authoritative bytes.  Digests are recomputed here instead of
being echoed from a worker or caller.  Receipts contain only identities, revisions,
digests, currentness and provenance; raw source content and hidden reasoning are never
persisted or passed to root context.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import ClassVar, Literal, Protocol, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import require_utc
from luna.parallel_cognition.controls import (
    ControlDisposition,
    ControlFencePhase,
    FenceDecision,
)
from luna.parallel_cognition.events import FakeBackendResult
from luna.parallel_cognition.models import (
    AgentExecutionAttempt,
    AgentExecutionReceipt,
    AgentLifecycleState,
    C011ContractModel,
    ClaimFreshness,
    ClaimRecord,
    ClaimSupportDisposition,
    CleanupState,
    ContextFreshness,
    ContextSourceReference,
    ContradictionState,
    EvidenceResolutionState,
    ProposedClaim,
    RedactionState,
    ResolvedEvidenceLineage,
    Sha256,
    canonical_contract_json,
    contract_sha256,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def claim_resolution_subject_sha256(
    *,
    result: FakeBackendResult,
    receipt: AgentExecutionReceipt,
    claim: ProposedClaim,
) -> str:
    """Bind the pre-adoption fence to one exact result, receipt, and claim."""

    basis = {
        "contract_type": "c011-claim-resolution-subject-v1",
        "result_sha256": contract_sha256(FakeBackendResult.model_validate(result)),
        "receipt_sha256": contract_sha256(AgentExecutionReceipt.model_validate(receipt)),
        "claim_sha256": contract_sha256(ProposedClaim.model_validate(claim)),
    }
    return sha256(_canonical_json(basis).encode("utf-8")).hexdigest()


def _normalized(
    values: tuple[str, ...],
    *,
    label: str,
    require_nonempty: bool = False,
) -> tuple[str, ...]:
    cleaned = tuple(item.strip() for item in values)
    if require_nonempty and not cleaned:
        raise ValueError(f"{label} must not be empty")
    if any(not item for item in cleaned):
        raise ValueError(f"{label} cannot contain blank values")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(cleaned))


class _ContentAddressedS3Contract(C011ContractModel):
    _identity_field: ClassVar[str]
    _identity_prefix: ClassVar[str]

    @model_validator(mode="after")
    def validate_content_identity(self) -> Self:
        payload = self.model_dump(mode="json", exclude={self._identity_field})
        basis = {
            "contract_type": f"{type(self).__module__}.{type(self).__qualname__}",
            "schema_version": self.schema_version,
            "payload": payload,
        }
        expected = (
            self._identity_prefix + sha256(_canonical_json(basis).encode("utf-8")).hexdigest()
        )
        supplied = getattr(self, self._identity_field)
        if not supplied:
            object.__setattr__(self, self._identity_field, expected)
        elif supplied != expected:
            raise ValueError(f"{self._identity_field} does not match canonical contract content")
        return self


class ReferenceKind(StrEnum):
    """Authoritative namespace used for one citation lookup."""

    SOURCE = "SOURCE"
    EVIDENCE = "EVIDENCE"
    OBSERVATION = "OBSERVATION"


class ArtifactCurrentness(StrEnum):
    """Provider currentness with no permissive UNKNOWN state."""

    CURRENT = "CURRENT"
    STALE = "STALE"


class ResolutionStatus(StrEnum):
    """Closed, fail-closed result for one typed reference."""

    RESOLVED_CURRENT = "RESOLVED_CURRENT"
    MISSING = "MISSING"
    STALE = "STALE"
    AMBIGUOUS = "AMBIGUOUS"
    UNBOUND = "UNBOUND"
    DIGEST_CHANGED = "DIGEST_CHANGED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"


class AuthoritativeSourceBinding(C011ContractModel):
    """Exact source identity claimed by evidence or observation."""

    task_id: UUID
    source_task_revision: int = Field(ge=0)
    source_ref: str = Field(min_length=1, max_length=2000)
    source_identity: str = Field(min_length=1, max_length=2000)
    source_revision: str = Field(min_length=1, max_length=500)
    content_sha256: Sha256


class AuthoritativeSourceRecord(C011ContractModel):
    """Source-store record whose bytes are hashed by the resolver."""

    task_id: UUID
    source_task_revision: int = Field(ge=0)
    source_ref: str = Field(min_length=1, max_length=2000)
    source_identity: str = Field(min_length=1, max_length=2000)
    source_revision: str = Field(min_length=1, max_length=500)
    content: bytes = Field(min_length=1, repr=False)
    currentness: ArtifactCurrentness
    currentness_checked_at: datetime
    provenance_refs: tuple[str, ...] = Field(min_length=1, max_length=128)

    @field_validator("currentness_checked_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("provenance_refs")
    @classmethod
    def normalize_provenance(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized(values, label="source provenance", require_nonempty=True)

    @property
    def content_sha256(self) -> str:
        return sha256(self.content).hexdigest()

    @property
    def binding(self) -> AuthoritativeSourceBinding:
        return AuthoritativeSourceBinding(
            task_id=self.task_id,
            source_task_revision=self.source_task_revision,
            source_ref=self.source_ref,
            source_identity=self.source_identity,
            source_revision=self.source_revision,
            content_sha256=self.content_sha256,
        )


class AuthoritativeEvidenceRecord(C011ContractModel):
    """Evidence-store record with an exact claimed source binding."""

    task_id: UUID
    source_task_revision: int = Field(ge=0)
    evidence_ref: str = Field(min_length=1, max_length=2000)
    evidence_identity: str = Field(min_length=1, max_length=2000)
    evidence_revision: str = Field(min_length=1, max_length=500)
    content: bytes = Field(min_length=1, repr=False)
    source: AuthoritativeSourceBinding
    currentness: ArtifactCurrentness
    currentness_checked_at: datetime
    provenance_refs: tuple[str, ...] = Field(min_length=1, max_length=128)

    @field_validator("currentness_checked_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("provenance_refs")
    @classmethod
    def normalize_provenance(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized(values, label="evidence provenance", require_nonempty=True)

    @property
    def content_sha256(self) -> str:
        return sha256(self.content).hexdigest()


class AuthoritativeObservationRecord(C011ContractModel):
    """Observation-store record with an exact claimed source binding."""

    task_id: UUID
    source_task_revision: int = Field(ge=0)
    observation_ref: str = Field(min_length=1, max_length=2000)
    observation_identity: str = Field(min_length=1, max_length=2000)
    observation_revision: str = Field(min_length=1, max_length=500)
    content: bytes = Field(min_length=1, repr=False)
    source: AuthoritativeSourceBinding
    currentness: ArtifactCurrentness
    currentness_checked_at: datetime
    provenance_refs: tuple[str, ...] = Field(min_length=1, max_length=128)

    @field_validator("currentness_checked_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("provenance_refs")
    @classmethod
    def normalize_provenance(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized(values, label="observation provenance", require_nonempty=True)

    @property
    def content_sha256(self) -> str:
        return sha256(self.content).hexdigest()


class AuthoritativeSourceProvider(Protocol):
    @property
    def provider_ref(self) -> str: ...

    def resolve_source(
        self,
        *,
        task_id: UUID,
        source_task_revision: int,
        source_ref: str,
    ) -> tuple[AuthoritativeSourceRecord, ...]: ...


class AuthoritativeEvidenceProvider(Protocol):
    @property
    def provider_ref(self) -> str: ...

    def resolve_evidence(
        self,
        *,
        task_id: UUID,
        source_task_revision: int,
        evidence_ref: str,
    ) -> tuple[AuthoritativeEvidenceRecord, ...]: ...


class AuthoritativeObservationProvider(Protocol):
    @property
    def provider_ref(self) -> str: ...

    def resolve_observation(
        self,
        *,
        task_id: UUID,
        source_task_revision: int,
        observation_ref: str,
    ) -> tuple[AuthoritativeObservationRecord, ...]: ...


class AuthoritativeAttemptProvider(Protocol):
    """Read the durable current attempt head; result-contained snapshots are untrusted."""

    @property
    def provider_ref(self) -> str: ...

    def resolve_attempt(
        self,
        *,
        task_id: UUID,
        attempt_id: str,
    ) -> tuple[AgentExecutionAttempt, ...]: ...


class ReferenceResolutionReceipt(_ContentAddressedS3Contract):
    """Receipt for one exact typed citation and its independently resolved source."""

    _identity_field = "resolution_receipt_id"
    _identity_prefix = "c011-reference-resolution:sha256:"

    resolution_receipt_id: str = ""
    kind: ReferenceKind
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    attempt_id: str = Field(pattern=r"^attempt:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    payload_id: str = Field(pattern=r"^c011-payload:sha256:[0-9a-f]{64}$")
    claim_key: str = Field(min_length=1, max_length=500)
    requested_ref: str = Field(min_length=1, max_length=2000)
    status: ResolutionStatus
    provider_ref: str = Field(min_length=1, max_length=2000)
    source_provider_ref: str = Field(min_length=1, max_length=2000)
    candidate_count: int = Field(ge=0)
    source_candidate_count: int = Field(ge=0)
    resolved_task_id: UUID | None = None
    resolved_source_task_revision: int | None = Field(default=None, ge=0)
    resolved_identity: str | None = Field(default=None, max_length=2000)
    resolved_revision: str | None = Field(default=None, max_length=500)
    resolved_content_sha256: Sha256 | None = None
    resolved_currentness: ArtifactCurrentness | None = None
    source_ref: str | None = Field(default=None, max_length=2000)
    source_identity: str | None = Field(default=None, max_length=2000)
    source_revision: str | None = Field(default=None, max_length=500)
    source_content_sha256: Sha256 | None = None
    source_currentness: ArtifactCurrentness | None = None
    currentness_checked_at: datetime | None = None
    source_currentness_checked_at: datetime | None = None
    resolved_at: datetime
    result_admission_decision_id: str = Field(pattern=r"^c011-fence-decision:sha256:[0-9a-f]{64}$")
    pre_adoption_decision_id: str = Field(pattern=r"^c011-fence-decision:sha256:[0-9a-f]{64}$")
    provenance_refs: tuple[str, ...] = Field(min_length=1, max_length=256)
    eligible_for_claim_support: bool
    quarantine_required: bool
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    @field_validator(
        "currentness_checked_at",
        "source_currentness_checked_at",
        "resolved_at",
    )
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @field_validator("provenance_refs")
    @classmethod
    def normalize_provenance(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized(values, label="resolution provenance", require_nonempty=True)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        artifact = (
            self.resolved_task_id,
            self.resolved_source_task_revision,
            self.resolved_identity,
            self.resolved_revision,
            self.resolved_content_sha256,
            self.resolved_currentness,
            self.currentness_checked_at,
        )
        source = (
            self.source_ref,
            self.source_identity,
            self.source_revision,
            self.source_content_sha256,
            self.source_currentness,
            self.source_currentness_checked_at,
        )
        artifact_any = any(item is not None for item in artifact)
        artifact_all = all(item is not None for item in artifact)
        source_any = any(item is not None for item in source)
        source_all = all(item is not None for item in source)
        if artifact_any and not artifact_all:
            raise ValueError("resolved artifact identity must be complete or absent")
        if source_any and not source_all:
            raise ValueError("resolved source identity must be complete or absent")
        current = self.status is ResolutionStatus.RESOLVED_CURRENT
        if self.eligible_for_claim_support is not current:
            raise ValueError("claim-support eligibility must match resolution status")
        if self.quarantine_required is current:
            raise ValueError("current resolution cannot require quarantine")
        if current:
            if self.candidate_count != 1 or self.source_candidate_count != 1:
                raise ValueError("current resolution requires one artifact and source")
            if not artifact_all or not source_all:
                raise ValueError("current resolution requires complete exact bindings")
            if (
                self.resolved_currentness is not ArtifactCurrentness.CURRENT
                or self.source_currentness is not ArtifactCurrentness.CURRENT
            ):
                raise ValueError("current resolution requires current provider records")
        if self.status is ResolutionStatus.MISSING and not (
            self.candidate_count == 0
            or (self.candidate_count == 1 and self.source_candidate_count == 0)
        ):
            raise ValueError("missing resolution requires a missing artifact or source")
        if (
            self.status is ResolutionStatus.AMBIGUOUS
            and max(self.candidate_count, self.source_candidate_count) < 2
        ):
            raise ValueError("ambiguous resolution requires multiple candidates")
        for checked_at in (
            self.currentness_checked_at,
            self.source_currentness_checked_at,
        ):
            if checked_at is not None and checked_at > self.resolved_at:
                raise ValueError("provider currentness cannot be checked in the future")
        return self


class ClaimResolutionReceipt(_ContentAddressedS3Contract):
    """Exact qualified-or-quarantined claim result with no adoption authority."""

    _identity_field = "claim_resolution_id"
    _identity_prefix = "c011-claim-resolution:sha256:"

    claim_resolution_id: str = ""
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    attempt_id: str = Field(pattern=r"^attempt:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    attempt_integrity_id: str = Field(pattern=r"^c011-attempt-state:sha256:[0-9a-f]{64}$")
    context_manifest_sha256: Sha256
    payload_id: str = Field(pattern=r"^c011-payload:sha256:[0-9a-f]{64}$")
    payload_sha256: Sha256
    execution_receipt_id: str = Field(pattern=r"^c011-execution-receipt:sha256:[0-9a-f]{64}$")
    execution_receipt_sha256: Sha256
    result_id: str = Field(pattern=r"^c011-fake-result:sha256:[0-9a-f]{64}$")
    result_sha256: Sha256
    result_admission_decision_id: str = Field(pattern=r"^c011-fence-decision:sha256:[0-9a-f]{64}$")
    pre_adoption_decision_id: str = Field(pattern=r"^c011-fence-decision:sha256:[0-9a-f]{64}$")
    root_coordination_epoch: int = Field(ge=1)
    cancellation_epoch: int = Field(ge=0)
    claim_key: str = Field(min_length=1, max_length=500)
    statement: str = Field(min_length=1, max_length=4000)
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    observation_refs: tuple[str, ...] = ()
    reference_receipts: tuple[ReferenceResolutionReceipt, ...] = Field(
        min_length=1,
        max_length=384,
    )
    support_disposition: ClaimSupportDisposition
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=128)
    provenance_refs: tuple[str, ...] = Field(min_length=1, max_length=512)
    resolved_at: datetime
    root_consideration_eligible: bool
    quarantine_required: bool
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    @field_validator("resolved_at")
    @classmethod
    def validate_resolved_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("source_refs", "evidence_refs", "observation_refs")
    @classmethod
    def normalize_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized(values, label="claim references")

    @field_validator("reason_codes", "provenance_refs")
    @classmethod
    def normalize_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized(values, label="claim resolution entries", require_nonempty=True)

    @field_validator("reference_receipts")
    @classmethod
    def normalize_receipts(
        cls,
        values: tuple[ReferenceResolutionReceipt, ...],
    ) -> tuple[ReferenceResolutionReceipt, ...]:
        ids = tuple(item.resolution_receipt_id for item in values)
        if len(ids) != len(set(ids)):
            raise ValueError("reference resolution receipt IDs must be unique")
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    item.kind.value,
                    item.requested_ref,
                    item.resolution_receipt_id,
                ),
            )
        )

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        expected = {
            *[(ReferenceKind.SOURCE, item) for item in self.source_refs],
            *[(ReferenceKind.EVIDENCE, item) for item in self.evidence_refs],
            *[(ReferenceKind.OBSERVATION, item) for item in self.observation_refs],
        }
        actual = {(item.kind, item.requested_ref) for item in self.reference_receipts}
        if actual != expected or len(actual) != len(self.reference_receipts):
            raise ValueError("reference receipts must exhaust exact typed claim refs")
        for item in self.reference_receipts:
            if (
                item.task_id,
                item.source_task_revision,
                item.assignment_id,
                item.attempt_id,
                item.payload_id,
                item.claim_key,
                item.result_admission_decision_id,
                item.pre_adoption_decision_id,
                item.resolved_at,
            ) != (
                self.task_id,
                self.source_task_revision,
                self.assignment_id,
                self.attempt_id,
                self.payload_id,
                self.claim_key,
                self.result_admission_decision_id,
                self.pre_adoption_decision_id,
                self.resolved_at,
            ):
                raise ValueError("reference receipt is not bound to this exact claim")
        qualified = self.support_disposition is ClaimSupportDisposition.QUALIFIED
        all_current = all(item.eligible_for_claim_support for item in self.reference_receipts)
        if qualified is not all_current:
            raise ValueError("claim qualification must match every typed resolution")
        if self.root_consideration_eligible is not qualified:
            raise ValueError("root consideration eligibility must match qualification")
        if self.quarantine_required is qualified:
            raise ValueError("qualified claim cannot require quarantine")
        if qualified and self.reason_codes != ("ALL_REFERENCES_CURRENT",):
            raise ValueError("qualified claim requires exact current-resolution reason")
        return self

    def to_claim_record(self) -> ClaimRecord:
        """Distill qualified references only; raw payload text never crosses this API."""

        if self.support_disposition is not ClaimSupportDisposition.QUALIFIED:
            raise ValueError("only a qualified claim may enter a distilled handoff")
        lineage = tuple(
            ResolvedEvidenceLineage(
                task_id=self.task_id,
                source_task_revision=self.source_task_revision,
                evidence_ref=item.requested_ref,
                evidence_sha256=item.resolved_content_sha256,
                source_ref=item.source_ref or item.requested_ref,
                source_sha256=item.source_content_sha256,
                resolution_state=EvidenceResolutionState.RESOLVED_CURRENT,
                freshness_checked_at=self.resolved_at,
                resolver_ref=item.provider_ref,
                resolution_receipt_sha256=contract_sha256(item),
            )
            for item in self.reference_receipts
        )
        return ClaimRecord(
            task_id=self.task_id,
            source_task_revision=self.source_task_revision,
            assignment_id=self.assignment_id,
            attempt_id=self.attempt_id,
            payload_id=self.payload_id,
            source_claim_key=self.claim_key,
            statement=self.statement,
            support_disposition=ClaimSupportDisposition.QUALIFIED,
            evidence_lineage=lineage,
            freshness=ClaimFreshness.CURRENT,
            contradiction_state=ContradictionState.NONE,
            qualification_reason=(
                "Every exact typed citation resolved to one current authoritative record."
            ),
        )


def _provider_ref(provider: object, *, label: str) -> str:
    value = getattr(provider, "provider_ref", None)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} provider_ref must be a non-blank string")
    return value.strip()


def _safe_tuple[RecordT: C011ContractModel](
    call: Callable[[], tuple[RecordT, ...]],
    record_type: type[RecordT],
) -> tuple[RecordT, ...] | None:
    try:
        values = call()
        if not isinstance(values, tuple):
            return None
        return tuple(record_type.model_validate(item) for item in values)
    except Exception:
        return None


class AuthoritativeResolver:
    """Resolve one claim only after current durable runtime and control rechecks."""

    def __init__(
        self,
        *,
        source_provider: AuthoritativeSourceProvider,
        evidence_provider: AuthoritativeEvidenceProvider,
        observation_provider: AuthoritativeObservationProvider,
        attempt_provider: AuthoritativeAttemptProvider,
        resolver_ref: str,
    ) -> None:
        if not resolver_ref.strip():
            raise ValueError("resolver_ref must not be blank")
        self._source = source_provider
        self._evidence = evidence_provider
        self._observation = observation_provider
        self._attempt = attempt_provider
        self._source_ref = _provider_ref(source_provider, label="source")
        self._evidence_ref = _provider_ref(evidence_provider, label="evidence")
        self._observation_ref = _provider_ref(observation_provider, label="observation")
        self._attempt_ref = _provider_ref(attempt_provider, label="attempt")
        self._resolver_ref = resolver_ref.strip()

    def _current_attempt(
        self,
        result: FakeBackendResult,
    ) -> tuple[AgentExecutionAttempt | None, str | None]:
        candidates = _safe_tuple(
            lambda: self._attempt.resolve_attempt(
                task_id=result.request.assignment.task_id,
                attempt_id=result.request.attempt.attempt_id,
            ),
            AgentExecutionAttempt,
        )
        if candidates is None:
            return None, "ATTEMPT_PROVIDER_ERROR"
        if not candidates:
            return None, "CURRENT_ATTEMPT_MISSING"
        if len(candidates) != 1:
            return None, "CURRENT_ATTEMPT_AMBIGUOUS"
        return candidates[0], None

    @staticmethod
    def _preconditions(
        *,
        result: FakeBackendResult,
        receipt: AgentExecutionReceipt,
        current_attempt: AgentExecutionAttempt | None,
        claim: ProposedClaim,
        result_admission: FenceDecision,
        pre_adoption: FenceDecision,
        resolved_at: datetime,
    ) -> tuple[str, ...]:
        assignment = result.request.assignment
        started = result.request.attempt
        context = result.request.context
        payload = result.payload
        reasons: list[str] = []
        if (
            result_admission.phase is not ControlFencePhase.RESULT_ADMISSION
            or result_admission.disposition is not ControlDisposition.ALLOW
            or result_admission.result_sha256 != contract_sha256(result)
            or result_admission.attempt_id != started.attempt_id
            or result_admission.expectation.assignment_id != assignment.assignment_id
        ):
            reasons.append("RESULT_ADMISSION_FENCE_MISMATCH")
        if (
            pre_adoption.phase is not ControlFencePhase.PRE_ADOPTION
            or pre_adoption.disposition is not ControlDisposition.ALLOW
            or pre_adoption.checked_at != resolved_at
            or pre_adoption.expectation != result_admission.expectation
            or pre_adoption.subject_artifact_sha256
            != claim_resolution_subject_sha256(
                result=result,
                receipt=receipt,
                claim=claim,
            )
        ):
            reasons.append("PRE_ADOPTION_FENCE_MISMATCH")
        current = pre_adoption.current
        if (
            current.task_id != assignment.task_id
            or current.source_task_revision != assignment.source_task_revision
            or current.root_coordination_epoch != assignment.root_coordination_epoch
            or current.cancellation_generation != started.cancellation_epoch
            or current.context_manifest_sha256 != assignment.context_manifest_sha256
            or current.cancellation_requested
            or not current.root_lease_active
            or not current.authority_ceiling_intact
            or not current.sources_current
        ):
            reasons.append("CURRENT_CONTROL_MISMATCH")
        if resolved_at >= assignment.budget.deadline_at:
            reasons.append("DEADLINE_REACHED")
        if current_attempt is None:
            reasons.append("CURRENT_ATTEMPT_UNAVAILABLE")
        else:
            stable_started = (
                started.task_id,
                started.source_task_revision,
                started.assignment_id,
                started.attempt_id,
                started.context_manifest_sha256,
                started.runtime_session_id,
                started.backend_id,
                started.profile_id,
                started.root_coordination_epoch,
                started.cancellation_epoch,
                started.created_at,
                started.started_at,
                started.deadline_at,
                started.isolation,
            )
            stable_current = (
                current_attempt.task_id,
                current_attempt.source_task_revision,
                current_attempt.assignment_id,
                current_attempt.attempt_id,
                current_attempt.context_manifest_sha256,
                current_attempt.runtime_session_id,
                current_attempt.backend_id,
                current_attempt.profile_id,
                current_attempt.root_coordination_epoch,
                current_attempt.cancellation_epoch,
                current_attempt.created_at,
                current_attempt.started_at,
                current_attempt.deadline_at,
                current_attempt.isolation,
            )
            if stable_current != stable_started:
                reasons.append("CURRENT_ATTEMPT_RUNTIME_BINDING_MISMATCH")
            if current_attempt.lifecycle_state is not AgentLifecycleState.CLEANUP_COMPLETE:
                reasons.append("CURRENT_ATTEMPT_NOT_CLEAN")
            if receipt.attempt_integrity_id != current_attempt.attempt_integrity_id:
                reasons.append("CURRENT_ATTEMPT_INTEGRITY_MISMATCH")
        context_sha256 = contract_sha256(context)
        expected_receipt = (
            assignment.task_id,
            assignment.source_task_revision,
            assignment.assignment_id,
            started.attempt_id,
            context_sha256,
            payload.payload_id,
            contract_sha256(payload),
            started.runtime_session_id,
            started.backend_id,
            started.profile_id,
            started.root_coordination_epoch,
            started.cancellation_epoch,
        )
        actual_receipt = (
            receipt.task_id,
            receipt.source_task_revision,
            receipt.assignment_id,
            receipt.attempt_id,
            receipt.context_manifest_sha256,
            receipt.payload_id,
            receipt.payload_sha256,
            receipt.runtime_session_id,
            receipt.backend_id,
            receipt.profile_id,
            receipt.root_coordination_epoch,
            receipt.cancellation_epoch,
        )
        if actual_receipt != expected_receipt:
            reasons.append("EXECUTION_RECEIPT_BINDING_MISMATCH")
        if (
            receipt.budget != assignment.budget
            or receipt.usage != result.usage
            or receipt.outcome_at != result.script.outcome_at
            or receipt.cleanup_at != result.script.cleanup_at
            or receipt.outcome_state is not AgentLifecycleState.RESULT_RECEIVED
            or receipt.cleanup_state is not CleanupState.CLEANUP_COMPLETE
            or receipt.cancel_requested_at is not None
            or receipt.late_result
            or receipt.outcome_at >= receipt.deadline_at
        ):
            reasons.append("EXECUTION_RECEIPT_NOT_ELIGIBLE")
        if (
            context.task_id != assignment.task_id
            or context.source_task_revision != assignment.source_task_revision
            or context_sha256 != assignment.context_manifest_sha256
            or assignment.granted_source_refs != tuple(item.source_ref for item in context.sources)
            or context.created_at > resolved_at
            or context.expires_at <= resolved_at
            or any(item.freshness is not ContextFreshness.CURRENT for item in context.sources)
            or any(item.redaction_state is RedactionState.UNKNOWN for item in context.sources)
        ):
            reasons.append("CONTEXT_NOT_CURRENT")
        payload_claims = tuple(item for item in payload.claims if item.claim_key == claim.claim_key)
        if len(payload_claims) != 1 or payload_claims[0] != claim:
            reasons.append("CLAIM_NOT_EXACT_PAYLOAD_MEMBER")
        context_refs = {item.source_ref for item in context.sources}
        cited_sources = {ref for item in payload.claims for ref in item.source_refs}
        if not cited_sources.issubset(context_refs):
            reasons.append("PAYLOAD_SOURCE_OUTSIDE_CONTEXT")
        if receipt.usage.result_bytes != len(canonical_contract_json(payload).encode("utf-8")):
            reasons.append("PAYLOAD_SIZE_BINDING_MISMATCH")
        return tuple(sorted(set(reasons)))

    def _source_candidates(
        self,
        *,
        task_id: UUID,
        revision: int,
        source_ref: str,
    ) -> tuple[AuthoritativeSourceRecord, ...] | None:
        return _safe_tuple(
            lambda: self._source.resolve_source(
                task_id=task_id,
                source_task_revision=revision,
                source_ref=source_ref,
            ),
            AuthoritativeSourceRecord,
        )

    @staticmethod
    def _source_status(
        *,
        candidates: tuple[AuthoritativeSourceRecord, ...] | None,
        expected: ContextSourceReference | None,
        task_id: UUID,
        revision: int,
        source_ref: str,
        resolved_at: datetime,
    ) -> tuple[ResolutionStatus, AuthoritativeSourceRecord | None, int]:
        if candidates is None:
            return ResolutionStatus.PROVIDER_ERROR, None, 0
        if not candidates:
            return ResolutionStatus.MISSING, None, 0
        if len(candidates) != 1:
            return ResolutionStatus.AMBIGUOUS, None, len(candidates)
        record = candidates[0]
        if record.task_id != task_id or record.source_ref != source_ref:
            return ResolutionStatus.UNBOUND, record, 1
        if record.source_task_revision != revision:
            return ResolutionStatus.STALE, record, 1
        if (
            record.currentness is not ArtifactCurrentness.CURRENT
            or record.currentness_checked_at > resolved_at
        ):
            return ResolutionStatus.STALE, record, 1
        if expected is None:
            return ResolutionStatus.UNBOUND, record, 1
        if (
            record.source_revision != expected.source_revision
            or record.content_sha256 != expected.content_sha256
            or expected.freshness is not ContextFreshness.CURRENT
        ):
            return ResolutionStatus.DIGEST_CHANGED, record, 1
        return ResolutionStatus.RESOLVED_CURRENT, record, 1

    def _resolve_reference(
        self,
        *,
        kind: ReferenceKind,
        reference: str,
        result: FakeBackendResult,
        claim: ProposedClaim,
        result_admission: FenceDecision,
        pre_adoption: FenceDecision,
        resolved_at: datetime,
        blocked: bool,
    ) -> ReferenceResolutionReceipt:
        assignment = result.request.assignment
        context = result.request.context
        payload = result.payload
        started = result.request.attempt
        provider_ref = {
            ReferenceKind.SOURCE: self._source_ref,
            ReferenceKind.EVIDENCE: self._evidence_ref,
            ReferenceKind.OBSERVATION: self._observation_ref,
        }[kind]
        artifact: (
            AuthoritativeSourceRecord
            | AuthoritativeEvidenceRecord
            | AuthoritativeObservationRecord
            | None
        )
        source: AuthoritativeSourceRecord | None = None
        artifact_count = 0
        source_count = 0
        status = ResolutionStatus.PRECONDITION_FAILED
        if not blocked and kind is ReferenceKind.SOURCE:
            expected = next(
                (item for item in context.sources if item.source_ref == reference),
                None,
            )
            candidates = self._source_candidates(
                task_id=assignment.task_id,
                revision=assignment.source_task_revision,
                source_ref=reference,
            )
            status, source, artifact_count = self._source_status(
                candidates=candidates,
                expected=expected,
                task_id=assignment.task_id,
                revision=assignment.source_task_revision,
                source_ref=reference,
                resolved_at=resolved_at,
            )
            artifact = source
            source_count = artifact_count
        elif not blocked:
            if kind is ReferenceKind.EVIDENCE:
                evidence_candidates = _safe_tuple(
                    lambda: self._evidence.resolve_evidence(
                        task_id=assignment.task_id,
                        source_task_revision=assignment.source_task_revision,
                        evidence_ref=reference,
                    ),
                    AuthoritativeEvidenceRecord,
                )
                artifact_candidates: (
                    tuple[AuthoritativeEvidenceRecord | AuthoritativeObservationRecord, ...] | None
                ) = evidence_candidates
            else:
                observation_candidates = _safe_tuple(
                    lambda: self._observation.resolve_observation(
                        task_id=assignment.task_id,
                        source_task_revision=assignment.source_task_revision,
                        observation_ref=reference,
                    ),
                    AuthoritativeObservationRecord,
                )
                artifact_candidates = observation_candidates
            if artifact_candidates is None:
                status, artifact = ResolutionStatus.PROVIDER_ERROR, None
            elif not artifact_candidates:
                status, artifact = ResolutionStatus.MISSING, None
            elif len(artifact_candidates) != 1:
                status, artifact = ResolutionStatus.AMBIGUOUS, None
                artifact_count = len(artifact_candidates)
            else:
                artifact_record = artifact_candidates[0]
                artifact = artifact_record
                artifact_count = 1
                actual_ref = (
                    artifact_record.evidence_ref
                    if isinstance(artifact_record, AuthoritativeEvidenceRecord)
                    else artifact_record.observation_ref
                )
                if artifact_record.task_id != assignment.task_id or actual_ref != reference:
                    status = ResolutionStatus.UNBOUND
                elif (
                    artifact_record.source_task_revision != assignment.source_task_revision
                    or artifact_record.currentness is not ArtifactCurrentness.CURRENT
                    or artifact_record.currentness_checked_at > resolved_at
                ):
                    status = ResolutionStatus.STALE
                else:
                    expected = next(
                        (
                            item
                            for item in context.sources
                            if item.source_ref == artifact_record.source.source_ref
                        ),
                        None,
                    )
                    source_candidates = self._source_candidates(
                        task_id=assignment.task_id,
                        revision=assignment.source_task_revision,
                        source_ref=artifact_record.source.source_ref,
                    )
                    source_status, source, source_count = self._source_status(
                        candidates=source_candidates,
                        expected=expected,
                        task_id=assignment.task_id,
                        revision=assignment.source_task_revision,
                        source_ref=artifact_record.source.source_ref,
                        resolved_at=resolved_at,
                    )
                    if source_status is not ResolutionStatus.RESOLVED_CURRENT:
                        status = source_status
                    elif source is None or source.binding != artifact_record.source:
                        status = ResolutionStatus.DIGEST_CHANGED
                    else:
                        status = ResolutionStatus.RESOLVED_CURRENT
        else:
            artifact = None

        identity: str | None
        artifact_revision: str | None
        artifact_digest: str | None
        if isinstance(artifact, AuthoritativeSourceRecord):
            identity = artifact.source_identity
            artifact_revision = artifact.source_revision
            artifact_digest = artifact.content_sha256
        elif isinstance(artifact, AuthoritativeEvidenceRecord):
            identity = artifact.evidence_identity
            artifact_revision = artifact.evidence_revision
            artifact_digest = artifact.content_sha256
        elif isinstance(artifact, AuthoritativeObservationRecord):
            identity = artifact.observation_identity
            artifact_revision = artifact.observation_revision
            artifact_digest = artifact.content_sha256
        else:
            identity = None
            artifact_revision = None
            artifact_digest = None
        if source is None and isinstance(artifact, AuthoritativeSourceRecord):
            source = artifact
        provenance = {
            self._resolver_ref,
            provider_ref,
            self._source_ref,
            assignment.assignment_id,
            started.attempt_id,
            payload.payload_id,
            result.result_id,
            result_admission.decision_id,
            pre_adoption.decision_id,
        }
        if artifact is not None:
            provenance.update(artifact.provenance_refs)
        if source is not None:
            provenance.update(source.provenance_refs)
        eligible = status is ResolutionStatus.RESOLVED_CURRENT
        return ReferenceResolutionReceipt(
            kind=kind,
            task_id=assignment.task_id,
            source_task_revision=assignment.source_task_revision,
            assignment_id=assignment.assignment_id,
            attempt_id=started.attempt_id,
            payload_id=payload.payload_id,
            claim_key=claim.claim_key,
            requested_ref=reference,
            status=status,
            provider_ref=provider_ref,
            source_provider_ref=self._source_ref,
            candidate_count=artifact_count,
            source_candidate_count=source_count,
            resolved_task_id=None if artifact is None else artifact.task_id,
            resolved_source_task_revision=(
                None if artifact is None else artifact.source_task_revision
            ),
            resolved_identity=identity,
            resolved_revision=artifact_revision,
            resolved_content_sha256=artifact_digest,
            resolved_currentness=None if artifact is None else artifact.currentness,
            source_ref=None if source is None else source.source_ref,
            source_identity=None if source is None else source.source_identity,
            source_revision=None if source is None else source.source_revision,
            source_content_sha256=None if source is None else source.content_sha256,
            source_currentness=None if source is None else source.currentness,
            currentness_checked_at=(None if artifact is None else artifact.currentness_checked_at),
            source_currentness_checked_at=(
                None if source is None else source.currentness_checked_at
            ),
            resolved_at=resolved_at,
            result_admission_decision_id=result_admission.decision_id,
            pre_adoption_decision_id=pre_adoption.decision_id,
            provenance_refs=tuple(sorted(provenance)),
            eligible_for_claim_support=eligible,
            quarantine_required=not eligible,
        )

    def resolve_claim(
        self,
        *,
        result: FakeBackendResult,
        receipt: AgentExecutionReceipt,
        claim: ProposedClaim,
        result_admission: FenceDecision,
        pre_adoption: FenceDecision,
        resolved_at: datetime,
    ) -> ClaimResolutionReceipt:
        """Resolve one exact payload claim after all current S3 fences pass."""

        observed_at = require_utc(resolved_at)
        result = FakeBackendResult.model_validate(result)
        receipt = AgentExecutionReceipt.model_validate(receipt)
        claim = ProposedClaim.model_validate(claim)
        result_admission = FenceDecision.model_validate(result_admission)
        pre_adoption = FenceDecision.model_validate(pre_adoption)
        current_attempt, attempt_error = self._current_attempt(result)
        reasons = list(
            self._preconditions(
                result=result,
                receipt=receipt,
                current_attempt=current_attempt,
                claim=claim,
                result_admission=result_admission,
                pre_adoption=pre_adoption,
                resolved_at=observed_at,
            )
        )
        if attempt_error is not None:
            reasons.append(attempt_error)
        typed_refs = (
            *((ReferenceKind.SOURCE, ref) for ref in claim.source_refs),
            *((ReferenceKind.EVIDENCE, ref) for ref in claim.evidence_refs),
            *((ReferenceKind.OBSERVATION, ref) for ref in claim.observation_refs),
        )
        raw_refs = tuple(ref for _, ref in typed_refs)
        if len(raw_refs) != len(set(raw_refs)):
            reasons.append("AMBIGUOUS_REFERENCE_NAMESPACE")
        references = tuple(
            self._resolve_reference(
                kind=kind,
                reference=reference,
                result=result,
                claim=claim,
                result_admission=result_admission,
                pre_adoption=pre_adoption,
                resolved_at=observed_at,
                blocked=bool(reasons),
            )
            for kind, reference in typed_refs
        )
        reasons.extend(
            f"{item.kind.value}_{item.status.value}"
            for item in references
            if not item.eligible_for_claim_support
        )
        qualified = not reasons and all(item.eligible_for_claim_support for item in references)
        reason_codes = (
            ("ALL_REFERENCES_CURRENT",)
            if qualified
            else tuple(sorted(set(reasons or ("REFERENCE_RESOLUTION_INCOMPLETE",))))
        )
        assignment = result.request.assignment
        payload = result.payload
        attempt_integrity_id = (
            receipt.attempt_integrity_id
            if current_attempt is None
            else current_attempt.attempt_integrity_id
        )
        provenance = {
            self._resolver_ref,
            self._attempt_ref,
            assignment.assignment_id,
            result.request.attempt.attempt_id,
            result.request.context.context_manifest_id,
            payload.payload_id,
            result.result_id,
            receipt.receipt_id,
            result_admission.decision_id,
            pre_adoption.decision_id,
            *(item.resolution_receipt_id for item in references),
        }
        return ClaimResolutionReceipt(
            task_id=assignment.task_id,
            source_task_revision=assignment.source_task_revision,
            assignment_id=assignment.assignment_id,
            attempt_id=result.request.attempt.attempt_id,
            attempt_integrity_id=attempt_integrity_id,
            context_manifest_sha256=contract_sha256(result.request.context),
            payload_id=payload.payload_id,
            payload_sha256=contract_sha256(payload),
            execution_receipt_id=receipt.receipt_id,
            execution_receipt_sha256=contract_sha256(receipt),
            result_id=result.result_id,
            result_sha256=contract_sha256(result),
            result_admission_decision_id=result_admission.decision_id,
            pre_adoption_decision_id=pre_adoption.decision_id,
            root_coordination_epoch=assignment.root_coordination_epoch,
            cancellation_epoch=result.request.attempt.cancellation_epoch,
            claim_key=claim.claim_key,
            statement=claim.statement,
            source_refs=claim.source_refs,
            evidence_refs=claim.evidence_refs,
            observation_refs=claim.observation_refs,
            reference_receipts=references,
            support_disposition=(
                ClaimSupportDisposition.QUALIFIED
                if qualified
                else ClaimSupportDisposition.VERIFY_REQUIRED
            ),
            reason_codes=reason_codes,
            provenance_refs=tuple(sorted(provenance)),
            resolved_at=observed_at,
            root_consideration_eligible=qualified,
            quarantine_required=not qualified,
        )


__all__ = [
    "ArtifactCurrentness",
    "AuthoritativeAttemptProvider",
    "AuthoritativeEvidenceProvider",
    "AuthoritativeEvidenceRecord",
    "AuthoritativeObservationProvider",
    "AuthoritativeObservationRecord",
    "AuthoritativeResolver",
    "AuthoritativeSourceBinding",
    "AuthoritativeSourceProvider",
    "AuthoritativeSourceRecord",
    "ClaimResolutionReceipt",
    "ReferenceKind",
    "ReferenceResolutionReceipt",
    "ResolutionStatus",
    "claim_resolution_subject_sha256",
]
