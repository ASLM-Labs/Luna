"""Controlled SFT corpus and candidate contracts for Luna Phase 19E."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from typing import Self

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel


class SFTSubset(StrEnum):
    """Training-data subsets with distinct initial mixing rules."""

    IMPLEMENTATION = "IMPLEMENTATION"
    MODEL_JUDGE = "MODEL_JUDGE"
    HARNESS_OPS = "HARNESS_OPS"
    SEED_AUTHORING = "SEED_AUTHORING"
    SECURITY = "SECURITY"


class SFTCandidateState(StrEnum):
    """Lifecycle state for a Phase 19E training candidate."""

    DATASET_READY = "DATASET_READY"
    TRAINED_CANDIDATE_UNPROMOTED = "TRAINED_CANDIDATE_UNPROMOTED"


class SFTPolicy(LunaContractModel):
    """Frozen policy for the first small controlled SFT candidate."""

    revision: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    required_split: str = "train"
    required_train_role: str = "policy"
    required_decision: str = "train_candidate"
    required_tool_schema: str = "luna-canonical-tools-v0.1"
    required_normalization: str = "privacy-and-context-v0.1"
    require_target_only_loss: bool = True
    require_source_derivation: bool = True
    max_model_judge_fraction: float = Field(default=0.20, ge=0.0, le=1.0)
    max_harness_ops_fraction: float = Field(default=0.05, ge=0.0, le=1.0)
    allow_seed_authoring: bool = False
    allow_security: bool = False
    runtime_authority: bool = False
    promotion_authority: bool = False
    locked_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @staticmethod
    def _payload(
        *,
        revision: str,
        required_split: str,
        required_train_role: str,
        required_decision: str,
        required_tool_schema: str,
        required_normalization: str,
        require_target_only_loss: bool,
        require_source_derivation: bool,
        max_model_judge_fraction: float,
        max_harness_ops_fraction: float,
        allow_seed_authoring: bool,
        allow_security: bool,
        runtime_authority: bool,
        promotion_authority: bool,
    ) -> dict[str, object]:
        return {
            "revision": revision,
            "required_split": required_split,
            "required_train_role": required_train_role,
            "required_decision": required_decision,
            "required_tool_schema": required_tool_schema,
            "required_normalization": required_normalization,
            "require_target_only_loss": require_target_only_loss,
            "require_source_derivation": require_source_derivation,
            "max_model_judge_fraction": max_model_judge_fraction,
            "max_harness_ops_fraction": max_harness_ops_fraction,
            "allow_seed_authoring": allow_seed_authoring,
            "allow_security": allow_security,
            "runtime_authority": runtime_authority,
            "promotion_authority": promotion_authority,
        }

    @classmethod
    def freeze(
        cls,
        *,
        revision: str,
        required_split: str = "train",
        required_train_role: str = "policy",
        required_decision: str = "train_candidate",
        required_tool_schema: str = "luna-canonical-tools-v0.1",
        required_normalization: str = "privacy-and-context-v0.1",
        require_target_only_loss: bool = True,
        require_source_derivation: bool = True,
        max_model_judge_fraction: float = 0.20,
        max_harness_ops_fraction: float = 0.05,
        allow_seed_authoring: bool = False,
        allow_security: bool = False,
        runtime_authority: bool = False,
        promotion_authority: bool = False,
    ) -> Self:
        payload = cls._payload(
            revision=revision,
            required_split=required_split,
            required_train_role=required_train_role,
            required_decision=required_decision,
            required_tool_schema=required_tool_schema,
            required_normalization=required_normalization,
            require_target_only_loss=require_target_only_loss,
            require_source_derivation=require_source_derivation,
            max_model_judge_fraction=max_model_judge_fraction,
            max_harness_ops_fraction=max_harness_ops_fraction,
            allow_seed_authoring=allow_seed_authoring,
            allow_security=allow_security,
            runtime_authority=runtime_authority,
            promotion_authority=promotion_authority,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        locked_sha256 = sha256(serialized.encode("utf-8")).hexdigest()
        return cls(
            revision=revision,
            required_split=required_split,
            required_train_role=required_train_role,
            required_decision=required_decision,
            required_tool_schema=required_tool_schema,
            required_normalization=required_normalization,
            require_target_only_loss=require_target_only_loss,
            require_source_derivation=require_source_derivation,
            max_model_judge_fraction=max_model_judge_fraction,
            max_harness_ops_fraction=max_harness_ops_fraction,
            allow_seed_authoring=allow_seed_authoring,
            allow_security=allow_security,
            runtime_authority=runtime_authority,
            promotion_authority=promotion_authority,
            locked_sha256=locked_sha256,
        )

    def computed_sha256(self) -> str:
        payload = self._payload(
            revision=self.revision,
            required_split=self.required_split,
            required_train_role=self.required_train_role,
            required_decision=self.required_decision,
            required_tool_schema=self.required_tool_schema,
            required_normalization=self.required_normalization,
            require_target_only_loss=self.require_target_only_loss,
            require_source_derivation=self.require_source_derivation,
            max_model_judge_fraction=self.max_model_judge_fraction,
            max_harness_ops_fraction=self.max_harness_ops_fraction,
            allow_seed_authoring=self.allow_seed_authoring,
            allow_security=self.allow_security,
            runtime_authority=self.runtime_authority,
            promotion_authority=self.promotion_authority,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.locked_sha256 != self.computed_sha256():
            raise ValueError("SFT policy digest mismatch")
        if self.runtime_authority:
            raise ValueError("Phase 19E SFT policy cannot grant runtime authority")
        if self.promotion_authority:
            raise ValueError("Phase 19E SFT policy cannot grant promotion authority")
        return self


class SFTCorpusAudit(LunaContractModel):
    """Deterministic audit result for a normalized JSONL SFT corpus."""

    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_ref: str = Field(min_length=1, max_length=4000)
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=0)
    record_count: int = Field(ge=0)
    source_trajectory_count: int = Field(ge=0)
    canonical_family_count: int = Field(ge=0)
    subset_counts: dict[SFTSubset, int]
    target_only_loss_verified: bool
    train_split_only: bool
    canonical_tool_schema_only: bool
    canonical_normalization_only: bool
    source_derivation_present: bool
    raw_hidden_chain_of_thought_absent: bool
    duplicate_record_ids: tuple[str, ...] = ()
    duplicate_training_fingerprints: tuple[str, ...] = ()
    malformed_line_numbers: tuple[int, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    ready_for_controlled_sft: bool

    @field_validator("duplicate_record_ids", "duplicate_training_fingerprints", "blocked_reasons")
    @classmethod
    def validate_unique_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("SFT audit strings cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("SFT audit strings must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_audit(self) -> Self:
        if self.record_count == 0 and self.ready_for_controlled_sft:
            raise ValueError("empty SFT corpus cannot be ready")
        if self.ready_for_controlled_sft and self.blocked_reasons:
            raise ValueError("ready SFT corpus cannot have blocked reasons")
        if any(value < 0 for value in self.subset_counts.values()):
            raise ValueError("SFT subset counts cannot be negative")
        if sum(self.subset_counts.values()) != self.record_count:
            raise ValueError("SFT subset counts must sum to record_count")
        return self


class SFTTrainingSpec(LunaContractModel):
    """Frozen trainer-neutral configuration for one controlled SFT attempt."""

    candidate_id: str = Field(min_length=1, max_length=300)
    base_model_id: str = Field(min_length=1, max_length=500)
    base_model_revision: str = Field(min_length=1, max_length=500)
    trainer_id: str = Field(min_length=1, max_length=500)
    trainer_revision: str = Field(min_length=1, max_length=500)
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_record_count: int = Field(gt=0)
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int = Field(ge=0)
    epochs: float = Field(gt=0.0, le=10.0)
    learning_rate: float = Field(gt=0.0, le=0.01)
    max_sequence_tokens: int = Field(ge=512, le=262144)
    target_only_loss: bool = True
    held_out_used_for_training: bool = False
    runtime_authority: bool = False
    promotion_authority: bool = False
    locked_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @staticmethod
    def _payload(
        *,
        candidate_id: str,
        base_model_id: str,
        base_model_revision: str,
        trainer_id: str,
        trainer_revision: str,
        corpus_sha256: str,
        corpus_record_count: int,
        policy_sha256: str,
        seed: int,
        epochs: float,
        learning_rate: float,
        max_sequence_tokens: int,
        target_only_loss: bool,
        held_out_used_for_training: bool,
        runtime_authority: bool,
        promotion_authority: bool,
    ) -> dict[str, object]:
        return {
            "candidate_id": candidate_id,
            "base_model_id": base_model_id,
            "base_model_revision": base_model_revision,
            "trainer_id": trainer_id,
            "trainer_revision": trainer_revision,
            "corpus_sha256": corpus_sha256,
            "corpus_record_count": corpus_record_count,
            "policy_sha256": policy_sha256,
            "seed": seed,
            "epochs": epochs,
            "learning_rate": learning_rate,
            "max_sequence_tokens": max_sequence_tokens,
            "target_only_loss": target_only_loss,
            "held_out_used_for_training": held_out_used_for_training,
            "runtime_authority": runtime_authority,
            "promotion_authority": promotion_authority,
        }

    @classmethod
    def freeze(
        cls,
        *,
        candidate_id: str,
        base_model_id: str,
        base_model_revision: str,
        trainer_id: str,
        trainer_revision: str,
        corpus_sha256: str,
        corpus_record_count: int,
        policy_sha256: str,
        seed: int,
        epochs: float,
        learning_rate: float,
        max_sequence_tokens: int,
        target_only_loss: bool = True,
        held_out_used_for_training: bool = False,
        runtime_authority: bool = False,
        promotion_authority: bool = False,
    ) -> Self:
        if not isfinite(epochs) or not isfinite(learning_rate):
            raise ValueError("SFT numeric configuration must be finite")
        payload = cls._payload(
            candidate_id=candidate_id,
            base_model_id=base_model_id,
            base_model_revision=base_model_revision,
            trainer_id=trainer_id,
            trainer_revision=trainer_revision,
            corpus_sha256=corpus_sha256,
            corpus_record_count=corpus_record_count,
            policy_sha256=policy_sha256,
            seed=seed,
            epochs=epochs,
            learning_rate=learning_rate,
            max_sequence_tokens=max_sequence_tokens,
            target_only_loss=target_only_loss,
            held_out_used_for_training=held_out_used_for_training,
            runtime_authority=runtime_authority,
            promotion_authority=promotion_authority,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        locked_sha256 = sha256(serialized.encode("utf-8")).hexdigest()
        return cls(
            candidate_id=candidate_id,
            base_model_id=base_model_id,
            base_model_revision=base_model_revision,
            trainer_id=trainer_id,
            trainer_revision=trainer_revision,
            corpus_sha256=corpus_sha256,
            corpus_record_count=corpus_record_count,
            policy_sha256=policy_sha256,
            seed=seed,
            epochs=epochs,
            learning_rate=learning_rate,
            max_sequence_tokens=max_sequence_tokens,
            target_only_loss=target_only_loss,
            held_out_used_for_training=held_out_used_for_training,
            runtime_authority=runtime_authority,
            promotion_authority=promotion_authority,
            locked_sha256=locked_sha256,
        )

    def computed_sha256(self) -> str:
        payload = self._payload(
            candidate_id=self.candidate_id,
            base_model_id=self.base_model_id,
            base_model_revision=self.base_model_revision,
            trainer_id=self.trainer_id,
            trainer_revision=self.trainer_revision,
            corpus_sha256=self.corpus_sha256,
            corpus_record_count=self.corpus_record_count,
            policy_sha256=self.policy_sha256,
            seed=self.seed,
            epochs=self.epochs,
            learning_rate=self.learning_rate,
            max_sequence_tokens=self.max_sequence_tokens,
            target_only_loss=self.target_only_loss,
            held_out_used_for_training=self.held_out_used_for_training,
            runtime_authority=self.runtime_authority,
            promotion_authority=self.promotion_authority,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_spec(self) -> Self:
        if self.locked_sha256 != self.computed_sha256():
            raise ValueError("SFT training spec digest mismatch")
        if not self.target_only_loss:
            raise ValueError("Phase 19E SFT requires target-only loss")
        if self.held_out_used_for_training:
            raise ValueError("held-out data cannot be used for SFT training")
        if self.runtime_authority:
            raise ValueError("SFT training cannot grant runtime authority")
        if self.promotion_authority:
            raise ValueError("SFT training cannot grant promotion authority")
        return self


class SFTTrainingReceipt(LunaContractModel):
    """Operator-supplied evidence that an external controlled training run actually completed."""

    candidate_id: str = Field(min_length=1, max_length=300)
    training_spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_model_revision: str = Field(min_length=1, max_length=500)
    trainer_revision: str = Field(min_length=1, max_length=500)
    training_executed: bool
    exit_code: int
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_size_bytes: int = Field(gt=0)
    training_log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    held_out_used_during_training: bool = False
    runtime_authority_granted: bool = False
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("training receipt evidence refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("training receipt evidence refs must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if not self.training_executed:
            raise ValueError("training receipt requires an actually executed training run")
        if self.exit_code != 0:
            raise ValueError("failed training run cannot become a candidate receipt")
        if self.held_out_used_during_training:
            raise ValueError("held-out data cannot be used during training")
        if self.runtime_authority_granted:
            raise ValueError("training receipt cannot grant runtime authority")
        return self


class SFTCandidateArtifact(LunaContractModel):
    """Recorded trained artifact that remains unpromoted until Phase 19F."""

    candidate_id: str = Field(min_length=1, max_length=300)
    state: SFTCandidateState = SFTCandidateState.TRAINED_CANDIDATE_UNPROMOTED
    training_spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_size_bytes: int = Field(gt=0)
    training_log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    promotion_authorized: bool = False

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        if self.state is not SFTCandidateState.TRAINED_CANDIDATE_UNPROMOTED:
            raise ValueError("Phase 19E candidate must remain unpromoted")
        if self.promotion_authorized:
            raise ValueError("Phase 19E candidate cannot authorize promotion")
        return self
