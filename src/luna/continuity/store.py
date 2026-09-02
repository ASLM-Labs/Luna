"""SQLite WAL store for atomic task state and immutable checkpoints."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from luna.continuity.cognitive import (
    CognitiveRehydrationManifest,
    CognitiveRehydrationPolicy,
    StoredCognitiveRehydrationManifest,
    StoredCognitiveRehydrationPolicy,
)
from luna.continuity.models import (
    CheckpointEnvelope,
    ContinuityIntegrity,
    StoredCheckpoint,
    canonical_model_json,
    model_digest,
)
from luna.contracts.base import utc_now
from luna.contracts.enums import TaskPhase
from luna.contracts.state import TaskState

SCHEMA_VERSION = 4


class ContinuityError(RuntimeError):
    """Base continuity-store failure."""


class ContinuityConflictError(ContinuityError):
    """Optimistic concurrency or immutable-terminal conflict."""


class CheckpointNotFoundError(ContinuityError):
    """Requested checkpoint or task checkpoint chain does not exist."""


class CognitiveManifestNotFoundError(ContinuityError):
    """Requested cognitive rehydration manifest does not exist."""


class CognitivePolicyNotFoundError(ContinuityError):
    """Requested cognitive rehydration policy does not exist."""


class ContinuityIntegrityError(ContinuityError):
    """Persisted continuity artifact or state digest is invalid."""


class SQLiteContinuityStore:
    """Open short-lived SQLite connections with WAL and FULL sync."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        """Yield one read connection and always close its Windows file handle."""
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            current = int(row["version"]) if row is not None else 0
            if current > SCHEMA_VERSION:
                raise ContinuityError(
                    f"database schema {current} is newer than runtime "
                    f"{SCHEMA_VERSION}"
                )
            if current < 1:
                connection.execute(
                    """
                    CREATE TABLE checkpoints (
                        checkpoint_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        state_revision INTEGER NOT NULL,
                        terminal INTEGER NOT NULL CHECK (terminal IN (0, 1)),
                        runtime_revision TEXT NOT NULL,
                        workspace_fingerprint TEXT NOT NULL,
                        environment_fingerprint TEXT NOT NULL,
                        previous_checkpoint_id TEXT,
                        created_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        FOREIGN KEY(previous_checkpoint_id)
                            REFERENCES checkpoints(checkpoint_id)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX checkpoints_task_created
                    ON checkpoints(task_id, created_at, checkpoint_id)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE task_states (
                        task_id TEXT PRIMARY KEY,
                        revision INTEGER NOT NULL,
                        phase TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        terminal INTEGER NOT NULL CHECK (terminal IN (0, 1))
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) "
                    "VALUES (?, ?)",
                    (1, utc_now().isoformat()),
                )
            if current < 2:
                connection.execute(
                    """
                    CREATE TABLE cognitive_rehydration_manifests (
                        manifest_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        checkpoint_id TEXT NOT NULL,
                        task_revision INTEGER NOT NULL,
                        task_state_sha256 TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX cognitive_rehydration_task_checkpoint
                    ON cognitive_rehydration_manifests(
                        task_id,
                        checkpoint_id,
                        manifest_id
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) "
                    "VALUES (?, ?)",
                    (2, utc_now().isoformat()),
                )
            if current < 3:
                connection.execute(
                    """
                    CREATE TABLE checkpoint_cognitive_manifests (
                        checkpoint_id TEXT PRIMARY KEY,
                        manifest_id TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(checkpoint_id)
                            REFERENCES checkpoints(checkpoint_id),
                        FOREIGN KEY(manifest_id)
                            REFERENCES cognitive_rehydration_manifests(manifest_id)
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) "
                    "VALUES (?, ?)",
                    (3, utc_now().isoformat()),
                )
            if current < 4:
                connection.execute(
                    """
                    CREATE TABLE cognitive_rehydration_policies (
                        policy_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        checkpoint_id TEXT NOT NULL,
                        task_revision INTEGER NOT NULL,
                        task_state_sha256 TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX cognitive_rehydration_policy_task_checkpoint
                    ON cognitive_rehydration_policies(
                        task_id,
                        checkpoint_id,
                        policy_id
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE checkpoint_cognitive_policies (
                        checkpoint_id TEXT PRIMARY KEY,
                        policy_id TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(checkpoint_id)
                            REFERENCES checkpoints(checkpoint_id),
                        FOREIGN KEY(policy_id)
                            REFERENCES cognitive_rehydration_policies(policy_id)
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) "
                    "VALUES (?, ?)",
                    (4, utc_now().isoformat()),
                )

    def schema_version(self) -> int:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version "
                "FROM schema_migrations"
            ).fetchone()
            return int(row["version"]) if row is not None else 0

    def journal_mode(self) -> str:
        with self._read_connection() as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
            if row is None:
                raise ContinuityError("SQLite did not report journal mode")
            return str(row[0]).casefold()

    def save_cognitive_rehydration_manifest(
        self,
        manifest: CognitiveRehydrationManifest,
    ) -> StoredCognitiveRehydrationManifest:
        """Persist one immutable content-addressed rehydration manifest."""

        with self._transaction() as connection:
            return self._save_cognitive_manifest_in_transaction(connection, manifest)

    def _save_cognitive_manifest_in_transaction(
        self,
        connection: sqlite3.Connection,
        manifest: CognitiveRehydrationManifest,
    ) -> StoredCognitiveRehydrationManifest:
        payload_json = canonical_model_json(manifest)
        payload_sha256 = model_digest(manifest)

        existing = connection.execute(
            """
            SELECT *
            FROM cognitive_rehydration_manifests
            WHERE manifest_id = ?
            """,
            (manifest.manifest_id,),
        ).fetchone()
        if existing is not None:
            stored = self._stored_cognitive_manifest_from_row(existing)
            if stored.manifest != manifest or stored.payload_sha256 != payload_sha256:
                raise ContinuityConflictError(
                    "cognitive rehydration manifest ID already exists "
                    "with different payload"
                )
            return stored

        connection.execute(
            """
            INSERT INTO cognitive_rehydration_manifests(
                manifest_id,
                task_id,
                checkpoint_id,
                task_revision,
                task_state_sha256,
                payload_json,
                payload_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                manifest.manifest_id,
                str(manifest.task_id),
                str(manifest.checkpoint_id),
                manifest.task_revision,
                manifest.task_state_sha256,
                payload_json,
                payload_sha256,
            ),
        )
        return StoredCognitiveRehydrationManifest(
            manifest=manifest,
            payload_sha256=payload_sha256,
        )

    @staticmethod
    def _stored_cognitive_manifest_from_row(
        row: sqlite3.Row,
    ) -> StoredCognitiveRehydrationManifest:
        payload_json = str(row["payload_json"])
        payload_sha256 = str(row["payload_sha256"])
        try:
            manifest = CognitiveRehydrationManifest.model_validate_json(payload_json)
            stored = StoredCognitiveRehydrationManifest(
                manifest=manifest,
                payload_sha256=payload_sha256,
            )
            if str(row["manifest_id"]) != manifest.manifest_id:
                raise ValueError("manifest row identity mismatch")
            if str(row["task_id"]) != str(manifest.task_id):
                raise ValueError("manifest row task ID mismatch")
            if str(row["checkpoint_id"]) != str(manifest.checkpoint_id):
                raise ValueError("manifest row checkpoint ID mismatch")
            if int(row["task_revision"]) != manifest.task_revision:
                raise ValueError("manifest row task revision mismatch")
            if str(row["task_state_sha256"]) != manifest.task_state_sha256:
                raise ValueError("manifest row task-state digest mismatch")
            return stored
        except (ValidationError, ValueError) as exc:
            raise ContinuityIntegrityError(
                f"invalid cognitive rehydration manifest {row['manifest_id']}: {exc}"
            ) from exc

    def load_cognitive_rehydration_manifest(
        self,
        manifest_id: str,
    ) -> StoredCognitiveRehydrationManifest:
        """Load one manifest and revalidate its content-addressed integrity."""

        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM cognitive_rehydration_manifests
                WHERE manifest_id = ?
                """,
                (manifest_id,),
            ).fetchone()
        if row is None:
            raise CognitiveManifestNotFoundError(
                f"cognitive rehydration manifest not found: {manifest_id}"
            )
        return self._stored_cognitive_manifest_from_row(row)

    def save_cognitive_rehydration_policy(
        self,
        policy: CognitiveRehydrationPolicy,
    ) -> StoredCognitiveRehydrationPolicy:
        """Persist one immutable content-addressed rehydration policy."""

        with self._transaction() as connection:
            return self._save_cognitive_policy_in_transaction(connection, policy)

    def _save_cognitive_policy_in_transaction(
        self,
        connection: sqlite3.Connection,
        policy: CognitiveRehydrationPolicy,
    ) -> StoredCognitiveRehydrationPolicy:
        payload_json = canonical_model_json(policy)
        payload_sha256 = model_digest(policy)

        existing = connection.execute(
            """
            SELECT *
            FROM cognitive_rehydration_policies
            WHERE policy_id = ?
            """,
            (policy.policy_id,),
        ).fetchone()
        if existing is not None:
            stored = self._stored_cognitive_policy_from_row(existing)
            if stored.policy != policy or stored.payload_sha256 != payload_sha256:
                raise ContinuityConflictError(
                    "cognitive rehydration policy ID already exists "
                    "with different payload"
                )
            return stored

        connection.execute(
            """
            INSERT INTO cognitive_rehydration_policies(
                policy_id,
                task_id,
                checkpoint_id,
                task_revision,
                task_state_sha256,
                payload_json,
                payload_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy.policy_id,
                str(policy.task_id),
                str(policy.checkpoint_id),
                policy.task_revision,
                policy.task_state_sha256,
                payload_json,
                payload_sha256,
            ),
        )
        return StoredCognitiveRehydrationPolicy(
            policy=policy,
            payload_sha256=payload_sha256,
        )

    @staticmethod
    def _stored_cognitive_policy_from_row(
        row: sqlite3.Row,
    ) -> StoredCognitiveRehydrationPolicy:
        payload_json = str(row["payload_json"])
        payload_sha256 = str(row["payload_sha256"])
        try:
            policy = CognitiveRehydrationPolicy.model_validate_json(payload_json)
            stored = StoredCognitiveRehydrationPolicy(
                policy=policy,
                payload_sha256=payload_sha256,
            )
            if str(row["policy_id"]) != policy.policy_id:
                raise ValueError("policy row identity mismatch")
            if str(row["task_id"]) != str(policy.task_id):
                raise ValueError("policy row task ID mismatch")
            if str(row["checkpoint_id"]) != str(policy.checkpoint_id):
                raise ValueError("policy row checkpoint ID mismatch")
            if int(row["task_revision"]) != policy.task_revision:
                raise ValueError("policy row task revision mismatch")
            if str(row["task_state_sha256"]) != policy.task_state_sha256:
                raise ValueError("policy row task-state digest mismatch")
            return stored
        except (ValidationError, ValueError) as exc:
            raise ContinuityIntegrityError(
                f"invalid cognitive rehydration policy {row['policy_id']}: {exc}"
            ) from exc

    def load_cognitive_rehydration_policy(
        self,
        policy_id: str,
    ) -> StoredCognitiveRehydrationPolicy:
        """Load one policy and revalidate its content-addressed integrity."""

        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM cognitive_rehydration_policies
                WHERE policy_id = ?
                """,
                (policy_id,),
            ).fetchone()
        if row is None:
            raise CognitivePolicyNotFoundError(
                f"cognitive rehydration policy not found: {policy_id}"
            )
        return self._stored_cognitive_policy_from_row(row)

    @staticmethod
    def _validate_checkpoint_cognitive_manifest_binding(
        envelope: CheckpointEnvelope,
        manifest: CognitiveRehydrationManifest,
    ) -> None:
        if manifest.task_id != envelope.state.task_id:
            raise ContinuityConflictError(
                "cognitive manifest task ID does not match checkpoint state"
            )
        if manifest.checkpoint_id != envelope.checkpoint.checkpoint_id:
            raise ContinuityConflictError(
                "cognitive manifest checkpoint ID does not match checkpoint"
            )
        if manifest.task_revision != envelope.state.revision:
            raise ContinuityConflictError(
                "cognitive manifest task revision does not match checkpoint state"
            )
        expected_state_sha256 = model_digest(envelope.state)
        if manifest.task_state_sha256 != expected_state_sha256:
            raise ContinuityConflictError(
                "cognitive manifest task-state digest does not match checkpoint state"
            )

    @staticmethod
    def _validate_checkpoint_cognitive_policy_binding(
        envelope: CheckpointEnvelope,
        policy: CognitiveRehydrationPolicy,
    ) -> None:
        if policy.task_id != envelope.state.task_id:
            raise ContinuityConflictError(
                "cognitive policy task ID does not match checkpoint state"
            )
        if policy.checkpoint_id != envelope.checkpoint.checkpoint_id:
            raise ContinuityConflictError(
                "cognitive policy checkpoint ID does not match checkpoint"
            )
        if policy.task_revision != envelope.state.revision:
            raise ContinuityConflictError(
                "cognitive policy task revision does not match checkpoint state"
            )
        expected_state_sha256 = model_digest(envelope.state)
        if policy.task_state_sha256 != expected_state_sha256:
            raise ContinuityConflictError(
                "cognitive policy task-state digest does not match checkpoint state"
            )

    def _save_checkpoint_in_transaction(
        self,
        connection: sqlite3.Connection,
        envelope: CheckpointEnvelope,
    ) -> StoredCheckpoint:
        payload_json = canonical_model_json(envelope)
        payload_sha256 = model_digest(envelope)
        state_json = canonical_model_json(envelope.state)
        state_sha256 = model_digest(envelope.state)
        task_id = str(envelope.state.task_id)

        latest = connection.execute(
            """
            SELECT checkpoint_id, terminal
            FROM checkpoints
            WHERE task_id = ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        current_state = connection.execute(
            "SELECT revision, terminal FROM task_states WHERE task_id = ?",
            (task_id,),
        ).fetchone()

        if latest is None:
            if envelope.previous_checkpoint_id is not None:
                raise ContinuityConflictError(
                    "first checkpoint cannot reference a previous checkpoint"
                )
        else:
            if bool(latest["terminal"]):
                raise ContinuityConflictError(
                    "terminal checkpoint is immutable; open a new task"
                )
            if str(envelope.previous_checkpoint_id) != str(latest["checkpoint_id"]):
                raise ContinuityConflictError(
                    "previous_checkpoint_id is not the latest checkpoint"
                )

        if (
            current_state is not None
            and envelope.state.revision <= int(current_state["revision"])
        ):
            raise ContinuityConflictError(
                "checkpoint state revision must advance persisted state"
            )
        if current_state is not None and bool(current_state["terminal"]):
            raise ContinuityConflictError(
                "terminal task state is immutable; open a new task"
            )

        connection.execute(
            """
            INSERT INTO checkpoints(
                checkpoint_id,
                task_id,
                state_revision,
                terminal,
                runtime_revision,
                workspace_fingerprint,
                environment_fingerprint,
                previous_checkpoint_id,
                created_at,
                payload_json,
                payload_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(envelope.checkpoint.checkpoint_id),
                task_id,
                envelope.state.revision,
                int(envelope.terminal),
                envelope.runtime_revision,
                envelope.checkpoint.workspace_fingerprint,
                envelope.checkpoint.environment_fingerprint,
                (
                    str(envelope.previous_checkpoint_id)
                    if envelope.previous_checkpoint_id is not None
                    else None
                ),
                envelope.checkpoint.created_at.isoformat(),
                payload_json,
                payload_sha256,
            ),
        )
        connection.execute(
            """
            INSERT INTO task_states(
                task_id,
                revision,
                phase,
                payload_json,
                payload_sha256,
                updated_at,
                terminal
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                revision = excluded.revision,
                phase = excluded.phase,
                payload_json = excluded.payload_json,
                payload_sha256 = excluded.payload_sha256,
                updated_at = excluded.updated_at,
                terminal = excluded.terminal
            """,
            (
                task_id,
                envelope.state.revision,
                envelope.state.phase.value,
                state_json,
                state_sha256,
                envelope.state.updated_at.isoformat(),
                int(envelope.terminal),
            ),
        )
        return StoredCheckpoint(
            envelope=envelope,
            payload_sha256=payload_sha256,
        )

    def save_checkpoint(self, envelope: CheckpointEnvelope) -> StoredCheckpoint:
        with self._transaction() as connection:
            return self._save_checkpoint_in_transaction(connection, envelope)

    def save_checkpoint_with_cognitive_policy(
        self,
        *,
        envelope: CheckpointEnvelope,
        policy: CognitiveRehydrationPolicy,
    ) -> tuple[StoredCheckpoint, StoredCognitiveRehydrationPolicy]:
        """Persist checkpoint, state, policy, and sidecar binding atomically."""

        self._validate_checkpoint_cognitive_policy_binding(envelope, policy)

        with self._transaction() as connection:
            stored_checkpoint = self._save_checkpoint_in_transaction(
                connection,
                envelope,
            )
            stored_policy = self._save_cognitive_policy_in_transaction(
                connection,
                policy,
            )
            connection.execute(
                """
                INSERT INTO checkpoint_cognitive_policies(
                    checkpoint_id,
                    policy_id,
                    created_at
                ) VALUES (?, ?, ?)
                """,
                (
                    str(envelope.checkpoint.checkpoint_id),
                    policy.policy_id,
                    utc_now().isoformat(),
                ),
            )

        return stored_checkpoint, stored_policy

    def save_checkpoint_with_cognitive_manifest(
        self,
        *,
        envelope: CheckpointEnvelope,
        manifest: CognitiveRehydrationManifest,
    ) -> tuple[StoredCheckpoint, StoredCognitiveRehydrationManifest]:
        """Persist checkpoint, state, manifest, and sidecar binding atomically."""

        self._validate_checkpoint_cognitive_manifest_binding(envelope, manifest)

        with self._transaction() as connection:
            stored_checkpoint = self._save_checkpoint_in_transaction(
                connection,
                envelope,
            )
            stored_manifest = self._save_cognitive_manifest_in_transaction(
                connection,
                manifest,
            )
            connection.execute(
                """
                INSERT INTO checkpoint_cognitive_manifests(
                    checkpoint_id,
                    manifest_id,
                    created_at
                ) VALUES (?, ?, ?)
                """,
                (
                    str(envelope.checkpoint.checkpoint_id),
                    manifest.manifest_id,
                    utc_now().isoformat(),
                ),
            )

        return stored_checkpoint, stored_manifest

    def save_checkpoint_with_cognitive_manifest_and_policy(
        self,
        *,
        envelope: CheckpointEnvelope,
        manifest: CognitiveRehydrationManifest,
        policy: CognitiveRehydrationPolicy,
    ) -> tuple[
        StoredCheckpoint,
        StoredCognitiveRehydrationManifest,
        StoredCognitiveRehydrationPolicy,
    ]:
        """Persist one complete CCF checkpoint binding atomically."""

        self._validate_checkpoint_cognitive_manifest_binding(envelope, manifest)
        self._validate_checkpoint_cognitive_policy_binding(envelope, policy)

        with self._transaction() as connection:
            stored_checkpoint = self._save_checkpoint_in_transaction(
                connection,
                envelope,
            )
            stored_manifest = self._save_cognitive_manifest_in_transaction(
                connection,
                manifest,
            )
            stored_policy = self._save_cognitive_policy_in_transaction(
                connection,
                policy,
            )
            connection.execute(
                """
                INSERT INTO checkpoint_cognitive_manifests(
                    checkpoint_id,
                    manifest_id,
                    created_at
                ) VALUES (?, ?, ?)
                """,
                (
                    str(envelope.checkpoint.checkpoint_id),
                    manifest.manifest_id,
                    utc_now().isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO checkpoint_cognitive_policies(
                    checkpoint_id,
                    policy_id,
                    created_at
                ) VALUES (?, ?, ?)
                """,
                (
                    str(envelope.checkpoint.checkpoint_id),
                    policy.policy_id,
                    utc_now().isoformat(),
                ),
            )

        return stored_checkpoint, stored_manifest, stored_policy

    def load_checkpoint_cognitive_manifest(
        self,
        checkpoint_id: UUID,
    ) -> StoredCognitiveRehydrationManifest:
        """Load and validate the cognitive manifest bound to one checkpoint."""

        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT manifest_id
                FROM checkpoint_cognitive_manifests
                WHERE checkpoint_id = ?
                """,
                (str(checkpoint_id),),
            ).fetchone()
        if row is None:
            raise CognitiveManifestNotFoundError(
                f"no cognitive manifest binding for checkpoint: {checkpoint_id}"
            )

        stored_checkpoint = self.load_checkpoint(checkpoint_id)
        stored_manifest = self.load_cognitive_rehydration_manifest(
            str(row["manifest_id"])
        )
        self._validate_checkpoint_cognitive_manifest_binding(
            stored_checkpoint.envelope,
            stored_manifest.manifest,
        )
        return stored_manifest

    def load_checkpoint_cognitive_policy(
        self,
        checkpoint_id: UUID,
    ) -> StoredCognitiveRehydrationPolicy:
        """Load and validate the exact policy bound to one checkpoint."""

        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT policy_id
                FROM checkpoint_cognitive_policies
                WHERE checkpoint_id = ?
                """,
                (str(checkpoint_id),),
            ).fetchone()
        if row is None:
            raise CognitivePolicyNotFoundError(
                f"no cognitive policy binding for checkpoint: {checkpoint_id}"
            )

        stored_checkpoint = self.load_checkpoint(checkpoint_id)
        try:
            stored_policy = self.load_cognitive_rehydration_policy(
                str(row["policy_id"])
            )
        except CognitivePolicyNotFoundError as exc:
            raise ContinuityIntegrityError(
                "cognitive policy binding references missing artifact: "
                f"{checkpoint_id} -> {row['policy_id']}"
            ) from exc
        self._validate_checkpoint_cognitive_policy_binding(
            stored_checkpoint.envelope,
            stored_policy.policy,
        )
        return stored_policy

    @staticmethod
    def _stored_from_row(row: sqlite3.Row) -> StoredCheckpoint:
        payload_json = str(row["payload_json"])
        payload_sha256 = str(row["payload_sha256"])
        try:
            envelope = CheckpointEnvelope.model_validate_json(payload_json)
            stored = StoredCheckpoint(
                envelope=envelope,
                payload_sha256=payload_sha256,
            )
        except (ValidationError, ValueError) as exc:
            raise ContinuityIntegrityError(
                f"invalid checkpoint {row['checkpoint_id']}: {exc}"
            ) from exc

        row_binding = {
            "checkpoint_id": str(row["checkpoint_id"]),
            "task_id": str(row["task_id"]),
            "state_revision": int(row["state_revision"]),
            "terminal": int(row["terminal"]),
            "runtime_revision": str(row["runtime_revision"]),
            "workspace_fingerprint": str(row["workspace_fingerprint"]),
            "environment_fingerprint": str(row["environment_fingerprint"]),
            "previous_checkpoint_id": (
                str(row["previous_checkpoint_id"])
                if row["previous_checkpoint_id"] is not None
                else None
            ),
            "created_at": str(row["created_at"]),
        }
        envelope_binding = {
            "checkpoint_id": str(envelope.checkpoint.checkpoint_id),
            "task_id": str(envelope.state.task_id),
            "state_revision": envelope.state.revision,
            "terminal": int(envelope.terminal),
            "runtime_revision": envelope.runtime_revision,
            "workspace_fingerprint": envelope.checkpoint.workspace_fingerprint,
            "environment_fingerprint": envelope.checkpoint.environment_fingerprint,
            "previous_checkpoint_id": (
                str(envelope.previous_checkpoint_id)
                if envelope.previous_checkpoint_id is not None
                else None
            ),
            "created_at": envelope.checkpoint.created_at.isoformat(),
        }

        if row_binding != envelope_binding:
            raise ContinuityIntegrityError(
                "checkpoint row binding mismatch: "
                f"{row['checkpoint_id']}"
            )

        return stored

    def load_checkpoint(self, checkpoint_id: UUID) -> StoredCheckpoint:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM checkpoints WHERE checkpoint_id = ?",
                (str(checkpoint_id),),
            ).fetchone()
        if row is None:
            raise CheckpointNotFoundError(f"checkpoint not found: {checkpoint_id}")
        return self._stored_from_row(row)

    def load_latest(self, task_id: UUID) -> StoredCheckpoint:
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM checkpoints
                WHERE task_id = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (str(task_id),),
            ).fetchone()
        if row is None:
            raise CheckpointNotFoundError(f"no checkpoint for task: {task_id}")
        return self._stored_from_row(row)

    def list_checkpoints(self, task_id: UUID) -> tuple[StoredCheckpoint, ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM checkpoints
                WHERE task_id = ?
                ORDER BY rowid
                """,
                (str(task_id),),
            ).fetchall()
        return tuple(self._stored_from_row(row) for row in rows)

    def load_task_state(self, task_id: UUID) -> TaskState:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM task_states WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
        if row is None:
            raise ContinuityError(f"task state not found: {task_id}")
        payload_json = str(row["payload_json"])
        payload_sha256 = str(row["payload_sha256"])
        try:
            state = TaskState.model_validate_json(payload_json)
        except (ValidationError, ValueError) as exc:
            raise ContinuityIntegrityError(
                f"invalid task state {task_id}: {exc}"
            ) from exc
        if model_digest(state) != payload_sha256:
            raise ContinuityIntegrityError(
                f"task state digest mismatch: {task_id}"
            )
        return state

    def resume_checkpoint(
        self,
        *,
        stored: StoredCheckpoint,
        resumed_state: TaskState,
    ) -> None:
        envelope = stored.envelope
        if envelope.terminal:
            raise ContinuityConflictError("terminal checkpoint cannot resume")
        expected_state_digest = model_digest(envelope.state)
        resumed_json = canonical_model_json(resumed_state)
        resumed_digest = model_digest(resumed_state)

        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT revision, phase, payload_sha256, terminal
                FROM task_states
                WHERE task_id = ?
                """,
                (str(envelope.state.task_id),),
            ).fetchone()
            if row is None:
                raise ContinuityConflictError(
                    "persisted task state disappeared before resume"
                )
            if bool(row["terminal"]):
                raise ContinuityConflictError("terminal task cannot resume")
            if (
                int(row["revision"]) != envelope.state.revision
                or str(row["phase"]) != TaskPhase.CHECKPOINTED.value
                or str(row["payload_sha256"]) != expected_state_digest
            ):
                raise ContinuityConflictError(
                    "checkpoint is stale or has already resumed"
                )

            cursor = connection.execute(
                """
                UPDATE task_states
                SET revision = ?,
                    phase = ?,
                    payload_json = ?,
                    payload_sha256 = ?,
                    updated_at = ?,
                    terminal = 0
                WHERE task_id = ? AND revision = ?
                """,
                (
                    resumed_state.revision,
                    resumed_state.phase.value,
                    resumed_json,
                    resumed_digest,
                    resumed_state.updated_at.isoformat(),
                    str(resumed_state.task_id),
                    envelope.state.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ContinuityConflictError(
                    "concurrent resume changed the task state"
                )

    def verify_integrity(self) -> ContinuityIntegrity:
        checkpoint_count = 0
        state_count = 0
        try:
            with self._read_connection() as connection:
                checkpoint_rows = connection.execute(
                    "SELECT * FROM checkpoints ORDER BY task_id, rowid"
                ).fetchall()
                manifest_rows = connection.execute(
                    "SELECT * FROM cognitive_rehydration_manifests "
                    "ORDER BY task_id, rowid"
                ).fetchall()
                binding_rows = connection.execute(
                    "SELECT * FROM checkpoint_cognitive_manifests "
                    "ORDER BY checkpoint_id"
                ).fetchall()
                policy_rows = connection.execute(
                    "SELECT * FROM cognitive_rehydration_policies "
                    "ORDER BY task_id, rowid"
                ).fetchall()
                policy_binding_rows = connection.execute(
                    "SELECT * FROM checkpoint_cognitive_policies "
                    "ORDER BY checkpoint_id"
                ).fetchall()
                state_rows = connection.execute(
                    "SELECT * FROM task_states ORDER BY task_id"
                ).fetchall()

            manifests_by_id: dict[str, StoredCognitiveRehydrationManifest] = {}
            for row in manifest_rows:
                stored_manifest = self._stored_cognitive_manifest_from_row(row)
                manifests_by_id[stored_manifest.manifest.manifest_id] = stored_manifest

            policies_by_id: dict[str, StoredCognitiveRehydrationPolicy] = {}
            for row in policy_rows:
                stored_policy = self._stored_cognitive_policy_from_row(row)
                policies_by_id[stored_policy.policy.policy_id] = stored_policy

            checkpoints_by_id: dict[str, StoredCheckpoint] = {}
            previous_by_task: dict[str, str | None] = {}
            for row in checkpoint_rows:
                stored = self._stored_from_row(row)
                envelope = stored.envelope
                checkpoints_by_id[str(envelope.checkpoint.checkpoint_id)] = stored
                task_key = str(envelope.state.task_id)
                expected_previous = previous_by_task.get(task_key)
                actual_previous = (
                    str(envelope.previous_checkpoint_id)
                    if envelope.previous_checkpoint_id is not None
                    else None
                )
                if actual_previous != expected_previous:
                    raise ContinuityIntegrityError(
                        f"checkpoint chain mismatch for task {task_key}"
                    )
                previous_by_task[task_key] = str(
                    envelope.checkpoint.checkpoint_id
                )
                checkpoint_count += 1

            for row in binding_rows:
                checkpoint_id = str(row["checkpoint_id"])
                manifest_id = str(row["manifest_id"])
                stored_checkpoint = checkpoints_by_id.get(checkpoint_id)
                if stored_checkpoint is None:
                    raise ContinuityIntegrityError(
                        f"cognitive binding checkpoint missing: {checkpoint_id}"
                    )
                bound_manifest = manifests_by_id.get(manifest_id)
                if bound_manifest is None:
                    raise ContinuityIntegrityError(
                        f"cognitive binding manifest missing: {manifest_id}"
                    )
                self._validate_checkpoint_cognitive_manifest_binding(
                    stored_checkpoint.envelope,
                    bound_manifest.manifest,
                )

            for row in policy_binding_rows:
                checkpoint_id = str(row["checkpoint_id"])
                policy_id = str(row["policy_id"])
                stored_checkpoint = checkpoints_by_id.get(checkpoint_id)
                if stored_checkpoint is None:
                    raise ContinuityIntegrityError(
                        f"cognitive policy checkpoint missing: {checkpoint_id}"
                    )
                bound_policy = policies_by_id.get(policy_id)
                if bound_policy is None:
                    raise ContinuityIntegrityError(
                        f"cognitive policy artifact missing: {policy_id}"
                    )
                self._validate_checkpoint_cognitive_policy_binding(
                    stored_checkpoint.envelope,
                    bound_policy.policy,
                )

            for row in state_rows:
                state = TaskState.model_validate_json(str(row["payload_json"]))
                if model_digest(state) != str(row["payload_sha256"]):
                    raise ContinuityIntegrityError(
                        f"task state digest mismatch: {row['task_id']}"
                    )
                if state.revision != int(row["revision"]):
                    raise ContinuityIntegrityError(
                        f"task state revision mismatch: {row['task_id']}"
                    )
                if state.phase.value != str(row["phase"]):
                    raise ContinuityIntegrityError(
                        f"task state phase mismatch: {row['task_id']}"
                    )
                state_count += 1
        except (
            ContinuityError,
            ValidationError,
            ValueError,
            sqlite3.DatabaseError,
        ) as exc:
            return ContinuityIntegrity(
                valid=False,
                database_schema_version=self.schema_version(),
                checkpoint_count=checkpoint_count,
                task_state_count=state_count,
                first_error=str(exc),
            )

        return ContinuityIntegrity(
            valid=True,
            database_schema_version=self.schema_version(),
            checkpoint_count=checkpoint_count,
            task_state_count=state_count,
        )
