from __future__ import annotations

import sqlite3
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.continuity import (
    CognitiveManifestNotFoundError,
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    ContinuityError,
    ContinuityIntegrityError,
    SQLiteContinuityStore,
    StoredCognitiveRehydrationManifest,
    build_cognitive_rehydration_manifest,
)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _manifest():
    return build_cognitive_rehydration_manifest(
        task_id=uuid4(),
        checkpoint_id=uuid4(),
        task_revision=7,
        task_state_sha256=_digest("task-state"),
        bindings=(
            CognitiveOwnerBinding(
                owner_kind=CognitiveOwnerKind.IDENTITY_PROFILE,
                source_ref="identity://luna/profile/1",
                content_sha256=_digest("identity"),
            ),
            CognitiveOwnerBinding(
                owner_kind=CognitiveOwnerKind.VERIFIED_MEMORY,
                source_ref="memory://stable",
                content_sha256=_digest("memory"),
            ),
        ),
    )


def test_manifest_round_trip_survives_new_store_instance(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    manifest = _manifest()
    first_store = SQLiteContinuityStore(database)

    stored = first_store.save_cognitive_rehydration_manifest(manifest)
    restarted = SQLiteContinuityStore(database)
    loaded = restarted.load_cognitive_rehydration_manifest(manifest.manifest_id)

    assert loaded == stored
    assert loaded.manifest == manifest
    assert restarted.verify_integrity().valid


def test_manifest_save_is_idempotent_for_identical_payload(tmp_path: Path) -> None:
    store = SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    manifest = _manifest()

    first = store.save_cognitive_rehydration_manifest(manifest)
    second = store.save_cognitive_rehydration_manifest(manifest)

    assert first == second


def test_manifest_persistence_does_not_create_checkpoint_or_task_state(
    tmp_path: Path,
) -> None:
    store = SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    manifest = _manifest()

    store.save_cognitive_rehydration_manifest(manifest)

    assert store.list_checkpoints(manifest.task_id) == ()
    with pytest.raises(ContinuityError, match="task state not found"):
        store.load_task_state(manifest.task_id)


def test_unknown_manifest_raises_explicit_not_found(tmp_path: Path) -> None:
    store = SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    missing_id = f"cognitive-rehydration:sha256:{'0' * 64}"

    with pytest.raises(CognitiveManifestNotFoundError, match="not found"):
        store.load_cognitive_rehydration_manifest(missing_id)


def test_manifest_payload_tampering_is_detected(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    store = SQLiteContinuityStore(database)
    manifest = _manifest()
    store.save_cognitive_rehydration_manifest(manifest)

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE cognitive_rehydration_manifests
            SET payload_sha256 = ?
            WHERE manifest_id = ?
            """,
            ("0" * 64, manifest.manifest_id),
        )

    with pytest.raises(ContinuityIntegrityError, match="payload digest mismatch"):
        store.load_cognitive_rehydration_manifest(manifest.manifest_id)
    assert not store.verify_integrity().valid


def test_manifest_row_metadata_tampering_is_detected(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    store = SQLiteContinuityStore(database)
    manifest = _manifest()
    store.save_cognitive_rehydration_manifest(manifest)

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE cognitive_rehydration_manifests
            SET task_revision = task_revision + 1
            WHERE manifest_id = ?
            """,
            (manifest.manifest_id,),
        )

    with pytest.raises(ContinuityIntegrityError, match="task revision mismatch"):
        store.load_cognitive_rehydration_manifest(manifest.manifest_id)
    assert not store.verify_integrity().valid


def test_manifest_schema_migrates_from_v1_to_current(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    store = SQLiteContinuityStore(database)
    assert store.schema_version() == 4

    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE checkpoint_cognitive_policies")
        connection.execute("DROP TABLE cognitive_rehydration_policies")
        connection.execute("DROP TABLE checkpoint_cognitive_manifests")
        connection.execute("DROP TABLE cognitive_rehydration_manifests")
        connection.execute("DELETE FROM schema_migrations WHERE version >= 2")

    restarted = SQLiteContinuityStore(database)

    assert restarted.schema_version() == 4
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN (
                  'cognitive_rehydration_manifests',
                  'checkpoint_cognitive_manifests'
              )
            ORDER BY name
            """
        ).fetchall()
    assert rows == [
        ("checkpoint_cognitive_manifests",),
        ("cognitive_rehydration_manifests",),
    ]


def test_stored_manifest_rejects_wrong_payload_digest() -> None:
    manifest = _manifest()

    with pytest.raises(ValidationError, match="payload digest mismatch"):
        StoredCognitiveRehydrationManifest(
            manifest=manifest,
            payload_sha256="0" * 64,
        )


def test_manifest_storage_remains_independent_from_checkpoint_table(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    store = SQLiteContinuityStore(database)
    manifest = _manifest()

    stored = store.save_cognitive_rehydration_manifest(manifest)

    with sqlite3.connect(database) as connection:
        checkpoint_count = connection.execute(
            "SELECT COUNT(*) FROM checkpoints"
        ).fetchone()
        manifest_count = connection.execute(
            "SELECT COUNT(*) FROM cognitive_rehydration_manifests"
        ).fetchone()

    assert checkpoint_count == (0,)
    assert manifest_count == (1,)
    assert stored.manifest.checkpoint_id == manifest.checkpoint_id
