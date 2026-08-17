from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

import luna.planning as package
from luna.contracts.invalidation import (
    CrossLayerInvalidationReport,
    InvalidationControlAction,
    InvalidationImpact,
    InvalidationLayer,
)
from luna.planning import (
    DecisionAlternative,
    DecisionAlternativeSet,
    KnowledgeOptionSpaceAttributionBinding,
    KnowledgeOptionSpaceProjector,
)


def _alternative(
    *,
    action_key: str,
    admissible: bool,
    suffix: str,
) -> DecisionAlternative:
    return DecisionAlternative(
        decision_ref=(
            f"decision:{suffix}:ACTIVE"
        ),
        action_key=action_key,
        description=(
            f"route {action_key}"
        ),
        status="ACTIVE",
        evidence_refs=(),
        blocker_refs=(
            ()
            if admissible
            else (
                "blocker://fixture",
            )
        ),
        admissible=admissible,
        reason_codes=(
            "fixture",
        ),
    )


def _set(
    *,
    task_id: UUID,
    step_id: UUID,
    basis: str,
    alternatives: tuple[
        DecisionAlternative,
        ...,
    ],
    task_revision: int = 1,
    decision_revision: int = 1,
) -> DecisionAlternativeSet:
    ranked = tuple(
        item.decision_ref
        for item in sorted(
            alternatives,
            key=lambda item: (
                0
                if item.admissible
                else 1,
                item.decision_ref,
            ),
        )
    )

    by_ref = {
        item.decision_ref: item
        for item in alternatives
    }

    selected = next(
        (
            ref
            for ref in ranked
            if by_ref[
                ref
            ].admissible
        ),
        None,
    )

    return DecisionAlternativeSet(
        task_id=task_id,
        step_id=step_id,
        source_task_state_revision=(
            task_revision
        ),
        source_decision_state_revision=(
            decision_revision
        ),
        decision_basis_fingerprint=basis,
        alternatives=alternatives,
        ranked_alternative_refs=ranked,
        selected_alternative_ref=selected,
        reason_codes=(
            "fixture",
        ),
    )


def _report(
    *,
    task_id: UUID,
    trigger_ref: str,
    option_evidence: tuple[str, ...] = (
        "evidence://changed",
    ),
) -> CrossLayerInvalidationReport:
    compression_ref = (
        "decision_compression:fixture"
    )
    alternatives_ref = (
        "decision_alternatives:fixture"
    )

    impacts = (
        InvalidationImpact(
            target_ref=trigger_ref,
            layer=(
                InvalidationLayer.ASSUMPTION
            ),
            direct=True,
            cause_refs=(
                trigger_ref,
            ),
            changed_basis_evidence_refs=(
                option_evidence
            ),
            reason_codes=(
                "direct_basis_invalidated",
            ),
        ),
        InvalidationImpact(
            target_ref=compression_ref,
            layer=(
                InvalidationLayer
                .DECISION_COMPRESSION
            ),
            direct=False,
            cause_refs=(
                trigger_ref,
            ),
            changed_basis_evidence_refs=(
                option_evidence
            ),
            reason_codes=(
                "dependent_basis_invalidated",
            ),
        ),
        InvalidationImpact(
            target_ref=alternatives_ref,
            layer=(
                InvalidationLayer
                .DECISION_ALTERNATIVES
            ),
            direct=False,
            cause_refs=(
                compression_ref,
            ),
            changed_basis_evidence_refs=(
                option_evidence
            ),
            reason_codes=(
                "dependent_basis_invalidated",
            ),
        ),
    )

    return CrossLayerInvalidationReport(
        task_id=task_id,
        previous_task_state_revision=1,
        input_task_state_revision=2,
        result_task_state_revision=3,
        previous_decision_state_revision=1,
        current_decision_state_revision=2,
        trigger_refs=(
            trigger_ref,
        ),
        evidence_refs=option_evidence,
        changed_basis_evidence_refs=(
            option_evidence
        ),
        provenance_refs=(
            "owner://c3",
        ),
        impacts=impacts,
        preserved_refs=(),
        control_action=(
            InvalidationControlAction.REPLAN
        ),
        changed_basis_required=True,
        reason_codes=(
            "changed_basis_required",
        ),
    )


def _binding(
    *,
    task_id: UUID,
    trigger_ref: str,
) -> KnowledgeOptionSpaceAttributionBinding:
    return KnowledgeOptionSpaceAttributionBinding(
        task_id=task_id,
        knowledge_ref=(
            "memory://record/a"
        ),
        trigger_ref=trigger_ref,
        evidence_refs=(
            "evidence://knowledge-attribution",
        ),
        provenance_refs=(
            "owner://knowledge-attribution",
        ),
    )


def test_o2_surface_is_public() -> None:
    assert (
        package.KnowledgeOptionSpaceAttributionBinding
        is KnowledgeOptionSpaceAttributionBinding
    )
    assert (
        package.KnowledgeOptionSpaceProjector
        is KnowledgeOptionSpaceProjector
    )


def test_route_add_remove_is_material_when_causally_bound() -> None:
    task_id = uuid4()
    step_id = uuid4()
    trigger_ref = (
        "assumption:"
        + str(
            uuid4()
        )
    )

    previous = _set(
        task_id=task_id,
        step_id=step_id,
        basis="1" * 64,
        alternatives=(
            _alternative(
                action_key="route-a",
                admissible=True,
                suffix="a",
            ),
        ),
        task_revision=1,
        decision_revision=1,
    )

    current = _set(
        task_id=task_id,
        step_id=step_id,
        basis="2" * 64,
        alternatives=(
            _alternative(
                action_key="route-a",
                admissible=True,
                suffix="a",
            ),
            _alternative(
                action_key="route-b",
                admissible=True,
                suffix="b",
            ),
        ),
        task_revision=2,
        decision_revision=2,
    )

    signal = (
        KnowledgeOptionSpaceProjector()
        .project(
            binding=_binding(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            report=_report(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            previous=previous,
            current=current,
        )
    )

    assert signal.material_change is True
    assert signal.evidence_refs == (
        "evidence://changed",
        "evidence://knowledge-attribution",
    )


def test_admissibility_change_is_material() -> None:
    task_id = uuid4()
    step_id = uuid4()
    trigger_ref = (
        "assumption:"
        + str(
            uuid4()
        )
    )

    previous = _set(
        task_id=task_id,
        step_id=step_id,
        basis="3" * 64,
        alternatives=(
            _alternative(
                action_key="route-a",
                admissible=True,
                suffix="a",
            ),
        ),
    )

    current = _set(
        task_id=task_id,
        step_id=step_id,
        basis="4" * 64,
        alternatives=(
            _alternative(
                action_key="route-a",
                admissible=False,
                suffix="a",
            ),
        ),
        task_revision=2,
        decision_revision=2,
    )

    signal = (
        KnowledgeOptionSpaceProjector()
        .project(
            binding=_binding(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            report=_report(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            previous=previous,
            current=current,
        )
    )

    assert signal.material_change is True


def test_basis_only_change_is_not_material() -> None:
    task_id = uuid4()
    step_id = uuid4()
    trigger_ref = (
        "assumption:"
        + str(
            uuid4()
        )
    )

    route = _alternative(
        action_key="route-a",
        admissible=True,
        suffix="a",
    )

    previous = _set(
        task_id=task_id,
        step_id=step_id,
        basis="5" * 64,
        alternatives=(route,),
    )

    current = _set(
        task_id=task_id,
        step_id=step_id,
        basis="6" * 64,
        alternatives=(route,),
        task_revision=2,
        decision_revision=2,
    )

    signal = (
        KnowledgeOptionSpaceProjector()
        .project(
            binding=_binding(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            report=_report(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            previous=previous,
            current=current,
        )
    )

    assert signal.material_change is False
    assert signal.evidence_refs == ()


def test_ranking_only_change_is_not_material() -> None:
    task_id = uuid4()
    step_id = uuid4()
    trigger_ref = (
        "assumption:"
        + str(
            uuid4()
        )
    )

    first = _alternative(
        action_key="route-a",
        admissible=True,
        suffix="a",
    )
    second = _alternative(
        action_key="route-b",
        admissible=True,
        suffix="b",
    )

    previous = _set(
        task_id=task_id,
        step_id=step_id,
        basis="7" * 64,
        alternatives=(
            first,
            second,
        ),
    )

    current = _set(
        task_id=task_id,
        step_id=step_id,
        basis="8" * 64,
        alternatives=(
            first,
            second,
        ),
        task_revision=2,
        decision_revision=2,
    ).model_copy(
        update={
            "ranked_alternative_refs": (
                second.decision_ref,
                first.decision_ref,
            ),
            "selected_alternative_ref": (
                second.decision_ref
            ),
        }
    )

    signal = (
        KnowledgeOptionSpaceProjector()
        .project(
            binding=_binding(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            report=_report(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            previous=previous,
            current=current,
        )
    )

    assert signal.material_change is False


def test_unbound_c3_trigger_is_rejected() -> None:
    task_id = uuid4()
    step_id = uuid4()

    bound_trigger = (
        "assumption:"
        + str(
            uuid4()
        )
    )

    report_trigger = (
        "assumption:"
        + str(
            uuid4()
        )
    )

    route = _alternative(
        action_key="route-a",
        admissible=True,
        suffix="a",
    )

    previous = _set(
        task_id=task_id,
        step_id=step_id,
        basis="9" * 64,
        alternatives=(route,),
    )

    current = _set(
        task_id=task_id,
        step_id=step_id,
        basis="a" * 64,
        alternatives=(route,),
        task_revision=2,
        decision_revision=2,
    )

    with pytest.raises(
        ValueError,
        match="trigger is absent from C3 report",
    ):
        KnowledgeOptionSpaceProjector().project(
            binding=_binding(
                task_id=task_id,
                trigger_ref=bound_trigger,
            ),
            report=_report(
                task_id=task_id,
                trigger_ref=report_trigger,
            ),
            previous=previous,
            current=current,
        )


def test_trigger_without_alternative_impact_is_not_material() -> None:
    task_id = uuid4()
    step_id = uuid4()

    trigger_ref = (
        "assumption:"
        + str(
            uuid4()
        )
    )

    report = _report(
        task_id=task_id,
        trigger_ref=trigger_ref,
    )

    report = report.model_copy(
        update={
            "impacts": (
                report.impacts[0],
            ),
        }
    )

    route_previous = _alternative(
        action_key="route-a",
        admissible=True,
        suffix="a",
    )

    route_current = _alternative(
        action_key="route-a",
        admissible=False,
        suffix="a",
    )

    previous = _set(
        task_id=task_id,
        step_id=step_id,
        basis="b" * 64,
        alternatives=(
            route_previous,
        ),
    )

    current = _set(
        task_id=task_id,
        step_id=step_id,
        basis="c" * 64,
        alternatives=(
            route_current,
        ),
        task_revision=2,
        decision_revision=2,
    )

    signal = (
        KnowledgeOptionSpaceProjector()
        .project(
            binding=_binding(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            report=report,
            previous=previous,
            current=current,
        )
    )

    assert signal.material_change is False


def test_material_delta_requires_causal_changed_basis_evidence() -> None:
    task_id = uuid4()
    step_id = uuid4()

    trigger_ref = (
        "assumption:"
        + str(
            uuid4()
        )
    )

    previous = _set(
        task_id=task_id,
        step_id=step_id,
        basis="d" * 64,
        alternatives=(
            _alternative(
                action_key="route-a",
                admissible=True,
                suffix="a",
            ),
        ),
    )

    current = _set(
        task_id=task_id,
        step_id=step_id,
        basis="e" * 64,
        alternatives=(
            _alternative(
                action_key="route-a",
                admissible=True,
                suffix="a",
            ),
            _alternative(
                action_key="route-b",
                admissible=True,
                suffix="b",
            ),
        ),
        task_revision=2,
        decision_revision=2,
    )

    with pytest.raises(
        ValueError,
        match="requires causal changed-basis evidence",
    ):
        KnowledgeOptionSpaceProjector().project(
            binding=_binding(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            report=_report(
                task_id=task_id,
                trigger_ref=trigger_ref,
                option_evidence=(),
            ),
            previous=previous,
            current=current,
        )


def test_duplicate_action_key_is_rejected() -> None:
    task_id = uuid4()
    step_id = uuid4()

    trigger_ref = (
        "assumption:"
        + str(
            uuid4()
        )
    )

    duplicate = (
        DecisionAlternativeSet.model_construct(
            task_id=task_id,
            step_id=step_id,
            source_task_state_revision=1,
            source_decision_state_revision=1,
            decision_basis_fingerprint=(
                "f" * 64
            ),
            alternatives=(
                _alternative(
                    action_key="route-a",
                    admissible=True,
                    suffix="a",
                ),
                _alternative(
                    action_key="route-a",
                    admissible=True,
                    suffix="b",
                ),
            ),
            ranked_alternative_refs=(),
            selected_alternative_ref=None,
            reason_codes=(
                "fixture",
            ),
            runtime_authority=False,
        )
    )

    with pytest.raises(
        ValueError,
        match="unique action-key route identity",
    ):
        KnowledgeOptionSpaceProjector().project(
            binding=_binding(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            report=_report(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            previous=duplicate,
            current=duplicate,
        )


@pytest.mark.parametrize(
    "field",
    (
        "truth_authority",
        "verification_authority",
        "ranking_authority",
        "decision_control_authority",
        "decision_mutation_authority",
        "memory_mutation_authority",
        "execution_authority",
        "runtime_authority",
    ),
)
def test_o2_binding_cannot_escalate_authority(
    field: str,
) -> None:
    binding = (
        KnowledgeOptionSpaceAttributionBinding(
            task_id=uuid4(),
            knowledge_ref=(
                "memory://record/a"
            ),
            trigger_ref=(
                "assumption:fixture"
            ),
            evidence_refs=(
                "evidence://knowledge-attribution",
            ),
            provenance_refs=(
                "owner://knowledge-attribution",
            ),
        )
    )

    payload = binding.model_dump(
        mode="python"
    )
    payload[field] = True

    with pytest.raises(
        ValidationError
    ):
        (
            KnowledgeOptionSpaceAttributionBinding
            .model_validate(
                payload
            )
        )


def test_projector_revalidates_forged_attribution_binding() -> None:
    task_id = uuid4()
    step_id = uuid4()
    trigger_ref = (
        "assumption:"
        + str(uuid4())
    )

    valid_binding = _binding(
        task_id=task_id,
        trigger_ref=trigger_ref,
    )

    forged_binding = valid_binding.model_copy(
        update={
            "evidence_refs": (),
        }
    )

    previous = _set(
        task_id=task_id,
        step_id=step_id,
        basis="1" * 64,
        alternatives=(
            _alternative(
                action_key="route-a",
                admissible=True,
                suffix="revalidate-a",
            ),
        ),
    )

    current = _set(
        task_id=task_id,
        step_id=step_id,
        basis="2" * 64,
        alternatives=(
            _alternative(
                action_key="route-a",
                admissible=True,
                suffix="revalidate-a",
            ),
            _alternative(
                action_key="route-b",
                admissible=True,
                suffix="revalidate-b",
            ),
        ),
        task_revision=2,
        decision_revision=2,
    )

    with pytest.raises(ValidationError):
        KnowledgeOptionSpaceProjector().project(
            binding=forged_binding,
            report=_report(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            previous=previous,
            current=current,
        )


def test_projector_revalidates_forged_route_admissibility() -> None:
    task_id = uuid4()
    step_id = uuid4()
    trigger_ref = (
        "assumption:"
        + str(uuid4())
    )

    valid_route = _alternative(
        action_key="route-a",
        admissible=True,
        suffix="forged-route",
    )

    forged_route = valid_route.model_copy(
        update={
            "admissible": False,
        }
    )

    previous = _set(
        task_id=task_id,
        step_id=step_id,
        basis="3" * 64,
        alternatives=(
            valid_route,
        ),
    )

    current = DecisionAlternativeSet.model_construct(
        task_id=task_id,
        step_id=step_id,
        source_task_state_revision=2,
        source_decision_state_revision=2,
        decision_basis_fingerprint=(
            "4" * 64
        ),
        alternatives=(
            forged_route,
        ),
        ranked_alternative_refs=(
            forged_route.decision_ref,
        ),
        selected_alternative_ref=None,
        reason_codes=(
            "forged-validator-bypass-fixture",
        ),
        runtime_authority=False,
    )

    with pytest.raises(ValidationError):
        KnowledgeOptionSpaceProjector().project(
            binding=_binding(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            report=_report(
                task_id=task_id,
                trigger_ref=trigger_ref,
            ),
            previous=previous,
            current=current,
        )
