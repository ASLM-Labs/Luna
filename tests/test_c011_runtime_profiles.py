from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

import luna.parallel_cognition.runtime_profiles as runtime_profiles_module
from luna.parallel_cognition import (
    C011RuntimeProfileCatalog,
    C011RuntimeProfileName,
    C011RuntimeProfileProjection,
    C011RuntimeProfileSpec,
    HierarchicalBudgetEnvelope,
    RuntimeEffortProfile,
    S4RuntimePolicy,
    WorkerBudgetEnvelope,
    project_c011_runtime_profile,
)

NOW = datetime(2026, 9, 7, 20, 0, tzinfo=UTC)


def _spec(
    name: C011RuntimeProfileName,
    **updates: object,
) -> C011RuntimeProfileSpec:
    defaults: dict[C011RuntimeProfileName, dict[str, int]] = {
        C011RuntimeProfileName.QUICK: {
            "max_total_workers": 1,
            "max_concurrent_workers": 1,
            "max_worker_context_bytes": 1024,
            "max_worker_result_bytes": 2048,
            "max_worker_claims": 2,
            "max_worker_tokens": 128,
            "max_worker_runtime_ms": 1000,
            "max_total_context_bytes": 1024,
            "max_total_result_bytes": 2048,
            "max_total_tokens": 128,
            "max_total_runtime_ms": 1000,
            "max_wall_time_ms": 1500,
        },
        C011RuntimeProfileName.NORMAL: {
            "max_total_workers": 2,
            "max_concurrent_workers": 2,
            "max_worker_context_bytes": 2048,
            "max_worker_result_bytes": 4096,
            "max_worker_claims": 4,
            "max_worker_tokens": 256,
            "max_worker_runtime_ms": 3000,
            "max_total_context_bytes": 4096,
            "max_total_result_bytes": 8192,
            "max_total_tokens": 512,
            "max_total_runtime_ms": 6000,
            "max_wall_time_ms": 5000,
        },
        C011RuntimeProfileName.DEEP: {
            "max_total_workers": 3,
            "max_concurrent_workers": 3,
            "max_worker_context_bytes": 4096,
            "max_worker_result_bytes": 8192,
            "max_worker_claims": 6,
            "max_worker_tokens": 512,
            "max_worker_runtime_ms": 8000,
            "max_total_context_bytes": 12_288,
            "max_total_result_bytes": 24_576,
            "max_total_tokens": 1536,
            "max_total_runtime_ms": 24_000,
            "max_wall_time_ms": 12_000,
        },
    }
    values: dict[str, object] = {
        "name": name,
        **defaults[name],
    }
    values.update(updates)
    return C011RuntimeProfileSpec(**values)  # type: ignore[arg-type]


def _catalog(
    *,
    quick: C011RuntimeProfileSpec | None = None,
    normal: C011RuntimeProfileSpec | None = None,
    deep: C011RuntimeProfileSpec | None = None,
) -> C011RuntimeProfileCatalog:
    return C011RuntimeProfileCatalog(
        profiles=(
            quick or _spec(C011RuntimeProfileName.QUICK),
            normal or _spec(C011RuntimeProfileName.NORMAL),
            deep or _spec(C011RuntimeProfileName.DEEP),
        )
    )


def _owner_worker(
    *,
    deadline_at: datetime | None = None,
    **updates: object,
) -> WorkerBudgetEnvelope:
    values: dict[str, object] = {
        "max_context_bytes": 10_000,
        "max_result_bytes": 20_000,
        "max_claims": 10,
        "max_tokens": 2000,
        "max_runtime_ms": 60_000,
        "deadline_at": deadline_at or NOW + timedelta(seconds=60),
    }
    values.update(updates)
    return WorkerBudgetEnvelope(**values)  # type: ignore[arg-type]


def _owner_hierarchy(
    *,
    overall_deadline_at: datetime | None = None,
    **updates: object,
) -> HierarchicalBudgetEnvelope:
    values: dict[str, object] = {
        "max_total_workers": 3,
        "max_concurrent_workers": 3,
        "delegation_depth": 1,
        "max_worker_context_bytes": 10_000,
        "max_worker_result_bytes": 20_000,
        "max_worker_tokens": 2000,
        "max_worker_runtime_ms": 60_000,
        "max_total_context_bytes": 30_000,
        "max_total_result_bytes": 60_000,
        "max_total_tokens": 6000,
        "max_total_runtime_ms": 180_000,
        "overall_deadline_at": overall_deadline_at
        or NOW + timedelta(seconds=60),
    }
    values.update(updates)
    return HierarchicalBudgetEnvelope(**values)  # type: ignore[arg-type]


def _project(
    selected: C011RuntimeProfileName = C011RuntimeProfileName.QUICK,
    *,
    catalog: C011RuntimeProfileCatalog | None = None,
    owner_worker: WorkerBudgetEnvelope | None = None,
    owner_hierarchy: HierarchicalBudgetEnvelope | None = None,
    observed_at: datetime = NOW,
    lease_expires_at: datetime | None = None,
) -> C011RuntimeProfileProjection:
    return project_c011_runtime_profile(
        catalog=catalog or _catalog(),
        selected=selected,
        owner_worker_ceiling=owner_worker or _owner_worker(),
        owner_hierarchical_ceiling=owner_hierarchy or _owner_hierarchy(),
        observed_at=observed_at,
        lease_expires_at=lease_expires_at or NOW + timedelta(seconds=60),
    )


def test_profile_spec_is_content_addressed_and_authority_negative() -> None:
    profile = _spec(C011RuntimeProfileName.QUICK)

    assert profile.profile_id.startswith("c011-runtime-profile:sha256:")
    assert profile.authority_granted is False

    payload = profile.model_dump(mode="json")
    payload["profile_id"] = "c011-runtime-profile:sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="profile_id"):
        C011RuntimeProfileSpec.model_validate(payload)


@pytest.mark.parametrize(
    "updates",
    (
        {"max_total_workers": 1, "max_concurrent_workers": 2},
        {"max_worker_context_bytes": 2049, "max_total_context_bytes": 2048},
        {"max_worker_result_bytes": 4097, "max_total_result_bytes": 4096},
        {"max_worker_tokens": 257, "max_total_tokens": 256},
        {"max_worker_runtime_ms": 1501, "max_wall_time_ms": 1500},
    ),
)
def test_profile_spec_rejects_incoherent_budget_shape(
    updates: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        _spec(C011RuntimeProfileName.QUICK, **updates)


def test_catalog_normalizes_order_and_is_content_addressed() -> None:
    catalog = C011RuntimeProfileCatalog(
        profiles=(
            _spec(C011RuntimeProfileName.DEEP),
            _spec(C011RuntimeProfileName.QUICK),
            _spec(C011RuntimeProfileName.NORMAL),
        )
    )

    assert tuple(item.name for item in catalog.profiles) == tuple(C011RuntimeProfileName)
    assert catalog.catalog_id.startswith("c011-runtime-profile-catalog:sha256:")
    assert catalog.authority_granted is False


def test_catalog_requires_exact_tiers() -> None:
    with pytest.raises(ValidationError):
        C011RuntimeProfileCatalog(
            profiles=(
                _spec(C011RuntimeProfileName.QUICK),
                _spec(C011RuntimeProfileName.NORMAL),
                _spec(C011RuntimeProfileName.NORMAL),
            )
        )


def test_catalog_rejects_non_monotone_profile_dimension() -> None:
    quick = _spec(
        C011RuntimeProfileName.QUICK,
        max_worker_tokens=300,
        max_total_tokens=300,
    )

    with pytest.raises(ValidationError, match="monotone"):
        _catalog(quick=quick)


def test_catalog_identity_rejects_tampering() -> None:
    catalog = _catalog()
    payload = catalog.model_dump(mode="json")
    payload["catalog_id"] = "c011-runtime-profile-catalog:sha256:" + "0" * 64

    with pytest.raises(ValidationError, match="catalog_id"):
        C011RuntimeProfileCatalog.model_validate(payload)


def test_v1_exports_no_hidden_default_catalog() -> None:
    assert not hasattr(
        runtime_profiles_module,
        "build_default_c011_runtime_profile_catalog",
    )


def test_quick_projection_fits_without_clamping() -> None:
    projection = _project()

    assert projection.selected is C011RuntimeProfileName.QUICK
    assert projection.worker_budget.max_context_bytes == 1024
    assert projection.worker_budget.max_result_bytes == 2048
    assert projection.worker_budget.max_claims == 2
    assert projection.worker_budget.max_tokens == 128
    assert projection.worker_budget.max_runtime_ms == 1000
    assert projection.hierarchical_budget.max_total_workers == 1
    assert projection.hierarchical_budget.max_concurrent_workers == 1
    assert projection.hierarchical_budget.max_total_tokens == 128
    assert projection.worker_budget.deadline_at == NOW + timedelta(milliseconds=1500)
    assert projection.hierarchical_budget.overall_deadline_at == (
        NOW + timedelta(milliseconds=1500)
    )
    assert projection.clamped_fields == ()
    assert projection.authority_granted is False


def test_deep_projection_clamps_componentwise_to_owner_ceiling() -> None:
    worker = _owner_worker(
        max_context_bytes=3000,
        max_result_bytes=6000,
        max_claims=5,
        max_tokens=400,
        max_runtime_ms=6000,
        deadline_at=NOW + timedelta(seconds=20),
    )
    hierarchy = _owner_hierarchy(
        max_total_workers=2,
        max_concurrent_workers=2,
        max_worker_context_bytes=3500,
        max_worker_result_bytes=7000,
        max_worker_tokens=450,
        max_worker_runtime_ms=7000,
        max_total_context_bytes=7000,
        max_total_result_bytes=14_000,
        max_total_tokens=900,
        max_total_runtime_ms=14_000,
        overall_deadline_at=NOW + timedelta(seconds=18),
    )

    projection = _project(
        C011RuntimeProfileName.DEEP,
        owner_worker=worker,
        owner_hierarchy=hierarchy,
        lease_expires_at=NOW + timedelta(seconds=15),
    )

    assert projection.worker_budget.max_context_bytes == 3000
    assert projection.worker_budget.max_result_bytes == 6000
    assert projection.worker_budget.max_claims == 5
    assert projection.worker_budget.max_tokens == 400
    assert projection.worker_budget.max_runtime_ms == 6000
    assert projection.hierarchical_budget.max_total_workers == 2
    assert projection.hierarchical_budget.max_concurrent_workers == 2
    assert projection.hierarchical_budget.max_total_context_bytes == 6000
    assert projection.hierarchical_budget.max_total_result_bytes == 12_000
    assert projection.hierarchical_budget.max_total_tokens == 800
    assert projection.hierarchical_budget.max_total_runtime_ms == 12_000
    assert projection.worker_budget.deadline_at == NOW + timedelta(seconds=12)
    assert "max_total_workers" in projection.clamped_fields
    assert "max_worker_tokens" in projection.clamped_fields
    assert "deadline_at" not in projection.clamped_fields


@pytest.mark.parametrize(
    ("worker_deadline", "hierarchy_deadline", "lease_deadline", "expected"),
    (
        (20, 30, 40, 12),
        (8, 30, 40, 8),
        (20, 7, 40, 7),
        (20, 30, 6, 6),
    ),
)
def test_deadline_is_minimum_of_all_current_bounds(
    worker_deadline: int,
    hierarchy_deadline: int,
    lease_deadline: int,
    expected: int,
) -> None:
    projection = _project(
        C011RuntimeProfileName.DEEP,
        owner_worker=_owner_worker(
            deadline_at=NOW + timedelta(seconds=worker_deadline),
        ),
        owner_hierarchy=_owner_hierarchy(
            overall_deadline_at=NOW + timedelta(seconds=hierarchy_deadline),
        ),
        lease_expires_at=NOW + timedelta(seconds=lease_deadline),
    )

    assert projection.worker_budget.deadline_at == NOW + timedelta(seconds=expected)


def test_worker_runtime_clamps_to_remaining_deadline_milliseconds() -> None:
    projection = _project(
        C011RuntimeProfileName.DEEP,
        owner_worker=_owner_worker(
            deadline_at=NOW + timedelta(milliseconds=750),
        ),
        owner_hierarchy=_owner_hierarchy(
            overall_deadline_at=NOW + timedelta(seconds=10),
        ),
        lease_expires_at=NOW + timedelta(seconds=10),
    )

    assert projection.worker_budget.max_runtime_ms == 750
    assert "max_worker_runtime_ms" in projection.clamped_fields


def test_zero_worker_or_zero_concurrency_owner_ceiling_fails_closed() -> None:
    hierarchy = _owner_hierarchy(
        max_total_workers=0,
        max_concurrent_workers=0,
    )

    with pytest.raises(ValueError, match="does not admit"):
        _project(owner_hierarchy=hierarchy)


def test_looser_worker_ceiling_is_clamped_by_hierarchy() -> None:
    projection = _project(
        owner_worker=_owner_worker(max_context_bytes=2000),
        owner_hierarchy=_owner_hierarchy(
            max_worker_context_bytes=1000,
            max_total_context_bytes=3000,
        ),
    )

    assert projection.worker_budget.max_context_bytes == 1000
    assert "max_worker_context_bytes" in projection.clamped_fields


@pytest.mark.parametrize(
    "lease_delta",
    (
        timedelta(seconds=0),
        timedelta(microseconds=500),
    ),
)
def test_elapsed_or_sub_millisecond_effective_window_fails_closed(
    lease_delta: timedelta,
) -> None:
    with pytest.raises(ValueError):
        _project(lease_expires_at=NOW + lease_delta)


def test_aggregate_budgets_shrink_after_worker_count_and_worker_clamp() -> None:
    projection = _project(
        C011RuntimeProfileName.DEEP,
        owner_worker=_owner_worker(
            max_context_bytes=1500,
            max_result_bytes=2500,
            max_tokens=100,
            max_runtime_ms=2000,
        ),
        owner_hierarchy=_owner_hierarchy(
            max_total_workers=2,
            max_concurrent_workers=2,
            max_worker_context_bytes=1500,
            max_worker_result_bytes=2500,
            max_worker_tokens=100,
            max_worker_runtime_ms=2000,
            max_total_context_bytes=20_000,
            max_total_result_bytes=20_000,
            max_total_tokens=20_000,
            max_total_runtime_ms=20_000,
        ),
    )

    assert projection.hierarchical_budget.max_total_context_bytes == 3000
    assert projection.hierarchical_budget.max_total_result_bytes == 5000
    assert projection.hierarchical_budget.max_total_tokens == 200
    assert projection.hierarchical_budget.max_total_runtime_ms == 4000


def test_projection_is_self_validating_and_content_addressed() -> None:
    projection = _project(C011RuntimeProfileName.NORMAL)

    assert projection.projection_id.startswith(
        "c011-runtime-profile-projection:sha256:"
    )
    assert projection.selected_profile_id.startswith(
        "c011-runtime-profile:sha256:"
    )
    assert len(projection.owner_worker_ceiling_sha256) == 64
    assert len(projection.owner_hierarchical_ceiling_sha256) == 64

    round_trip = C011RuntimeProfileProjection.model_validate_json(
        projection.model_dump_json()
    )
    assert round_trip == projection

    payload = projection.model_dump(mode="json")
    payload["projection_id"] = ""
    payload["worker_budget"]["max_tokens"] += 1
    with pytest.raises(ValidationError, match="worker budget"):
        C011RuntimeProfileProjection.model_validate(payload)


def test_clamped_fields_are_sorted_unique_and_tamper_checked() -> None:
    projection = _project(
        C011RuntimeProfileName.DEEP,
        owner_worker=_owner_worker(max_tokens=100),
    )
    assert projection.clamped_fields == tuple(sorted(projection.clamped_fields))
    assert len(projection.clamped_fields) == len(set(projection.clamped_fields))

    payload = projection.model_dump(mode="json")
    payload["projection_id"] = ""
    payload["clamped_fields"] = ["max_worker_tokens", "fake"]
    with pytest.raises(ValidationError, match="clamp evidence"):
        C011RuntimeProfileProjection.model_validate(payload)


def test_existing_c011_profile_and_cancellation_owners_remain_distinct() -> None:
    policy = S4RuntimePolicy()
    assert policy.poll_interval_ms == 10
    assert policy.cooperative_cancel_grace_ms == 250
    assert policy.terminate_grace_ms == 250
    assert policy.hard_kill_grace_ms == 1000

    assert tuple(RuntimeEffortProfile) == (
        RuntimeEffortProfile.STANDARD,
        RuntimeEffortProfile.ULTRA,
    )


def test_runtime_profile_module_does_not_import_execution_or_provider_owners() -> None:
    source = runtime_profiles_module.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")

    assert "S4RuntimePolicy" not in text
    assert "WorkerProviderProfile" not in text
    assert "ProviderCapacity" not in text
    assert "RuntimeEffortProfile" not in text
    assert "subprocess" not in text
