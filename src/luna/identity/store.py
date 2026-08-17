"""Durable canonical IdentityProfile persistence without runtime authority."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from luna.contracts.base import utc_now
from luna.identity.models import IdentityProfile

IDENTITY_STORE_SCHEMA_VERSION = 1


class IdentityStoreError(RuntimeError):
    """Base error for durable canonical identity state."""


class IdentityNotInitializedError(IdentityStoreError):
    """Raised when no canonical current identity has been initialized."""


class IdentityConflictError(IdentityStoreError):
    """Raised when initialization would replace an existing canonical identity."""


class IdentityIntegrityError(IdentityStoreError):
    """Raised when persisted canonical identity state fails integrity checks."""


def _canonical_profile_json(profile: IdentityProfile) -> str:
    payload = profile.model_dump(mode="json")
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _profile_digest(profile: IdentityProfile) -> str:
    rendered = _canonical_profile_json(profile)
    return sha256(rendered.encode("utf-8")).hexdigest()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS identity_profiles (
    profile_id TEXT NOT NULL,
    profile_revision INTEGER NOT NULL CHECK (profile_revision >= 1),
    identity_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, profile_revision)
);

CREATE TABLE IF NOT EXISTS identity_current (
    singleton_key INTEGER PRIMARY KEY CHECK (singleton_key = 1),
    profile_id TEXT NOT NULL,
    profile_revision INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (profile_id, profile_revision)
        REFERENCES identity_profiles(profile_id, profile_revision)
        ON DELETE RESTRICT
);
"""


class SQLiteIdentityStore:
    """Persist exactly one canonical Luna identity lineage."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path).resolve()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise IdentityStoreError("failed to create identity store directory") from exc
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA secure_delete = ON")
            connection.execute("PRAGMA busy_timeout = 5000")

            row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
            if row is None or str(row[0]).casefold() != "wal":
                raise IdentityStoreError("SQLite did not enable WAL journal mode")

            return connection
        except IdentityStoreError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            raise IdentityStoreError("failed to open identity store") from exc

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        except IdentityStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise IdentityStoreError("identity store read failed") from exc
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._read_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize_schema(self) -> None:
        with self._read_connection() as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
            if row is None:
                raise IdentityStoreError("SQLite did not report identity schema version")

            version = int(row[0])
            if version not in (0, IDENTITY_STORE_SCHEMA_VERSION):
                raise IdentityStoreError(
                    f"unsupported identity store schema version: {version}"
                )

            connection.executescript(_SCHEMA)

            if version == 0:
                connection.execute(
                    f"PRAGMA user_version = {IDENTITY_STORE_SCHEMA_VERSION}"
                )

            connection.commit()

    @staticmethod
    def _profile_count(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM identity_profiles"
        ).fetchone()
        if row is None:
            raise IdentityIntegrityError("identity profile count is unavailable")
        return int(row["count"])

    @staticmethod
    def _profile_from_row(row: sqlite3.Row) -> IdentityProfile:
        try:
            profile = IdentityProfile.model_validate_json(str(row["payload_json"]))
        except ValidationError as exc:
            raise IdentityIntegrityError(
                "stored canonical identity payload is invalid"
            ) from exc

        if str(profile.profile_id) != str(row["profile_id"]):
            raise IdentityIntegrityError(
                "stored identity profile_id does not match row identity"
            )

        if profile.profile_revision != int(row["profile_revision"]):
            raise IdentityIntegrityError(
                "stored identity profile_revision does not match row identity"
            )

        if profile.identity_version != str(row["identity_version"]):
            raise IdentityIntegrityError(
                "stored identity version does not match row identity"
            )

        if _profile_digest(profile) != str(row["payload_sha256"]):
            raise IdentityIntegrityError("stored canonical identity digest mismatch")

        return profile

    def initialize(self, profile: IdentityProfile) -> IdentityProfile:
        """Explicitly bootstrap the one canonical identity at revision one."""

        if profile.profile_revision != 1:
            raise IdentityConflictError(
                "initial canonical identity must use profile_revision=1"
            )

        payload_json = _canonical_profile_json(profile)
        payload_sha256 = _profile_digest(profile)
        now = utc_now().isoformat()

        with self._transaction() as connection:
            current = connection.execute(
                """
                SELECT profile_id, profile_revision
                FROM identity_current
                WHERE singleton_key = 1
                """
            ).fetchone()

            if current is not None:
                raise IdentityConflictError(
                    "canonical identity is already initialized"
                )

            if self._profile_count(connection) != 0:
                raise IdentityIntegrityError(
                    "identity history exists without a canonical current pointer"
                )

            try:
                connection.execute(
                    """
                    INSERT INTO identity_profiles (
                        profile_id,
                        profile_revision,
                        identity_version,
                        payload_json,
                        payload_sha256,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(profile.profile_id),
                        profile.profile_revision,
                        profile.identity_version,
                        payload_json,
                        payload_sha256,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO identity_current (
                        singleton_key,
                        profile_id,
                        profile_revision,
                        updated_at
                    )
                    VALUES (1, ?, ?, ?)
                    """,
                    (
                        str(profile.profile_id),
                        profile.profile_revision,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise IdentityConflictError(
                    "canonical identity initialization conflicted with durable state"
                ) from exc

        return profile

    def load_current(self) -> IdentityProfile:
        """Return the exact durable canonical current IdentityProfile."""

        with self._read_connection() as connection:
            current = connection.execute(
                """
                SELECT profile_id, profile_revision
                FROM identity_current
                WHERE singleton_key = 1
                """
            ).fetchone()

            profile_count = self._profile_count(connection)

            if current is None:
                if profile_count != 0:
                    raise IdentityIntegrityError(
                        "identity history exists without a canonical current pointer"
                    )
                raise IdentityNotInitializedError(
                    "canonical identity has not been initialized"
                )

            distinct_row = connection.execute(
                """
                SELECT COUNT(DISTINCT profile_id) AS count
                FROM identity_profiles
                """
            ).fetchone()
            if distinct_row is None:
                raise IdentityIntegrityError(
                    "identity lineage count is unavailable"
                )
            if int(distinct_row["count"]) != 1:
                raise IdentityIntegrityError(
                    "multiple identity lineages exist in the canonical identity store"
                )

            row = connection.execute(
                """
                SELECT
                    profile_id,
                    profile_revision,
                    identity_version,
                    payload_json,
                    payload_sha256,
                    created_at
                FROM identity_profiles
                WHERE profile_id = ? AND profile_revision = ?
                """,
                (
                    str(current["profile_id"]),
                    int(current["profile_revision"]),
                ),
            ).fetchone()

            if row is None:
                raise IdentityIntegrityError(
                    "canonical identity pointer references missing durable state"
                )

            profile = self._profile_from_row(row)

            if str(profile.profile_id) != str(current["profile_id"]):
                raise IdentityIntegrityError(
                    "canonical identity pointer profile_id mismatch"
                )

            if profile.profile_revision != int(current["profile_revision"]):
                raise IdentityIntegrityError(
                    "canonical identity pointer revision mismatch"
                )

            return profile
