from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from luna.continuity import (
    build_identity_owner_binding,
    resolve_identity_owner_binding,
)
from luna.identity import (
    IdentityConflictError,
    IdentityIntegrityError,
    IdentityNotInitializedError,
    IdentityProfile,
    IdentityProfileService,
    SQLiteIdentityStore,
    UserProfile,
)


def _service(tmp_path: Path) -> tuple[Path, IdentityProfileService]:
    path = tmp_path / "identity.sqlite3"
    return path, IdentityProfileService(SQLiteIdentityStore(path))


def _profile() -> IdentityProfile:
    return IdentityProfile(
        user_profile=UserProfile(
            user_id="owner-1",
            display_name="Owner",
            preferred_address="Owner",
        )
    )


def test_explicit_initialization_establishes_canonical_current_identity(
    tmp_path: Path,
) -> None:
    _, service = _service(tmp_path)
    profile = _profile()

    stored = service.initialize(profile)

    assert stored == profile
    assert service.current_identity() == profile


def test_canonical_identity_survives_process_style_restart(tmp_path: Path) -> None:
    path, service = _service(tmp_path)
    profile = _profile()
    service.initialize(profile)

    restarted = IdentityProfileService(SQLiteIdentityStore(path))
    current = restarted.current_identity()

    assert current == profile
    assert current.profile_id == profile.profile_id
    assert current.profile_revision == profile.profile_revision
    assert current.identity_version == profile.identity_version


def test_repeated_current_identity_reads_are_deterministic(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    profile = _profile()
    service.initialize(profile)

    first = service.current_identity()
    second = service.current_identity()

    assert first == second
    assert first.profile_id == second.profile_id


def test_empty_store_does_not_fabricate_default_identity(tmp_path: Path) -> None:
    _, service = _service(tmp_path)

    with pytest.raises(
        IdentityNotInitializedError,
        match="has not been initialized",
    ):
        service.current_identity()


def test_second_initialization_cannot_replace_canonical_identity(
    tmp_path: Path,
) -> None:
    _, service = _service(tmp_path)
    canonical = _profile()
    service.initialize(canonical)

    replacement = IdentityProfile()

    with pytest.raises(
        IdentityConflictError,
        match="already initialized",
    ):
        service.initialize(replacement)

    assert service.current_identity() == canonical


def test_fresh_identity_object_has_no_canonical_authority(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    canonical = _profile()
    service.initialize(canonical)

    fresh = IdentityProfile()

    assert fresh.profile_id != canonical.profile_id
    assert service.current_identity() == canonical


def test_initialization_rejects_non_initial_revision(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    profile = IdentityProfile(profile_revision=2)

    with pytest.raises(
        IdentityConflictError,
        match="profile_revision=1",
    ):
        service.initialize(profile)


def test_digest_tampering_is_integrity_failure(tmp_path: Path) -> None:
    path, service = _service(tmp_path)
    profile = _profile()
    service.initialize(profile)

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE identity_profiles
            SET payload_sha256 = ?
            WHERE profile_id = ? AND profile_revision = ?
            """,
            (
                "0" * 64,
                str(profile.profile_id),
                profile.profile_revision,
            ),
        )

    restarted = IdentityProfileService(SQLiteIdentityStore(path))

    with pytest.raises(
        IdentityIntegrityError,
        match="digest mismatch",
    ):
        restarted.current_identity()


def test_missing_current_pointer_with_history_is_integrity_failure(
    tmp_path: Path,
) -> None:
    path, service = _service(tmp_path)
    service.initialize(_profile())

    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM identity_current")

    restarted = IdentityProfileService(SQLiteIdentityStore(path))

    with pytest.raises(
        IdentityIntegrityError,
        match="history exists without",
    ):
        restarted.current_identity()


def test_provider_loaded_identity_is_ccf_binding_compatible(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    service.initialize(_profile())

    first = build_identity_owner_binding(service.current_identity())
    repeated = build_identity_owner_binding(service.current_identity())

    assert repeated == first


def test_restart_preserves_exact_ccf_owner_resolution(tmp_path: Path) -> None:
    path, service = _service(tmp_path)
    service.initialize(_profile())

    historical = build_identity_owner_binding(service.current_identity())

    restarted = IdentityProfileService(SQLiteIdentityStore(path))
    current = restarted.current_identity()
    current_binding = build_identity_owner_binding(current)

    assert current_binding == historical

    resolution = resolve_identity_owner_binding(
        historical_binding=historical,
        current_identity=current,
    )
    assert resolution is not None


def test_identity_lifecycle_has_no_runtime_or_tool_authority_dependency() -> None:
    root = Path(__file__).resolve().parents[1]

    for relative in (
        "src/luna/identity/store.py",
        "src/luna/identity/service.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")

        assert "luna.runtime" not in text
        assert "luna.tools" not in text
        assert "RuntimeActor" not in text
        assert "ToolDispatcher" not in text
