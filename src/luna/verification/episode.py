"""Non-authoritative, content-addressed verification episode manifests."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from luna.contracts.base import SCHEMA_VERSION, LunaContractModel, require_utc, stable_payload
from luna.contracts.evidence import Evidence
from luna.contracts.task import TaskContract
from luna.verification.models import CompletionGateResult, VerificationPolicy

DETERMINISTIC_VERIFIER_SEMANTICS_VERSION = "1"
VERIFICATION_BASIS_SCHEMA_VERSION = 1


def _canonical_sha256(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


class VerificationEvidenceRef(LunaContractModel):
    """Reference to one exact evidence payload supplied to verification."""

    evidence_id: UUID
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class VerificationEpisodeManifest(LunaContractModel):
    """Frozen projection of one audited verification occurrence."""

    episode_id: str = Field(pattern=r"^verification-episode:sha256:[0-9a-f]{64}$")
    task_id: UUID
    trace_id: UUID
    source_task_revision: int = Field(ge=0)
    verifier_semantics_version: str = Field(min_length=1, max_length=100)
    verification_time: datetime
    task_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_evidence: tuple[VerificationEvidenceRef, ...]
    verification_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_report_id: UUID
    verification_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    completion_decision_id: UUID
    completion_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_event_id: UUID
    completion_event_id: UUID
    execution_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator("verification_time")
    @classmethod
    def validate_verification_time(cls, value: datetime) -> datetime:
        return require_utc(value)


def _semantic_evidence_payload(item: Evidence) -> dict[str, object]:
    return {
        "evidence_id": str(item.evidence_id),
        "task_id": str(item.task_id),
        "requirement_id": item.requirement_id,
        "source_kind": item.source_kind.value,
        "source_ref": item.source_ref,
        "result": item.result.value,
        "observed_at": item.observed_at.isoformat(),
        "environment_fingerprint": item.environment_fingerprint,
        "revision": item.revision,
        "freshness_seconds": item.freshness_seconds,
        "reproducible": item.reproducible,
        "confidence": item.confidence,
    }


def compute_verification_basis_fingerprint(
    *,
    contract: TaskContract,
    evidence: Iterable[Evidence],
    policy: VerificationPolicy,
    verification_time: datetime,
) -> str:
    """Hash inputs that can affect deterministic verification semantics."""
    verified_at = require_utc(verification_time)
    evidence_records = tuple(evidence)

    payload = {
        "basis_schema_version": VERIFICATION_BASIS_SCHEMA_VERSION,
        "verifier_semantics_version": DETERMINISTIC_VERIFIER_SEMANTICS_VERSION,
        "task_id": str(contract.task_id),
        "verification_contract": {
            "required_conditions": contract.required_conditions,
            "forbidden_outcomes": contract.forbidden_outcomes,
            "evidence_required": contract.evidence_required,
            "unknowns": contract.unknowns,
        },
        "policy": stable_payload(policy),
        "verification_time": verified_at.isoformat(),
        "evidence": tuple(
            _semantic_evidence_payload(item)
            for item in evidence_records
        ),
    }

    return _canonical_sha256(payload)


def _artifact_sha256(model: LunaContractModel) -> str:
    return _canonical_sha256(stable_payload(model))


def build_verification_episode(
    *,
    contract: TaskContract,
    source_task_revision: int,
    evidence: Iterable[Evidence],
    policy: VerificationPolicy,
    gate_result: CompletionGateResult,
    trace_id: UUID,
) -> VerificationEpisodeManifest:
    """Build a non-authoritative manifest over one completion-gate occurrence."""
    evidence_records = tuple(evidence)
    report = gate_result.report
    decision = gate_result.decision

    if report.task_id != contract.task_id:
        raise ValueError(
            "verification episode contract and report task IDs must match"
        )

    if report.policy != policy:
        raise ValueError(
            "verification episode policy must match the gate report policy"
        )

    verification_time = report.generated_at

    basis = compute_verification_basis_fingerprint(
        contract=contract,
        evidence=evidence_records,
        policy=policy,
        verification_time=verification_time,
    )

    input_refs = tuple(
        VerificationEvidenceRef(
            evidence_id=item.evidence_id,
            payload_sha256=_artifact_sha256(item),
        )
        for item in evidence_records
    )

    task_contract_sha256 = _artifact_sha256(contract)
    verification_policy_sha256 = _artifact_sha256(policy)
    verification_report_sha256 = _artifact_sha256(report)
    completion_decision_sha256 = _artifact_sha256(decision)

    occurrence_payload = {
        "schema_version": SCHEMA_VERSION,
        "task_id": str(contract.task_id),
        "trace_id": str(trace_id),
        "source_task_revision": source_task_revision,
        "verifier_semantics_version": DETERMINISTIC_VERIFIER_SEMANTICS_VERSION,
        "verification_time": verification_time.isoformat(),
        "task_contract_sha256": task_contract_sha256,
        "verification_policy_sha256": verification_policy_sha256,
        "input_evidence": tuple(
            stable_payload(item)
            for item in input_refs
        ),
        "verification_basis_fingerprint": basis,
        "verification_report_id": str(report.report_id),
        "verification_report_sha256": verification_report_sha256,
        "completion_decision_id": str(decision.decision_id),
        "completion_decision_sha256": completion_decision_sha256,
        "verification_event_id": str(gate_result.verification_event_id),
        "completion_event_id": str(gate_result.completion_event_id),
        "execution_authority": False,
        "verification_authority": False,
        "completion_authority": False,
    }

    episode_digest = _canonical_sha256(occurrence_payload)

    return VerificationEpisodeManifest(
        episode_id=f"verification-episode:sha256:{episode_digest}",
        task_id=contract.task_id,
        trace_id=trace_id,
        source_task_revision=source_task_revision,
        verifier_semantics_version=DETERMINISTIC_VERIFIER_SEMANTICS_VERSION,
        verification_time=verification_time,
        task_contract_sha256=task_contract_sha256,
        verification_policy_sha256=verification_policy_sha256,
        input_evidence=input_refs,
        verification_basis_fingerprint=basis,
        verification_report_id=report.report_id,
        verification_report_sha256=verification_report_sha256,
        completion_decision_id=decision.decision_id,
        completion_decision_sha256=completion_decision_sha256,
        verification_event_id=gate_result.verification_event_id,
        completion_event_id=gate_result.completion_event_id,
    )
