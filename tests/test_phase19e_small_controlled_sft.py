from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from luna.sft import (
    SFTCandidateState,
    SFTSubset,
    SFTTrainingReceipt,
    audit_sft_corpus,
    build_default_sft_policy,
    prepare_sft_candidate,
    register_training_receipt,
)


def _record(
    *,
    record_id: str = "task-a:source::step-1",
    source_id: str = "task-a:source",
    family: str = "task-a",
    task: str = "task-a",
    category: str = "build-lib",
    split: str = "train",
    target_index: int = 2,
    loss_mask: list[int] | None = None,
    tool_schema: str = "luna-canonical-tools-v0.1",
    normalization: str = "privacy-and-context-v0.1",
    source_derivation: str | None = "cumulative-next-assistant-v1",
) -> dict[str, object]:
    training: dict[str, object] = {
        "split": split,
        "train_role": "policy",
        "trajectory_weight": 1.0,
        "step_weight": 1.0,
        "loss_weight": 1.0,
        "d1_decision": "train_candidate",
        "d1_decision_reasons": [],
        "tool_schema": tool_schema,
        "normalization": normalization,
        "segment": {
            "phase": "orient_inspect",
            "compressed": False,
            "context_chars_before": 100,
            "context_chars_after": 100,
            "omitted_messages": 0,
            "omitted_chars": 0,
            "checkpoint_sha256": "",
        },
        "protected_paths_hint": [],
    }
    if source_derivation is not None:
        training["source_derivation"] = source_derivation
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "Use observable evidence only."},
        {"role": "user", "content": "Inspect and verify the task."},
        {"role": "assistant", "content": "I will inspect the relevant file first."},
    ]
    return {
        "record_id": record_id,
        "source_trajectory_id": source_id,
        "task": task,
        "canonical_family": family,
        "lang": "python",
        "category": category,
        "assistant_step": 1,
        "assistant_steps": 1,
        "messages": messages,
        "tools": [],
        "target_message_index": target_index,
        "loss_mask": loss_mask if loss_mask is not None else [0, 0, 1],
        "_luna_training": training,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def _valid_audit(tmp_path: Path):
    path = tmp_path / "train.jsonl"
    _write_jsonl(
        path,
        [
            _record(),
            _record(
                record_id="task-b:source::step-1",
                source_id="task-b:source",
                family="task-b",
                task="task-b",
            ),
        ],
    )
    policy = build_default_sft_policy()
    return policy, audit_sft_corpus(path=path, policy=policy)


def test_default_policy_is_locked_and_non_authoritative() -> None:
    policy = build_default_sft_policy()

    assert policy.locked_sha256 == policy.computed_sha256()
    assert policy.runtime_authority is False
    assert policy.promotion_authority is False


def test_valid_normalized_corpus_is_ready(tmp_path: Path) -> None:
    policy, audit = _valid_audit(tmp_path)

    assert audit.policy_sha256 == policy.locked_sha256
    assert audit.record_count == 2
    assert audit.source_trajectory_count == 2
    assert audit.canonical_family_count == 2
    assert audit.subset_counts[SFTSubset.IMPLEMENTATION] == 2
    assert audit.target_only_loss_verified is True
    assert audit.train_split_only is True
    assert audit.canonical_tool_schema_only is True
    assert audit.canonical_normalization_only is True
    assert audit.source_derivation_present is True
    assert audit.raw_hidden_chain_of_thought_absent is True
    assert audit.ready_for_controlled_sft is True
    assert audit.blocked_reasons == ()


def test_validation_or_heldout_rows_cannot_enter_training(tmp_path: Path) -> None:
    path = tmp_path / "bad-split.jsonl"
    _write_jsonl(path, [_record(split="validation")])

    audit = audit_sft_corpus(path=path, policy=build_default_sft_policy())

    assert audit.ready_for_controlled_sft is False
    assert audit.train_split_only is False
    assert "non_train_split_present" in audit.blocked_reasons


def test_loss_mask_must_target_only_the_target_assistant_message(tmp_path: Path) -> None:
    path = tmp_path / "bad-mask.jsonl"
    _write_jsonl(path, [_record(loss_mask=[0, 1, 1])])

    audit = audit_sft_corpus(path=path, policy=build_default_sft_policy())

    assert audit.target_only_loss_verified is False
    assert "loss_mask_not_target_only" in audit.blocked_reasons


def test_candidate_target_must_be_assistant(tmp_path: Path) -> None:
    path = tmp_path / "bad-target.jsonl"
    _write_jsonl(path, [_record(target_index=1, loss_mask=[0, 1, 0])])

    audit = audit_sft_corpus(path=path, policy=build_default_sft_policy())

    assert audit.ready_for_controlled_sft is False
    assert "target_message_must_be_assistant" in audit.blocked_reasons


def test_noncanonical_tool_schema_or_normalization_is_blocked(tmp_path: Path) -> None:
    path = tmp_path / "bad-normalization.jsonl"
    _write_jsonl(
        path,
        [_record(tool_schema="codex-js-wrapper", normalization="raw-unscrubbed")],
    )

    audit = audit_sft_corpus(path=path, policy=build_default_sft_policy())

    assert audit.canonical_tool_schema_only is False
    assert audit.canonical_normalization_only is False
    assert "noncanonical_tool_schema" in audit.blocked_reasons
    assert "noncanonical_normalization" in audit.blocked_reasons


def test_raw_hidden_chain_of_thought_field_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "hidden-cot.jsonl"
    row = _record()
    row["raw_hidden_chain_of_thought"] = "do not train this"
    _write_jsonl(path, [row])

    audit = audit_sft_corpus(path=path, policy=build_default_sft_policy())

    assert audit.raw_hidden_chain_of_thought_absent is False
    assert "raw_hidden_chain_of_thought_present" in audit.blocked_reasons


def test_duplicate_training_record_is_blocked(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.jsonl"
    row = _record()
    _write_jsonl(path, [row, row])

    audit = audit_sft_corpus(path=path, policy=build_default_sft_policy())

    assert audit.ready_for_controlled_sft is False
    assert audit.duplicate_record_ids == ("task-a:source::step-1",)
    assert audit.duplicate_training_fingerprints


def test_initial_mix_blocks_seed_security_and_excess_judge(tmp_path: Path) -> None:
    seed_path = tmp_path / "seed.jsonl"
    _write_jsonl(seed_path, [_record(category="seed-authoring", task="seed-authoring-a")])
    seed_audit = audit_sft_corpus(path=seed_path, policy=build_default_sft_policy())
    assert "seed_authoring_not_allowed_in_initial_sft" in seed_audit.blocked_reasons

    security_path = tmp_path / "security.jsonl"
    _write_jsonl(security_path, [_record(category="security-classify")])
    security_audit = audit_sft_corpus(
        path=security_path,
        policy=build_default_sft_policy(),
    )
    assert "security_not_allowed_in_initial_sft" in security_audit.blocked_reasons

    judge_path = tmp_path / "judge.jsonl"
    _write_jsonl(judge_path, [_record(category="code-review")])
    judge_audit = audit_sft_corpus(path=judge_path, policy=build_default_sft_policy())
    assert "model_judge_fraction_exceeds_policy" in judge_audit.blocked_reasons


def test_candidate_spec_is_frozen_after_ready_audit(tmp_path: Path) -> None:
    policy, audit = _valid_audit(tmp_path)

    spec = prepare_sft_candidate(
        policy=policy,
        audit=audit,
        candidate_id="luna-19e-candidate-001",
        base_model_id="local/base-model",
        base_model_revision="base-rev-001",
        trainer_id="external-controlled-sft",
        trainer_revision="trainer-rev-001",
        seed=19,
        epochs=1.0,
        learning_rate=2e-5,
        max_sequence_tokens=32768,
    )

    assert spec.locked_sha256 == spec.computed_sha256()
    assert spec.corpus_sha256 == audit.corpus_sha256
    assert spec.target_only_loss is True
    assert spec.held_out_used_for_training is False
    assert spec.promotion_authority is False


def test_blocked_audit_cannot_create_candidate(tmp_path: Path) -> None:
    path = tmp_path / "blocked.jsonl"
    _write_jsonl(path, [_record(split="held_out")])
    policy = build_default_sft_policy()
    audit = audit_sft_corpus(path=path, policy=policy)

    with pytest.raises(ValueError, match="blocked"):
        prepare_sft_candidate(
            policy=policy,
            audit=audit,
            candidate_id="blocked-candidate",
            base_model_id="base",
            base_model_revision="rev",
            trainer_id="trainer",
            trainer_revision="trainer-rev",
            seed=19,
            epochs=1.0,
            learning_rate=2e-5,
            max_sequence_tokens=4096,
        )


def test_training_receipt_requires_real_success_without_heldout() -> None:
    digest = sha256(b"artifact").hexdigest()

    with pytest.raises(ValidationError, match="actually executed"):
        SFTTrainingReceipt(
            candidate_id="candidate",
            training_spec_sha256=digest,
            corpus_sha256=digest,
            base_model_revision="base-rev",
            trainer_revision="trainer-rev",
            training_executed=False,
            exit_code=0,
            artifact_sha256=digest,
            artifact_size_bytes=8,
            training_log_sha256=digest,
            evidence_refs=("log:training",),
        )

    with pytest.raises(ValidationError, match="held-out"):
        SFTTrainingReceipt(
            candidate_id="candidate",
            training_spec_sha256=digest,
            corpus_sha256=digest,
            base_model_revision="base-rev",
            trainer_revision="trainer-rev",
            training_executed=True,
            exit_code=0,
            artifact_sha256=digest,
            artifact_size_bytes=8,
            training_log_sha256=digest,
            held_out_used_during_training=True,
            evidence_refs=("log:training",),
        )


def test_registered_trained_candidate_remains_unpromoted(tmp_path: Path) -> None:
    policy, audit = _valid_audit(tmp_path)
    spec = prepare_sft_candidate(
        policy=policy,
        audit=audit,
        candidate_id="candidate-001",
        base_model_id="base",
        base_model_revision="base-rev",
        trainer_id="trainer",
        trainer_revision="trainer-rev",
        seed=19,
        epochs=1.0,
        learning_rate=2e-5,
        max_sequence_tokens=4096,
    )
    artifact_digest = sha256(b"trained-adapter-fixture").hexdigest()
    log_digest = sha256(b"training-log-fixture").hexdigest()
    receipt = SFTTrainingReceipt(
        candidate_id=spec.candidate_id,
        training_spec_sha256=spec.locked_sha256,
        corpus_sha256=spec.corpus_sha256,
        base_model_revision=spec.base_model_revision,
        trainer_revision=spec.trainer_revision,
        training_executed=True,
        exit_code=0,
        artifact_sha256=artifact_digest,
        artifact_size_bytes=23,
        training_log_sha256=log_digest,
        evidence_refs=("fixture:external-training-receipt",),
    )

    candidate = register_training_receipt(spec=spec, receipt=receipt)

    assert candidate.state is SFTCandidateState.TRAINED_CANDIDATE_UNPROMOTED
    assert candidate.artifact_sha256 == artifact_digest
    assert candidate.promotion_authorized is False


def test_receipt_must_match_frozen_spec(tmp_path: Path) -> None:
    policy, audit = _valid_audit(tmp_path)
    spec = prepare_sft_candidate(
        policy=policy,
        audit=audit,
        candidate_id="candidate-001",
        base_model_id="base",
        base_model_revision="base-rev",
        trainer_id="trainer",
        trainer_revision="trainer-rev",
        seed=19,
        epochs=1.0,
        learning_rate=2e-5,
        max_sequence_tokens=4096,
    )
    digest = sha256(b"fixture").hexdigest()
    receipt = SFTTrainingReceipt(
        candidate_id="different-candidate",
        training_spec_sha256=spec.locked_sha256,
        corpus_sha256=spec.corpus_sha256,
        base_model_revision=spec.base_model_revision,
        trainer_revision=spec.trainer_revision,
        training_executed=True,
        exit_code=0,
        artifact_sha256=digest,
        artifact_size_bytes=7,
        training_log_sha256=digest,
        evidence_refs=("fixture:receipt",),
    )

    with pytest.raises(ValueError, match="candidate does not match"):
        register_training_receipt(spec=spec, receipt=receipt)
