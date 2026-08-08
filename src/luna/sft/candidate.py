"""Trainer-neutral candidate preparation and receipt registration for Phase 19E."""

from __future__ import annotations

from luna.sft.models import (
    SFTCandidateArtifact,
    SFTCorpusAudit,
    SFTPolicy,
    SFTTrainingReceipt,
    SFTTrainingSpec,
)


def prepare_sft_candidate(
    *,
    policy: SFTPolicy,
    audit: SFTCorpusAudit,
    candidate_id: str,
    base_model_id: str,
    base_model_revision: str,
    trainer_id: str,
    trainer_revision: str,
    seed: int,
    epochs: float,
    learning_rate: float,
    max_sequence_tokens: int,
) -> SFTTrainingSpec:
    """Freeze one candidate plan only after the governed corpus is ready."""

    if policy.locked_sha256 != policy.computed_sha256():
        raise ValueError("SFT policy is not revision locked")
    if audit.policy_sha256 != policy.locked_sha256:
        raise ValueError("SFT corpus audit was produced under a different policy")
    if not audit.ready_for_controlled_sft:
        raise ValueError("SFT corpus audit is blocked and cannot create a candidate")
    return SFTTrainingSpec.freeze(
        candidate_id=candidate_id,
        base_model_id=base_model_id,
        base_model_revision=base_model_revision,
        trainer_id=trainer_id,
        trainer_revision=trainer_revision,
        corpus_sha256=audit.corpus_sha256,
        corpus_record_count=audit.record_count,
        policy_sha256=policy.locked_sha256,
        seed=seed,
        epochs=epochs,
        learning_rate=learning_rate,
        max_sequence_tokens=max_sequence_tokens,
    )


def register_training_receipt(
    *,
    spec: SFTTrainingSpec,
    receipt: SFTTrainingReceipt,
) -> SFTCandidateArtifact:
    """Register external training evidence without granting release promotion."""

    if spec.locked_sha256 != spec.computed_sha256():
        raise ValueError("SFT training spec is not revision locked")
    if receipt.candidate_id != spec.candidate_id:
        raise ValueError("training receipt candidate does not match SFT spec")
    if receipt.training_spec_sha256 != spec.locked_sha256:
        raise ValueError("training receipt spec digest does not match SFT spec")
    if receipt.corpus_sha256 != spec.corpus_sha256:
        raise ValueError("training receipt corpus digest does not match SFT spec")
    if receipt.base_model_revision != spec.base_model_revision:
        raise ValueError("training receipt base model revision does not match SFT spec")
    if receipt.trainer_revision != spec.trainer_revision:
        raise ValueError("training receipt trainer revision does not match SFT spec")
    return SFTCandidateArtifact(
        candidate_id=spec.candidate_id,
        training_spec_sha256=spec.locked_sha256,
        corpus_sha256=spec.corpus_sha256,
        artifact_sha256=receipt.artifact_sha256,
        artifact_size_bytes=receipt.artifact_size_bytes,
        training_log_sha256=receipt.training_log_sha256,
        evidence_refs=receipt.evidence_refs,
    )
