"""C7 evidence-ref reconciliation for bounded worker results.

Worker results summarize independent reasoning and reference existing evidence
and observations. Reconciliation does not create evidence, mutate task state,
execute work, invalidate authoritative state, or decide task completion.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.planning.coordination import (
    CoordinationMode,
    CoordinationPlan,
    WorkerAssignment,
)


class WorkerResultStatus(StrEnum):
    """Bounded worker outcome before authoritative verification."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ReconciliationVerdict(StrEnum):
    """Non-authoritative C7 disposition over worker results."""

    ACCEPT = "ACCEPT"
    VERIFY = "VERIFY"
    STALE = "STALE"
    CONFLICT = "CONFLICT"
    REJECT = "REJECT"


class CoordinationClaim(LunaContractModel):
    """Comparable worker or main-solver claim without truth authority."""

    claim_key: str = Field(min_length=1, max_length=1000)
    claim_value: str = Field(min_length=1, max_length=4000)
    evidence_ids: tuple[UUID, ...] = ()
    provenance_refs: tuple[str, ...] = Field(min_length=1)
    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator("claim_key", "claim_value")
    @classmethod
    def validate_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("coordination claim text cannot be blank")
        return cleaned

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("coordination claim evidence IDs must be unique")
        return values

    @field_validator("provenance_refs")
    @classmethod
    def validate_provenance_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("coordination claim provenance refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("coordination claim provenance refs must be unique")
        return cleaned


class WorkerResult(LunaContractModel):
    """Evidence-ref result returned from one bounded C7 assignment."""

    result_id: str = Field(pattern=r"^worker-result:sha256:[0-9a-f]{64}$")
    task_id: UUID
    assignment_id: str = Field(pattern=r"^assignment:sha256:[0-9a-f]{64}$")
    source_task_revision: int = Field(ge=0)
    assignment_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: WorkerResultStatus
    claims: tuple[CoordinationClaim, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    observation_ids: tuple[UUID, ...] = ()
    blocker_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = Field(min_length=1)
    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator("evidence_ids", "observation_ids")
    @classmethod
    def validate_unique_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("worker result IDs must be unique")
        return values

    @field_validator("blocker_refs", "provenance_refs")
    @classmethod
    def validate_unique_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("worker result refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("worker result refs must be unique")
        return cleaned

    @classmethod
    def compute_result_fingerprint(
        cls,
        *,
        task_id: UUID,
        assignment_id: str,
        source_task_revision: int,
        assignment_basis_fingerprint: str,
        status: WorkerResultStatus,
        claims: tuple[CoordinationClaim, ...],
        evidence_ids: tuple[UUID, ...],
        observation_ids: tuple[UUID, ...],
        blocker_refs: tuple[str, ...],
        provenance_refs: tuple[str, ...],
    ) -> str:
        payload = {
            "assignment_basis_fingerprint": assignment_basis_fingerprint,
            "assignment_id": assignment_id,
            "blocker_refs": blocker_refs,
            "claims": tuple(item.model_dump(mode="json") for item in claims),
            "evidence_ids": tuple(str(item) for item in evidence_ids),
            "observation_ids": tuple(str(item) for item in observation_ids),
            "provenance_refs": provenance_refs,
            "source_task_revision": source_task_revision,
            "status": status.value,
            "task_id": str(task_id),
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_status_payload(self) -> Self:
        expected_fingerprint = self.compute_result_fingerprint(
            task_id=self.task_id,
            assignment_id=self.assignment_id,
            source_task_revision=self.source_task_revision,
            assignment_basis_fingerprint=self.assignment_basis_fingerprint,
            status=self.status,
            claims=self.claims,
            evidence_ids=self.evidence_ids,
            observation_ids=self.observation_ids,
            blocker_refs=self.blocker_refs,
            provenance_refs=self.provenance_refs,
        )
        expected_id = f"worker-result:sha256:{expected_fingerprint}"
        if self.result_id != expected_id:
            raise ValueError("worker result ID must derive from its complete result payload")

        claim_keys = tuple(item.claim_key for item in self.claims)
        if len(claim_keys) != len(set(claim_keys)):
            raise ValueError("worker result claim keys must be unique")

        referenced_claim_evidence = {
            evidence_id
            for claim in self.claims
            for evidence_id in claim.evidence_ids
        }
        if not referenced_claim_evidence.issubset(set(self.evidence_ids)):
            raise ValueError(
                "claim evidence must be included in worker result evidence IDs"
            )

        if self.status is WorkerResultStatus.SUCCESS:
            if not self.claims and not self.evidence_ids and not self.observation_ids:
                raise ValueError(
                    "successful worker result requires claims, evidence, or observations"
                )
            if self.blocker_refs:
                raise ValueError("successful worker result cannot carry blockers")

        if (
            self.status in {WorkerResultStatus.BLOCKED, WorkerResultStatus.FAILED}
            and not self.blocker_refs
        ):
            raise ValueError("blocked or failed worker result requires blockers")

        return self


class ReconciliationReport(LunaContractModel):
    """Non-authoritative C7 reconciliation over one coordination plan."""

    task_id: UUID
    coordination_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_task_revision: int = Field(ge=0)
    current_task_revision: int = Field(ge=0)
    verdict: ReconciliationVerdict
    accepted_result_ids: tuple[str, ...] = ()
    stale_assignment_ids: tuple[str, ...] = ()
    conflicting_claim_keys: tuple[str, ...] = ()
    rejected_result_ids: tuple[str, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    observation_ids: tuple[UUID, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)
    provenance_refs: tuple[str, ...] = Field(min_length=1)
    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator(
        "accepted_result_ids",
        "stale_assignment_ids",
        "conflicting_claim_keys",
        "rejected_result_ids",
        "reason_codes",
        "provenance_refs",
    )
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("reconciliation refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("reconciliation refs must be unique")
        return cleaned

    @field_validator("evidence_ids", "observation_ids")
    @classmethod
    def validate_unique_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("reconciliation IDs must be unique")
        return values

    @model_validator(mode="after")
    def validate_verdict_payload(self) -> Self:
        if self.current_task_revision < self.source_task_revision:
            raise ValueError(
                "current task revision cannot precede reconciliation source revision"
            )
        if self.verdict is ReconciliationVerdict.STALE and not self.stale_assignment_ids:
            raise ValueError("STALE reconciliation requires stale assignments")
        if (
            self.verdict is ReconciliationVerdict.CONFLICT
            and not self.conflicting_claim_keys
        ):
            raise ValueError("CONFLICT reconciliation requires conflicting claims")
        if self.verdict is ReconciliationVerdict.REJECT and not self.rejected_result_ids:
            raise ValueError("REJECT reconciliation requires rejected results")
        return self


class CoordinationReconciler:
    """Reconcile bounded worker outputs without becoming a truth authority."""

    @staticmethod
    def _fingerprint(payload: dict[str, object]) -> str:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def result(
        cls,
        *,
        assignment: WorkerAssignment,
        status: WorkerResultStatus,
        claims: tuple[CoordinationClaim, ...] = (),
        evidence_ids: tuple[UUID, ...] = (),
        observation_ids: tuple[UUID, ...] = (),
        blocker_refs: tuple[str, ...] = (),
        provenance_refs: tuple[str, ...] = (),
    ) -> WorkerResult:
        """Build one deterministic worker result bound to its assignment."""
        effective_provenance = provenance_refs or (
            f"task:{assignment.task_id}",
            assignment.assignment_id,
        )
        fingerprint = WorkerResult.compute_result_fingerprint(
            task_id=assignment.task_id,
            assignment_id=assignment.assignment_id,
            source_task_revision=assignment.source_task_revision,
            assignment_basis_fingerprint=assignment.assignment_basis_fingerprint,
            status=status,
            claims=claims,
            evidence_ids=evidence_ids,
            observation_ids=observation_ids,
            blocker_refs=blocker_refs,
            provenance_refs=effective_provenance,
        )

        return WorkerResult(
            result_id=f"worker-result:sha256:{fingerprint}",
            task_id=assignment.task_id,
            assignment_id=assignment.assignment_id,
            source_task_revision=assignment.source_task_revision,
            assignment_basis_fingerprint=assignment.assignment_basis_fingerprint,
            status=status,
            claims=claims,
            evidence_ids=evidence_ids,
            observation_ids=observation_ids,
            blocker_refs=blocker_refs,
            provenance_refs=effective_provenance,
        )

    def reconcile(
        self,
        *,
        plan: CoordinationPlan,
        results: tuple[WorkerResult, ...],
        current_task_revision: int,
        current_assignment_basis_fingerprints: Mapping[str, str],
        reference_claims: tuple[CoordinationClaim, ...] = (),
    ) -> ReconciliationReport:
        """Return one deterministic non-authoritative disposition."""
        if current_task_revision < plan.source_task_revision:
            raise ValueError("current task revision cannot precede plan source revision")

        assignments_by_id = {
            assignment.assignment_id: assignment for assignment in plan.assignments
        }

        for basis in current_assignment_basis_fingerprints.values():
            if len(basis) != 64 or any(
                character not in "0123456789abcdef" for character in basis
            ):
                raise ValueError(
                    "current assignment basis fingerprints must be lowercase sha256"
                )

        reference_claim_keys = tuple(
            claim.claim_key for claim in reference_claims
        )
        if len(reference_claim_keys) != len(set(reference_claim_keys)):
            raise ValueError("reference claim keys must be unique")

        result_ids = tuple(item.result_id for item in results)
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("worker result IDs must be unique")

        result_assignment_ids = tuple(item.assignment_id for item in results)
        if len(result_assignment_ids) != len(set(result_assignment_ids)):
            raise ValueError("each assignment may return at most one worker result")

        rejected: list[str] = []
        stale: list[str] = []
        accepted_results: list[WorkerResult] = []

        for result in results:
            assignment = assignments_by_id.get(result.assignment_id)
            if assignment is None:
                rejected.append(result.result_id)
                continue
            if (
                result.task_id != plan.task_id
                or result.source_task_revision != assignment.source_task_revision
                or result.assignment_basis_fingerprint
                != assignment.assignment_basis_fingerprint
            ):
                rejected.append(result.result_id)
                continue

            current_basis = current_assignment_basis_fingerprints.get(
                assignment.assignment_id
            )
            if current_basis is None:
                continue
            if current_basis != assignment.assignment_basis_fingerprint:
                stale.append(assignment.assignment_id)
                continue

            accepted_results.append(result)

        expected_assignment_ids = set(assignments_by_id)
        returned_assignment_ids = {
            result.assignment_id
            for result in results
            if result.assignment_id in assignments_by_id
        }
        missing_assignment_ids = expected_assignment_ids - returned_assignment_ids

        all_claims = [
            claim
            for result in accepted_results
            for claim in result.claims
        ]

        reference_by_key = {claim.claim_key: claim for claim in reference_claims}
        conflicting_keys: set[str] = set()

        values_by_key: dict[str, set[str]] = {}
        for claim in all_claims:
            values_by_key.setdefault(claim.claim_key, set()).add(claim.claim_value)

        for key, values in values_by_key.items():
            if len(values) > 1:
                conflicting_keys.add(key)

        if plan.mode is CoordinationMode.INDEPENDENT_REVIEW:
            for claim in all_claims:
                reference = reference_by_key.get(claim.claim_key)
                if reference is not None and reference.claim_value != claim.claim_value:
                    conflicting_keys.add(claim.claim_key)

        evidence_ids = tuple(
            dict.fromkeys(
                evidence_id
                for result in accepted_results
                for evidence_id in result.evidence_ids
            )
        )
        observation_ids = tuple(
            dict.fromkeys(
                observation_id
                for result in accepted_results
                for observation_id in result.observation_ids
            )
        )

        reasons: list[str] = []

        if rejected:
            verdict = ReconciliationVerdict.REJECT
            reasons.append("worker_result_not_bound_to_coordination_plan")
        elif stale:
            verdict = ReconciliationVerdict.STALE
            reasons.append("assignment_semantic_basis_changed")
        elif conflicting_keys:
            verdict = ReconciliationVerdict.CONFLICT
            reasons.append("independent_worker_claims_conflict")
        elif plan.mode is CoordinationMode.SOLO:
            if results:
                verdict = ReconciliationVerdict.REJECT
                rejected = list(result_ids)
                reasons.append("solo_plan_cannot_accept_worker_results")
            else:
                verdict = ReconciliationVerdict.ACCEPT
                reasons.append("solo_plan_requires_no_worker_reconciliation")
        elif missing_assignment_ids:
            verdict = ReconciliationVerdict.VERIFY
            reasons.append("expected_worker_result_missing")
        elif any(
            assignment.assignment_id
            not in current_assignment_basis_fingerprints
            for assignment in plan.assignments
        ):
            verdict = ReconciliationVerdict.VERIFY
            reasons.append("current_assignment_basis_unavailable")
        elif any(
            result.status is not WorkerResultStatus.SUCCESS
            for result in accepted_results
        ):
            verdict = ReconciliationVerdict.VERIFY
            reasons.append("worker_result_not_fully_successful")
        elif not accepted_results:
            verdict = ReconciliationVerdict.VERIFY
            reasons.append("no_eligible_worker_results")
        elif any(
            not result.evidence_ids and not result.observation_ids
            for result in accepted_results
        ):
            verdict = ReconciliationVerdict.VERIFY
            reasons.append(
                "worker_result_lacks_external_evidence_or_observation"
            )
        elif plan.mode is CoordinationMode.INDEPENDENT_REVIEW:
            worker_claim_keys = {claim.claim_key for claim in all_claims}
            reference_keys = set(reference_by_key)
            if not reference_keys:
                verdict = ReconciliationVerdict.VERIFY
                reasons.append("independent_review_has_no_reference_claim")
            elif not worker_claim_keys.intersection(reference_keys):
                verdict = ReconciliationVerdict.VERIFY
                reasons.append("independent_review_has_no_comparable_main_claim")
            elif not reference_keys.issubset(worker_claim_keys):
                verdict = ReconciliationVerdict.VERIFY
                reasons.append("independent_review_reference_claims_not_fully_covered")
            else:
                verdict = ReconciliationVerdict.ACCEPT
                reasons.append("independent_review_agrees_on_all_reference_claims")
        else:
            verdict = ReconciliationVerdict.ACCEPT
            reasons.append("parallel_worker_results_reconciled")

        if current_task_revision != plan.source_task_revision:
            reasons.append("task_revision_changed_semantic_basis_checked")

        provenance_refs = (
            f"task:{plan.task_id}",
            f"c7:{plan.coordination_basis_fingerprint}",
            *(result.result_id for result in results),
        )

        return ReconciliationReport(
            task_id=plan.task_id,
            coordination_basis_fingerprint=plan.coordination_basis_fingerprint,
            source_task_revision=plan.source_task_revision,
            current_task_revision=current_task_revision,
            verdict=verdict,
            accepted_result_ids=tuple(
                result.result_id for result in accepted_results
            ),
            stale_assignment_ids=tuple(stale),
            conflicting_claim_keys=tuple(sorted(conflicting_keys)),
            rejected_result_ids=tuple(rejected),
            evidence_ids=evidence_ids,
            observation_ids=observation_ids,
            reason_codes=tuple(reasons),
            provenance_refs=provenance_refs,
        )
