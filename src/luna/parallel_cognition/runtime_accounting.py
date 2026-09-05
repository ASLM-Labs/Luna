"""Passive, fail-closed runtime token-accounting contracts for C-011.

The evaluator classifies supplied capability evidence only. It cannot call a model,
wire a runtime, grant execution authority, or treat text re-tokenization as native
usage measurement.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import require_utc
from luna.parallel_cognition.models import C011ContractModel, Sha256

GitObjectId = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
RuntimeUsageField = Literal["input_tokens", "output_tokens", "total_tokens"]

_REQUIRED_USAGE_FIELDS: tuple[RuntimeUsageField, ...] = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
)
_CURRENT_ABI_V1_EXPORTS = (
    "luna_nr2b_abi_version",
    "luna_nr2b_engine_create",
    "luna_nr2b_generate",
    "luna_nr2b_engine_destroy",
)
_CURRENT_ABI_V2_EXPORTS = (
    "luna_nr2b_abi_version",
    "luna_nr2b_engine_create",
    "luna_nr2b_engine_create_v2",
    "luna_nr2b_generate",
    "luna_nr2b_generate_v2",
    "luna_nr2b_engine_destroy",
)
_PROHIBITED_SUBSTITUTES = (
    "BUDGET_CEILING",
    "BYTE_ESTIMATE",
    "DRIVER_ZERO_PLACEHOLDER",
    "TEXT_RETOKENIZATION",
    "WORD_ESTIMATE",
)


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
    basis = {
        "contract_type": f"{type(model).__module__}.{type(model).__qualname__}",
        "schema_version": model.schema_version,
        "payload": model.model_dump(mode="json", exclude={identity_field}),
    }
    return f"{prefix}{sha256(_canonical_json(basis).encode('utf-8')).hexdigest()}"


def _unique_sorted(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError(f"{label} cannot contain blank values")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(normalized))


class RuntimeMeasurementSource(StrEnum):
    ENGINE_NATIVE_COUNTERS = "ENGINE_NATIVE_COUNTERS"
    DRIVER_REPORTED = "DRIVER_REPORTED"
    DERIVED_TEXT_RETOKENIZATION = "DERIVED_TEXT_RETOKENIZATION"
    NONE = "NONE"


class RuntimeAccountingDisposition(StrEnum):
    BLOCKED_USAGE_CHANNEL_ABSENT = "BLOCKED_USAGE_CHANNEL_ABSENT"
    BLOCKED_UNTRUSTED_MEASUREMENT = "BLOCKED_UNTRUSTED_MEASUREMENT"
    BLOCKED_TARGET_DRIFT = "BLOCKED_TARGET_DRIFT"
    READY_FOR_MEASURED_EXECUTION = "READY_FOR_MEASURED_EXECUTION"


class RuntimeAccountingReference(C011ContractModel):
    locator: str = Field(min_length=1, max_length=2000)
    content_sha256: Sha256
    source_revision: str = Field(min_length=1, max_length=500)


class RuntimeTokenSemantics(C011ContractModel):
    semantics_id: str = ""
    revision: Literal["1.0.0"] = "1.0.0"
    input_basis: Literal[
        "POST_CHAT_TEMPLATE_MODEL_TOKENIZATION"
    ] = "POST_CHAT_TEMPLATE_MODEL_TOKENIZATION"
    includes_special_tokens_actually_fed: Literal[True] = True
    includes_bos_if_actually_fed: Literal[True] = True
    output_basis: Literal["SAMPLED_NON_EOG_TOKENS"] = "SAMPLED_NON_EOG_TOKENS"
    terminal_eog_included: Literal[False] = False
    total_basis: Literal["INPUT_PLUS_OUTPUT"] = "INPUT_PLUS_OUTPUT"
    required_source: Literal[
        RuntimeMeasurementSource.ENGINE_NATIVE_COUNTERS
    ] = RuntimeMeasurementSource.ENGINE_NATIVE_COUNTERS
    prohibited_substitutes: tuple[str, ...] = _PROHIBITED_SUBSTITUTES

    @field_validator("prohibited_substitutes")
    @classmethod
    def validate_substitutes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = _unique_sorted(values, label="prohibited accounting substitutes")
        if normalized != _PROHIBITED_SUBSTITUTES:
            raise ValueError("token semantics require the canonical prohibited substitutes")
        return normalized

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = _content_identity(
            self,
            identity_field="semantics_id",
            prefix="c011-runtime-token-semantics:sha256:",
        )
        if not self.semantics_id:
            object.__setattr__(self, "semantics_id", expected)
        elif self.semantics_id != expected:
            raise ValueError("runtime token semantics ID does not match content")
        return self


class RuntimeTokenUsage(C011ContractModel):
    usage_id: str = ""
    source: RuntimeMeasurementSource
    input_tokens: int = Field(gt=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(gt=0)
    observed_at_utc: datetime
    evidence_refs: tuple[RuntimeAccountingReference, ...] = Field(
        min_length=1, max_length=16
    )

    @field_validator("observed_at_utc")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("evidence_refs")
    @classmethod
    def normalize_refs(
        cls,
        values: tuple[RuntimeAccountingReference, ...],
    ) -> tuple[RuntimeAccountingReference, ...]:
        locators = tuple(item.locator for item in values)
        if len(locators) != len(set(locators)):
            raise ValueError("runtime usage evidence locators must be unique")
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    item.locator,
                    item.content_sha256,
                    item.source_revision,
                ),
            )
        )

    @model_validator(mode="after")
    def validate_usage(self) -> Self:
        if self.source is RuntimeMeasurementSource.NONE:
            raise ValueError("a runtime usage observation requires a measurement source")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total tokens must equal input plus output tokens")
        expected = _content_identity(
            self,
            identity_field="usage_id",
            prefix="c011-runtime-token-usage:sha256:",
        )
        if not self.usage_id:
            object.__setattr__(self, "usage_id", expected)
        elif self.usage_id != expected:
            raise ValueError("runtime token usage ID does not match content")
        return self


class RuntimeAccountingPolicy(C011ContractModel):
    policy_id: str = ""
    revision: Literal["1.0.0"] = "1.0.0"
    target_branch: str = Field(min_length=1, max_length=500)
    target_commit_oid: GitObjectId
    target_tree_oid: GitObjectId
    evaluated_at_utc: datetime
    token_semantics: RuntimeTokenSemantics = Field(default_factory=RuntimeTokenSemantics)
    minimum_usage_abi_version: Literal[2] = 2
    required_usage_fields: tuple[RuntimeUsageField, ...] = _REQUIRED_USAGE_FIELDS
    accepted_measurement_sources: tuple[RuntimeMeasurementSource, ...] = (
        RuntimeMeasurementSource.ENGINE_NATIVE_COUNTERS,
    )
    owner_authorization_scope: Literal[
        "RUNTIME_ACCOUNTING_CONTRACT_ONLY"
    ] = "RUNTIME_ACCOUNTING_CONTRACT_ONLY"
    authorization_grants_execution_authority: Literal[False] = False
    runtime_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("evaluated_at_utc")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.required_usage_fields != _REQUIRED_USAGE_FIELDS:
            raise ValueError("runtime accounting requires the canonical usage fields")
        if self.accepted_measurement_sources != (
            RuntimeMeasurementSource.ENGINE_NATIVE_COUNTERS,
        ):
            raise ValueError("only engine-native counters are accepted measurements")
        expected = _content_identity(
            self,
            identity_field="policy_id",
            prefix="c011-runtime-accounting-policy:sha256:",
        )
        if not self.policy_id:
            object.__setattr__(self, "policy_id", expected)
        elif self.policy_id != expected:
            raise ValueError("runtime accounting policy ID does not match content")
        return self


class NativeUsageCapabilitySnapshot(C011ContractModel):
    snapshot_id: str = ""
    target_branch: str = Field(min_length=1, max_length=500)
    target_commit_oid: GitObjectId
    target_tree_oid: GitObjectId
    evaluated_at_utc: datetime
    abi_version: int = Field(ge=1)
    exported_symbols: tuple[str, ...] = Field(min_length=4, max_length=32)
    prompt_token_count_computed_inside_shim: bool
    generation_loop_samples_one_token_per_step: bool
    usage_channel_present: bool
    usage_result_fields: tuple[RuntimeUsageField, ...] = ()
    measurement_source: RuntimeMeasurementSource = RuntimeMeasurementSource.NONE
    usage: RuntimeTokenUsage | None = None
    worker_reported_tokens: int = Field(ge=0)
    source_refs: tuple[RuntimeAccountingReference, ...] = Field(
        min_length=1, max_length=16
    )
    capability_status: Literal["QUEUED"] = "QUEUED"
    default_enabled: Literal[False] = False
    rollout_stage: Literal["BLOCKED"] = "BLOCKED"
    provider_call_executed: Literal[False] = False
    real_model_execution_completed: Literal[False] = False
    transition_authority: Literal[False] = False

    @field_validator("evaluated_at_utc")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("exported_symbols")
    @classmethod
    def normalize_exports(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("exported symbols cannot contain blank values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("exported symbols must be unique")
        return normalized

    @field_validator("source_refs")
    @classmethod
    def normalize_refs(
        cls,
        values: tuple[RuntimeAccountingReference, ...],
    ) -> tuple[RuntimeAccountingReference, ...]:
        locators = tuple(item.locator for item in values)
        if len(locators) != len(set(locators)):
            raise ValueError("capability source locators must be unique")
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    item.locator,
                    item.content_sha256,
                    item.source_revision,
                ),
            )
        )

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.usage_channel_present:
            if self.abi_version < 2:
                raise ValueError("a measured usage channel requires ABI version 2 or newer")
            if (
                not self.usage_result_fields
                or self.measurement_source is RuntimeMeasurementSource.NONE
                or self.usage is None
            ):
                raise ValueError("a usage channel requires fields, source, and observation")
            if self.measurement_source is not self.usage.source:
                raise ValueError("snapshot and usage measurement sources must match")
        elif (
            self.usage_result_fields
            or self.measurement_source is not RuntimeMeasurementSource.NONE
            or self.usage is not None
        ):
            raise ValueError("an absent usage channel cannot claim usage evidence")
        if self.usage is not None and self.usage.observed_at_utc > self.evaluated_at_utc:
            raise ValueError("runtime usage evidence cannot postdate the snapshot")
        expected = _content_identity(
            self,
            identity_field="snapshot_id",
            prefix="c011-native-usage-capability:sha256:",
        )
        if not self.snapshot_id:
            object.__setattr__(self, "snapshot_id", expected)
        elif self.snapshot_id != expected:
            raise ValueError("native usage capability snapshot ID does not match content")
        return self


class RuntimeAccountingDecision(C011ContractModel):
    decision_id: str = ""
    policy_id: str = Field(
        pattern=r"^c011-runtime-accounting-policy:sha256:[0-9a-f]{64}$"
    )
    snapshot_id: str = Field(
        pattern=r"^c011-native-usage-capability:sha256:[0-9a-f]{64}$"
    )
    disposition: RuntimeAccountingDisposition
    blocked_reasons: tuple[str, ...] = ()
    accounting_ready: bool = False
    owner_authorization_recorded: Literal[True] = True
    execution_attempted: Literal[False] = False
    provider_call_executed: Literal[False] = False
    real_model_execution_completed: Literal[False] = False
    capability_status_after: Literal["QUEUED"] = "QUEUED"
    rollout_stage_after: Literal["BLOCKED"] = "BLOCKED"
    task_state_authority: Literal[False] = False
    root_context_adoption_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    canary_authority: Literal[False] = False
    active_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("blocked_reasons")
    @classmethod
    def normalize_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_sorted(values, label="runtime accounting blocked reasons")

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.disposition is RuntimeAccountingDisposition.READY_FOR_MEASURED_EXECUTION:
            if self.blocked_reasons or not self.accounting_ready:
                raise ValueError("accounting readiness cannot contain blocked reasons")
        elif self.accounting_ready or not self.blocked_reasons:
            raise ValueError("a blocked accounting decision requires reasons")
        expected = _content_identity(
            self,
            identity_field="decision_id",
            prefix="c011-runtime-accounting-decision:sha256:",
        )
        if not self.decision_id:
            object.__setattr__(self, "decision_id", expected)
        elif self.decision_id != expected:
            raise ValueError("runtime accounting decision ID does not match content")
        return self


def evaluate_runtime_accounting(
    *,
    policy: RuntimeAccountingPolicy,
    snapshot: NativeUsageCapabilitySnapshot,
) -> RuntimeAccountingDecision:
    """Classify measurement readiness without running or authorizing a model."""

    current_policy = RuntimeAccountingPolicy.model_validate(
        policy.model_dump(mode="json")
    )
    current_snapshot = NativeUsageCapabilitySnapshot.model_validate(
        snapshot.model_dump(mode="json")
    )
    drift_reasons: list[str] = []
    if current_snapshot.target_branch != current_policy.target_branch:
        drift_reasons.append("snapshot target branch does not match the frozen policy")
    if current_snapshot.target_commit_oid != current_policy.target_commit_oid:
        drift_reasons.append("snapshot target commit does not match the frozen policy")
    if current_snapshot.target_tree_oid != current_policy.target_tree_oid:
        drift_reasons.append("snapshot target tree does not match the frozen policy")
    if current_snapshot.evaluated_at_utc != current_policy.evaluated_at_utc:
        drift_reasons.append("snapshot evaluation time does not match the frozen policy")

    absent_reasons: list[str] = []
    if current_snapshot.abi_version < current_policy.minimum_usage_abi_version:
        absent_reasons.append("native ABI version is below the measured-usage minimum")
    if not current_snapshot.usage_channel_present:
        absent_reasons.append("native ABI exposes no usage channel")
    if current_snapshot.usage_result_fields != current_policy.required_usage_fields:
        absent_reasons.append("native ABI does not expose the required usage result fields")

    untrusted_reasons: list[str] = []
    if (
        current_snapshot.usage_channel_present
        and current_snapshot.measurement_source
        not in current_policy.accepted_measurement_sources
    ):
        untrusted_reasons.append(
            "usage source is not an engine-native counter measurement"
        )

    if drift_reasons:
        disposition = RuntimeAccountingDisposition.BLOCKED_TARGET_DRIFT
        reasons = drift_reasons
    elif absent_reasons:
        disposition = RuntimeAccountingDisposition.BLOCKED_USAGE_CHANNEL_ABSENT
        reasons = absent_reasons
    elif untrusted_reasons:
        disposition = RuntimeAccountingDisposition.BLOCKED_UNTRUSTED_MEASUREMENT
        reasons = untrusted_reasons
    else:
        disposition = RuntimeAccountingDisposition.READY_FOR_MEASURED_EXECUTION
        reasons = []

    return RuntimeAccountingDecision(
        policy_id=current_policy.policy_id,
        snapshot_id=current_snapshot.snapshot_id,
        disposition=disposition,
        blocked_reasons=tuple(reasons),
        accounting_ready=(
            disposition is RuntimeAccountingDisposition.READY_FOR_MEASURED_EXECUTION
        ),
    )


CURRENT_ABI_V1_EXPORTS = _CURRENT_ABI_V1_EXPORTS
CURRENT_ABI_V2_EXPORTS = _CURRENT_ABI_V2_EXPORTS
REQUIRED_USAGE_FIELDS = _REQUIRED_USAGE_FIELDS

__all__ = [
    "CURRENT_ABI_V1_EXPORTS",
    "CURRENT_ABI_V2_EXPORTS",
    "REQUIRED_USAGE_FIELDS",
    "NativeUsageCapabilitySnapshot",
    "RuntimeAccountingDecision",
    "RuntimeAccountingDisposition",
    "RuntimeAccountingPolicy",
    "RuntimeAccountingReference",
    "RuntimeMeasurementSource",
    "RuntimeTokenSemantics",
    "RuntimeTokenUsage",
    "evaluate_runtime_accounting",
]
