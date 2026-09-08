"""Pure non-expanding C-011 runtime work-profile projection."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import require_utc
from luna.parallel_cognition.admission import HierarchicalBudgetEnvelope
from luna.parallel_cognition.models import (
    C011ContractModel,
    WorkerBudgetEnvelope,
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


class _ContentAddressedRuntimeProfileContract(C011ContractModel):
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
            self._identity_prefix
            + sha256(_canonical_json(basis).encode("utf-8")).hexdigest()
        )
        supplied = getattr(self, self._identity_field)
        if not supplied:
            object.__setattr__(self, self._identity_field, expected)
        elif supplied != expected:
            raise ValueError(
                f"{self._identity_field} does not match canonical contract content"
            )
        return self


class C011RuntimeProfileName(StrEnum):
    """User-facing bounded C-011 work-effort tiers."""

    QUICK = "QUICK"
    NORMAL = "NORMAL"
    DEEP = "DEEP"


_PROFILE_ORDER = {
    C011RuntimeProfileName.QUICK: 0,
    C011RuntimeProfileName.NORMAL: 1,
    C011RuntimeProfileName.DEEP: 2,
}

_MONOTONE_FIELDS = (
    "max_total_workers",
    "max_concurrent_workers",
    "max_worker_context_bytes",
    "max_worker_result_bytes",
    "max_worker_claims",
    "max_worker_tokens",
    "max_worker_runtime_ms",
    "max_total_context_bytes",
    "max_total_result_bytes",
    "max_total_tokens",
    "max_total_runtime_ms",
    "max_wall_time_ms",
)


class C011RuntimeProfileSpec(_ContentAddressedRuntimeProfileContract):
    """One reviewed work-budget request; never an authority source."""

    profile_id: str = ""
    name: C011RuntimeProfileName
    max_total_workers: int = Field(ge=1, le=3)
    max_concurrent_workers: int = Field(ge=1, le=3)
    max_worker_context_bytes: int = Field(ge=1)
    max_worker_result_bytes: int = Field(ge=1)
    max_worker_claims: int = Field(ge=0)
    max_worker_tokens: int = Field(ge=0)
    max_worker_runtime_ms: int = Field(ge=1)
    max_total_context_bytes: int = Field(ge=1)
    max_total_result_bytes: int = Field(ge=1)
    max_total_tokens: int = Field(ge=0)
    max_total_runtime_ms: int = Field(ge=1)
    max_wall_time_ms: int = Field(ge=1)
    authority_granted: Literal[False] = False

    _identity_field = "profile_id"
    _identity_prefix = "c011-runtime-profile:sha256:"

    @model_validator(mode="after")
    def validate_budget_shape(self) -> Self:
        if self.max_concurrent_workers > self.max_total_workers:
            raise ValueError("runtime profile concurrency cannot exceed total workers")
        pairs = (
            (
                self.max_worker_context_bytes,
                self.max_total_context_bytes,
                "context",
            ),
            (
                self.max_worker_result_bytes,
                self.max_total_result_bytes,
                "result",
            ),
            (
                self.max_worker_tokens,
                self.max_total_tokens,
                "token",
            ),
            (
                self.max_worker_runtime_ms,
                self.max_total_runtime_ms,
                "runtime",
            ),
        )
        for worker, total, label in pairs:
            if worker > total:
                raise ValueError(
                    f"runtime profile per-worker {label} budget exceeds aggregate"
                )
        if self.max_worker_runtime_ms > self.max_wall_time_ms:
            raise ValueError("runtime profile worker runtime exceeds wall-time window")
        return self


class C011RuntimeProfileCatalog(_ContentAddressedRuntimeProfileContract):
    """Injected reviewed QUICK/NORMAL/DEEP catalog with no production defaults."""

    catalog_id: str = ""
    revision: Literal["1.0.0"] = "1.0.0"
    profiles: tuple[C011RuntimeProfileSpec, ...] = Field(min_length=3, max_length=3)
    authority_granted: Literal[False] = False

    _identity_field = "catalog_id"
    _identity_prefix = "c011-runtime-profile-catalog:sha256:"

    @field_validator("profiles")
    @classmethod
    def normalize_profiles(
        cls,
        values: tuple[C011RuntimeProfileSpec, ...],
    ) -> tuple[C011RuntimeProfileSpec, ...]:
        return tuple(sorted(values, key=lambda item: _PROFILE_ORDER[item.name]))

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        expected_names = tuple(C011RuntimeProfileName)
        actual_names = tuple(item.name for item in self.profiles)
        if actual_names != expected_names:
            raise ValueError("runtime profile catalog requires QUICK/NORMAL/DEEP")
        profile_ids = tuple(item.profile_id for item in self.profiles)
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("runtime profile catalog IDs must be unique")

        for lower, upper in zip(self.profiles, self.profiles[1:], strict=False):
            for field_name in _MONOTONE_FIELDS:
                if getattr(lower, field_name) > getattr(upper, field_name):
                    raise ValueError(
                        "runtime profile catalog must be monotone QUICK <= NORMAL <= DEEP"
                    )
        return self

    def profile(self, name: C011RuntimeProfileName) -> C011RuntimeProfileSpec:
        for profile in self.profiles:
            if profile.name is name:
                return profile.model_copy(deep=True)
        raise ValueError(f"runtime profile is not registered: {name.value}")


def _validate_owner_ceilings(
    *,
    owner_worker_ceiling: WorkerBudgetEnvelope,
    owner_hierarchical_ceiling: HierarchicalBudgetEnvelope,
    observed_at: datetime,
    lease_expires_at: datetime,
) -> tuple[
    WorkerBudgetEnvelope,
    HierarchicalBudgetEnvelope,
    datetime,
    datetime,
]:
    worker = WorkerBudgetEnvelope.model_validate(
        owner_worker_ceiling.model_dump(mode="json")
    )
    hierarchy = HierarchicalBudgetEnvelope.model_validate(
        owner_hierarchical_ceiling.model_dump(mode="json")
    )
    observed = require_utc(observed_at)
    lease_expiry = require_utc(lease_expires_at)

    if observed >= worker.deadline_at:
        raise ValueError("owner worker deadline has elapsed")
    if observed >= hierarchy.overall_deadline_at:
        raise ValueError("owner hierarchical deadline has elapsed")
    if observed >= lease_expiry:
        raise ValueError("root lease has expired")

    return worker, hierarchy, observed, lease_expiry


def _remaining_milliseconds(start: datetime, end: datetime) -> int:
    delta = end - start
    return (
        delta.days * 86_400_000
        + delta.seconds * 1000
        + delta.microseconds // 1000
    )


def _compute_projection(
    *,
    profile: C011RuntimeProfileSpec,
    owner_worker_ceiling: WorkerBudgetEnvelope,
    owner_hierarchical_ceiling: HierarchicalBudgetEnvelope,
    observed_at: datetime,
    lease_expires_at: datetime,
) -> tuple[
    WorkerBudgetEnvelope,
    HierarchicalBudgetEnvelope,
    tuple[str, ...],
]:
    worker, hierarchy, observed, lease_expiry = _validate_owner_ceilings(
        owner_worker_ceiling=owner_worker_ceiling,
        owner_hierarchical_ceiling=owner_hierarchical_ceiling,
        observed_at=observed_at,
        lease_expires_at=lease_expires_at,
    )

    try:
        requested_deadline = observed + timedelta(
            milliseconds=profile.max_wall_time_ms
        )
    except OverflowError as exc:
        raise ValueError("runtime profile wall-time window is not representable") from exc

    effective_deadline = min(
        requested_deadline,
        worker.deadline_at,
        hierarchy.overall_deadline_at,
        lease_expiry,
    )
    remaining_runtime_ms = _remaining_milliseconds(observed, effective_deadline)
    if remaining_runtime_ms < 1:
        raise ValueError("runtime profile has less than one millisecond remaining")

    total_workers = min(
        profile.max_total_workers,
        hierarchy.max_total_workers,
    )
    concurrent_workers = min(
        profile.max_concurrent_workers,
        hierarchy.max_concurrent_workers,
        total_workers,
    )
    if total_workers < 1 or concurrent_workers < 1:
        raise ValueError("owner ceiling does not admit a runtime-profile worker")

    worker_context = min(
        profile.max_worker_context_bytes,
        worker.max_context_bytes,
        hierarchy.max_worker_context_bytes,
    )
    worker_result = min(
        profile.max_worker_result_bytes,
        worker.max_result_bytes,
        hierarchy.max_worker_result_bytes,
    )
    worker_claims = min(
        profile.max_worker_claims,
        worker.max_claims,
    )
    worker_tokens = min(
        profile.max_worker_tokens,
        worker.max_tokens,
        hierarchy.max_worker_tokens,
    )
    worker_runtime = min(
        profile.max_worker_runtime_ms,
        worker.max_runtime_ms,
        hierarchy.max_worker_runtime_ms,
        remaining_runtime_ms,
    )
    if worker_context < 1 or worker_result < 1 or worker_runtime < 1:
        raise ValueError("owner ceiling cannot represent the selected runtime profile")

    total_context = min(
        profile.max_total_context_bytes,
        hierarchy.max_total_context_bytes,
        worker_context * total_workers,
    )
    total_result = min(
        profile.max_total_result_bytes,
        hierarchy.max_total_result_bytes,
        worker_result * total_workers,
    )
    total_tokens = min(
        profile.max_total_tokens,
        hierarchy.max_total_tokens,
        worker_tokens * total_workers,
    )
    total_runtime = min(
        profile.max_total_runtime_ms,
        hierarchy.max_total_runtime_ms,
        worker_runtime * total_workers,
    )

    projected_worker = WorkerBudgetEnvelope(
        max_context_bytes=worker_context,
        max_result_bytes=worker_result,
        max_claims=worker_claims,
        max_tokens=worker_tokens,
        max_runtime_ms=worker_runtime,
        deadline_at=effective_deadline,
    )
    projected_hierarchy = HierarchicalBudgetEnvelope(
        max_total_workers=total_workers,
        max_concurrent_workers=concurrent_workers,
        delegation_depth=1,
        max_worker_context_bytes=worker_context,
        max_worker_result_bytes=worker_result,
        max_worker_tokens=worker_tokens,
        max_worker_runtime_ms=worker_runtime,
        max_total_context_bytes=total_context,
        max_total_result_bytes=total_result,
        max_total_tokens=total_tokens,
        max_total_runtime_ms=total_runtime,
        overall_deadline_at=effective_deadline,
    )

    effective_values = {
        "max_total_workers": total_workers,
        "max_concurrent_workers": concurrent_workers,
        "max_worker_context_bytes": worker_context,
        "max_worker_result_bytes": worker_result,
        "max_worker_claims": worker_claims,
        "max_worker_tokens": worker_tokens,
        "max_worker_runtime_ms": worker_runtime,
        "max_total_context_bytes": total_context,
        "max_total_result_bytes": total_result,
        "max_total_tokens": total_tokens,
        "max_total_runtime_ms": total_runtime,
    }
    clamped = {
        field_name
        for field_name, effective_value in effective_values.items()
        if effective_value < getattr(profile, field_name)
    }
    if effective_deadline < requested_deadline:
        clamped.add("deadline_at")

    return (
        projected_worker,
        projected_hierarchy,
        tuple(sorted(clamped)),
    )


class C011RuntimeProfileProjection(_ContentAddressedRuntimeProfileContract):
    """Self-validating receipt for one non-expanding profile projection."""

    projection_id: str = ""
    selected: C011RuntimeProfileName
    catalog: C011RuntimeProfileCatalog
    owner_worker_ceiling: WorkerBudgetEnvelope
    owner_hierarchical_ceiling: HierarchicalBudgetEnvelope
    observed_at: datetime
    lease_expires_at: datetime
    worker_budget: WorkerBudgetEnvelope
    hierarchical_budget: HierarchicalBudgetEnvelope
    clamped_fields: tuple[str, ...] = ()
    authority_granted: Literal[False] = False

    _identity_field = "projection_id"
    _identity_prefix = "c011-runtime-profile-projection:sha256:"

    @field_validator("observed_at", "lease_expires_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("clamped_fields")
    @classmethod
    def normalize_clamped_fields(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in values)
        if any(not item for item in cleaned):
            raise ValueError("runtime profile clamped field names cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("runtime profile clamped field names must be unique")
        return tuple(sorted(cleaned))

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        profile = self.catalog.profile(self.selected)
        expected_worker, expected_hierarchy, expected_clamped = _compute_projection(
            profile=profile,
            owner_worker_ceiling=self.owner_worker_ceiling,
            owner_hierarchical_ceiling=self.owner_hierarchical_ceiling,
            observed_at=self.observed_at,
            lease_expires_at=self.lease_expires_at,
        )
        if self.worker_budget != expected_worker:
            raise ValueError("runtime profile worker budget does not match projection inputs")
        if self.hierarchical_budget != expected_hierarchy:
            raise ValueError(
                "runtime profile hierarchical budget does not match projection inputs"
            )
        if self.clamped_fields != expected_clamped:
            raise ValueError("runtime profile clamp evidence does not match projection inputs")
        return self

    @property
    def selected_profile_id(self) -> str:
        return self.catalog.profile(self.selected).profile_id

    @property
    def owner_worker_ceiling_sha256(self) -> str:
        return contract_sha256(self.owner_worker_ceiling)

    @property
    def owner_hierarchical_ceiling_sha256(self) -> str:
        return contract_sha256(self.owner_hierarchical_ceiling)


def project_c011_runtime_profile(
    *,
    catalog: C011RuntimeProfileCatalog,
    selected: C011RuntimeProfileName,
    owner_worker_ceiling: WorkerBudgetEnvelope,
    owner_hierarchical_ceiling: HierarchicalBudgetEnvelope,
    observed_at: datetime,
    lease_expires_at: datetime,
) -> C011RuntimeProfileProjection:
    """Project one named profile without ever raising current owner ceilings."""
    current_catalog = C011RuntimeProfileCatalog.model_validate(
        catalog.model_dump(mode="json")
    )
    profile = current_catalog.profile(selected)
    worker_budget, hierarchical_budget, clamped_fields = _compute_projection(
        profile=profile,
        owner_worker_ceiling=owner_worker_ceiling,
        owner_hierarchical_ceiling=owner_hierarchical_ceiling,
        observed_at=observed_at,
        lease_expires_at=lease_expires_at,
    )
    return C011RuntimeProfileProjection(
        selected=selected,
        catalog=current_catalog,
        owner_worker_ceiling=owner_worker_ceiling,
        owner_hierarchical_ceiling=owner_hierarchical_ceiling,
        observed_at=observed_at,
        lease_expires_at=lease_expires_at,
        worker_budget=worker_budget,
        hierarchical_budget=hierarchical_budget,
        clamped_fields=clamped_fields,
    )


__all__ = [
    "C011RuntimeProfileCatalog",
    "C011RuntimeProfileName",
    "C011RuntimeProfileProjection",
    "C011RuntimeProfileSpec",
    "project_c011_runtime_profile",
]
