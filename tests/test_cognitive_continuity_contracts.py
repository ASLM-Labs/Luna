from __future__ import annotations

from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from luna.continuity import (
    CognitiveContinuityProjection,
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveRehydrationManifest,
    build_cognitive_continuity_projection,
    build_cognitive_rehydration_manifest,
)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _binding(
    owner_kind: CognitiveOwnerKind,
    source_ref: str,
    digest_seed: str,
) -> CognitiveOwnerBinding:
    return CognitiveOwnerBinding(
        owner_kind=owner_kind,
        source_ref=source_ref,
        content_sha256=_digest(digest_seed),
    )


def _manifest(
    *,
    task_id: UUID | None = None,
    checkpoint_id: UUID | None = None,
    task_revision: int = 4,
    task_state_sha256: str | None = None,
    bindings: tuple[CognitiveOwnerBinding, ...] | None = None,
) -> CognitiveRehydrationManifest:
    resolved_bindings = bindings or (
        _binding(
            CognitiveOwnerKind.IDENTITY_PROFILE,
            "identity://luna/profile/1",
            "identity",
        ),
        _binding(
            CognitiveOwnerKind.VERIFIED_MEMORY,
            "memory://stable",
            "memory",
        ),
    )
    return build_cognitive_rehydration_manifest(
        task_id=task_id or uuid4(),
        checkpoint_id=checkpoint_id or uuid4(),
        task_revision=task_revision,
        task_state_sha256=task_state_sha256 or _digest("task-state"),
        bindings=resolved_bindings,
    )


def test_manifest_is_content_addressed_and_deterministic() -> None:
    task_id = uuid4()
    checkpoint_id = uuid4()
    bindings = (
        _binding(
            CognitiveOwnerKind.IDENTITY_PROFILE,
            "identity://luna/profile/1",
            "identity",
        ),
        _binding(
            CognitiveOwnerKind.VERIFIED_MEMORY,
            "memory://stable",
            "memory",
        ),
    )

    first = _manifest(
        task_id=task_id,
        checkpoint_id=checkpoint_id,
        bindings=bindings,
    )
    second = _manifest(
        task_id=task_id,
        checkpoint_id=checkpoint_id,
        bindings=bindings,
    )

    assert first == second
    assert first.manifest_id == second.manifest_id
    assert first.manifest_id.startswith("cognitive-rehydration:sha256:")


def test_manifest_binding_order_does_not_change_identity() -> None:
    task_id = uuid4()
    checkpoint_id = uuid4()
    identity = _binding(
        CognitiveOwnerKind.IDENTITY_PROFILE,
        "identity://luna/profile/1",
        "identity",
    )
    memory = _binding(
        CognitiveOwnerKind.VERIFIED_MEMORY,
        "memory://stable",
        "memory",
    )

    forward = _manifest(
        task_id=task_id,
        checkpoint_id=checkpoint_id,
        bindings=(identity, memory),
    )
    reverse = _manifest(
        task_id=task_id,
        checkpoint_id=checkpoint_id,
        bindings=(memory, identity),
    )

    assert forward.manifest_id == reverse.manifest_id
    assert forward.bindings == reverse.bindings


def test_manifest_rejects_duplicate_owner_binding() -> None:
    identity = _binding(
        CognitiveOwnerKind.IDENTITY_PROFILE,
        "identity://luna/profile/1",
        "identity",
    )
    memory = _binding(
        CognitiveOwnerKind.VERIFIED_MEMORY,
        "memory://stable",
        "memory",
    )

    with pytest.raises(ValidationError, match="bindings must be unique"):
        _manifest(bindings=(identity, memory, memory))


@pytest.mark.parametrize("identity_count", (0, 2))
def test_manifest_requires_exactly_one_identity_binding(identity_count: int) -> None:
    bindings: list[CognitiveOwnerBinding] = [
        _binding(
            CognitiveOwnerKind.VERIFIED_MEMORY,
            "memory://stable",
            "memory",
        )
    ]
    bindings.extend(
        _binding(
            CognitiveOwnerKind.IDENTITY_PROFILE,
            f"identity://luna/profile/{index}",
            f"identity-{index}",
        )
        for index in range(identity_count)
    )

    with pytest.raises(ValidationError, match="exactly one identity binding"):
        _manifest(bindings=tuple(bindings))


@pytest.mark.parametrize(
    "field_name",
    ("runtime_authority", "execution_authority", "completion_authority"),
)
def test_manifest_cannot_grant_authority(field_name: str) -> None:
    manifest = _manifest()
    payload = manifest.model_dump(mode="python")
    payload[field_name] = True

    with pytest.raises(ValidationError):
        CognitiveRehydrationManifest.model_validate(payload)


def test_owner_binding_cannot_grant_authority() -> None:
    binding = _binding(
        CognitiveOwnerKind.IDENTITY_PROFILE,
        "identity://luna/profile/1",
        "identity",
    )
    payload = binding.model_dump(mode="python")
    payload["runtime_authority"] = True

    with pytest.raises(ValidationError):
        CognitiveOwnerBinding.model_validate(payload)


def test_manifest_identity_changes_with_task_state_digest() -> None:
    task_id = uuid4()
    checkpoint_id = uuid4()
    bindings = (
        _binding(
            CognitiveOwnerKind.IDENTITY_PROFILE,
            "identity://luna/profile/1",
            "identity",
        ),
    )

    first = _manifest(
        task_id=task_id,
        checkpoint_id=checkpoint_id,
        task_state_sha256=_digest("task-state-a"),
        bindings=bindings,
    )
    second = _manifest(
        task_id=task_id,
        checkpoint_id=checkpoint_id,
        task_state_sha256=_digest("task-state-b"),
        bindings=bindings,
    )

    assert first.manifest_id != second.manifest_id


def test_manifest_rejects_tampered_identity() -> None:
    manifest = _manifest()
    payload = manifest.model_dump(mode="python")
    payload["manifest_id"] = f"cognitive-rehydration:sha256:{'0' * 64}"

    with pytest.raises(ValidationError, match="identity mismatch"):
        CognitiveRehydrationManifest.model_validate(payload)


def test_owner_binding_contract_does_not_copy_canonical_payloads() -> None:
    forbidden = {
        "content",
        "decision_state",
        "entries",
        "evidence",
        "payload",
        "statement",
    }

    assert forbidden.isdisjoint(CognitiveOwnerBinding.model_fields)

def _projection(
    *,
    task_id: UUID | None = None,
    task_revision: int = 4,
    task_state_sha256: str | None = None,
    manifest_id: str | None = None,
    readiness_sha256: str | None = None,
    retained_bindings: tuple[CognitiveOwnerBinding, ...] | None = None,
    rejected_source_refs: tuple[str, ...] = (),
    active_assumption_ids: tuple[UUID, ...] = (),
    active_decision_ids: tuple[UUID, ...] = (),
    open_plan_step_ids: tuple[UUID, ...] = (),
    unresolved_requirement_keys: tuple[str, ...] = (),
    revalidation_required_keys: tuple[str, ...] = (),
) -> CognitiveContinuityProjection:
    resolved_task_id = task_id or uuid4()
    resolved_bindings = retained_bindings or (
        _binding(
            CognitiveOwnerKind.IDENTITY_PROFILE,
            "identity://luna/profile/1",
            "identity",
        ),
        _binding(
            CognitiveOwnerKind.VERIFIED_MEMORY,
            "memory://stable",
            "memory",
        ),
    )
    resolved_manifest_id = manifest_id or _manifest(
        task_id=resolved_task_id,
        task_revision=task_revision,
        task_state_sha256=task_state_sha256 or _digest("task-state"),
    ).manifest_id
    return build_cognitive_continuity_projection(
        task_id=resolved_task_id,
        task_revision=task_revision,
        task_state_sha256=task_state_sha256 or _digest("task-state"),
        manifest_id=resolved_manifest_id,
        readiness_sha256=readiness_sha256 or _digest("readiness"),
        retained_bindings=resolved_bindings,
        rejected_source_refs=rejected_source_refs,
        active_assumption_ids=active_assumption_ids,
        active_decision_ids=active_decision_ids,
        open_plan_step_ids=open_plan_step_ids,
        unresolved_requirement_keys=unresolved_requirement_keys,
        revalidation_required_keys=revalidation_required_keys,
    )


def test_projection_is_content_addressed_and_deterministic() -> None:
    task_id = uuid4()
    task_state_sha256 = _digest("task-state")
    manifest = _manifest(
        task_id=task_id,
        task_state_sha256=task_state_sha256,
    )
    identity = _binding(
        CognitiveOwnerKind.IDENTITY_PROFILE,
        "identity://luna/profile/1",
        "identity",
    )
    memory = _binding(
        CognitiveOwnerKind.VERIFIED_MEMORY,
        "memory://stable",
        "memory",
    )
    assumption_id = uuid4()
    decision_id = uuid4()
    step_id = uuid4()

    first = _projection(
        task_id=task_id,
        task_state_sha256=task_state_sha256,
        manifest_id=manifest.manifest_id,
        retained_bindings=(identity, memory),
        active_assumption_ids=(assumption_id,),
        active_decision_ids=(decision_id,),
        open_plan_step_ids=(step_id,),
        unresolved_requirement_keys=("repo_head",),
        revalidation_required_keys=("workspace_state",),
    )
    second = _projection(
        task_id=task_id,
        task_state_sha256=task_state_sha256,
        manifest_id=manifest.manifest_id,
        retained_bindings=(identity, memory),
        active_assumption_ids=(assumption_id,),
        active_decision_ids=(decision_id,),
        open_plan_step_ids=(step_id,),
        unresolved_requirement_keys=("repo_head",),
        revalidation_required_keys=("workspace_state",),
    )

    assert first == second
    assert first.projection_id.startswith("cognitive-continuity:sha256:")


def test_projection_canonicalizes_set_like_inputs() -> None:
    task_id = uuid4()
    task_state_sha256 = _digest("task-state")
    manifest = _manifest(
        task_id=task_id,
        task_state_sha256=task_state_sha256,
    )
    identity = _binding(
        CognitiveOwnerKind.IDENTITY_PROFILE,
        "identity://luna/profile/1",
        "identity",
    )
    memory = _binding(
        CognitiveOwnerKind.VERIFIED_MEMORY,
        "memory://stable",
        "memory",
    )
    first_id = uuid4()
    second_id = uuid4()

    forward = _projection(
        task_id=task_id,
        task_state_sha256=task_state_sha256,
        manifest_id=manifest.manifest_id,
        retained_bindings=(identity, memory),
        rejected_source_refs=("memory://old-b", "memory://old-a"),
        active_assumption_ids=(first_id, second_id),
        unresolved_requirement_keys=("zeta", "alpha"),
    )
    reverse = _projection(
        task_id=task_id,
        task_state_sha256=task_state_sha256,
        manifest_id=manifest.manifest_id,
        retained_bindings=(memory, identity),
        rejected_source_refs=("memory://old-a", "memory://old-b"),
        active_assumption_ids=(second_id, first_id),
        unresolved_requirement_keys=("alpha", "zeta"),
    )

    assert forward == reverse
    assert forward.projection_id == reverse.projection_id


def test_projection_requires_exactly_one_retained_identity_binding() -> None:
    memory = _binding(
        CognitiveOwnerKind.VERIFIED_MEMORY,
        "memory://stable",
        "memory",
    )

    with pytest.raises(ValidationError, match="exactly one identity binding"):
        _projection(retained_bindings=(memory,))


def test_projection_rejects_duplicate_retained_binding() -> None:
    identity = _binding(
        CognitiveOwnerKind.IDENTITY_PROFILE,
        "identity://luna/profile/1",
        "identity",
    )
    memory = _binding(
        CognitiveOwnerKind.VERIFIED_MEMORY,
        "memory://stable",
        "memory",
    )

    with pytest.raises(ValidationError, match="retained cognitive owner bindings"):
        _projection(retained_bindings=(identity, memory, memory))


def test_projection_rejects_retained_and_rejected_overlap() -> None:
    identity = _binding(
        CognitiveOwnerKind.IDENTITY_PROFILE,
        "identity://luna/profile/1",
        "identity",
    )
    memory = _binding(
        CognitiveOwnerKind.VERIFIED_MEMORY,
        "memory://stable",
        "memory",
    )

    with pytest.raises(ValidationError, match="both retained and rejected"):
        _projection(
            retained_bindings=(identity, memory),
            rejected_source_refs=("memory://stable",),
        )


@pytest.mark.parametrize(
    "field_name",
    ("runtime_authority", "execution_authority", "completion_authority"),
)
def test_projection_cannot_grant_authority(field_name: str) -> None:
    projection = _projection()
    payload = projection.model_dump(mode="python")
    payload[field_name] = True

    with pytest.raises(ValidationError):
        CognitiveContinuityProjection.model_validate(payload)


def test_projection_identity_changes_with_readiness_digest() -> None:
    task_id = uuid4()
    task_state_sha256 = _digest("task-state")
    manifest = _manifest(
        task_id=task_id,
        task_state_sha256=task_state_sha256,
    )

    first = _projection(
        task_id=task_id,
        task_state_sha256=task_state_sha256,
        manifest_id=manifest.manifest_id,
        readiness_sha256=_digest("readiness-a"),
    )
    second = _projection(
        task_id=task_id,
        task_state_sha256=task_state_sha256,
        manifest_id=manifest.manifest_id,
        readiness_sha256=_digest("readiness-b"),
    )

    assert first.projection_id != second.projection_id


def test_projection_identity_changes_with_manifest() -> None:
    task_id = uuid4()
    task_state_sha256 = _digest("task-state")
    first_manifest = _manifest(
        task_id=task_id,
        checkpoint_id=uuid4(),
        task_state_sha256=task_state_sha256,
    )
    second_manifest = _manifest(
        task_id=task_id,
        checkpoint_id=uuid4(),
        task_state_sha256=task_state_sha256,
    )

    first = _projection(
        task_id=task_id,
        task_state_sha256=task_state_sha256,
        manifest_id=first_manifest.manifest_id,
    )
    second = _projection(
        task_id=task_id,
        task_state_sha256=task_state_sha256,
        manifest_id=second_manifest.manifest_id,
    )

    assert first.projection_id != second.projection_id


def test_projection_rejects_tampered_identity() -> None:
    projection = _projection()
    payload = projection.model_dump(mode="python")
    payload["projection_id"] = f"cognitive-continuity:sha256:{'0' * 64}"

    with pytest.raises(ValidationError, match="projection identity mismatch"):
        CognitiveContinuityProjection.model_validate(payload)


def test_projection_contract_does_not_copy_canonical_payloads() -> None:
    forbidden = {
        "content",
        "entries",
        "evidence",
        "payload",
        "statement",
    }

    assert forbidden.isdisjoint(CognitiveContinuityProjection.model_fields)
