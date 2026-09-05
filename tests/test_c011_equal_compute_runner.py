from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from threading import Barrier, Lock
from typing import cast

import pytest
from pydantic import ValidationError

from luna.evaluation_governance import EvaluationPartition
from luna.parallel_cognition.equal_compute_preflight import (
    RealEqualComputeEvidenceClass,
    RealEqualComputeEvidenceReference,
    RealEqualComputeEvidenceState,
    RealEqualComputePreflightPolicy,
    RealEqualComputePreflightSnapshot,
    RealEqualComputePrerequisite,
    RealEqualComputePrerequisiteEvidence,
)
from luna.parallel_cognition.equal_compute_runner import (
    REAL_EQUAL_COMPUTE_RUBRIC_SHA256,
    REPRESENTATIVE_DIMENSIONS,
    FrozenRealEqualComputeSuite,
    RealEqualComputeArmReceipt,
    RealEqualComputeCallRole,
    RealEqualComputeGenerationCall,
    RealEqualComputeGenerationResult,
    RealEqualComputeRunDisposition,
    RealEqualComputeRunnerError,
    RealEqualComputeRunReceipt,
    build_c011_bounded_representative_suite,
    execute_real_equal_compute,
)
from luna.parallel_cognition.live import LiveNativeTokenUsage
from luna.parallel_cognition.runtime_configuration import (
    RealRuntimeAssetBinding,
    RealRuntimeConfigurationSet,
    build_default_real_runtime_configuration_set,
)
from luna.parallel_cognition.shadow_evaluation import (
    EqualComputeBudget,
    ShadowConfiguration,
)

TARGET_BRANCH = "capability/c011-single-voice-parallel-cognition"
TARGET_COMMIT = "6550d6fa50c59e8eb60e8aa68778cd433217d5c7"
TARGET_TREE = "edfc4629acd86d40d791d78dfaf4d69e3153040a"
EVALUATED_AT = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _configuration_set(
    *,
    parallel_workers: int = 2,
    max_total_tokens: int = 2048,
    max_context_bytes: int = 32768,
) -> RealRuntimeConfigurationSet:
    asset = RealRuntimeAssetBinding(
        backend_id="local-native:c011-e5-test",
        provider_profile_id="c011-provider-profile:sha256:" + _digest("profile"),
        provider_binding_id="c011-native-driver-binding:sha256:" + _digest("binding"),
        model_identity="model@sha256:" + _digest("model"),
        model_artifact_sha256=_digest("model"),
        bridge_artifact_sha256=_digest("bridge"),
        driver_artifact_sha256=_digest("driver"),
        runtime_bundle_sha256=_digest("runtime"),
        environment_sha256=_digest("environment"),
        sampling_sha256=_digest("sampling"),
    )
    return build_default_real_runtime_configuration_set(
        asset_binding=asset,
        equal_compute_budget=EqualComputeBudget(
            max_total_tokens=max_total_tokens,
            max_tool_calls=0,
            max_compute_units=1000,
            max_context_bytes=max_context_bytes,
            max_wall_time_ms=300000,
        ),
        parallel_workers=cast("object", parallel_workers),  # type: ignore[arg-type]
    )


def _suite() -> FrozenRealEqualComputeSuite:
    return build_c011_bounded_representative_suite(
        target_branch=TARGET_BRANCH,
        source_commit_oid=TARGET_COMMIT,
        source_tree_oid=TARGET_TREE,
    )


def _policy() -> RealEqualComputePreflightPolicy:
    return RealEqualComputePreflightPolicy(
        target_branch=TARGET_BRANCH,
        target_commit_oid=TARGET_COMMIT,
        target_tree_oid=TARGET_TREE,
        evaluated_at_utc=EVALUATED_AT,
    )


def _reference(
    prerequisite: RealEqualComputePrerequisite,
    digest: str,
) -> RealEqualComputeEvidenceReference:
    return RealEqualComputeEvidenceReference(
        locator=f"fixture:{prerequisite.value.lower()}",
        content_sha256=digest,
        source_revision="fixture-v1",
    )


def _all_verified_items(
    configuration: RealRuntimeConfigurationSet,
    suite: FrozenRealEqualComputeSuite,
    *,
    suite_digest: str | None = None,
) -> tuple[RealEqualComputePrerequisiteEvidence, ...]:
    runtime_digests = {
        ShadowConfiguration.SOLO: configuration.arms[0].configuration_sha256,
        ShadowConfiguration.ULTRA_SOLO: configuration.arms[1].configuration_sha256,
        ShadowConfiguration.PARALLEL: configuration.arms[2].configuration_sha256,
    }
    digests = {
        RealEqualComputePrerequisite.CURRENT_ASSET_BINDING: (
            configuration.asset_binding.asset_binding_id.rsplit(":", maxsplit=1)[-1]
        ),
        RealEqualComputePrerequisite.MEASURED_TOKEN_ACCOUNTING: _digest("native-usage"),
        RealEqualComputePrerequisite.SOLO_RUNTIME_CONTRACT: runtime_digests[
            ShadowConfiguration.SOLO
        ],
        RealEqualComputePrerequisite.ULTRA_SOLO_RUNTIME_CONTRACT: runtime_digests[
            ShadowConfiguration.ULTRA_SOLO
        ],
        RealEqualComputePrerequisite.PARALLEL_RUNTIME_CONTRACT: runtime_digests[
            ShadowConfiguration.PARALLEL
        ],
        RealEqualComputePrerequisite.REPRESENTATIVE_FROZEN_SUITE: (
            suite_digest or suite.suite_sha256
        ),
        RealEqualComputePrerequisite.INDEPENDENT_EVALUATOR_ATTESTATION: _digest(
            "independent-evaluator"
        ),
        RealEqualComputePrerequisite.CONTAMINATION_PROVENANCE_ATTESTATION: _digest(
            "contamination"
        ),
        RealEqualComputePrerequisite.HARDWARE_RESOURCE_ATTESTATION: _digest("hardware"),
        RealEqualComputePrerequisite.SAFETY_CONTAINMENT_ATTESTATION: _digest("safety"),
        RealEqualComputePrerequisite.EXTERNAL_LEDGER_ANCHOR: _digest("ledger"),
    }
    repository_source = {
        RealEqualComputePrerequisite.SOLO_RUNTIME_CONTRACT,
        RealEqualComputePrerequisite.ULTRA_SOLO_RUNTIME_CONTRACT,
        RealEqualComputePrerequisite.PARALLEL_RUNTIME_CONTRACT,
    }
    external = {
        RealEqualComputePrerequisite.INDEPENDENT_EVALUATOR_ATTESTATION,
        RealEqualComputePrerequisite.CONTAMINATION_PROVENANCE_ATTESTATION,
        RealEqualComputePrerequisite.HARDWARE_RESOURCE_ATTESTATION,
        RealEqualComputePrerequisite.SAFETY_CONTAINMENT_ATTESTATION,
        RealEqualComputePrerequisite.EXTERNAL_LEDGER_ANCHOR,
    }
    items: list[RealEqualComputePrerequisiteEvidence] = []
    for prerequisite in RealEqualComputePrerequisite:
        if prerequisite in external:
            evidence_class = RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION
        elif prerequisite in repository_source:
            evidence_class = RealEqualComputeEvidenceClass.REPOSITORY_SOURCE
        elif prerequisite is RealEqualComputePrerequisite.REPRESENTATIVE_FROZEN_SUITE:
            evidence_class = RealEqualComputeEvidenceClass.REPOSITORY_RECEIPT
        else:
            evidence_class = RealEqualComputeEvidenceClass.REAL_PROVIDER_MEASUREMENT
        items.append(
            RealEqualComputePrerequisiteEvidence(
                prerequisite=prerequisite,
                state=RealEqualComputeEvidenceState.VERIFIED,
                evidence_class=evidence_class,
                evidence_refs=(_reference(prerequisite, digests[prerequisite]),),
                observed_at_utc=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
                provenance_complete=True,
                independently_attested=prerequisite in external,
            )
        )
    return tuple(items)


def _blocked_items(
    configuration: RealRuntimeConfigurationSet,
    suite: FrozenRealEqualComputeSuite,
) -> tuple[RealEqualComputePrerequisiteEvidence, ...]:
    ready = _all_verified_items(configuration, suite)
    external = {
        RealEqualComputePrerequisite.INDEPENDENT_EVALUATOR_ATTESTATION,
        RealEqualComputePrerequisite.CONTAMINATION_PROVENANCE_ATTESTATION,
        RealEqualComputePrerequisite.EXTERNAL_LEDGER_ANCHOR,
    }
    partial = {
        RealEqualComputePrerequisite.HARDWARE_RESOURCE_ATTESTATION,
        RealEqualComputePrerequisite.SAFETY_CONTAINMENT_ATTESTATION,
    }
    items: list[RealEqualComputePrerequisiteEvidence] = []
    for item in ready:
        if item.prerequisite in external:
            items.append(
                RealEqualComputePrerequisiteEvidence(
                    prerequisite=item.prerequisite,
                    state=RealEqualComputeEvidenceState.OPEN,
                    evidence_class=RealEqualComputeEvidenceClass.NONE,
                    limitations=("external attestation is absent",),
                )
            )
        elif item.prerequisite in partial:
            items.append(
                RealEqualComputePrerequisiteEvidence(
                    prerequisite=item.prerequisite,
                    state=RealEqualComputeEvidenceState.PARTIAL,
                    evidence_class=RealEqualComputeEvidenceClass.REPOSITORY_RECEIPT,
                    evidence_refs=item.evidence_refs,
                    observed_at_utc=item.observed_at_utc,
                    provenance_complete=False,
                    limitations=("repository evidence is not external attestation",),
                )
            )
        else:
            items.append(item)
    return tuple(items)


def _snapshot(
    items: tuple[RealEqualComputePrerequisiteEvidence, ...],
) -> RealEqualComputePreflightSnapshot:
    return RealEqualComputePreflightSnapshot(
        target_branch=TARGET_BRANCH,
        target_commit_oid=TARGET_COMMIT,
        target_tree_oid=TARGET_TREE,
        evaluated_at_utc=EVALUATED_AT,
        items=items,
    )


@dataclass(slots=True)
class _FakeExecutor:
    configuration_set_id: str = ""
    parallel_workers: int = 2
    output_tokens: int = 2
    input_tokens: int = 5
    fail_role: RealEqualComputeCallRole | None = None
    wrong_call_id: bool = False
    harmony_output: bool = False
    calls: list[RealEqualComputeGenerationCall] = field(default_factory=list)
    maximum: int = 0
    _active: int = 0
    _lock: Lock = field(default_factory=Lock)
    _barriers: dict[str, Barrier] = field(default_factory=dict)

    def execute(
        self,
        *,
        call: RealEqualComputeGenerationCall,
    ) -> RealEqualComputeGenerationResult:
        with self._lock:
            self.calls.append(call)
            self._active += 1
            self.maximum = max(self.maximum, self._active)
            barrier = self._barriers.setdefault(
                call.case_id,
                Barrier(self.parallel_workers),
            )
        try:
            parallel_roles = (
                RealEqualComputeCallRole.PARALLEL_EVIDENCE,
                RealEqualComputeCallRole.PARALLEL_ADVERSARIAL,
                RealEqualComputeCallRole.PARALLEL_ALTERNATIVE,
            )
            if call.role in parallel_roles[: self.parallel_workers]:
                barrier.wait(timeout=5)
            if call.role is self.fail_role:
                raise RuntimeError("bounded fake generation failure")
            text = (
                "<|channel|>analysis"
                if self.harmony_output
                else f"final:{call.case_id}:{call.role.value}"
            )
            return RealEqualComputeGenerationResult(
                call_id=(
                    "c011-real-equal-compute-call:sha256:" + "0" * 64
                    if self.wrong_call_id
                    else call.call_id
                ),
                final_text=text,
                native_usage=LiveNativeTokenUsage(
                    input_tokens=self.input_tokens,
                    output_tokens=self.output_tokens,
                    total_tokens=self.input_tokens + self.output_tokens,
                ),
                runtime_ms=1,
            )
        finally:
            with self._lock:
                self._active -= 1


@dataclass(slots=True)
class _NeverExecutor:
    configuration_set_id: str = ""
    calls: int = 0

    def execute(
        self,
        *,
        call: RealEqualComputeGenerationCall,
    ) -> RealEqualComputeGenerationResult:
        del call
        self.calls += 1
        raise AssertionError("blocked runner reached the generation boundary")


def _execute_ready(
    executor: _FakeExecutor,
    *,
    configuration: RealRuntimeConfigurationSet | None = None,
) -> RealEqualComputeRunReceipt:
    current_configuration = configuration or _configuration_set()
    if not executor.configuration_set_id:
        executor.configuration_set_id = current_configuration.configuration_set_id
    suite = _suite()
    return execute_real_equal_compute(
        policy=_policy(),
        snapshot=_snapshot(_all_verified_items(current_configuration, suite)),
        configuration_set=current_configuration,
        suite=suite,
        executor=executor,
    )


def test_frozen_suite_is_content_addressed_bounded_and_phase19b_compatible() -> None:
    suite = _suite()
    projected = suite.evaluation_suite()

    assert suite.suite_id.startswith("c011-real-equal-compute-suite:sha256:")
    assert len(suite.cases) == 6
    assert tuple(item.case_id for item in suite.cases) == tuple(
        f"C011-EQ-{index:03d}" for index in range(1, 7)
    )
    assert {item.task_family for item in suite.cases} == set(REPRESENTATIVE_DIMENSIONS)
    assert sum(item.partition is EvaluationPartition.HELD_OUT for item in suite.cases) == 3
    assert sum(item.partition is EvaluationPartition.OOD for item in suite.cases) == 3
    assert suite.evaluator.implementation_sha256 == REAL_EQUAL_COMPUTE_RUBRIC_SHA256
    assert projected.case_ids == tuple(item.case_id for item in suite.cases)
    assert projected.computed_sha256() == projected.locked_sha256
    assert suite.contamination_provenance_attested is False
    assert suite.evaluator_independence_attested is False
    assert suite.external_ledger_anchored is False


def test_suite_and_case_content_tampering_fail_closed() -> None:
    suite = _suite()
    payload = suite.model_dump(mode="json")
    payload["suite_id"] = "c011-real-equal-compute-suite:sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="suite_id"):
        FrozenRealEqualComputeSuite.model_validate(payload)

    payload = suite.model_dump(mode="json")
    payload["cases"][0]["objective"] = "tampered"
    with pytest.raises(ValidationError, match="case digest"):
        FrozenRealEqualComputeSuite.model_validate(payload)


def test_current_external_gaps_block_before_executor_creation_boundary() -> None:
    configuration = _configuration_set()
    suite = _suite()
    executor = _NeverExecutor(configuration_set_id=configuration.configuration_set_id)

    receipt = execute_real_equal_compute(
        policy=_policy(),
        snapshot=_snapshot(_blocked_items(configuration, suite)),
        configuration_set=configuration,
        suite=suite,
        executor=executor,
    )

    assert receipt.disposition is RealEqualComputeRunDisposition.BLOCKED_PREFLIGHT
    assert executor.calls == 0
    assert receipt.provider_calls_executed == 0
    assert receipt.case_receipts == ()
    assert receipt.full_triplet_completed is False
    assert receipt.controlled_c011_execution is False
    assert receipt.promotion_authority is False


def test_ready_preflight_executes_exact_six_case_three_arm_schedule() -> None:
    executor = _FakeExecutor()

    receipt = _execute_ready(executor)

    assert receipt.disposition is RealEqualComputeRunDisposition.EXECUTED
    assert receipt.provider_calls_executed == 36
    assert len(executor.calls) == 36
    assert len({item.call_id for item in executor.calls}) == 36
    assert len(receipt.case_receipts) == 6
    assert receipt.max_concurrent_generations_observed == 2
    assert executor.maximum == 2
    assert receipt.full_triplet_completed is True
    assert receipt.raw_output_persisted is False
    assert receipt.raw_analysis_persisted is False


def test_each_arm_uses_its_frozen_roles_and_equal_output_ceiling() -> None:
    executor = _FakeExecutor()
    receipt = _execute_ready(executor)
    first = receipt.case_receipts[0]

    assert tuple(len(item.call_receipts) for item in first.arms) == (1, 2, 3)
    assert {item.output_token_ceiling for item in first.arms} == {256}
    assert {item.normalized_compute_units for item in first.arms} == {1000}
    assert tuple(item.role for item in first.arms[0].call_receipts) == (
        RealEqualComputeCallRole.SOLO_ROOT,
    )
    assert tuple(item.role for item in first.arms[1].call_receipts) == (
        RealEqualComputeCallRole.ULTRA_DRAFT,
        RealEqualComputeCallRole.ULTRA_VERIFY,
    )
    assert tuple(item.role for item in first.arms[2].call_receipts) == (
        RealEqualComputeCallRole.PARALLEL_EVIDENCE,
        RealEqualComputeCallRole.PARALLEL_ADVERSARIAL,
        RealEqualComputeCallRole.PARALLEL_ROOT,
    )
    first_calls = [item for item in executor.calls if item.case_id == "C011-EQ-001"]
    assert sum(item.max_output_tokens for item in first_calls[:1]) == 256
    assert sum(item.max_output_tokens for item in first_calls[1:3]) == 256
    assert sum(item.max_output_tokens for item in first_calls[3:]) == 256


def test_receipt_persists_hashes_and_native_usage_but_not_final_text() -> None:
    receipt = _execute_ready(_FakeExecutor())
    serialized = receipt.model_dump_json()

    assert "final:C011" not in serialized
    assert "final_text" not in serialized
    assert "ENGINE_NATIVE_COUNTERS" in serialized
    assert all(
        arm.native_total_tokens == arm.native_input_tokens + arm.native_output_tokens
        for case in receipt.case_receipts
        for arm in case.arms
    )


def test_ready_but_mismatched_suite_evidence_blocks_without_calls() -> None:
    configuration = _configuration_set()
    suite = _suite()
    executor = _NeverExecutor(configuration_set_id=configuration.configuration_set_id)

    receipt = execute_real_equal_compute(
        policy=_policy(),
        snapshot=_snapshot(
            _all_verified_items(configuration, suite, suite_digest=_digest("other-suite"))
        ),
        configuration_set=configuration,
        suite=suite,
        executor=executor,
    )

    assert receipt.disposition is RealEqualComputeRunDisposition.BLOCKED_BINDING
    assert receipt.blocked_reasons == (
        "preflight suite evidence does not bind the frozen suite",
    )
    assert executor.calls == 0


def test_ready_but_mismatched_executor_binding_blocks_without_calls() -> None:
    configuration = _configuration_set()
    suite = _suite()
    executor = _FakeExecutor(
        configuration_set_id="c011-real-runtime-set:sha256:" + "0" * 64
    )

    receipt = execute_real_equal_compute(
        policy=_policy(),
        snapshot=_snapshot(_all_verified_items(configuration, suite)),
        configuration_set=configuration,
        suite=suite,
        executor=executor,
    )

    assert receipt.disposition is RealEqualComputeRunDisposition.BLOCKED_BINDING
    assert receipt.blocked_reasons == (
        "generation executor does not bind the runtime configuration set",
    )
    assert executor.calls == []


def test_result_call_binding_mismatch_fails_without_retry() -> None:
    executor = _FakeExecutor(wrong_call_id=True)
    with pytest.raises(RealEqualComputeRunnerError, match="call binding"):
        _execute_ready(executor)
    assert len(executor.calls) == 1


def test_output_budget_overrun_fails_without_retry() -> None:
    executor = _FakeExecutor(output_tokens=257)
    with pytest.raises(RealEqualComputeRunnerError, match="output-token ceiling"):
        _execute_ready(executor)
    assert len(executor.calls) == 1


def test_native_total_budget_overrun_fails_without_retry() -> None:
    configuration = _configuration_set(max_total_tokens=256)
    executor = _FakeExecutor(input_tokens=300)
    with pytest.raises(RealEqualComputeRunnerError, match="native total-token budget"):
        _execute_ready(executor, configuration=configuration)
    assert len(executor.calls) == 1


def test_known_context_budget_overrun_fails_before_provider_call() -> None:
    configuration = _configuration_set(max_context_bytes=1)
    executor = _FakeExecutor()
    with pytest.raises(RealEqualComputeRunnerError, match="context-byte budget"):
        _execute_ready(executor, configuration=configuration)
    assert executor.calls == []


def test_harmony_control_marker_is_rejected_before_receipt() -> None:
    executor = _FakeExecutor(harmony_output=True)
    with pytest.raises(ValidationError, match="Harmony control marker"):
        _execute_ready(executor)
    assert len(executor.calls) == 1


def test_generation_failure_is_never_replayed() -> None:
    executor = _FakeExecutor(fail_role=RealEqualComputeCallRole.ULTRA_DRAFT)
    with pytest.raises(RuntimeError, match="bounded fake generation failure"):
        _execute_ready(executor)
    call_ids = tuple(item.call_id for item in executor.calls)
    assert len(call_ids) == 2
    assert len(call_ids) == len(set(call_ids))


def test_three_worker_variant_executes_exactly_three_concurrent_reviews() -> None:
    configuration = _configuration_set(parallel_workers=3)
    executor = _FakeExecutor(parallel_workers=3)

    receipt = _execute_ready(executor, configuration=configuration)

    assert receipt.provider_calls_executed == 42
    assert receipt.max_concurrent_generations_observed == 3
    assert executor.maximum == 3
    assert tuple(
        item.role for item in receipt.case_receipts[0].arms[-1].call_receipts
    ) == (
        RealEqualComputeCallRole.PARALLEL_EVIDENCE,
        RealEqualComputeCallRole.PARALLEL_ADVERSARIAL,
        RealEqualComputeCallRole.PARALLEL_ALTERNATIVE,
        RealEqualComputeCallRole.PARALLEL_ROOT,
    )


def test_all_runner_and_suite_contracts_remain_authority_negative() -> None:
    receipt = _execute_ready(_FakeExecutor())
    assert receipt.production_runtime_wiring is False
    assert receipt.controlled_c011_execution is False
    assert receipt.task_state_authority is False
    assert receipt.root_context_adoption_authority is False
    assert receipt.completion_authority is False
    assert receipt.user_facing_voice_authority is False
    assert receipt.canary_authority is False
    assert receipt.active_authority is False
    assert receipt.promotion_authority is False


def test_receipt_aggregate_tampering_fails_closed() -> None:
    receipt = _execute_ready(_FakeExecutor())
    arm_payload = receipt.case_receipts[0].arms[0].model_dump(mode="json")
    arm_payload["native_total_tokens"] += 1
    with pytest.raises(ValidationError, match="call receipts"):
        RealEqualComputeArmReceipt.model_validate(arm_payload)

    run_payload = receipt.model_dump(mode="json")
    run_payload["run_id"] = ""
    run_payload["provider_calls_executed"] -= 1
    with pytest.raises(ValidationError, match="complete receipts"):
        RealEqualComputeRunReceipt.model_validate(run_payload)
