"""Immutable C-011A contracts with structural integrity and no live execution.

The SHA-256 identities in this module prove deterministic content consistency only.
They do not authenticate a runtime, root owner, worker, or evidence resolver. Durable
event provenance begins in S2; current-source resolver authority begins in S3.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, ClassVar, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc
from luna.contracts.enums import PlanStepStatus

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _normalized_unique_text(
    values: tuple[str, ...],
    *,
    label: str,
    require_nonempty: bool = False,
) -> tuple[str, ...]:
    cleaned = tuple(value.strip() for value in values)
    if require_nonempty and not cleaned:
        raise ValueError(f"{label} must not be empty")
    if any(not value for value in cleaned):
        raise ValueError(f"{label} cannot contain blank values")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(cleaned))


class C011ContractModel(LunaContractModel):
    """Strict, deeply composable base for the isolated S1 contract package."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        str_strip_whitespace=True,
        use_enum_values=False,
    )


def canonical_contract_json(model: C011ContractModel) -> str:
    """Revalidate and serialize one C-011 contract deterministically."""

    validated = type(model).model_validate(model.model_dump(mode="json"))
    return _canonical_json(validated.model_dump(mode="json"))


def contract_sha256(model: C011ContractModel) -> str:
    """Return the deterministic digest of a fully validated contract artifact."""

    return sha256(canonical_contract_json(model).encode("utf-8")).hexdigest()


def reconstruct_contract[ContractT: C011ContractModel](
    contract_type: type[ContractT],
    value: str | bytes | bytearray,
) -> ContractT:
    """Reconstruct and fully validate a C-011 contract from serialized JSON."""

    return contract_type.model_validate_json(value)


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
    digest = sha256(_canonical_json(basis).encode("utf-8")).hexdigest()
    return f"{prefix}{digest}"


class _ContentAddressedContract(C011ContractModel):
    """Populate or verify a domain-separated identity after field normalization."""

    _identity_field: ClassVar[str]
    _identity_prefix: ClassVar[str]

    @model_validator(mode="after")
    def validate_content_identity(self) -> Self:
        expected = _content_identity(
            self,
            identity_field=self._identity_field,
            prefix=self._identity_prefix,
        )
        supplied = getattr(self, self._identity_field)
        if not supplied:
            object.__setattr__(self, self._identity_field, expected)
        elif supplied != expected:
            raise ValueError(f"{self._identity_field} does not match canonical contract content")
        return self


class ContextFreshness(StrEnum):
    """Declared freshness state; truth is resolved authoritatively in S3."""

    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class RedactionState(StrEnum):
    """Structural redaction state for one referenced context source."""

    REDACTED = "REDACTED"
    NOT_REQUIRED = "NOT_REQUIRED"
    UNKNOWN = "UNKNOWN"


class ParallelCognitionRole(StrEnum):
    """Bounded temporary role; never a persistent persona or authority source."""

    PARALLEL = "PARALLEL"
    INDEPENDENT_REVIEWER = "INDEPENDENT_REVIEWER"


class AgentLifecycleState(StrEnum):
    """RFC-C011 lifecycle vocabulary; durable transitions belong to S2."""

    PROPOSED = "PROPOSED"
    ADMITTED = "ADMITTED"
    DENIED = "DENIED"
    CREATED = "CREATED"
    STARTED = "STARTED"
    RESULT_RECEIVED = "RESULT_RECEIVED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    TIMED_OUT = "TIMED_OUT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TERMINATED = "TERMINATED"
    CLEANUP_COMPLETE = "CLEANUP_COMPLETE"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    RECONCILED = "RECONCILED"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"
    VERIFY_REQUIRED = "VERIFY_REQUIRED"
    CLOSED = "CLOSED"


class CleanupState(StrEnum):
    """Runtime-observed cleanup outcome represented by an S1 receipt schema."""

    CLEANUP_COMPLETE = "CLEANUP_COMPLETE"
    CLEANUP_FAILED = "CLEANUP_FAILED"


class EvidenceResolutionState(StrEnum):
    """Shape of evidence resolution; real resolver authority begins in S3."""

    RESOLVED_CURRENT = "RESOLVED_CURRENT"
    RESOLVED_STALE = "RESOLVED_STALE"
    MISSING = "MISSING"
    UNRESOLVED = "UNRESOLVED"


class ClaimSupportDisposition(StrEnum):
    """Root-side structural disposition for a proposed claim."""

    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    VERIFY_REQUIRED = "VERIFY_REQUIRED"


class ClaimFreshness(StrEnum):
    """Claim-level freshness after evidence-lineage resolution."""

    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ContradictionState(StrEnum):
    """Whether material counterevidence remains unresolved."""

    NONE = "NONE"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


class AdoptionDisposition(StrEnum):
    """Root decision for one qualified claim."""

    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"
    VERIFY_REQUIRED = "VERIFY_REQUIRED"


class ContextSourceReference(C011ContractModel):
    """Digest-only reference to one bounded read-only source."""

    task_id: UUID
    source_task_revision: int = Field(ge=0)
    source_ref: str = Field(min_length=1, max_length=2000)
    source_revision: str = Field(min_length=1, max_length=500)
    content_sha256: Sha256
    freshness: ContextFreshness
    freshness_checked_at: datetime
    redaction_state: RedactionState
    size_bytes: int = Field(ge=0)

    @field_validator("freshness_checked_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)


class ReadOnlyContextManifest(_ContentAddressedContract):
    """Explicit digest-only context with an immutable read-only authority ceiling."""

    _identity_field = "context_manifest_id"
    _identity_prefix = "c011-context:sha256:"

    context_manifest_id: str = ""
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    sources: tuple[ContextSourceReference, ...] = Field(min_length=1, max_length=128)
    total_size_bytes: int = Field(ge=0)
    created_at: datetime
    expires_at: datetime
    write_authority: Literal[False] = False
    network_authority: Literal[False] = False
    process_authority: Literal[False] = False
    tool_authority: Literal[False] = False
    external_action_authority: Literal[False] = False
    inherited_memory_authority: Literal[False] = False
    memory_commit_authority: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator("created_at", "expires_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("sources")
    @classmethod
    def normalize_sources(
        cls,
        values: tuple[ContextSourceReference, ...],
    ) -> tuple[ContextSourceReference, ...]:
        refs = tuple(item.source_ref for item in values)
        if len(refs) != len(set(refs)):
            raise ValueError("context source references must be unique")
        return tuple(sorted(values, key=lambda item: item.source_ref))

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("context manifest expiry must be after creation")
        if any(item.task_id != self.task_id for item in self.sources):
            raise ValueError("all context sources must belong to the manifest task")
        if any(item.source_task_revision != self.source_task_revision for item in self.sources):
            raise ValueError("all context sources must match the manifest task revision")
        if any(item.freshness_checked_at > self.created_at for item in self.sources):
            raise ValueError("context freshness cannot be checked after manifest creation")
        if self.total_size_bytes != sum(item.size_bytes for item in self.sources):
            raise ValueError("context size accounting must equal referenced source sizes")
        return self


class SourceStepSemantics(C011ContractModel):
    """Complete immutable semantic binding for one source plan step."""

    step_id: UUID
    sequence: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=2000)
    status: PlanStepStatus
    expectation_payload_sha256: Sha256 | None = None
    dependency_step_ids: tuple[UUID, ...] = ()
    status_reason: str | None = Field(default=None, max_length=2000)
    source_step_payload_sha256: Sha256

    @field_validator("dependency_step_ids")
    @classmethod
    def normalize_dependencies(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("source-step dependencies must be unique")
        return tuple(sorted(values, key=str))

    @model_validator(mode="after")
    def validate_step(self) -> Self:
        if self.step_id in self.dependency_step_ids:
            raise ValueError("a source step cannot depend on itself")
        requires_reason = {
            PlanStepStatus.BLOCKED,
            PlanStepStatus.FAILED,
            PlanStepStatus.SKIPPED_WITH_REASON,
        }
        if self.status in requires_reason and not self.status_reason:
            raise ValueError(f"{self.status.value} source step requires status_reason")
        return self


class WorkerBudgetEnvelope(C011ContractModel):
    """Declared integer-only resource ceilings bound into assignment identity.

    ``max_tokens`` is the generated-output ceiling used by provider admission and
    the child driver. Engine-native input and total measurements remain separate
    provenance on a live result.
    """

    max_context_bytes: int = Field(ge=1)
    max_result_bytes: int = Field(ge=1)
    max_claims: int = Field(ge=0)
    max_tokens: int = Field(ge=0)
    max_runtime_ms: int = Field(ge=1)
    deadline_at: datetime

    @field_validator("deadline_at")
    @classmethod
    def validate_deadline(cls, value: datetime) -> datetime:
        return require_utc(value)


class AssignmentSemanticSpec(_ContentAddressedContract):
    """Complete C-011 assignment semantics; every material field defines identity."""

    _identity_field = "assignment_id"
    _identity_prefix = "c011-assignment:sha256:"

    assignment_id: str = ""
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    task_contract_sha256: Sha256
    source_steps: tuple[SourceStepSemantics, ...] = Field(min_length=1, max_length=32)
    acceptance_basis_sha256: Sha256
    acceptance_target_refs: tuple[str, ...] = Field(min_length=1, max_length=64)
    context_manifest_sha256: Sha256
    autonomy_policy_sha256: Sha256
    tool_policy_sha256: Sha256
    worker_role: ParallelCognitionRole
    objective: str = Field(min_length=1, max_length=4000)
    granted_source_refs: tuple[str, ...] = Field(min_length=1, max_length=128)
    capability_selection_basis_sha256: Sha256
    root_coordination_epoch: int = Field(ge=0)
    delegation_depth: Literal[1] = 1
    budget: WorkerBudgetEnvelope
    write_authority: Literal[False] = False
    network_authority: Literal[False] = False
    process_authority: Literal[False] = False
    tool_authority: Literal[False] = False
    external_action_authority: Literal[False] = False
    delegation_authority: Literal[False] = False
    memory_commit_authority: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    @field_validator("acceptance_target_refs", "granted_source_refs")
    @classmethod
    def normalize_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_unique_text(
            values,
            label="assignment references",
            require_nonempty=True,
        )

    @field_validator("source_steps")
    @classmethod
    def normalize_source_steps(
        cls,
        values: tuple[SourceStepSemantics, ...],
    ) -> tuple[SourceStepSemantics, ...]:
        step_ids = tuple(item.step_id for item in values)
        sequences = tuple(item.sequence for item in values)
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("source step IDs must be unique")
        if len(sequences) != len(set(sequences)):
            raise ValueError("source step sequences must be unique")
        return tuple(sorted(values, key=lambda item: item.sequence))

    @model_validator(mode="after")
    def validate_step_graph(self) -> Self:
        sequence_by_id = {item.step_id: item.sequence for item in self.source_steps}
        for step in self.source_steps:
            for dependency_id in step.dependency_step_ids:
                dependency_sequence = sequence_by_id.get(dependency_id)
                if dependency_sequence is None:
                    raise ValueError("assignment must include the complete step dependency")
                if dependency_sequence >= step.sequence:
                    raise ValueError("source-step dependencies must reference earlier steps")
        return self


class IsolationReferences(C011ContractModel):
    """References to isolation evidence; they are not self-authenticating proof."""

    process_ref: str = Field(min_length=1, max_length=2000)
    session_ref: str = Field(min_length=1, max_length=2000)
    context_ref: str = Field(min_length=1, max_length=2000)


class AgentExecutionAttempt(_ContentAddressedContract):
    """One immutable lifecycle snapshot for a unique runtime-issued attempt ID."""

    _identity_field = "attempt_integrity_id"
    _identity_prefix = "c011-attempt-state:sha256:"

    attempt_integrity_id: str = ""
    attempt_id: str = Field(pattern=r"^attempt:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    context_manifest_sha256: Sha256
    runtime_session_id: str | None = Field(default=None, max_length=500)
    backend_id: str | None = Field(default=None, max_length=500)
    profile_id: str | None = Field(default=None, max_length=500)
    root_coordination_epoch: int = Field(ge=0)
    cancellation_epoch: int = Field(ge=0)
    created_at: datetime
    started_at: datetime | None = None
    deadline_at: datetime
    isolation: IsolationReferences | None = None
    lifecycle_state: AgentLifecycleState
    display_name: str | None = Field(default=None, max_length=200)
    write_authority: Literal[False] = False
    network_authority: Literal[False] = False
    process_authority: Literal[False] = False
    tool_authority: Literal[False] = False
    external_action_authority: Literal[False] = False
    delegation_authority: Literal[False] = False
    memory_commit_authority: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    @field_validator("created_at", "started_at", "deadline_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @field_validator("runtime_session_id", "backend_id", "profile_id", "display_name")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional attempt identifiers cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_attempt_state(self) -> Self:
        if self.deadline_at <= self.created_at:
            raise ValueError("attempt deadline must be after creation")
        if self.started_at is not None:
            if self.started_at < self.created_at:
                raise ValueError("attempt cannot start before creation")
            if self.started_at >= self.deadline_at:
                raise ValueError("attempt must start before its deadline")

        precreation = {
            AgentLifecycleState.PROPOSED,
            AgentLifecycleState.ADMITTED,
            AgentLifecycleState.DENIED,
        }
        provisioned = (
            self.runtime_session_id,
            self.backend_id,
            self.profile_id,
            self.isolation,
        )
        if self.lifecycle_state in precreation:
            if any(value is not None for value in provisioned) or self.started_at is not None:
                raise ValueError("pre-creation attempt state cannot claim runtime provisioning")
            return self

        has_any_provisioning = any(value is not None for value in provisioned)
        has_all_provisioning = all(value is not None for value in provisioned)
        if has_any_provisioning and not has_all_provisioning:
            raise ValueError("attempt runtime provisioning must be complete or absent")
        if self.started_at is not None and not has_all_provisioning:
            raise ValueError("started attempt requires complete runtime provisioning")

        if self.lifecycle_state is AgentLifecycleState.CREATED:
            if not has_all_provisioning:
                raise ValueError("created attempt requires complete runtime provisioning")
            if self.started_at is not None:
                raise ValueError("created attempt cannot claim execution already started")
            return self

        execution_started_states = {
            AgentLifecycleState.STARTED,
            AgentLifecycleState.RESULT_RECEIVED,
            AgentLifecycleState.FAILED,
            AgentLifecycleState.TERMINATED,
            AgentLifecycleState.RECONCILED,
            AgentLifecycleState.ADOPTED,
            AgentLifecycleState.REJECTED,
        }
        if self.lifecycle_state in execution_started_states and (
            not has_all_provisioning or self.started_at is None
        ):
            raise ValueError(f"{self.lifecycle_state.value} attempt requires established execution")
        return self


class ProposedClaim(C011ContractModel):
    """Untrusted worker claim with explicit citations and no authority fields."""

    claim_key: str = Field(min_length=1, max_length=500)
    statement: str = Field(min_length=1, max_length=4000)
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    observation_refs: tuple[str, ...] = ()

    @field_validator("source_refs", "evidence_refs", "observation_refs")
    @classmethod
    def normalize_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_unique_text(values, label="claim references")

    @model_validator(mode="after")
    def validate_citations(self) -> Self:
        if not (self.source_refs or self.evidence_refs or self.observation_refs):
            raise ValueError("a proposed claim requires at least one explicit citation")
        return self


class AgentPayload(_ContentAddressedContract):
    """Untrusted worker output; runtime and authority assertions are excluded."""

    _identity_field = "payload_id"
    _identity_prefix = "c011-payload:sha256:"

    payload_id: str = ""
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    attempt_id: str = Field(pattern=r"^attempt:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    context_manifest_sha256: Sha256
    summary: str = Field(min_length=1, max_length=8000)
    claims: tuple[ProposedClaim, ...] = Field(default=(), max_length=128)
    cited_source_refs: tuple[str, ...] = ()
    cited_evidence_refs: tuple[str, ...] = ()
    cited_observation_refs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    uncertainty: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    recommended_next_action: str | None = Field(default=None, max_length=4000)
    untrusted: Literal[True] = True
    write_authority: Literal[False] = False
    network_authority: Literal[False] = False
    process_authority: Literal[False] = False
    tool_authority: Literal[False] = False
    delegation_authority: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    memory_commit_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    @field_validator(
        "cited_source_refs",
        "cited_evidence_refs",
        "cited_observation_refs",
        "assumptions",
        "uncertainty",
        "conflicts",
    )
    @classmethod
    def normalize_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_unique_text(values, label="payload references")

    @field_validator("claims")
    @classmethod
    def normalize_claims(cls, values: tuple[ProposedClaim, ...]) -> tuple[ProposedClaim, ...]:
        keys = tuple(item.claim_key for item in values)
        if len(keys) != len(set(keys)):
            raise ValueError("payload claim keys must be unique")
        return tuple(sorted(values, key=lambda item: item.claim_key))

    @model_validator(mode="after")
    def validate_claim_citations(self) -> Self:
        source_refs = set(self.cited_source_refs)
        evidence_refs = set(self.cited_evidence_refs)
        observation_refs = set(self.cited_observation_refs)
        for claim in self.claims:
            if not set(claim.source_refs).issubset(source_refs):
                raise ValueError("claim source refs must be declared by the payload")
            if not set(claim.evidence_refs).issubset(evidence_refs):
                raise ValueError("claim evidence refs must be declared by the payload")
            if not set(claim.observation_refs).issubset(observation_refs):
                raise ValueError("claim observation refs must be declared by the payload")
        return self


class AgentResourceUsage(C011ContractModel):
    """Integer-only budget usage observed by the receipt-producing boundary.

    ``tokens`` records generated output for native results so it is comparable to
    ``WorkerBudgetEnvelope.max_tokens``. The full input/output/total measurement is
    retained separately as engine-native provenance on ``LiveBackendResult``.
    """

    context_bytes: int = Field(ge=0)
    result_bytes: int = Field(ge=0)
    claims_count: int = Field(ge=0)
    tokens: int = Field(ge=0)
    runtime_ms: int = Field(ge=0)


class AgentExecutionReceipt(_ContentAddressedContract):
    """Structurally bound runtime observation; S1 does not authenticate its issuer."""

    _identity_field = "receipt_id"
    _identity_prefix = "c011-execution-receipt:sha256:"

    receipt_id: str = ""
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    attempt_id: str = Field(pattern=r"^attempt:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    attempt_integrity_id: str = Field(pattern=r"^c011-attempt-state:sha256:[0-9a-f]{64}$")
    context_manifest_sha256: Sha256
    payload_id: str = Field(pattern=r"^c011-payload:sha256:[0-9a-f]{64}$")
    payload_sha256: Sha256
    runtime_session_id: str = Field(min_length=1, max_length=500)
    backend_id: str = Field(min_length=1, max_length=500)
    profile_id: str = Field(min_length=1, max_length=500)
    root_coordination_epoch: int = Field(ge=0)
    cancellation_epoch: int = Field(ge=0)
    budget: WorkerBudgetEnvelope
    usage: AgentResourceUsage
    started_at: datetime
    outcome_at: datetime
    deadline_at: datetime
    cancel_requested_at: datetime | None = None
    cleanup_at: datetime
    outcome_state: AgentLifecycleState
    cleanup_state: CleanupState
    late_result: bool
    event_refs: tuple[str, ...] = Field(min_length=1, max_length=128)
    completion_authority: Literal[False] = False

    @field_validator(
        "started_at",
        "outcome_at",
        "deadline_at",
        "cancel_requested_at",
        "cleanup_at",
    )
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @field_validator("event_refs")
    @classmethod
    def normalize_event_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_unique_text(
            values,
            label="receipt event references",
            require_nonempty=True,
        )

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        outcomes = {
            AgentLifecycleState.RESULT_RECEIVED,
            AgentLifecycleState.CANCELLED,
            AgentLifecycleState.TIMED_OUT,
            AgentLifecycleState.FAILED,
            AgentLifecycleState.TERMINATED,
        }
        if self.outcome_state not in outcomes:
            raise ValueError("receipt requires a terminal execution outcome")
        if not (self.started_at <= self.outcome_at <= self.cleanup_at):
            raise ValueError("receipt timestamps must be monotonic")
        if self.deadline_at != self.budget.deadline_at:
            raise ValueError("receipt deadline must match its declared budget")
        expected_late = (
            self.outcome_state is AgentLifecycleState.RESULT_RECEIVED
            and self.outcome_at > self.deadline_at
        )
        if self.late_result is not expected_late:
            raise ValueError("late-result flag must match the observed outcome time")
        if self.cancel_requested_at is not None and not (
            self.started_at <= self.cancel_requested_at <= self.cleanup_at
        ):
            raise ValueError("cancel request timestamp must fall inside execution")
        if (
            self.outcome_state
            in {
                AgentLifecycleState.CANCELLED,
                AgentLifecycleState.TERMINATED,
            }
            and self.cancel_requested_at is None
        ):
            raise ValueError("cancelled or terminated receipt requires a cancel request")
        limits = (
            (self.usage.context_bytes, self.budget.max_context_bytes),
            (self.usage.result_bytes, self.budget.max_result_bytes),
            (self.usage.claims_count, self.budget.max_claims),
            (self.usage.tokens, self.budget.max_tokens),
            (self.usage.runtime_ms, self.budget.max_runtime_ms),
        )
        if any(observed > maximum for observed, maximum in limits):
            raise ValueError("receipt usage exceeds the declared assignment budget")
        return self


class ResolvedEvidenceLineage(C011ContractModel):
    """Digest-bound resolution record whose issuer authority is deferred to S3."""

    task_id: UUID
    source_task_revision: int = Field(ge=0)
    evidence_ref: str = Field(min_length=1, max_length=2000)
    evidence_sha256: Sha256 | None = None
    source_ref: str = Field(min_length=1, max_length=2000)
    source_sha256: Sha256 | None = None
    resolution_state: EvidenceResolutionState
    freshness_checked_at: datetime
    resolver_ref: str = Field(min_length=1, max_length=2000)
    resolution_receipt_sha256: Sha256 | None = None

    @field_validator("freshness_checked_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_resolution_shape(self) -> Self:
        resolved = self.resolution_state in {
            EvidenceResolutionState.RESOLVED_CURRENT,
            EvidenceResolutionState.RESOLVED_STALE,
        }
        digests = (
            self.evidence_sha256,
            self.source_sha256,
            self.resolution_receipt_sha256,
        )
        if resolved and any(value is None for value in digests):
            raise ValueError("resolved evidence lineage requires exact content digests")
        return self


class ClaimRecord(_ContentAddressedContract):
    """Root-qualified or blocked claim with explicit evidence-lineage state."""

    _identity_field = "claim_record_id"
    _identity_prefix = "c011-claim-record:sha256:"

    claim_record_id: str = ""
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    attempt_id: str = Field(pattern=r"^attempt:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    payload_id: str = Field(pattern=r"^c011-payload:sha256:[0-9a-f]{64}$")
    source_claim_key: str = Field(min_length=1, max_length=500)
    statement: str = Field(min_length=1, max_length=4000)
    support_disposition: ClaimSupportDisposition
    evidence_lineage: tuple[ResolvedEvidenceLineage, ...] = Field(max_length=128)
    freshness: ClaimFreshness
    contradiction_state: ContradictionState
    qualification_reason: str = Field(min_length=1, max_length=4000)

    @field_validator("evidence_lineage")
    @classmethod
    def normalize_lineage(
        cls,
        values: tuple[ResolvedEvidenceLineage, ...],
    ) -> tuple[ResolvedEvidenceLineage, ...]:
        refs = tuple(item.evidence_ref for item in values)
        if len(refs) != len(set(refs)):
            raise ValueError("claim evidence-lineage refs must be unique")
        return tuple(sorted(values, key=lambda item: item.evidence_ref))

    @model_validator(mode="after")
    def validate_qualification(self) -> Self:
        if any(item.task_id != self.task_id for item in self.evidence_lineage):
            raise ValueError("claim evidence lineage must belong to the claim task")
        if any(
            item.source_task_revision != self.source_task_revision for item in self.evidence_lineage
        ):
            raise ValueError("claim evidence lineage must match the claim revision")
        if self.support_disposition is ClaimSupportDisposition.QUALIFIED:
            if not self.evidence_lineage:
                raise ValueError("qualified claim requires resolved evidence lineage")
            if any(
                item.resolution_state is not EvidenceResolutionState.RESOLVED_CURRENT
                for item in self.evidence_lineage
            ):
                raise ValueError("qualified claim requires current resolved evidence")
            if self.freshness is not ClaimFreshness.CURRENT:
                raise ValueError("qualified claim requires current freshness")
            if self.contradiction_state is ContradictionState.UNRESOLVED:
                raise ValueError("unresolved contradiction blocks claim qualification")
        return self


class DistilledHandoff(_ContentAddressedContract):
    """Bounded root-facing handoff containing qualified claims only."""

    _identity_field = "handoff_id"
    _identity_prefix = "c011-distilled-handoff:sha256:"

    handoff_id: str = ""
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    attempt_id: str = Field(pattern=r"^attempt:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    context_manifest_sha256: Sha256
    payload_id: str = Field(pattern=r"^c011-payload:sha256:[0-9a-f]{64}$")
    payload_sha256: Sha256
    receipt_id: str = Field(pattern=r"^c011-execution-receipt:sha256:[0-9a-f]{64}$")
    receipt_sha256: Sha256
    qualified_claims: tuple[ClaimRecord, ...] = Field(default=(), max_length=128)
    assumptions: tuple[str, ...] = Field(default=(), max_length=128)
    uncertainty: tuple[str, ...] = Field(default=(), max_length=128)
    conflicts: tuple[str, ...] = Field(default=(), max_length=128)
    recommended_next_action: str | None = Field(default=None, max_length=4000)
    created_at: datetime
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("assumptions", "uncertainty", "conflicts")
    @classmethod
    def normalize_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_unique_text(values, label="handoff text entries")

    @field_validator("qualified_claims")
    @classmethod
    def normalize_claims(cls, values: tuple[ClaimRecord, ...]) -> tuple[ClaimRecord, ...]:
        claim_ids = tuple(item.claim_record_id for item in values)
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("handoff claim records must be unique")
        return tuple(sorted(values, key=lambda item: item.claim_record_id))

    @model_validator(mode="after")
    def validate_claims(self) -> Self:
        for claim in self.qualified_claims:
            if claim.support_disposition is not ClaimSupportDisposition.QUALIFIED:
                raise ValueError("distilled handoff can contain only qualified claims")
            if (
                claim.task_id != self.task_id
                or claim.source_task_revision != self.source_task_revision
                or claim.assignment_id != self.assignment_id
                or claim.attempt_id != self.attempt_id
                or claim.payload_id != self.payload_id
            ):
                raise ValueError("handoff claim chain does not match its source artifacts")
        return self


class AdoptionDecision(C011ContractModel):
    """Exactly one root disposition for one qualified claim record."""

    claim_record_id: str = Field(pattern=r"^c011-claim-record:sha256:[0-9a-f]{64}$")
    disposition: AdoptionDisposition
    reason: str = Field(min_length=1, max_length=4000)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=128)

    @field_validator("evidence_refs")
    @classmethod
    def normalize_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_unique_text(values, label="adoption evidence refs")


class AdoptionReceipt(_ContentAddressedContract):
    """Root-decision schema with exhaustive claim partition and no completion power."""

    _identity_field = "adoption_receipt_id"
    _identity_prefix = "c011-adoption-receipt:sha256:"

    adoption_receipt_id: str = ""
    task_id: UUID
    root_coordination_epoch: int = Field(ge=0)
    handoff_id: str = Field(pattern=r"^c011-distilled-handoff:sha256:[0-9a-f]{64}$")
    handoff_sha256: Sha256
    considered_claim_ids: tuple[str, ...] = Field(default=(), max_length=128)
    decisions: tuple[AdoptionDecision, ...] = Field(default=(), max_length=128)
    current_root_state_revision: int = Field(ge=0)
    resulting_root_state_revision: int | None = Field(default=None, ge=0)
    authoritative_evidence_basis: tuple[str, ...] = Field(min_length=1, max_length=128)
    root_owner_ref: str = Field(min_length=1, max_length=2000)
    adopted_at: datetime
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator("adopted_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("considered_claim_ids", "authoritative_evidence_basis")
    @classmethod
    def normalize_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_unique_text(values, label="adoption references")

    @field_validator("decisions")
    @classmethod
    def normalize_decisions(
        cls,
        values: tuple[AdoptionDecision, ...],
    ) -> tuple[AdoptionDecision, ...]:
        ids = tuple(item.claim_record_id for item in values)
        if len(ids) != len(set(ids)):
            raise ValueError("adoption decisions must address unique claims")
        return tuple(sorted(values, key=lambda item: item.claim_record_id))

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        decided_ids = tuple(item.claim_record_id for item in self.decisions)
        if set(decided_ids) != set(self.considered_claim_ids):
            raise ValueError("adoption decisions must exhaust the considered claim set")
        adopted = any(item.disposition is AdoptionDisposition.ADOPTED for item in self.decisions)
        if adopted:
            if self.resulting_root_state_revision is None:
                raise ValueError("adopted claims require a resulting root state revision")
            if self.resulting_root_state_revision < self.current_root_state_revision:
                raise ValueError("adoption cannot roll back the root state revision")
        elif self.resulting_root_state_revision is not None:
            raise ValueError("no-adoption receipt cannot claim a resulting revision")
        return self


def _revalidated[ContractT: C011ContractModel](model: ContractT) -> ContractT:
    return type(model).model_validate(model.model_dump(mode="json"))


def validate_c011_contract_chain(
    *,
    context: ReadOnlyContextManifest,
    assignment: AssignmentSemanticSpec,
    attempt: AgentExecutionAttempt,
    payload: AgentPayload,
    receipt: AgentExecutionReceipt,
    claims: tuple[ClaimRecord, ...],
    handoff: DistilledHandoff,
    adoption: AdoptionReceipt | None = None,
) -> None:
    """Validate internal S1 bindings without claiming authenticated provenance."""

    context = _revalidated(context)
    assignment = _revalidated(assignment)
    attempt = _revalidated(attempt)
    payload = _revalidated(payload)
    receipt = _revalidated(receipt)
    claims = tuple(_revalidated(item) for item in claims)
    handoff = _revalidated(handoff)
    if adoption is not None:
        adoption = _revalidated(adoption)

    task_id = assignment.task_id
    revision = assignment.source_task_revision
    if context.task_id != task_id or context.source_task_revision != revision:
        raise ValueError("context task binding does not match assignment")
    context_digest = contract_sha256(context)
    if assignment.context_manifest_sha256 != context_digest:
        raise ValueError("assignment context digest does not match manifest")
    context_refs = tuple(item.source_ref for item in context.sources)
    if assignment.granted_source_refs != context_refs:
        raise ValueError("assignment grants must exactly match manifest source refs")
    if context.total_size_bytes > assignment.budget.max_context_bytes:
        raise ValueError("context manifest exceeds assignment context budget")
    if any(item.freshness is not ContextFreshness.CURRENT for item in context.sources):
        raise ValueError("non-current context cannot enter a distilled handoff chain")
    if any(item.redaction_state is RedactionState.UNKNOWN for item in context.sources):
        raise ValueError("unknown redaction state cannot enter a handoff chain")

    expected_links = (task_id, revision, assignment.assignment_id, context_digest)
    if (
        attempt.task_id,
        attempt.source_task_revision,
        attempt.assignment_id,
        attempt.context_manifest_sha256,
    ) != expected_links:
        raise ValueError("attempt does not bind the admitted assignment and context")
    if attempt.root_coordination_epoch != assignment.root_coordination_epoch:
        raise ValueError("attempt root coordination epoch mismatch")
    if attempt.deadline_at != assignment.budget.deadline_at:
        raise ValueError("attempt deadline does not match assignment budget")
    if (
        attempt.runtime_session_id is None
        or attempt.backend_id is None
        or attempt.profile_id is None
        or attempt.isolation is None
        or attempt.started_at is None
    ):
        raise ValueError("receipt chain requires a fully provisioned started attempt")

    if (
        payload.task_id,
        payload.source_task_revision,
        payload.assignment_id,
        payload.attempt_id,
        payload.context_manifest_sha256,
    ) != (
        task_id,
        revision,
        assignment.assignment_id,
        attempt.attempt_id,
        context_digest,
    ):
        raise ValueError("payload does not bind the attempt chain")
    cited_context_refs = {
        source_ref for claim in payload.claims for source_ref in claim.source_refs
    }
    if not cited_context_refs.issubset(context_refs):
        raise ValueError("payload cites sources outside its read-only context")

    payload_digest = contract_sha256(payload)
    receipt_links = (
        receipt.task_id,
        receipt.source_task_revision,
        receipt.assignment_id,
        receipt.attempt_id,
        receipt.attempt_integrity_id,
        receipt.context_manifest_sha256,
        receipt.payload_id,
        receipt.payload_sha256,
    )
    expected_receipt_links = (
        task_id,
        revision,
        assignment.assignment_id,
        attempt.attempt_id,
        attempt.attempt_integrity_id,
        context_digest,
        payload.payload_id,
        payload_digest,
    )
    if receipt_links != expected_receipt_links:
        raise ValueError("execution receipt artifact binding mismatch")
    runtime_links = (
        receipt.runtime_session_id,
        receipt.backend_id,
        receipt.profile_id,
        receipt.root_coordination_epoch,
        receipt.cancellation_epoch,
    )
    expected_runtime_links = (
        attempt.runtime_session_id,
        attempt.backend_id,
        attempt.profile_id,
        attempt.root_coordination_epoch,
        attempt.cancellation_epoch,
    )
    if runtime_links != expected_runtime_links:
        raise ValueError("execution receipt runtime binding mismatch")
    if receipt.budget != assignment.budget:
        raise ValueError("execution receipt budget differs from assignment")
    if receipt.usage.context_bytes != context.total_size_bytes:
        raise ValueError("receipt context usage must match manifest accounting")
    payload_size = len(canonical_contract_json(payload).encode("utf-8"))
    if receipt.usage.result_bytes != payload_size:
        raise ValueError("receipt result usage must match canonical payload bytes")
    if receipt.usage.claims_count != len(payload.claims):
        raise ValueError("receipt claim count must match payload")
    if receipt.outcome_state is not AgentLifecycleState.RESULT_RECEIVED:
        raise ValueError("non-result execution cannot produce a distilled handoff")
    if receipt.cleanup_state is not CleanupState.CLEANUP_COMPLETE:
        raise ValueError("incomplete cleanup blocks distilled handoff")
    if receipt.late_result:
        raise ValueError("late worker result cannot enter a distilled handoff")

    proposed_by_key = {item.claim_key: item for item in payload.claims}
    for claim in claims:
        if (
            claim.task_id,
            claim.source_task_revision,
            claim.assignment_id,
            claim.attempt_id,
            claim.payload_id,
        ) != (
            task_id,
            revision,
            assignment.assignment_id,
            attempt.attempt_id,
            payload.payload_id,
        ):
            raise ValueError("claim record source-chain mismatch")
        proposed = proposed_by_key.get(claim.source_claim_key)
        if proposed is None or proposed.statement != claim.statement:
            raise ValueError("claim record does not resolve an exact proposed claim")
        allowed_refs = {
            *proposed.source_refs,
            *proposed.evidence_refs,
            *proposed.observation_refs,
        }
        if any(item.evidence_ref not in allowed_refs for item in claim.evidence_lineage):
            raise ValueError("claim lineage references undeclared worker evidence")

    claim_ids = tuple(sorted(item.claim_record_id for item in claims))
    handoff_claim_ids = tuple(item.claim_record_id for item in handoff.qualified_claims)
    if handoff_claim_ids != claim_ids:
        raise ValueError("handoff must contain exactly the supplied qualified claims")
    if (
        handoff.task_id,
        handoff.source_task_revision,
        handoff.assignment_id,
        handoff.attempt_id,
        handoff.context_manifest_sha256,
        handoff.payload_id,
        handoff.payload_sha256,
        handoff.receipt_id,
        handoff.receipt_sha256,
    ) != (
        task_id,
        revision,
        assignment.assignment_id,
        attempt.attempt_id,
        context_digest,
        payload.payload_id,
        payload_digest,
        receipt.receipt_id,
        contract_sha256(receipt),
    ):
        raise ValueError("distilled handoff artifact binding mismatch")

    if adoption is None:
        return
    if adoption.task_id != task_id:
        raise ValueError("adoption task binding mismatch")
    if adoption.root_coordination_epoch != assignment.root_coordination_epoch:
        raise ValueError("adoption root coordination epoch mismatch")
    if adoption.current_root_state_revision != revision:
        raise ValueError("stale root state blocks adoption")
    if adoption.handoff_id != handoff.handoff_id or adoption.handoff_sha256 != contract_sha256(
        handoff
    ):
        raise ValueError("adoption handoff binding mismatch")
    if adoption.considered_claim_ids != claim_ids:
        raise ValueError("adoption must consider exactly the qualified handoff claims")
