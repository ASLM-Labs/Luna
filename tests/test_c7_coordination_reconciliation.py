from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from luna.contracts.plan import PlanStep
from luna.contracts.task import TaskContract, TaskScope
from luna.planning.coordination import (
    CoordinationMode,
    GeneralCoordinationPlanner,
)
from luna.planning.reconciliation import (
    CoordinationClaim,
    CoordinationReconciler,
    ReconciliationReport,
    ReconciliationVerdict,
    WorkerResult,
    WorkerResultStatus,
)

_C6_BASIS = "a" * 64


def _contract() -> TaskContract:
    return TaskContract(
        objective="Coordinate bounded independent work.",
        required_conditions=("coordination remains evidence-bound",),
        evidence_required=("verification evidence exists",),
        scope=TaskScope(
            workspace_root=".",
            allowed_paths=("src/luna", "tests"),
            write_allowed=True,
        ),
    )


def _steps() -> tuple[PlanStep, PlanStep, PlanStep]:
    return (
        PlanStep(sequence=1, description="Inspect independent surface."),
        PlanStep(sequence=2, description="Implement independent change."),
        PlanStep(sequence=3, description="Independently verify the result."),
    )


def _parallel_plan(*, revision: int = 10):
    contract = _contract()
    steps = _steps()
    plan = GeneralCoordinationPlanner().plan(
        task_contract=contract,
        source_task_revision=revision,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        worker_capacity=2,
    )
    assert plan.mode is CoordinationMode.PARALLEL_WORKERS
    return plan


def _review_plan(*, revision: int = 10):
    contract = _contract()
    steps = _steps()
    plan = GeneralCoordinationPlanner().plan(
        task_contract=contract,
        source_task_revision=revision,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        independent_review_required=True,
        independent_review_step_id=steps[2].step_id,
        worker_capacity=2,
    )
    assert plan.mode is CoordinationMode.INDEPENDENT_REVIEW
    return plan


def _claim(
    key: str,
    value: str,
    *,
    evidence_ids: tuple[UUID, ...] = (),
) -> CoordinationClaim:
    return CoordinationClaim(
        claim_key=key,
        claim_value=value,
        evidence_ids=evidence_ids,
        provenance_refs=("test:claim",),
    )


def _success_result(
    reconciler: CoordinationReconciler,
    assignment,
    *,
    key: str,
    value: str,
    evidence_id: UUID | None = None,
):
    evidence_ids = (evidence_id,) if evidence_id is not None else ()
    claim = _claim(key, value, evidence_ids=evidence_ids)
    return reconciler.result(
        assignment=assignment,
        status=WorkerResultStatus.SUCCESS,
        claims=(claim,),
        evidence_ids=evidence_ids,
    )


def _current_bases(plan) -> dict[str, str]:
    return {
        assignment.assignment_id: assignment.assignment_basis_fingerprint
        for assignment in plan.assignments
    }


def test_c7_revision_change_does_not_make_same_semantic_basis_stale() -> None:
    plan = _parallel_plan(revision=20)
    reconciler = CoordinationReconciler()
    evidence_one = uuid4()
    evidence_two = uuid4()

    results = (
        _success_result(
            reconciler,
            plan.assignments[0],
            key="surface:a",
            value="PASS",
            evidence_id=evidence_one,
        ),
        _success_result(
            reconciler,
            plan.assignments[1],
            key="surface:b",
            value="PASS",
            evidence_id=evidence_two,
        ),
    )

    report = reconciler.reconcile(
        plan=plan,
        results=results,
        current_task_revision=21,
        current_assignment_basis_fingerprints=_current_bases(plan),
    )

    assert report.verdict is ReconciliationVerdict.ACCEPT
    assert report.stale_assignment_ids == ()
    assert "task_revision_changed_semantic_basis_checked" in report.reason_codes
    assert set(report.evidence_ids) == {evidence_one, evidence_two}


def test_c7_changed_semantic_basis_is_stale() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()

    results = tuple(
        _success_result(
            reconciler,
            assignment,
            key=f"claim:{index}",
            value="PASS",
            evidence_id=uuid4(),
        )
        for index, assignment in enumerate(plan.assignments)
    )

    bases = _current_bases(plan)
    bases[plan.assignments[0].assignment_id] = "b" * 64

    report = reconciler.reconcile(
        plan=plan,
        results=results,
        current_task_revision=11,
        current_assignment_basis_fingerprints=bases,
    )

    assert report.verdict is ReconciliationVerdict.STALE
    assert report.stale_assignment_ids == (
        plan.assignments[0].assignment_id,
    )
    assert "assignment_semantic_basis_changed" in report.reason_codes


def test_c7_unknown_current_basis_requires_verify_not_stale() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()

    results = tuple(
        _success_result(
            reconciler,
            assignment,
            key=f"claim:{index}",
            value="PASS",
            evidence_id=uuid4(),
        )
        for index, assignment in enumerate(plan.assignments)
    )

    bases = _current_bases(plan)
    del bases[plan.assignments[0].assignment_id]

    report = reconciler.reconcile(
        plan=plan,
        results=results,
        current_task_revision=10,
        current_assignment_basis_fingerprints=bases,
    )

    assert report.verdict is ReconciliationVerdict.VERIFY
    assert report.stale_assignment_ids == ()
    assert "current_assignment_basis_unavailable" in report.reason_codes


def test_c7_parallel_workers_with_conflicting_claims_conflict() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()

    results = (
        _success_result(
            reconciler,
            plan.assignments[0],
            key="shared:decision",
            value="PASS",
            evidence_id=uuid4(),
        ),
        _success_result(
            reconciler,
            plan.assignments[1],
            key="shared:decision",
            value="FAIL",
            evidence_id=uuid4(),
        ),
    )

    report = reconciler.reconcile(
        plan=plan,
        results=results,
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
    )

    assert report.verdict is ReconciliationVerdict.CONFLICT
    assert report.conflicting_claim_keys == ("shared:decision",)
    assert "independent_worker_claims_conflict" in report.reason_codes


def test_c7_parallel_workers_with_compatible_evidence_are_accepted() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()

    results = (
        _success_result(
            reconciler,
            plan.assignments[0],
            key="surface:a",
            value="PASS",
            evidence_id=uuid4(),
        ),
        _success_result(
            reconciler,
            plan.assignments[1],
            key="surface:b",
            value="PASS",
            evidence_id=uuid4(),
        ),
    )

    report = reconciler.reconcile(
        plan=plan,
        results=results,
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
    )

    assert report.verdict is ReconciliationVerdict.ACCEPT
    assert len(report.accepted_result_ids) == 2
    assert "parallel_worker_results_reconciled" in report.reason_codes
    assert report.completion_authority is False


def test_c7_missing_parallel_worker_result_requires_verify() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()

    result = _success_result(
        reconciler,
        plan.assignments[0],
        key="surface:a",
        value="PASS",
        evidence_id=uuid4(),
    )

    report = reconciler.reconcile(
        plan=plan,
        results=(result,),
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
    )

    assert report.verdict is ReconciliationVerdict.VERIFY
    assert "expected_worker_result_missing" in report.reason_codes


def test_c7_non_successful_worker_result_requires_verify() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()

    first = _success_result(
        reconciler,
        plan.assignments[0],
        key="surface:a",
        value="PASS",
        evidence_id=uuid4(),
    )
    second = reconciler.result(
        assignment=plan.assignments[1],
        status=WorkerResultStatus.BLOCKED,
        blocker_refs=("worker:blocked",),
    )

    report = reconciler.reconcile(
        plan=plan,
        results=(first, second),
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
    )

    assert report.verdict is ReconciliationVerdict.VERIFY
    assert "worker_result_not_fully_successful" in report.reason_codes


def test_c7_claims_without_external_evidence_require_verify() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()

    results = (
        _success_result(
            reconciler,
            plan.assignments[0],
            key="surface:a",
            value="PASS",
        ),
        _success_result(
            reconciler,
            plan.assignments[1],
            key="surface:b",
            value="PASS",
        ),
    )

    report = reconciler.reconcile(
        plan=plan,
        results=results,
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
    )

    assert report.verdict is ReconciliationVerdict.VERIFY
    assert (
        "worker_result_lacks_external_evidence_or_observation"
        in report.reason_codes
    )


def test_c7_independent_review_disagreement_is_conflict() -> None:
    plan = _review_plan()
    reconciler = CoordinationReconciler()
    evidence_id = uuid4()

    reviewer = _success_result(
        reconciler,
        plan.assignments[0],
        key="acceptance:test-suite",
        value="FAIL",
        evidence_id=evidence_id,
    )
    main_claim = _claim("acceptance:test-suite", "PASS")

    report = reconciler.reconcile(
        plan=plan,
        results=(reviewer,),
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
        reference_claims=(main_claim,),
    )

    assert report.verdict is ReconciliationVerdict.CONFLICT
    assert report.conflicting_claim_keys == ("acceptance:test-suite",)


def test_c7_independent_review_agreement_can_be_accepted() -> None:
    plan = _review_plan()
    reconciler = CoordinationReconciler()
    evidence_id = uuid4()

    reviewer = _success_result(
        reconciler,
        plan.assignments[0],
        key="acceptance:test-suite",
        value="PASS",
        evidence_id=evidence_id,
    )
    main_claim = _claim("acceptance:test-suite", "PASS")

    report = reconciler.reconcile(
        plan=plan,
        results=(reviewer,),
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
        reference_claims=(main_claim,),
    )

    assert report.verdict is ReconciliationVerdict.ACCEPT
    assert "independent_review_agrees_on_all_reference_claims" in report.reason_codes
    assert report.completion_authority is False


def test_c7_independent_review_without_comparable_main_claim_requires_verify() -> None:
    plan = _review_plan()
    reconciler = CoordinationReconciler()

    reviewer = _success_result(
        reconciler,
        plan.assignments[0],
        key="review:different-surface",
        value="PASS",
        evidence_id=uuid4(),
    )

    report = reconciler.reconcile(
        plan=plan,
        results=(reviewer,),
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
        reference_claims=(_claim("main:other-surface", "PASS"),),
    )

    assert report.verdict is ReconciliationVerdict.VERIFY
    assert "independent_review_has_no_comparable_main_claim" in report.reason_codes


def test_c7_result_from_unknown_assignment_is_rejected() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()
    evidence_id = uuid4()

    fake_assignment_id = f"assignment:sha256:{'b' * 64}"
    fake_basis = "b" * 64
    fake_claims = (
        _claim(
            "fake:claim",
            "PASS",
            evidence_ids=(evidence_id,),
        ),
    )
    fake_evidence_ids = (evidence_id,)
    fake_provenance = ("test:fake-worker",)

    fake_fingerprint = WorkerResult.compute_result_fingerprint(
        task_id=plan.task_id,
        assignment_id=fake_assignment_id,
        source_task_revision=plan.source_task_revision,
        assignment_basis_fingerprint=fake_basis,
        status=WorkerResultStatus.SUCCESS,
        claims=fake_claims,
        evidence_ids=fake_evidence_ids,
        observation_ids=(),
        blocker_refs=(),
        provenance_refs=fake_provenance,
    )

    fake = WorkerResult(
        result_id=f"worker-result:sha256:{fake_fingerprint}",
        task_id=plan.task_id,
        assignment_id=fake_assignment_id,
        source_task_revision=plan.source_task_revision,
        assignment_basis_fingerprint=fake_basis,
        status=WorkerResultStatus.SUCCESS,
        claims=fake_claims,
        evidence_ids=fake_evidence_ids,
        provenance_refs=fake_provenance,
    )

    report = reconciler.reconcile(
        plan=plan,
        results=(fake,),
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
    )

    assert report.verdict is ReconciliationVerdict.REJECT
    assert report.rejected_result_ids == (fake.result_id,)


def test_c7_worker_claim_evidence_must_exist_in_result_evidence() -> None:
    task_id = uuid4()
    assignment_id = f"assignment:sha256:{'b' * 64}"
    assignment_basis = "b" * 64
    claims = (
        _claim(
            "claim:test",
            "PASS",
            evidence_ids=(uuid4(),),
        ),
    )
    provenance_refs = ("test",)

    fingerprint = WorkerResult.compute_result_fingerprint(
        task_id=task_id,
        assignment_id=assignment_id,
        source_task_revision=1,
        assignment_basis_fingerprint=assignment_basis,
        status=WorkerResultStatus.SUCCESS,
        claims=claims,
        evidence_ids=(),
        observation_ids=(),
        blocker_refs=(),
        provenance_refs=provenance_refs,
    )

    with pytest.raises(
        ValidationError,
        match="claim evidence must be included in worker result evidence IDs",
    ):
        WorkerResult(
            result_id=f"worker-result:sha256:{fingerprint}",
            task_id=task_id,
            assignment_id=assignment_id,
            source_task_revision=1,
            assignment_basis_fingerprint=assignment_basis,
            status=WorkerResultStatus.SUCCESS,
            claims=claims,
            provenance_refs=provenance_refs,
        )


def test_c7_each_assignment_may_return_at_most_one_result() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()
    assignment = plan.assignments[0]

    first = _success_result(
        reconciler,
        assignment,
        key="claim:first",
        value="PASS",
        evidence_id=uuid4(),
    )
    second = _success_result(
        reconciler,
        assignment,
        key="claim:second",
        value="PASS",
        evidence_id=uuid4(),
    )

    with pytest.raises(
        ValueError,
        match="each assignment may return at most one worker result",
    ):
        reconciler.reconcile(
            plan=plan,
            results=(first, second),
            current_task_revision=10,
            current_assignment_basis_fingerprints=_current_bases(plan),
        )


def test_c7_reconciliation_cannot_gain_completion_authority() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()

    results = tuple(
        _success_result(
            reconciler,
            assignment,
            key=f"claim:{index}",
            value="PASS",
            evidence_id=uuid4(),
        )
        for index, assignment in enumerate(plan.assignments)
    )

    report = reconciler.reconcile(
        plan=plan,
        results=results,
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
    )

    payload = report.model_dump(mode="python")
    payload["completion_authority"] = True

    with pytest.raises(ValidationError):
        ReconciliationReport.model_validate(payload)


def test_c7_worker_result_builder_is_deterministic() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()
    assignment = plan.assignments[0]
    evidence_id = uuid4()
    claim = _claim(
        "deterministic:test",
        "PASS",
        evidence_ids=(evidence_id,),
    )

    first = reconciler.result(
        assignment=assignment,
        status=WorkerResultStatus.SUCCESS,
        claims=(claim,),
        evidence_ids=(evidence_id,),
    )
    second = reconciler.result(
        assignment=assignment,
        status=WorkerResultStatus.SUCCESS,
        claims=(claim,),
        evidence_ids=(evidence_id,),
    )

    assert first == second
    assert first.result_id == second.result_id


def test_c7_worker_result_rejects_payload_tampering() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()

    result = _success_result(
        reconciler,
        plan.assignments[0],
        key="tamper:test",
        value="PASS",
        evidence_id=uuid4(),
    )

    payload = result.model_dump(mode="python")
    payload["source_task_revision"] += 1

    with pytest.raises(
        ValidationError,
        match="worker result ID must derive from its complete result payload",
    ):
        WorkerResult.model_validate(payload)


def test_c7_result_identity_tracks_revision_but_assignment_identity_does_not() -> None:
    contract = _contract()
    steps = _steps()
    planner = GeneralCoordinationPlanner()
    reconciler = CoordinationReconciler()
    evidence_id = uuid4()

    first_plan = planner.plan(
        task_contract=contract,
        source_task_revision=20,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        worker_capacity=2,
    )
    second_plan = planner.plan(
        task_contract=contract,
        source_task_revision=21,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        worker_capacity=2,
    )

    first_assignment = first_plan.assignments[0]
    second_assignment = second_plan.assignments[0]

    assert first_assignment.assignment_id == second_assignment.assignment_id

    first_result = _success_result(
        reconciler,
        first_assignment,
        key="identity:test",
        value="PASS",
        evidence_id=evidence_id,
    )
    second_result = _success_result(
        reconciler,
        second_assignment,
        key="identity:test",
        value="PASS",
        evidence_id=evidence_id,
    )

    assert first_result.result_id != second_result.result_id


def test_c7_each_successful_parallel_worker_requires_external_evidence() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()

    evidenced = _success_result(
        reconciler,
        plan.assignments[0],
        key="surface:a",
        value="PASS",
        evidence_id=uuid4(),
    )
    claim_only = _success_result(
        reconciler,
        plan.assignments[1],
        key="surface:b",
        value="PASS",
    )

    report = reconciler.reconcile(
        plan=plan,
        results=(evidenced, claim_only),
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
    )

    assert report.verdict is ReconciliationVerdict.VERIFY
    assert (
        "worker_result_lacks_external_evidence_or_observation"
        in report.reason_codes
    )


def test_c7_independent_review_must_cover_all_reference_claims() -> None:
    plan = _review_plan()
    reconciler = CoordinationReconciler()

    reviewer = _success_result(
        reconciler,
        plan.assignments[0],
        key="acceptance:a",
        value="PASS",
        evidence_id=uuid4(),
    )

    report = reconciler.reconcile(
        plan=plan,
        results=(reviewer,),
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
        reference_claims=(
            _claim("acceptance:a", "PASS"),
            _claim("acceptance:b", "PASS"),
        ),
    )

    assert report.verdict is ReconciliationVerdict.VERIFY
    assert (
        "independent_review_reference_claims_not_fully_covered"
        in report.reason_codes
    )


def test_c7_independent_review_requires_reference_claims() -> None:
    plan = _review_plan()
    reconciler = CoordinationReconciler()

    reviewer = _success_result(
        reconciler,
        plan.assignments[0],
        key="acceptance:a",
        value="PASS",
        evidence_id=uuid4(),
    )

    report = reconciler.reconcile(
        plan=plan,
        results=(reviewer,),
        current_task_revision=10,
        current_assignment_basis_fingerprints=_current_bases(plan),
    )

    assert report.verdict is ReconciliationVerdict.VERIFY
    assert "independent_review_has_no_reference_claim" in report.reason_codes


def test_c7_reference_claim_keys_must_be_unique() -> None:
    plan = _review_plan()
    reconciler = CoordinationReconciler()

    reviewer = _success_result(
        reconciler,
        plan.assignments[0],
        key="acceptance:a",
        value="PASS",
        evidence_id=uuid4(),
    )

    with pytest.raises(ValueError, match="reference claim keys must be unique"):
        reconciler.reconcile(
            plan=plan,
            results=(reviewer,),
            current_task_revision=10,
            current_assignment_basis_fingerprints=_current_bases(plan),
            reference_claims=(
                _claim("acceptance:a", "PASS"),
                _claim("acceptance:a", "PASS"),
            ),
        )


def test_c7_malformed_current_basis_cannot_create_stale_verdict() -> None:
    plan = _parallel_plan()
    reconciler = CoordinationReconciler()

    results = tuple(
        _success_result(
            reconciler,
            assignment,
            key=f"claim:{index}",
            value="PASS",
            evidence_id=uuid4(),
        )
        for index, assignment in enumerate(plan.assignments)
    )

    bases = _current_bases(plan)
    bases[plan.assignments[0].assignment_id] = "not-a-sha256"

    with pytest.raises(
        ValueError,
        match="current assignment basis fingerprints must be lowercase sha256",
    ):
        reconciler.reconcile(
            plan=plan,
            results=results,
            current_task_revision=11,
            current_assignment_basis_fingerprints=bases,
        )
