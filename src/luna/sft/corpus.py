"""Streaming audit for normalized Phase 19E SFT JSONL corpora."""

from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import cast

from luna.sft.models import SFTCorpusAudit, SFTPolicy, SFTSubset

_HIDDEN_COT_KEYS = {
    "chain_of_thought",
    "hidden_chain_of_thought",
    "raw_hidden_chain_of_thought",
}


def classify_subset(*, task: str, category: str) -> SFTSubset:
    """Classify normalized records into conservative initial-curriculum subsets."""

    task_key = task.strip().lower()
    category_key = category.strip().lower()
    if category_key == "code-review" or "model-judge" in category_key:
        return SFTSubset.MODEL_JUDGE
    if category_key == "seed-authoring" or "seed-authoring" in task_key:
        return SFTSubset.SEED_AUTHORING
    if category_key.startswith("security") or task_key.startswith("security-"):
        return SFTSubset.SECURITY
    if category_key == "harness-construction" or task_key.startswith("harness-setup"):
        return SFTSubset.HARNESS_OPS
    return SFTSubset.IMPLEMENTATION


def _dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return cast(dict[str, object], value)


def _list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast(list[object], value)


def _string(mapping: dict[str, object], key: str) -> str | None:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _int(mapping: dict[str, object], key: str) -> int | None:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _float(mapping: dict[str, object], key: str) -> float | None:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _contains_hidden_cot(value: object) -> bool:
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        for key, nested in mapping.items():
            if isinstance(key, str) and key.strip().lower() in _HIDDEN_COT_KEYS:
                return True
            if _contains_hidden_cot(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_hidden_cot(item) for item in cast(list[object], value))
    return False


def _canonical_training_fingerprint(record: dict[str, object]) -> str:
    payload = {
        "canonical_family": record.get("canonical_family"),
        "assistant_step": record.get("assistant_step"),
        "messages": record.get("messages"),
        "tools": record.get("tools"),
        "target_message_index": record.get("target_message_index"),
        "loss_mask": record.get("loss_mask"),
        "_luna_training": record.get("_luna_training"),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()


def audit_sft_corpus(*, path: Path, policy: SFTPolicy) -> SFTCorpusAudit:
    """Audit one normalized JSONL corpus without loading the full dataset into memory."""

    if not path.is_file():
        raise ValueError(f"SFT corpus not found: {path}")
    if policy.locked_sha256 != policy.computed_sha256():
        raise ValueError("SFT policy is not revision locked")

    digest = sha256()
    byte_count = 0
    with path.open("rb") as raw_stream:
        for chunk in iter(lambda: raw_stream.read(1024 * 1024), b""):
            digest.update(chunk)
            byte_count += len(chunk)
    corpus_sha256 = digest.hexdigest()
    record_ids: set[str] = set()
    duplicate_record_ids: set[str] = set()
    fingerprints: set[str] = set()
    duplicate_fingerprints: set[str] = set()
    source_ids: set[str] = set()
    families: set[str] = set()
    subset_counter: Counter[SFTSubset] = Counter()
    malformed_lines: set[int] = set()
    blocked: set[str] = set()

    target_only_loss_verified = True
    train_split_only = True
    canonical_tool_schema_only = True
    canonical_normalization_only = True
    source_derivation_present = True
    raw_hidden_cot_absent = True
    record_count = 0

    with path.open("r", encoding="utf-8", newline="") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            record_count += 1
            try:
                loaded: object = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines.add(line_number)
                blocked.add("malformed_json")
                continue
            record = _dict(loaded)
            if record is None:
                malformed_lines.add(line_number)
                blocked.add("record_must_be_object")
                continue

            if _contains_hidden_cot(record):
                raw_hidden_cot_absent = False
                blocked.add("raw_hidden_chain_of_thought_present")

            record_id = _string(record, "record_id")
            source_id = _string(record, "source_trajectory_id")
            family = _string(record, "canonical_family")
            task = _string(record, "task")
            category = _string(record, "category")
            assistant_step = _int(record, "assistant_step")
            assistant_steps = _int(record, "assistant_steps")
            target_index = _int(record, "target_message_index")
            messages = _list(record.get("messages"))
            loss_mask = _list(record.get("loss_mask"))
            training = _dict(record.get("_luna_training"))

            required_values = (
                record_id,
                source_id,
                family,
                task,
                category,
                assistant_step,
                assistant_steps,
                target_index,
                messages,
                loss_mask,
                training,
            )
            if any(value is None for value in required_values):
                malformed_lines.add(line_number)
                blocked.add("missing_or_invalid_required_field")
                continue

            assert record_id is not None
            assert source_id is not None
            assert family is not None
            assert task is not None
            assert category is not None
            assert assistant_step is not None
            assert assistant_steps is not None
            assert target_index is not None
            assert messages is not None
            assert loss_mask is not None
            assert training is not None

            if record_id in record_ids:
                duplicate_record_ids.add(record_id)
                blocked.add("duplicate_record_id")
            record_ids.add(record_id)
            source_ids.add(source_id)
            families.add(family)

            fingerprint = _canonical_training_fingerprint(record)
            if fingerprint in fingerprints:
                duplicate_fingerprints.add(fingerprint)
                blocked.add("duplicate_training_fingerprint")
            fingerprints.add(fingerprint)

            subset = classify_subset(task=task, category=category)
            subset_counter[subset] += 1

            if assistant_steps < 1 or assistant_step < 1 or assistant_step > assistant_steps:
                malformed_lines.add(line_number)
                blocked.add("invalid_assistant_step")

            if target_index < 0 or target_index >= len(messages):
                target_only_loss_verified = False
                malformed_lines.add(line_number)
                blocked.add("invalid_target_message_index")
            else:
                target_message = _dict(messages[target_index])
                if target_message is None or _string(target_message, "role") != "assistant":
                    target_only_loss_verified = False
                    blocked.add("target_message_must_be_assistant")

            if len(loss_mask) != len(messages):
                target_only_loss_verified = False
                blocked.add("loss_mask_length_mismatch")
            else:
                mask_values_valid = all(
                    isinstance(value, int) and not isinstance(value, bool) and value in {0, 1}
                    for value in loss_mask
                )
                if not mask_values_valid:
                    target_only_loss_verified = False
                    blocked.add("loss_mask_not_binary")
                elif target_index < 0 or target_index >= len(loss_mask):
                    target_only_loss_verified = False
                elif any(
                    value != (1 if index == target_index else 0)
                    for index, value in enumerate(loss_mask)
                ):
                    target_only_loss_verified = False
                    blocked.add("loss_mask_not_target_only")

            if _string(training, "split") != policy.required_split:
                train_split_only = False
                blocked.add("non_train_split_present")
            if _string(training, "train_role") != policy.required_train_role:
                blocked.add("unsupported_train_role")
            if _string(training, "d1_decision") != policy.required_decision:
                blocked.add("record_not_approved_for_training")
            if _string(training, "tool_schema") != policy.required_tool_schema:
                canonical_tool_schema_only = False
                blocked.add("noncanonical_tool_schema")
            if _string(training, "normalization") != policy.required_normalization:
                canonical_normalization_only = False
                blocked.add("noncanonical_normalization")
            if policy.require_source_derivation and _string(training, "source_derivation") is None:
                source_derivation_present = False
                blocked.add("missing_source_derivation")

            for weight_key in ("trajectory_weight", "step_weight", "loss_weight"):
                weight = _float(training, weight_key)
                if weight is None or weight <= 0.0:
                    blocked.add("invalid_training_weight")

    if subset_counter[SFTSubset.SEED_AUTHORING] and not policy.allow_seed_authoring:
        blocked.add("seed_authoring_not_allowed_in_initial_sft")
    if subset_counter[SFTSubset.SECURITY] and not policy.allow_security:
        blocked.add("security_not_allowed_in_initial_sft")
    if record_count > 0:
        judge_fraction = subset_counter[SFTSubset.MODEL_JUDGE] / record_count
        harness_fraction = subset_counter[SFTSubset.HARNESS_OPS] / record_count
        if judge_fraction > policy.max_model_judge_fraction:
            blocked.add("model_judge_fraction_exceeds_policy")
        if harness_fraction > policy.max_harness_ops_fraction:
            blocked.add("harness_ops_fraction_exceeds_policy")
    else:
        blocked.add("empty_corpus")

    ready = not blocked
    return SFTCorpusAudit(
        policy_sha256=policy.locked_sha256,
        source_ref=str(path),
        corpus_sha256=corpus_sha256,
        byte_count=byte_count,
        record_count=record_count,
        source_trajectory_count=len(source_ids),
        canonical_family_count=len(families),
        subset_counts={subset: subset_counter[subset] for subset in SFTSubset},
        target_only_loss_verified=target_only_loss_verified,
        train_split_only=train_split_only,
        canonical_tool_schema_only=canonical_tool_schema_only,
        canonical_normalization_only=canonical_normalization_only,
        source_derivation_present=source_derivation_present,
        raw_hidden_chain_of_thought_absent=raw_hidden_cot_absent,
        duplicate_record_ids=tuple(sorted(duplicate_record_ids)),
        duplicate_training_fingerprints=tuple(sorted(duplicate_fingerprints)),
        malformed_line_numbers=tuple(sorted(malformed_lines)),
        blocked_reasons=tuple(sorted(blocked)),
        ready_for_controlled_sft=ready,
    )
