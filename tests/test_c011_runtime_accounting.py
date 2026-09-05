from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from luna.parallel_cognition.runtime_accounting import (
    CURRENT_ABI_V1_EXPORTS,
    CURRENT_ABI_V2_EXPORTS,
    REQUIRED_USAGE_FIELDS,
    NativeUsageCapabilitySnapshot,
    RuntimeAccountingDisposition,
    RuntimeAccountingPolicy,
    RuntimeAccountingReference,
    RuntimeMeasurementSource,
    RuntimeTokenSemantics,
    RuntimeTokenUsage,
    evaluate_runtime_accounting,
)

EVALUATED_AT = datetime(2026, 9, 1, 9, 21, 50, tzinfo=UTC)
TARGET_BRANCH = "capability/c011-single-voice-parallel-cognition"
TARGET_COMMIT = "a86c41510187a95b057c3ea615f79f70dc6bb9cf"
TARGET_TREE = "bb9149310341700cf6e923ceb691f4277bd7eee7"


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _reference(name: str = "fixture") -> RuntimeAccountingReference:
    return RuntimeAccountingReference(
        locator=f"fixture:{name}",
        content_sha256=_digest(name),
        source_revision="fixture-v1",
    )


def _policy(**updates: object) -> RuntimeAccountingPolicy:
    values: dict[str, object] = {
        "target_branch": TARGET_BRANCH,
        "target_commit_oid": TARGET_COMMIT,
        "target_tree_oid": TARGET_TREE,
        "evaluated_at_utc": EVALUATED_AT,
    }
    values.update(updates)
    return RuntimeAccountingPolicy(**values)  # type: ignore[arg-type]


def _usage(
    source: RuntimeMeasurementSource = RuntimeMeasurementSource.ENGINE_NATIVE_COUNTERS,
    **updates: object,
) -> RuntimeTokenUsage:
    values: dict[str, object] = {
        "source": source,
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "observed_at_utc": EVALUATED_AT,
        "evidence_refs": (_reference("usage"),),
    }
    values.update(updates)
    return RuntimeTokenUsage(**values)  # type: ignore[arg-type]


def _current_v1_snapshot(**updates: object) -> NativeUsageCapabilitySnapshot:
    values: dict[str, object] = {
        "target_branch": TARGET_BRANCH,
        "target_commit_oid": TARGET_COMMIT,
        "target_tree_oid": TARGET_TREE,
        "evaluated_at_utc": EVALUATED_AT,
        "abi_version": 1,
        "exported_symbols": CURRENT_ABI_V1_EXPORTS,
        "prompt_token_count_computed_inside_shim": True,
        "generation_loop_samples_one_token_per_step": True,
        "usage_channel_present": False,
        "worker_reported_tokens": 0,
        "source_refs": (_reference("abi-v1"),),
    }
    values.update(updates)
    return NativeUsageCapabilitySnapshot(**values)  # type: ignore[arg-type]


def _v2_snapshot(
    source: RuntimeMeasurementSource = RuntimeMeasurementSource.ENGINE_NATIVE_COUNTERS,
    **updates: object,
) -> NativeUsageCapabilitySnapshot:
    values: dict[str, object] = {
        "target_branch": TARGET_BRANCH,
        "target_commit_oid": TARGET_COMMIT,
        "target_tree_oid": TARGET_TREE,
        "evaluated_at_utc": EVALUATED_AT,
        "abi_version": 2,
        "exported_symbols": CURRENT_ABI_V2_EXPORTS,
        "prompt_token_count_computed_inside_shim": True,
        "generation_loop_samples_one_token_per_step": True,
        "usage_channel_present": True,
        "usage_result_fields": REQUIRED_USAGE_FIELDS,
        "measurement_source": source,
        "usage": _usage(source),
        "worker_reported_tokens": 18,
        "source_refs": (_reference("abi-v2"),),
    }
    values.update(updates)
    return NativeUsageCapabilitySnapshot(**values)  # type: ignore[arg-type]


def test_current_abi_v1_blocks_without_running_a_model() -> None:
    decision = evaluate_runtime_accounting(
        policy=_policy(),
        snapshot=_current_v1_snapshot(),
    )

    assert (
        decision.disposition
        is RuntimeAccountingDisposition.BLOCKED_USAGE_CHANNEL_ABSENT
    )
    assert decision.accounting_ready is False
    assert decision.execution_attempted is False
    assert decision.provider_call_executed is False
    assert decision.real_model_execution_completed is False
    assert decision.capability_status_after == "QUEUED"
    assert decision.rollout_stage_after == "BLOCKED"
    assert decision.task_state_authority is False
    assert decision.root_context_adoption_authority is False
    assert decision.completion_authority is False
    assert decision.user_facing_voice_authority is False
    assert decision.canary_authority is False
    assert decision.active_authority is False
    assert decision.promotion_authority is False


def test_synthetic_complete_abi_v2_only_reaches_non_executing_readiness() -> None:
    decision = evaluate_runtime_accounting(policy=_policy(), snapshot=_v2_snapshot())

    assert (
        decision.disposition
        is RuntimeAccountingDisposition.READY_FOR_MEASURED_EXECUTION
    )
    assert decision.accounting_ready is True
    assert decision.execution_attempted is False
    assert decision.provider_call_executed is False
    assert decision.promotion_authority is False


@pytest.mark.parametrize(
    "source",
    [
        RuntimeMeasurementSource.DRIVER_REPORTED,
        RuntimeMeasurementSource.DERIVED_TEXT_RETOKENIZATION,
    ],
)
def test_non_native_usage_sources_cannot_be_laundered_into_measurement(
    source: RuntimeMeasurementSource,
) -> None:
    decision = evaluate_runtime_accounting(
        policy=_policy(),
        snapshot=_v2_snapshot(source),
    )

    assert (
        decision.disposition
        is RuntimeAccountingDisposition.BLOCKED_UNTRUSTED_MEASUREMENT
    )
    assert decision.accounting_ready is False


def test_driver_zero_placeholder_is_not_a_valid_usage_observation() -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        _usage(
            RuntimeMeasurementSource.DRIVER_REPORTED,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
        )


def test_usage_total_must_equal_input_plus_output() -> None:
    with pytest.raises(ValidationError, match="input plus output"):
        _usage(total_tokens=19)


def test_absent_channel_cannot_claim_usage_evidence() -> None:
    with pytest.raises(ValidationError, match="absent usage channel"):
        _current_v1_snapshot(
            measurement_source=RuntimeMeasurementSource.DRIVER_REPORTED,
            usage=_usage(RuntimeMeasurementSource.DRIVER_REPORTED),
        )


def test_abi_v1_cannot_claim_a_measured_usage_channel() -> None:
    with pytest.raises(ValidationError, match="requires ABI version 2"):
        _current_v1_snapshot(
            usage_channel_present=True,
            usage_result_fields=REQUIRED_USAGE_FIELDS,
            measurement_source=RuntimeMeasurementSource.ENGINE_NATIVE_COUNTERS,
            usage=_usage(),
        )


def test_incomplete_v2_usage_fields_remain_blocked() -> None:
    decision = evaluate_runtime_accounting(
        policy=_policy(),
        snapshot=_v2_snapshot(usage_result_fields=("input_tokens",)),
    )

    assert (
        decision.disposition
        is RuntimeAccountingDisposition.BLOCKED_USAGE_CHANNEL_ABSENT
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("target_branch", "other", "target branch"),
        ("target_commit_oid", "1" * 40, "target commit"),
        ("target_tree_oid", "2" * 40, "target tree"),
        (
            "evaluated_at_utc",
            datetime(2026, 9, 1, 9, 22, tzinfo=UTC),
            "evaluation time",
        ),
    ],
)
def test_frozen_target_drift_blocks_otherwise_ready_accounting(
    field: str,
    value: object,
    reason: str,
) -> None:
    decision = evaluate_runtime_accounting(
        policy=_policy(),
        snapshot=_v2_snapshot(**{field: value}),
    )

    assert decision.disposition is RuntimeAccountingDisposition.BLOCKED_TARGET_DRIFT
    assert any(reason in item for item in decision.blocked_reasons)


def test_semantics_freeze_exact_model_token_boundaries() -> None:
    semantics = RuntimeTokenSemantics()

    assert semantics.input_basis == "POST_CHAT_TEMPLATE_MODEL_TOKENIZATION"
    assert semantics.includes_special_tokens_actually_fed is True
    assert semantics.includes_bos_if_actually_fed is True
    assert semantics.output_basis == "SAMPLED_NON_EOG_TOKENS"
    assert semantics.terminal_eog_included is False
    assert semantics.total_basis == "INPUT_PLUS_OUTPUT"
    assert semantics.required_source is RuntimeMeasurementSource.ENGINE_NATIVE_COUNTERS
    assert "TEXT_RETOKENIZATION" in semantics.prohibited_substitutes
    assert "DRIVER_ZERO_PLACEHOLDER" in semantics.prohibited_substitutes


@pytest.mark.parametrize(
    "artifact",
    ["semantics", "usage", "policy", "snapshot", "decision"],
)
def test_content_addressed_ids_reject_tampering(artifact: str) -> None:
    policy = _policy()
    snapshot = _current_v1_snapshot()
    decision = evaluate_runtime_accounting(policy=policy, snapshot=snapshot)
    models = {
        "semantics": policy.token_semantics,
        "usage": _usage(),
        "policy": policy,
        "snapshot": snapshot,
        "decision": decision,
    }
    model = models[artifact]
    field = {
        "semantics": "semantics_id",
        "usage": "usage_id",
        "policy": "policy_id",
        "snapshot": "snapshot_id",
        "decision": "decision_id",
    }[artifact]
    prefix = str(model.model_dump(mode="json")[field]).rsplit(":", 1)[0]
    payload = model.model_dump(mode="json")
    payload[field] = f"{prefix}:{'0' * 64}"

    with pytest.raises(ValidationError, match="does not match content"):
        type(model).model_validate(payload)


def test_accounting_module_has_no_provider_execution_or_runtime_wiring() -> None:
    project_root = Path(__file__).resolve().parents[1]
    source = (
        project_root
        / "src"
        / "luna"
        / "parallel_cognition"
        / "runtime_accounting.py"
    ).read_text(encoding="utf-8")
    runtime_files = tuple((project_root / "src" / "luna" / "runtime").glob("*.py"))

    assert "native_real_driver" not in source
    assert "subprocess" not in source
    assert "ctypes" not in source
    assert "http" not in source
    assert all(
        "runtime_accounting" not in path.read_text(encoding="utf-8")
        for path in runtime_files
    )
