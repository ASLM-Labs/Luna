from __future__ import annotations

import sqlite3
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from luna.evaluation_governance import (
    BenchmarkContaminationReport,
    ContaminationFinding,
    ContaminationReason,
    EvaluationCase,
    EvaluationPartition,
    EvaluatorKind,
    EvaluatorSpec,
    FrozenEvaluationSuite,
)
from luna.parallel_cognition import (
    EqualComputeBudget,
    ShadowArmSpec,
    ShadowComparisonStatus,
    ShadowConfiguration,
    ShadowEvaluationComparison,
    ShadowEvaluationPlan,
    ShadowEvidenceKind,
    ShadowEvidenceReference,
    ShadowLedgerConflictError,
    ShadowLedgerIntegrityError,
    ShadowMetricObservation,
    ShadowRunObservation,
    ShadowRunSlot,
    SQLiteShadowEvaluationLedger,
    compare_shadow_observations,
)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _evaluator(
    *,
    kind: EvaluatorKind = EvaluatorKind.DETERMINISTIC,
    model_identity: str | None = None,
) -> EvaluatorSpec:
    return EvaluatorSpec(
        evaluator_id="c011-s5c-independent-evaluator",
        revision="1.0.0",
        kind=kind,
        implementation_sha256=_digest("c011-s5c-evaluator-v1"),
        independent_from_candidate_artifacts=True,
        independent_from_training_data=True,
        model_identity=model_identity,
    )


def _suite(*, evaluator: EvaluatorSpec | None = None) -> FrozenEvaluationSuite:
    cases = (
        EvaluationCase(
            case_id="held-001",
            source_trajectory_id="trajectory-held-001",
            partition=EvaluationPartition.HELD_OUT,
            task_family="held-task",
            repository_family="held-repo",
            trajectory_family="held-trajectory",
            content_sha256=_digest("held-content"),
            evidence_refs=("fixture:held-001",),
        ),
        EvaluationCase(
            case_id="ood-001",
            source_trajectory_id="trajectory-ood-001",
            partition=EvaluationPartition.OOD,
            task_family="ood-task",
            repository_family="ood-repo",
            trajectory_family="ood-trajectory",
            content_sha256=_digest("ood-content"),
            evidence_refs=("fixture:ood-001",),
        ),
    )
    return FrozenEvaluationSuite.freeze(
        suite_name="c011-s5c-shadow-suite",
        revision="1.0.0",
        evaluator=evaluator or _evaluator(),
        cases=cases,
    )


def _contamination_report(*, contaminated: bool = False) -> BenchmarkContaminationReport:
    if not contaminated:
        return BenchmarkContaminationReport()
    return BenchmarkContaminationReport(
        findings=(
            ContaminationFinding(
                case_id="held-001",
                exposure_source_trajectory_id="training-copy",
                reason=ContaminationReason.EXACT_CONTENT,
            ),
        )
    )


def _arms() -> tuple[ShadowArmSpec, ...]:
    return tuple(
        ShadowArmSpec(
            configuration=configuration,
            execution_configuration_sha256=_digest(f"execution:{configuration.value}"),
            backend_id="local-native:c011-s5c-fixture",
            provider_profile_id="c011-provider-profile:fixture",
            provider_binding_id="c011-provider-binding:fixture",
            model_identity="candidate-model",
            driver_sha256=_digest("driver"),
            runtime_sha256=_digest("runtime"),
            environment_sha256=_digest("environment"),
            sampling_sha256=_digest("sampling"),
            seed=41,
            worker_count=2 if configuration is ShadowConfiguration.PARALLEL else 0,
        )
        for configuration in (
            ShadowConfiguration.SOLO,
            ShadowConfiguration.ULTRA_SOLO,
            ShadowConfiguration.PARALLEL,
        )
    )


def _plan(
    *,
    suite: FrozenEvaluationSuite | None = None,
    contaminated: bool = False,
    contamination_complete: bool = True,
    evaluator_independence_verified: bool = True,
    repetitions: int = 1,
    prompt_tag: str = "prompt",
) -> ShadowEvaluationPlan:
    evaluation_suite = suite or _suite()
    slots: list[ShadowRunSlot] = []
    sequence = 0
    for case_id in evaluation_suite.case_ids:
        for repetition in range(1, repetitions + 1):
            for configuration in (
                ShadowConfiguration.SOLO,
                ShadowConfiguration.ULTRA_SOLO,
                ShadowConfiguration.PARALLEL,
            ):
                sequence += 1
                slots.append(
                    ShadowRunSlot(
                        schedule_index=sequence,
                        case_id=case_id,
                        repetition=repetition,
                        configuration=configuration,
                    )
                )
    return ShadowEvaluationPlan(
        task_id="11111111-1111-4111-8111-111111111111",
        source_task_revision=7,
        task_contract_sha256=_digest("task-contract"),
        workload_sha256=_digest("workload"),
        prompt_sha256=_digest(prompt_tag),
        context_manifest_sha256=_digest("context"),
        execution_tree_sha256=_digest("tree"),
        compute_accounting_sha256=_digest("accounting-v1"),
        metric_policy_sha256=_digest("metric-policy-v1"),
        contamination_exposure_manifest_sha256=_digest("exposure-manifest"),
        contamination_provenance_complete=contamination_complete,
        evaluator_independence_evidence_sha256=_digest("evaluator-independence"),
        evaluator_independence_verified=evaluator_independence_verified,
        evaluation_suite=evaluation_suite,
        contamination_report=_contamination_report(contaminated=contaminated),
        equal_compute_budget=EqualComputeBudget(
            max_total_tokens=100,
            max_tool_calls=2,
            max_compute_units=120,
            max_context_bytes=4096,
            max_wall_time_ms=5000,
        ),
        repetitions=repetitions,
        arms=_arms(),
        run_slots=tuple(slots),
    )


def _metrics(
    configuration: ShadowConfiguration,
    *,
    compute_units: int = 100,
    quality: int | None = None,
) -> ShadowMetricObservation:
    quality_by_configuration = {
        ShadowConfiguration.SOLO: 700,
        ShadowConfiguration.ULTRA_SOLO: 760,
        ShadowConfiguration.PARALLEL: 790,
    }
    worker_compute = 60 if configuration is ShadowConfiguration.PARALLEL else 0
    root_compute = compute_units - worker_compute
    return ShadowMetricObservation(
        quality_score_milli=(
            quality_by_configuration[configuration] if quality is None else quality
        ),
        required_evidence_count=4,
        verified_required_evidence_count=4,
        required_evidence_coverage_milli=1000,
        latency_ms=800 if configuration is ShadowConfiguration.PARALLEL else 1000,
        input_tokens=40,
        output_tokens=10,
        tool_calls=1,
        root_compute_units=root_compute,
        worker_compute_units=worker_compute,
        compute_units=compute_units,
        context_bytes=2048,
        duplicate_work_units=(
            2 if configuration is ShadowConfiguration.PARALLEL else 0
        ),
        stale_rejections=1 if configuration is ShadowConfiguration.PARALLEL else 0,
        worker_rejections=1 if configuration is ShadowConfiguration.PARALLEL else 0,
        unnecessary_spawns=0,
        changed_basis_respawns=0,
        contradictions_detected=1,
        contradictions_resolved=1,
        user_voice_violations=0,
    )


def _observation(
    plan: ShadowEvaluationPlan,
    configuration: ShadowConfiguration,
    *,
    case_id: str = "held-001",
    repetition: int = 1,
    compute_units: int = 100,
    evidence_kind: ShadowEvidenceKind = ShadowEvidenceKind.DETERMINISTIC_FIXTURE,
    result_tag: str = "accepted",
) -> ShadowRunObservation:
    slot = next(
        item
        for item in plan.run_slots
        if (
            item.case_id == case_id
            and item.repetition == repetition
            and item.configuration is configuration
        )
    )
    arm = next(item for item in plan.arms if item.configuration is configuration)
    return ShadowRunObservation(
        plan_id=plan.plan_id,
        slot_id=slot.slot_id,
        case_id=case_id,
        repetition=repetition,
        configuration=configuration,
        execution_configuration_sha256=arm.execution_configuration_sha256,
        evidence_kind=evidence_kind,
        result_sha256=_digest(f"{case_id}:{configuration.value}:{result_tag}"),
        evaluator_evidence_refs=(
            ShadowEvidenceReference(
                locator=f"fixture:{case_id}:{configuration.value}",
                content_sha256=_digest(f"evidence:{case_id}:{configuration.value}"),
            ),
        ),
        metrics=_metrics(configuration, compute_units=compute_units),
    )


def _triplet(plan: ShadowEvaluationPlan) -> tuple[ShadowRunObservation, ...]:
    return tuple(_observation(plan, configuration) for configuration in ShadowConfiguration)


def _comparison(
    plan: ShadowEvaluationPlan,
    observations: tuple[ShadowRunObservation, ...],
) -> ShadowEvaluationComparison:
    return compare_shadow_observations(
        plan=plan,
        case_id="held-001",
        repetition=1,
        observations=observations,
    )


def test_shadow_plan_binds_complete_schedule_and_is_content_addressed() -> None:
    first = _plan(repetitions=2)
    second = _plan(repetitions=2)

    assert first.plan_id == second.plan_id
    assert len(first.run_slots) == 12
    with pytest.raises(ValidationError, match="plan ID"):
        ShadowEvaluationPlan.model_validate(
            first.model_dump(mode="json") | {"plan_id": "c011-shadow-plan:sha256:" + "0" * 64}
        )
    with pytest.raises(ValidationError, match="exact suite/repetition/arm grid"):
        ShadowEvaluationPlan.model_validate(
            first.model_dump(mode="json") | {"plan_id": "", "run_slots": first.run_slots[:-1]}
        )


def test_candidate_model_cannot_be_its_own_model_judge() -> None:
    judge = _evaluator(
        kind=EvaluatorKind.MODEL_JUDGE,
        model_identity="candidate-model",
    )
    with pytest.raises(ValidationError, match="cannot judge itself"):
        _plan(suite=_suite(evaluator=judge))


def test_metric_accounting_and_evidence_coverage_fail_closed() -> None:
    with pytest.raises(ValidationError, match="compute units"):
        ShadowMetricObservation.model_validate(
            _metrics(ShadowConfiguration.SOLO).model_dump(mode="json")
            | {"compute_units": 99}
        )
    with pytest.raises(ValidationError, match="coverage"):
        ShadowMetricObservation.model_validate(
            _metrics(ShadowConfiguration.SOLO).model_dump(mode="json")
            | {"required_evidence_coverage_milli": 750}
        )


def test_complete_equal_compute_triplet_is_deterministic_and_non_authoritative() -> None:
    plan = _plan()
    observations = _triplet(plan)
    first = _comparison(plan, observations)
    second = _comparison(plan, tuple(reversed(observations)))

    assert first == second
    assert first.status is ShadowComparisonStatus.COMPARABLE
    assert first.deltas_vs_solo[0].quality_score_milli == 60
    assert first.deltas_vs_solo[1].quality_score_milli == 90
    assert first.non_inferiority_established is False
    assert first.task_state_authority is False
    assert first.root_context_adoption_authority is False
    assert first.completion_authority is False
    assert first.user_facing_voice_authority is False
    assert first.promotion_authority is False


@pytest.mark.parametrize(
    ("plan", "mutator", "reason"),
    (
        (
            _plan(),
            lambda values: values[:2],
            "exactly three observations",
        ),
        (
            _plan(),
            lambda values: (
                *values[:2],
                _observation(_plan(), ShadowConfiguration.PARALLEL, compute_units=90),
            ),
            "compute totals are not equal",
        ),
        (
            _plan(),
            lambda values: (
                *values[:2],
                _observation(
                    _plan(),
                    ShadowConfiguration.PARALLEL,
                    evidence_kind=ShadowEvidenceKind.REAL_PROVIDER,
                ),
            ),
            "cannot mix fixture and real-provider evidence",
        ),
        (
            _plan(contaminated=True),
            lambda values: values,
            "contamination findings",
        ),
        (
            _plan(contamination_complete=False),
            lambda values: values,
            "contamination provenance is incomplete",
        ),
        (
            _plan(evaluator_independence_verified=False),
            lambda values: values,
            "evaluator independence evidence is incomplete",
        ),
    ),
)
def test_incomplete_or_noncomparable_evidence_is_blocked(
    plan: ShadowEvaluationPlan,
    mutator: Callable[
        [tuple[ShadowRunObservation, ...]], tuple[ShadowRunObservation, ...]
    ],
    reason: str,
) -> None:
    observations = mutator(_triplet(plan))
    comparison = compare_shadow_observations(
        plan=plan,
        case_id="held-001",
        repetition=1,
        observations=observations,
    )
    assert comparison.status is ShadowComparisonStatus.BLOCKED
    assert any(reason in item for item in comparison.blocked_reasons)
    assert comparison.deltas_vs_solo == ()


def test_empty_evidence_is_blocked_instead_of_raising() -> None:
    comparison = compare_shadow_observations(
        plan=_plan(),
        case_id="held-001",
        repetition=1,
        observations=(),
    )
    assert comparison.status is ShadowComparisonStatus.BLOCKED
    assert comparison.observation_ids == ()
    assert comparison.evidence_kinds == ()


def test_slot_arm_and_repetition_drift_are_blocked() -> None:
    plan = _plan(repetitions=2)
    observations = list(_triplet(plan))
    wrong_slot = next(
        item
        for item in plan.run_slots
        if item.case_id == "held-001" and item.repetition == 2
    )
    observations[0] = ShadowRunObservation.model_validate(
        observations[0].model_dump(mode="json")
        | {"slot_id": wrong_slot.slot_id, "observation_id": ""}
    )
    observations[1] = ShadowRunObservation.model_validate(
        observations[1].model_dump(mode="json")
        | {
            "execution_configuration_sha256": _digest("wrong-arm"),
            "observation_id": "",
        }
    )
    observations[2] = ShadowRunObservation.model_validate(
        observations[2].model_dump(mode="json")
        | {"repetition": 2, "observation_id": ""}
    )

    comparison = _comparison(plan, tuple(observations))
    assert comparison.status is ShadowComparisonStatus.BLOCKED
    assert {
        "observation run-slot binding mismatch",
        "observation arm configuration binding mismatch",
        "observation repetition binding mismatch",
    }.issubset(comparison.blocked_reasons)


def test_ledger_appends_complete_run_atomically_and_reopens(tmp_path: Path) -> None:
    path = tmp_path / "shadow.sqlite3"
    plan = _plan()
    observations = _triplet(plan)
    comparison = _comparison(plan, observations)
    ledger = SQLiteShadowEvaluationLedger(path)

    accepted = ledger.append_completed_run(
        plan=plan,
        observations=observations,
        comparison=comparison,
    )
    assert accepted == comparison
    assert ledger.entry_count() == 5
    assert ledger.observations(
        plan_id=plan.plan_id,
        case_id="held-001",
        repetition=1,
    ) == observations

    reopened = SQLiteShadowEvaluationLedger(path)
    reopened.append_completed_run(
        plan=plan,
        observations=tuple(reversed(observations)),
        comparison=comparison,
    )
    assert reopened.entry_count() == 5
    reopened.verify_integrity()


def test_ledger_rejects_incomplete_run_without_partial_rows(tmp_path: Path) -> None:
    plan = _plan()
    observations = _triplet(plan)[:2]
    comparison = compare_shadow_observations(
        plan=plan,
        case_id="held-001",
        repetition=1,
        observations=observations,
    )
    ledger = SQLiteShadowEvaluationLedger(tmp_path / "incomplete.sqlite3")

    with pytest.raises(ShadowLedgerConflictError, match="one observation per arm"):
        ledger.append_completed_run(
            plan=plan,
            observations=observations,
            comparison=comparison,
        )
    assert ledger.entry_count() == 0


def test_identical_schedule_slots_are_scoped_to_the_frozen_plan(tmp_path: Path) -> None:
    first = _plan(prompt_tag="prompt-a")
    second = _plan(prompt_tag="prompt-b")
    assert first.plan_id != second.plan_id
    assert tuple(item.slot_id for item in first.run_slots) == tuple(
        item.slot_id for item in second.run_slots
    )
    ledger = SQLiteShadowEvaluationLedger(tmp_path / "plan-scoped.sqlite3")

    for plan in (first, second):
        observations = _triplet(plan)
        ledger.append_completed_run(
            plan=plan,
            observations=observations,
            comparison=_comparison(plan, observations),
        )

    assert ledger.entry_count() == 10
    ledger.verify_integrity()


def test_conflicting_run_slot_replay_is_rejected_without_partial_append(
    tmp_path: Path,
) -> None:
    ledger = SQLiteShadowEvaluationLedger(tmp_path / "shadow.sqlite3")
    plan = _plan()
    observations = _triplet(plan)
    ledger.append_completed_run(
        plan=plan,
        observations=observations,
        comparison=_comparison(plan, observations),
    )
    conflicting = tuple(
        _observation(plan, item.configuration, result_tag="conflict")
        for item in observations
    )
    with pytest.raises(ShadowLedgerConflictError):
        ledger.append_completed_run(
            plan=plan,
            observations=conflicting,
            comparison=_comparison(plan, conflicting),
        )
    assert ledger.entry_count() == 5


def test_fabricated_comparison_leaves_no_ledger_rows(tmp_path: Path) -> None:
    ledger = SQLiteShadowEvaluationLedger(tmp_path / "shadow.sqlite3")
    plan = _plan()
    observations = _triplet(plan)
    comparison = _comparison(plan, observations)
    fabricated = comparison.model_copy(
        update={"comparison_id": "c011-shadow-comparison:sha256:" + "0" * 64}
    )
    with pytest.raises(ValidationError):
        ledger.append_completed_run(
            plan=plan,
            observations=observations,
            comparison=fabricated,
        )
    assert ledger.entry_count() == 0


def test_ledger_payload_and_tail_deletion_tampering_fail_integrity(tmp_path: Path) -> None:
    path = tmp_path / "shadow.sqlite3"
    plan = _plan()
    observations = _triplet(plan)
    ledger = SQLiteShadowEvaluationLedger(path)
    ledger.append_completed_run(
        plan=plan,
        observations=observations,
        comparison=_comparison(plan, observations),
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE shadow_entries SET artifact_json = '{}' WHERE sequence = 2"
        )
    with pytest.raises(ShadowLedgerIntegrityError):
        ledger.verify_integrity()

    tail_path = tmp_path / "shadow-tail.sqlite3"
    tail = SQLiteShadowEvaluationLedger(tail_path)
    tail.append_completed_run(
        plan=plan,
        observations=observations,
        comparison=_comparison(plan, observations),
    )
    with sqlite3.connect(tail_path) as connection:
        connection.execute("DELETE FROM shadow_entries WHERE artifact_kind = 'COMPARISON'")
    with pytest.raises(ShadowLedgerIntegrityError, match="incomplete observation triplet"):
        tail.verify_integrity()


def test_ledger_persists_hashes_not_raw_output_or_hidden_reasoning(tmp_path: Path) -> None:
    secret_output = "PRIVATE-HARMONY-ANALYSIS-DO-NOT-PERSIST"
    plan = _plan()
    observations = list(_triplet(plan))
    observations[0] = observations[0].model_copy(
        update={"result_sha256": _digest(secret_output), "observation_id": ""}
    )
    observations[0] = ShadowRunObservation.model_validate(
        observations[0].model_dump(mode="json")
    )
    comparison = _comparison(plan, tuple(observations))
    path = tmp_path / "shadow.sqlite3"
    SQLiteShadowEvaluationLedger(path).append_completed_run(
        plan=plan,
        observations=tuple(observations),
        comparison=comparison,
    )
    assert secret_output.encode("utf-8") not in path.read_bytes()


def test_s5c_module_has_no_execution_or_runtime_integration_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (
        root / "src/luna/parallel_cognition/shadow_evaluation.py"
    ).read_text(encoding="utf-8")
    runtime = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "src/luna/runtime").glob("*.py")
    )
    for forbidden in (
        "LocalNativeDriverAdapter",
        "SubprocessWorkerBackend",
        "LunaNativeWorker",
        "subprocess.Popen",
        "luna.runtime",
    ):
        assert forbidden not in source
    assert "shadow_evaluation" not in runtime
    assert "SQLiteShadowEvaluationLedger" not in runtime
