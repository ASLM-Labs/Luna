"""Deterministic S3 aggregate reconciliation without majority-vote authority."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import require_utc
from luna.parallel_cognition.models import C011ContractModel, Sha256, contract_sha256
from luna.parallel_cognition.resolution import ClaimResolutionReceipt


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class _ContentAddressedReconciliation(C011ContractModel):
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


class ReconciliationDisposition(StrEnum):
    """Aggregate result; ACCEPT grants root consideration only."""

    ACCEPT = "ACCEPT"
    CONFLICT = "CONFLICT"
    VERIFY = "VERIFY"


class IssuedClaimSpec(C011ContractModel):
    """One root-issued claim key and the lanes required to address it."""

    claim_key: str = Field(min_length=1, max_length=500)
    required_assignment_ids: tuple[str, ...] = Field(min_length=1, max_length=3)

    @field_validator("required_assignment_ids")
    @classmethod
    def normalize_assignments(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in values)
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("issued claim assignment IDs must be unique")
        return tuple(sorted(cleaned))


class RootIssuedClaimSchema(_ContentAddressedReconciliation):
    """Root-owned namespace; workers cannot invent eligible claim keys."""

    _identity_field = "claim_schema_id"
    _identity_prefix = "c011-root-claim-schema:sha256:"

    claim_schema_id: str = ""
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    plan_seal_sha256: Sha256
    assignment_ids: tuple[str, ...] = Field(min_length=1, max_length=3)
    claims: tuple[IssuedClaimSpec, ...] = Field(min_length=1, max_length=128)
    issued_at: datetime
    expires_at: datetime
    worker_authored: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    @field_validator("issued_at", "expires_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("assignment_ids")
    @classmethod
    def normalize_assignment_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in values)
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("claim schema assignment IDs must be unique")
        return tuple(sorted(cleaned))

    @field_validator("claims")
    @classmethod
    def normalize_claims(cls, values: tuple[IssuedClaimSpec, ...]) -> tuple[IssuedClaimSpec, ...]:
        keys = tuple(item.claim_key for item in values)
        if len(keys) != len(set(keys)):
            raise ValueError("root-issued claim keys must be unique")
        return tuple(sorted(values, key=lambda item: item.claim_key))

    @model_validator(mode="after")
    def validate_schema(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("root claim schema expiry must be after issuance")
        allowed = set(self.assignment_ids)
        if any(not set(item.required_assignment_ids).issubset(allowed) for item in self.claims):
            raise ValueError("issued claim requires an assignment outside the schema")
        return self


class ReconciledClaim(C011ContractModel):
    """Deterministic disposition for one root-issued claim key."""

    claim_key: str = Field(min_length=1, max_length=500)
    disposition: ReconciliationDisposition
    statement: str | None = Field(default=None, max_length=4000)
    assignment_ids: tuple[str, ...] = Field(max_length=3)
    claim_resolution_ids: tuple[str, ...] = Field(max_length=384)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=32)

    @field_validator("assignment_ids", "claim_resolution_ids", "reason_codes")
    @classmethod
    def normalize_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in values)
        if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
            raise ValueError("reconciled claim entries must be nonblank and unique")
        return tuple(sorted(cleaned))

    @model_validator(mode="after")
    def validate_claim(self) -> Self:
        if self.disposition is ReconciliationDisposition.ACCEPT:
            if len(self.assignment_ids) != len(self.claim_resolution_ids):
                raise ValueError("accepted claim assignments and receipts must be one-to-one")
            if self.statement is None or self.reason_codes != ("EXACT_AGREEMENT",):
                raise ValueError("accepted claim requires exact agreement")
        elif self.statement is not None:
            raise ValueError("unresolved claim cannot select a statement")
        return self


class ReconciliationReceipt(_ContentAddressedReconciliation):
    """Aggregate result with provenance and no adoption or completion authority."""

    _identity_field = "reconciliation_receipt_id"
    _identity_prefix = "c011-reconciliation:sha256:"

    reconciliation_receipt_id: str = ""
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    claim_schema_id: str = Field(pattern=r"^c011-root-claim-schema:sha256:[0-9a-f]{64}$")
    claim_schema_sha256: Sha256
    input_resolution_ids: tuple[str, ...] = Field(max_length=384)
    input_resolution_sha256s: tuple[Sha256, ...] = Field(max_length=384)
    claims: tuple[ReconciledClaim, ...] = Field(min_length=1, max_length=128)
    disposition: ReconciliationDisposition
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=128)
    reconciled_at: datetime
    eligible_for_root_consideration: bool
    automatically_adopted: Literal[False] = False
    majority_vote_used: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    @field_validator("reconciled_at")
    @classmethod
    def validate_reconciled_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("input_resolution_ids", "input_resolution_sha256s", "reason_codes")
    @classmethod
    def normalize_entries(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in values)
        if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
            raise ValueError("reconciliation entries must be nonblank and unique")
        return tuple(sorted(cleaned))

    @field_validator("claims")
    @classmethod
    def normalize_claims(cls, values: tuple[ReconciledClaim, ...]) -> tuple[ReconciledClaim, ...]:
        keys = tuple(item.claim_key for item in values)
        if len(keys) != len(set(keys)):
            raise ValueError("reconciled claim keys must be unique")
        return tuple(sorted(values, key=lambda item: item.claim_key))

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        expected_eligible = self.disposition is ReconciliationDisposition.ACCEPT
        if self.eligible_for_root_consideration is not expected_eligible:
            raise ValueError("root-consideration eligibility must match reconciliation")
        claim_dispositions = {item.disposition for item in self.claims}
        if self.disposition is ReconciliationDisposition.ACCEPT and claim_dispositions != {
            ReconciliationDisposition.ACCEPT
        }:
            raise ValueError("aggregate ACCEPT requires every issued claim to agree")
        if (
            self.disposition is ReconciliationDisposition.CONFLICT
            and ReconciliationDisposition.CONFLICT not in claim_dispositions
        ):
            raise ValueError("aggregate CONFLICT requires a conflicting claim")
        return self


class DeterministicReconciler:
    """Reconcile eligible resolutions by exact equality, never by vote count."""

    def reconcile(
        self,
        *,
        schema: RootIssuedClaimSchema,
        resolutions: tuple[ClaimResolutionReceipt, ...],
        reconciled_at: datetime,
    ) -> ReconciliationReceipt:
        current_schema = RootIssuedClaimSchema.model_validate(schema.model_dump(mode="json"))
        current = tuple(
            ClaimResolutionReceipt.model_validate(item.model_dump(mode="json"))
            for item in resolutions
        )
        observed_at = require_utc(reconciled_at)
        schema_keys = {item.claim_key for item in current_schema.claims}
        schema_assignments = set(current_schema.assignment_ids)
        global_reasons: set[str] = set()
        if not (current_schema.issued_at <= observed_at < current_schema.expires_at):
            global_reasons.add("CLAIM_SCHEMA_NOT_CURRENT")
        if len({item.claim_resolution_id for item in current}) != len(current):
            global_reasons.add("DUPLICATE_RESOLUTION_ID")
        unique_by_id = {item.claim_resolution_id: item for item in current}
        unique = tuple(unique_by_id.values())
        if any(
            item.task_id != current_schema.task_id
            or item.source_task_revision != current_schema.source_task_revision
            for item in unique
        ):
            global_reasons.add("RESOLUTION_TASK_BINDING_MISMATCH")
        if any(item.assignment_id not in schema_assignments for item in unique):
            global_reasons.add("UNISSUED_ASSIGNMENT")
        if any(item.claim_key not in schema_keys for item in unique):
            global_reasons.add("UNISSUED_CLAIM_KEY")

        results_by_assignment: dict[str, set[str]] = {}
        for item in unique:
            results_by_assignment.setdefault(item.assignment_id, set()).add(item.result_id)
        if any(len(result_ids) != 1 for result_ids in results_by_assignment.values()):
            global_reasons.add("MULTIPLE_RESULTS_FOR_ASSIGNMENT")

        reconciled_claims: list[ReconciledClaim] = []
        by_key: dict[str, list[ClaimResolutionReceipt]] = {}
        for item in unique:
            by_key.setdefault(item.claim_key, []).append(item)
        for spec in current_schema.claims:
            items = tuple(
                sorted(
                    by_key.get(spec.claim_key, ()),
                    key=lambda item: (
                        item.assignment_id,
                        item.claim_resolution_id,
                    ),
                )
            )
            reasons: set[str] = set()
            raw_assignments = tuple(item.assignment_id for item in items)
            assignments = tuple(sorted(set(raw_assignments)))
            if len(raw_assignments) != len(assignments):
                reasons.add("DUPLICATE_ASSIGNMENT_CLAIM")
            if set(assignments) != set(spec.required_assignment_ids):
                reasons.add("REQUIRED_ASSIGNMENT_MISSING_OR_EXTRA")
            if any(
                not item.root_consideration_eligible or item.quarantine_required for item in items
            ):
                reasons.add("INELIGIBLE_RESOLUTION")
            statements = {item.statement for item in items}
            if len(statements) > 1:
                disposition = ReconciliationDisposition.CONFLICT
                reasons.add("STATEMENT_CONFLICT")
                statement: str | None = None
            elif reasons or global_reasons or not items:
                disposition = ReconciliationDisposition.VERIFY
                statement = None
                if global_reasons:
                    reasons.add("AGGREGATE_INPUT_INVALID")
                if not items:
                    reasons.add("CLAIM_RESULT_MISSING")
            else:
                disposition = ReconciliationDisposition.ACCEPT
                statement = items[0].statement
                reasons = {"EXACT_AGREEMENT"}
            reconciled_claims.append(
                ReconciledClaim(
                    claim_key=spec.claim_key,
                    disposition=disposition,
                    statement=statement,
                    assignment_ids=assignments,
                    claim_resolution_ids=tuple(item.claim_resolution_id for item in items),
                    reason_codes=tuple(sorted(reasons)),
                )
            )

        dispositions = {item.disposition for item in reconciled_claims}
        if ReconciliationDisposition.CONFLICT in dispositions:
            aggregate = ReconciliationDisposition.CONFLICT
        elif global_reasons or ReconciliationDisposition.VERIFY in dispositions:
            aggregate = ReconciliationDisposition.VERIFY
        else:
            aggregate = ReconciliationDisposition.ACCEPT
        aggregate_reasons = set(global_reasons)
        aggregate_reasons.update(
            f"{item.claim_key}:{reason}"
            for item in reconciled_claims
            for reason in item.reason_codes
            if reason != "EXACT_AGREEMENT"
        )
        if not aggregate_reasons:
            aggregate_reasons.add("ALL_ISSUED_CLAIMS_EXACTLY_AGREE")
        ordered_inputs = tuple(
            sorted(
                unique,
                key=lambda item: (
                    item.assignment_id,
                    item.claim_key,
                    item.claim_resolution_id,
                ),
            )
        )
        return ReconciliationReceipt(
            task_id=current_schema.task_id,
            source_task_revision=current_schema.source_task_revision,
            claim_schema_id=current_schema.claim_schema_id,
            claim_schema_sha256=contract_sha256(current_schema),
            input_resolution_ids=tuple(item.claim_resolution_id for item in ordered_inputs),
            input_resolution_sha256s=tuple(contract_sha256(item) for item in ordered_inputs),
            claims=tuple(reconciled_claims),
            disposition=aggregate,
            reason_codes=tuple(sorted(aggregate_reasons)),
            reconciled_at=observed_at,
            eligible_for_root_consideration=(aggregate is ReconciliationDisposition.ACCEPT),
        )


__all__ = [
    "DeterministicReconciler",
    "IssuedClaimSpec",
    "ReconciledClaim",
    "ReconciliationDisposition",
    "ReconciliationReceipt",
    "RootIssuedClaimSchema",
]
