"""Content-addressed cognitive rehydration binding contracts."""

from __future__ import annotations

import json
from collections.abc import Iterable
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.context.integrity_models import ContextRequirement
from luna.contracts.base import SCHEMA_VERSION, LunaContractModel

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_MANIFEST_ID_PATTERN = r"^cognitive-rehydration:sha256:[0-9a-f]{64}$"


class CognitiveOwnerKind(StrEnum):
    """Canonical owner families that may be referenced during rehydration."""

    IDENTITY_PROFILE = "IDENTITY_PROFILE"
    VERIFIED_MEMORY = "VERIFIED_MEMORY"
    WORKING_SESSION = "WORKING_SESSION"
    VERIFICATION_EVIDENCE = "VERIFICATION_EVIDENCE"


class CognitiveOwnerBinding(LunaContractModel):
    """Opaque ref/digest binding to one canonical owner snapshot."""

    owner_kind: CognitiveOwnerKind
    source_ref: str = Field(min_length=1, max_length=4000)
    content_sha256: str = Field(pattern=_SHA256_PATTERN)

    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False


class CognitiveOwnerResolutionStatus(StrEnum):
    """Snapshot-level comparison result; not a semantic truth verdict."""

    MATCHED = "MATCHED"
    CHANGED = "CHANGED"
    MISSING = "MISSING"
    UNAVAILABLE = "UNAVAILABLE"


class CognitiveOwnerResolutionReason(StrEnum):
    """Deterministic reason for one owner snapshot resolution."""

    SNAPSHOT_MATCH = "SNAPSHOT_MATCH"
    CONTENT_CHANGED = "CONTENT_CHANGED"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    SOURCE_AND_CONTENT_CHANGED = "SOURCE_AND_CONTENT_CHANGED"
    OWNER_MISSING = "OWNER_MISSING"
    OWNER_UNAVAILABLE = "OWNER_UNAVAILABLE"


class CognitiveOwnerResolution(LunaContractModel):
    """Non-authoritative comparison between historical and current owner bindings."""

    historical_binding: CognitiveOwnerBinding
    current_binding: CognitiveOwnerBinding | None = None
    status: CognitiveOwnerResolutionStatus
    reason_code: CognitiveOwnerResolutionReason

    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        current = self.current_binding

        if self.status in {
            CognitiveOwnerResolutionStatus.MATCHED,
            CognitiveOwnerResolutionStatus.CHANGED,
        }:
            if current is None:
                raise ValueError("matched/changed owner resolution requires current binding")
            if current.owner_kind is not self.historical_binding.owner_kind:
                raise ValueError("current owner binding kind must match historical owner kind")

            source_changed = current.source_ref != self.historical_binding.source_ref
            content_changed = (
                current.content_sha256 != self.historical_binding.content_sha256
            )

            if not source_changed and not content_changed:
                expected_status = CognitiveOwnerResolutionStatus.MATCHED
                expected_reason = CognitiveOwnerResolutionReason.SNAPSHOT_MATCH
            elif source_changed and content_changed:
                expected_status = CognitiveOwnerResolutionStatus.CHANGED
                expected_reason = (
                    CognitiveOwnerResolutionReason.SOURCE_AND_CONTENT_CHANGED
                )
            elif source_changed:
                expected_status = CognitiveOwnerResolutionStatus.CHANGED
                expected_reason = CognitiveOwnerResolutionReason.SOURCE_CHANGED
            else:
                expected_status = CognitiveOwnerResolutionStatus.CHANGED
                expected_reason = CognitiveOwnerResolutionReason.CONTENT_CHANGED

            if self.status is not expected_status or self.reason_code is not expected_reason:
                raise ValueError("cognitive owner resolution comparison mismatch")
            return self

        if current is not None:
            raise ValueError("missing/unavailable owner resolution cannot carry current binding")

        expected_reason = (
            CognitiveOwnerResolutionReason.OWNER_MISSING
            if self.status is CognitiveOwnerResolutionStatus.MISSING
            else CognitiveOwnerResolutionReason.OWNER_UNAVAILABLE
        )
        if self.reason_code is not expected_reason:
            raise ValueError("cognitive owner absence reason mismatch")
        return self

    @property
    def requires_semantic_reconciliation(self) -> bool:
        """Return whether current semantic truth must be resolved beyond snapshot equality."""

        return self.status is not CognitiveOwnerResolutionStatus.MATCHED


def build_cognitive_owner_resolution(
    *,
    historical_binding: CognitiveOwnerBinding,
    current_binding: CognitiveOwnerBinding | None = None,
    absence_status: CognitiveOwnerResolutionStatus | None = None,
) -> CognitiveOwnerResolution:
    """Build one snapshot resolution without claiming semantic contradiction."""

    if current_binding is not None:
        if absence_status is not None:
            raise ValueError("absence_status is invalid when current binding is present")
        if current_binding.owner_kind is not historical_binding.owner_kind:
            raise ValueError("current owner binding kind must match historical owner kind")

        source_changed = current_binding.source_ref != historical_binding.source_ref
        content_changed = current_binding.content_sha256 != historical_binding.content_sha256

        if not source_changed and not content_changed:
            status = CognitiveOwnerResolutionStatus.MATCHED
            reason = CognitiveOwnerResolutionReason.SNAPSHOT_MATCH
        elif source_changed and content_changed:
            status = CognitiveOwnerResolutionStatus.CHANGED
            reason = CognitiveOwnerResolutionReason.SOURCE_AND_CONTENT_CHANGED
        elif source_changed:
            status = CognitiveOwnerResolutionStatus.CHANGED
            reason = CognitiveOwnerResolutionReason.SOURCE_CHANGED
        else:
            status = CognitiveOwnerResolutionStatus.CHANGED
            reason = CognitiveOwnerResolutionReason.CONTENT_CHANGED

        return CognitiveOwnerResolution(
            historical_binding=historical_binding,
            current_binding=current_binding,
            status=status,
            reason_code=reason,
        )

    if absence_status not in {
        CognitiveOwnerResolutionStatus.MISSING,
        CognitiveOwnerResolutionStatus.UNAVAILABLE,
    }:
        raise ValueError(
            "missing current binding requires MISSING or UNAVAILABLE absence_status"
        )

    reason = (
        CognitiveOwnerResolutionReason.OWNER_MISSING
        if absence_status is CognitiveOwnerResolutionStatus.MISSING
        else CognitiveOwnerResolutionReason.OWNER_UNAVAILABLE
    )
    return CognitiveOwnerResolution(
        historical_binding=historical_binding,
        status=absence_status,
        reason_code=reason,
    )


def _canonical_json_sha256(payload: object) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(rendered.encode("utf-8")).hexdigest()


def _canonical_bindings(
    bindings: Iterable[CognitiveOwnerBinding],
) -> tuple[CognitiveOwnerBinding, ...]:
    return tuple(
        sorted(
            bindings,
            key=lambda item: (item.owner_kind.value, item.source_ref),
        )
    )


def _manifest_identity_payload(
    *,
    task_id: UUID,
    checkpoint_id: UUID,
    task_revision: int,
    task_state_sha256: str,
    bindings: Iterable[CognitiveOwnerBinding],
    semantics_version: int = 1,
) -> dict[str, object]:
    ordered = _canonical_bindings(bindings)
    return {
        "schema_version": SCHEMA_VERSION,
        "semantics_version": semantics_version,
        "task_id": str(task_id),
        "checkpoint_id": str(checkpoint_id),
        "task_revision": task_revision,
        "task_state_sha256": task_state_sha256,
        "bindings": [item.model_dump(mode="json") for item in ordered],
        "runtime_authority": False,
        "execution_authority": False,
        "completion_authority": False,
    }


def compute_cognitive_rehydration_manifest_id(
    *,
    task_id: UUID,
    checkpoint_id: UUID,
    task_revision: int,
    task_state_sha256: str,
    bindings: Iterable[CognitiveOwnerBinding],
    semantics_version: int = 1,
) -> str:
    """Return the content-addressed identity for one rehydration manifest."""

    digest = _canonical_json_sha256(
        _manifest_identity_payload(
            task_id=task_id,
            checkpoint_id=checkpoint_id,
            task_revision=task_revision,
            task_state_sha256=task_state_sha256,
            bindings=bindings,
            semantics_version=semantics_version,
        )
    )
    return f"cognitive-rehydration:sha256:{digest}"


class CognitiveRehydrationManifest(LunaContractModel):
    """Durable non-authoritative binding across canonical cognitive owners."""

    manifest_id: str = Field(pattern=_MANIFEST_ID_PATTERN)
    semantics_version: Literal[1] = 1

    task_id: UUID
    checkpoint_id: UUID
    task_revision: int = Field(ge=0)
    task_state_sha256: str = Field(pattern=_SHA256_PATTERN)

    bindings: tuple[CognitiveOwnerBinding, ...] = Field(min_length=1)

    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator("bindings")
    @classmethod
    def validate_bindings(
        cls,
        values: tuple[CognitiveOwnerBinding, ...],
    ) -> tuple[CognitiveOwnerBinding, ...]:
        ordered = _canonical_bindings(values)
        keys = tuple((item.owner_kind, item.source_ref) for item in ordered)
        if len(keys) != len(set(keys)):
            raise ValueError("cognitive owner bindings must be unique")

        identity_count = sum(
            item.owner_kind is CognitiveOwnerKind.IDENTITY_PROFILE for item in ordered
        )
        if identity_count != 1:
            raise ValueError(
                "cognitive rehydration manifest requires exactly one identity binding"
            )
        return ordered

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = compute_cognitive_rehydration_manifest_id(
            task_id=self.task_id,
            checkpoint_id=self.checkpoint_id,
            task_revision=self.task_revision,
            task_state_sha256=self.task_state_sha256,
            bindings=self.bindings,
            semantics_version=self.semantics_version,
        )
        if self.manifest_id != expected:
            raise ValueError("cognitive rehydration manifest identity mismatch")
        return self


class StoredCognitiveRehydrationManifest(LunaContractModel):
    """Persisted rehydration manifest plus its full-payload integrity digest."""

    manifest: CognitiveRehydrationManifest
    payload_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        expected = _canonical_json_sha256(self.manifest.model_dump(mode="json"))
        if self.payload_sha256 != expected:
            raise ValueError("cognitive rehydration manifest payload digest mismatch")
        return self


def build_cognitive_rehydration_manifest(
    *,
    task_id: UUID,
    checkpoint_id: UUID,
    task_revision: int,
    task_state_sha256: str,
    bindings: Iterable[CognitiveOwnerBinding],
) -> CognitiveRehydrationManifest:
    """Build a deterministic manifest without copying canonical owner truth."""

    bindings_tuple = tuple(bindings)
    manifest_id = compute_cognitive_rehydration_manifest_id(
        task_id=task_id,
        checkpoint_id=checkpoint_id,
        task_revision=task_revision,
        task_state_sha256=task_state_sha256,
        bindings=bindings_tuple,
    )
    return CognitiveRehydrationManifest(
        manifest_id=manifest_id,
        task_id=task_id,
        checkpoint_id=checkpoint_id,
        task_revision=task_revision,
        task_state_sha256=task_state_sha256,
        bindings=bindings_tuple,
    )


_POLICY_ID_PATTERN = (
    r"^cognitive-rehydration-policy:sha256:[0-9a-f]{64}$"
)


def _canonical_requirements(
    requirements: Iterable[ContextRequirement],
) -> tuple[ContextRequirement, ...]:
    items = tuple(requirements)
    keys = tuple(item.key for item in items)
    if len(keys) != len(set(keys)):
        raise ValueError("cognitive rehydration policy requirement keys must be unique")
    return tuple(
        sorted(
            items,
            key=lambda item: (item.key, item.claim_type.value),
        )
    )


def _policy_identity_payload(
    *,
    task_id: UUID,
    checkpoint_id: UUID,
    task_revision: int,
    task_state_sha256: str,
    requirements: Iterable[ContextRequirement],
    semantics_version: int = 1,
) -> dict[str, object]:
    ordered = _canonical_requirements(requirements)
    return {
        "schema_version": SCHEMA_VERSION,
        "semantics_version": semantics_version,
        "task_id": str(task_id),
        "checkpoint_id": str(checkpoint_id),
        "task_revision": task_revision,
        "task_state_sha256": task_state_sha256,
        "requirements": [
            item.model_dump(mode="json")
            for item in ordered
        ],
        "runtime_authority": False,
        "execution_authority": False,
        "verification_authority": False,
        "completion_authority": False,
    }


def compute_cognitive_rehydration_policy_id(
    *,
    task_id: UUID,
    checkpoint_id: UUID,
    task_revision: int,
    task_state_sha256: str,
    requirements: Iterable[ContextRequirement],
    semantics_version: int = 1,
) -> str:
    """Return the content-addressed identity for one rehydration policy."""

    digest = _canonical_json_sha256(
        _policy_identity_payload(
            task_id=task_id,
            checkpoint_id=checkpoint_id,
            task_revision=task_revision,
            task_state_sha256=task_state_sha256,
            requirements=requirements,
            semantics_version=semantics_version,
        )
    )
    return f"cognitive-rehydration-policy:sha256:{digest}"


class CognitiveRehydrationPolicy(LunaContractModel):
    """Exact historical context-readiness policy bound to one checkpoint."""

    policy_id: str = Field(pattern=_POLICY_ID_PATTERN)
    semantics_version: Literal[1] = 1

    task_id: UUID
    checkpoint_id: UUID
    task_revision: int = Field(ge=0)
    task_state_sha256: str = Field(pattern=_SHA256_PATTERN)

    requirements: tuple[ContextRequirement, ...] = ()

    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator("requirements")
    @classmethod
    def validate_requirements(
        cls,
        values: tuple[ContextRequirement, ...],
    ) -> tuple[ContextRequirement, ...]:
        return _canonical_requirements(values)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = compute_cognitive_rehydration_policy_id(
            task_id=self.task_id,
            checkpoint_id=self.checkpoint_id,
            task_revision=self.task_revision,
            task_state_sha256=self.task_state_sha256,
            requirements=self.requirements,
            semantics_version=self.semantics_version,
        )
        if self.policy_id != expected:
            raise ValueError("cognitive rehydration policy identity mismatch")
        return self


class StoredCognitiveRehydrationPolicy(LunaContractModel):
    """Persisted rehydration policy plus its full-payload integrity digest."""

    policy: CognitiveRehydrationPolicy
    payload_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        expected = _canonical_json_sha256(self.policy.model_dump(mode="json"))
        if self.payload_sha256 != expected:
            raise ValueError("cognitive rehydration policy payload digest mismatch")
        return self


def build_cognitive_rehydration_policy(
    *,
    task_id: UUID,
    checkpoint_id: UUID,
    task_revision: int,
    task_state_sha256: str,
    requirements: Iterable[ContextRequirement],
) -> CognitiveRehydrationPolicy:
    """Build exact deterministic readiness policy without granting authority."""

    requirements_tuple = tuple(requirements)
    policy_id = compute_cognitive_rehydration_policy_id(
        task_id=task_id,
        checkpoint_id=checkpoint_id,
        task_revision=task_revision,
        task_state_sha256=task_state_sha256,
        requirements=requirements_tuple,
    )
    return CognitiveRehydrationPolicy(
        policy_id=policy_id,
        task_id=task_id,
        checkpoint_id=checkpoint_id,
        task_revision=task_revision,
        task_state_sha256=task_state_sha256,
        requirements=requirements_tuple,
    )


_PROJECTION_ID_PATTERN = r"^cognitive-continuity:sha256:[0-9a-f]{64}$"


def _canonical_source_refs(values: Iterable[str]) -> tuple[str, ...]:
    cleaned = tuple(value.strip() for value in values)
    if any(not value for value in cleaned):
        raise ValueError("cognitive continuity source refs cannot be blank")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError("cognitive continuity source refs must be unique")
    return tuple(sorted(cleaned))


def _canonical_uuid_refs(values: Iterable[UUID], *, label: str) -> tuple[UUID, ...]:
    items = tuple(values)
    if len(items) != len(set(items)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(items, key=str))


def _canonical_keys(values: Iterable[str], *, label: str) -> tuple[str, ...]:
    cleaned = tuple(value.strip() for value in values)
    if any(not value for value in cleaned):
        raise ValueError(f"{label} cannot contain blank values")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(cleaned))


def _projection_identity_payload(
    *,
    task_id: UUID,
    task_revision: int,
    task_state_sha256: str,
    manifest_id: str,
    readiness_sha256: str,
    retained_bindings: Iterable[CognitiveOwnerBinding],
    rejected_source_refs: Iterable[str],
    active_assumption_ids: Iterable[UUID],
    active_decision_ids: Iterable[UUID],
    open_plan_step_ids: Iterable[UUID],
    unresolved_requirement_keys: Iterable[str],
    revalidation_required_keys: Iterable[str],
    semantics_version: int = 1,
) -> dict[str, object]:
    ordered_bindings = _canonical_bindings(retained_bindings)
    return {
        "schema_version": SCHEMA_VERSION,
        "semantics_version": semantics_version,
        "task_id": str(task_id),
        "task_revision": task_revision,
        "task_state_sha256": task_state_sha256,
        "manifest_id": manifest_id,
        "readiness_sha256": readiness_sha256,
        "retained_bindings": [
            item.model_dump(mode="json") for item in ordered_bindings
        ],
        "rejected_source_refs": list(_canonical_source_refs(rejected_source_refs)),
        "active_assumption_ids": [
            str(item)
            for item in _canonical_uuid_refs(
                active_assumption_ids,
                label="active assumption IDs",
            )
        ],
        "active_decision_ids": [
            str(item)
            for item in _canonical_uuid_refs(
                active_decision_ids,
                label="active decision IDs",
            )
        ],
        "open_plan_step_ids": [
            str(item)
            for item in _canonical_uuid_refs(
                open_plan_step_ids,
                label="open plan step IDs",
            )
        ],
        "unresolved_requirement_keys": list(
            _canonical_keys(
                unresolved_requirement_keys,
                label="unresolved requirement keys",
            )
        ),
        "revalidation_required_keys": list(
            _canonical_keys(
                revalidation_required_keys,
                label="revalidation-required keys",
            )
        ),
        "runtime_authority": False,
        "execution_authority": False,
        "completion_authority": False,
    }


def compute_cognitive_continuity_projection_id(
    *,
    task_id: UUID,
    task_revision: int,
    task_state_sha256: str,
    manifest_id: str,
    readiness_sha256: str,
    retained_bindings: Iterable[CognitiveOwnerBinding],
    rejected_source_refs: Iterable[str] = (),
    active_assumption_ids: Iterable[UUID] = (),
    active_decision_ids: Iterable[UUID] = (),
    open_plan_step_ids: Iterable[UUID] = (),
    unresolved_requirement_keys: Iterable[str] = (),
    revalidation_required_keys: Iterable[str] = (),
    semantics_version: int = 1,
) -> str:
    """Return the content-addressed identity for one reconciled projection."""

    digest = _canonical_json_sha256(
        _projection_identity_payload(
            task_id=task_id,
            task_revision=task_revision,
            task_state_sha256=task_state_sha256,
            manifest_id=manifest_id,
            readiness_sha256=readiness_sha256,
            retained_bindings=retained_bindings,
            rejected_source_refs=rejected_source_refs,
            active_assumption_ids=active_assumption_ids,
            active_decision_ids=active_decision_ids,
            open_plan_step_ids=open_plan_step_ids,
            unresolved_requirement_keys=unresolved_requirement_keys,
            revalidation_required_keys=revalidation_required_keys,
            semantics_version=semantics_version,
        )
    )
    return f"cognitive-continuity:sha256:{digest}"


class CognitiveContinuityProjection(LunaContractModel):
    """Ephemeral post-reconciliation view over current canonical owner bindings."""

    projection_id: str = Field(pattern=_PROJECTION_ID_PATTERN)
    semantics_version: Literal[1] = 1

    task_id: UUID
    task_revision: int = Field(ge=0)
    task_state_sha256: str = Field(pattern=_SHA256_PATTERN)

    manifest_id: str = Field(pattern=_MANIFEST_ID_PATTERN)
    readiness_sha256: str = Field(pattern=_SHA256_PATTERN)

    retained_bindings: tuple[CognitiveOwnerBinding, ...] = Field(min_length=1)
    rejected_source_refs: tuple[str, ...] = ()

    active_assumption_ids: tuple[UUID, ...] = ()
    active_decision_ids: tuple[UUID, ...] = ()
    open_plan_step_ids: tuple[UUID, ...] = ()

    unresolved_requirement_keys: tuple[str, ...] = ()
    revalidation_required_keys: tuple[str, ...] = ()

    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator("retained_bindings")
    @classmethod
    def validate_retained_bindings(
        cls,
        values: tuple[CognitiveOwnerBinding, ...],
    ) -> tuple[CognitiveOwnerBinding, ...]:
        ordered = _canonical_bindings(values)
        keys = tuple((item.owner_kind, item.source_ref) for item in ordered)
        if len(keys) != len(set(keys)):
            raise ValueError("retained cognitive owner bindings must be unique")

        identity_count = sum(
            item.owner_kind is CognitiveOwnerKind.IDENTITY_PROFILE for item in ordered
        )
        if identity_count != 1:
            raise ValueError(
                "cognitive continuity projection requires exactly one identity binding"
            )
        return ordered

    @field_validator("rejected_source_refs")
    @classmethod
    def validate_rejected_source_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_source_refs(values)

    @field_validator(
        "active_assumption_ids",
        "active_decision_ids",
        "open_plan_step_ids",
    )
    @classmethod
    def validate_uuid_refs(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return _canonical_uuid_refs(values, label="cognitive continuity UUID refs")

    @field_validator(
        "unresolved_requirement_keys",
        "revalidation_required_keys",
    )
    @classmethod
    def validate_requirement_keys(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_keys(values, label="cognitive continuity requirement keys")

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        retained_refs = {item.source_ref for item in self.retained_bindings}
        overlap = retained_refs.intersection(self.rejected_source_refs)
        if overlap:
            raise ValueError(
                "cognitive continuity source ref cannot be both retained and rejected"
            )

        expected = compute_cognitive_continuity_projection_id(
            task_id=self.task_id,
            task_revision=self.task_revision,
            task_state_sha256=self.task_state_sha256,
            manifest_id=self.manifest_id,
            readiness_sha256=self.readiness_sha256,
            retained_bindings=self.retained_bindings,
            rejected_source_refs=self.rejected_source_refs,
            active_assumption_ids=self.active_assumption_ids,
            active_decision_ids=self.active_decision_ids,
            open_plan_step_ids=self.open_plan_step_ids,
            unresolved_requirement_keys=self.unresolved_requirement_keys,
            revalidation_required_keys=self.revalidation_required_keys,
            semantics_version=self.semantics_version,
        )
        if self.projection_id != expected:
            raise ValueError("cognitive continuity projection identity mismatch")
        return self


def build_cognitive_continuity_projection(
    *,
    task_id: UUID,
    task_revision: int,
    task_state_sha256: str,
    manifest_id: str,
    readiness_sha256: str,
    retained_bindings: Iterable[CognitiveOwnerBinding],
    rejected_source_refs: Iterable[str] = (),
    active_assumption_ids: Iterable[UUID] = (),
    active_decision_ids: Iterable[UUID] = (),
    open_plan_step_ids: Iterable[UUID] = (),
    unresolved_requirement_keys: Iterable[str] = (),
    revalidation_required_keys: Iterable[str] = (),
) -> CognitiveContinuityProjection:
    """Build a deterministic current-state view without copying owner payloads."""

    bindings_tuple = tuple(retained_bindings)
    rejected_tuple = tuple(rejected_source_refs)
    assumptions_tuple = tuple(active_assumption_ids)
    decisions_tuple = tuple(active_decision_ids)
    steps_tuple = tuple(open_plan_step_ids)
    unresolved_tuple = tuple(unresolved_requirement_keys)
    revalidation_tuple = tuple(revalidation_required_keys)

    projection_id = compute_cognitive_continuity_projection_id(
        task_id=task_id,
        task_revision=task_revision,
        task_state_sha256=task_state_sha256,
        manifest_id=manifest_id,
        readiness_sha256=readiness_sha256,
        retained_bindings=bindings_tuple,
        rejected_source_refs=rejected_tuple,
        active_assumption_ids=assumptions_tuple,
        active_decision_ids=decisions_tuple,
        open_plan_step_ids=steps_tuple,
        unresolved_requirement_keys=unresolved_tuple,
        revalidation_required_keys=revalidation_tuple,
    )
    return CognitiveContinuityProjection(
        projection_id=projection_id,
        task_id=task_id,
        task_revision=task_revision,
        task_state_sha256=task_state_sha256,
        manifest_id=manifest_id,
        readiness_sha256=readiness_sha256,
        retained_bindings=bindings_tuple,
        rejected_source_refs=rejected_tuple,
        active_assumption_ids=assumptions_tuple,
        active_decision_ids=decisions_tuple,
        open_plan_step_ids=steps_tuple,
        unresolved_requirement_keys=unresolved_tuple,
        revalidation_required_keys=revalidation_tuple,
    )
