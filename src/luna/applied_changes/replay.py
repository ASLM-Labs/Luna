"""Cold readback of immutable applied-change evidence."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from luna.applied_changes.models import (
    AppliedChangeBindingError,
    AppliedChangeBindingState,
    AppliedChangeRecord,
    applied_change_manifest_sha256,
)
from luna.contracts.base import LunaContractModel


class AppliedChangeReplayState(StrEnum):
    """Availability of historical applied-change evidence."""

    ABSENT = "ABSENT"
    UNAVAILABLE = "UNAVAILABLE"
    AVAILABLE = "AVAILABLE"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"


class AppliedChangeReplayIntegrityError(StrEnum):
    """Stable reason a BOUND receipt could not be reconstructed."""

    RECEIPT_INVALID = "RECEIPT_INVALID"
    STORE_READ_FAILED = "STORE_READ_FAILED"
    RECORD_SET_MISSING = "RECORD_SET_MISSING"
    RECORD_BINDING_MISMATCH = "RECORD_BINDING_MISMATCH"
    RECORD_COUNT_MISMATCH = "RECORD_COUNT_MISMATCH"
    MANIFEST_MISMATCH = "MANIFEST_MISMATCH"


class AppliedChangeReplayStore(Protocol):
    """Minimal read-only store surface required for cold readback."""

    def list_for_result(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> tuple[AppliedChangeRecord, ...]: ...


class AppliedChangeReplayResult(LunaContractModel):
    """Fail-closed result of immutable historical evidence readback."""

    model_config = ConfigDict(frozen=True)

    state: AppliedChangeReplayState

    task_id: UUID
    request_id: UUID
    result_id: UUID

    expected_count: int | None = Field(
        default=None,
        ge=1,
    )

    expected_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    binding_error: AppliedChangeBindingError | None = None
    integrity_error: AppliedChangeReplayIntegrityError | None = None

    records: tuple[AppliedChangeRecord, ...] = ()

    @model_validator(mode="after")
    def validate_state(self) -> AppliedChangeReplayResult:
        if self.state is AppliedChangeReplayState.ABSENT:
            if (
                self.expected_count is not None
                or self.expected_manifest_sha256 is not None
                or self.binding_error is not None
                or self.integrity_error is not None
                or self.records
            ):
                raise ValueError(
                    "ABSENT replay cannot carry applied-change evidence"
                )
            return self

        if self.state is AppliedChangeReplayState.UNAVAILABLE:
            if self.expected_count is None:
                raise ValueError(
                    "UNAVAILABLE replay requires expected_count"
                )
            if self.binding_error is None:
                raise ValueError(
                    "UNAVAILABLE replay requires binding_error"
                )
            if (
                self.expected_manifest_sha256 is not None
                or self.integrity_error is not None
                or self.records
            ):
                raise ValueError(
                    "UNAVAILABLE replay cannot claim durable records"
                )
            return self

        if self.state is AppliedChangeReplayState.INTEGRITY_FAILURE:
            if self.integrity_error is None:
                raise ValueError(
                    "INTEGRITY_FAILURE requires integrity_error"
                )
            if self.binding_error is not None or self.records:
                raise ValueError(
                    "INTEGRITY_FAILURE cannot expose trusted records"
                )
            return self

        if self.expected_count is None:
            raise ValueError(
                "AVAILABLE replay requires expected_count"
            )

        if self.expected_manifest_sha256 is None:
            raise ValueError(
                "AVAILABLE replay requires expected manifest"
            )

        if self.binding_error is not None:
            raise ValueError(
                "AVAILABLE replay cannot carry binding_error"
            )

        if self.integrity_error is not None:
            raise ValueError(
                "AVAILABLE replay cannot carry integrity_error"
            )

        if not self.records:
            raise ValueError(
                "AVAILABLE replay requires durable records"
            )

        if len(self.records) != self.expected_count:
            raise ValueError(
                "AVAILABLE replay count does not match records"
            )

        binding = (
            self.task_id,
            self.request_id,
            self.result_id,
        )

        if any(
            (
                record.task_id,
                record.request_id,
                record.result_id,
            )
            != binding
            for record in self.records
        ):
            raise ValueError(
                "AVAILABLE replay records do not share exact binding"
            )

        if (
            applied_change_manifest_sha256(self.records)
            != self.expected_manifest_sha256
        ):
            raise ValueError(
                "AVAILABLE replay manifest does not match records"
            )

        return self


def _integrity_failure(
    *,
    task_id: UUID,
    request_id: UUID,
    result_id: UUID,
    error: AppliedChangeReplayIntegrityError,
    expected_count: int | None = None,
    expected_manifest_sha256: str | None = None,
) -> AppliedChangeReplayResult:
    return AppliedChangeReplayResult(
        state=AppliedChangeReplayState.INTEGRITY_FAILURE,
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        expected_count=expected_count,
        expected_manifest_sha256=expected_manifest_sha256,
        integrity_error=error,
    )


def _manifest_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    if len(value) != 64:
        return None

    if any(
        character not in "0123456789abcdef"
        for character in value
    ):
        return None

    return value


def resolve_applied_change_replay(
    *,
    task_id: UUID,
    request_id: UUID,
    result_id: UUID,
    metadata: Mapping[str, object],
    store: AppliedChangeReplayStore,
) -> AppliedChangeReplayResult:
    """Read historical applied-change evidence without workspace access."""

    if not any(
        key.startswith("applied_change_")
        for key in metadata
    ):
        return AppliedChangeReplayResult(
            state=AppliedChangeReplayState.ABSENT,
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
        )

    raw_state = metadata.get(
        "applied_change_binding_state"
    )
    raw_count = metadata.get(
        "applied_change_count"
    )

    if (
        not isinstance(raw_state, str)
        or type(raw_count) is not int
        or raw_count < 1
    ):
        return _integrity_failure(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            error=(
                AppliedChangeReplayIntegrityError.RECEIPT_INVALID
            ),
        )

    expected_count = raw_count

    try:
        binding_state = AppliedChangeBindingState(raw_state)
    except ValueError:
        return _integrity_failure(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            expected_count=expected_count,
            error=(
                AppliedChangeReplayIntegrityError.RECEIPT_INVALID
            ),
        )

    raw_manifest = metadata.get(
        "applied_change_manifest_sha256"
    )
    raw_binding_error = metadata.get(
        "applied_change_binding_error"
    )

    if binding_state is AppliedChangeBindingState.UNAVAILABLE:
        if (
            raw_manifest is not None
            or not isinstance(raw_binding_error, str)
        ):
            return _integrity_failure(
                task_id=task_id,
                request_id=request_id,
                result_id=result_id,
                expected_count=expected_count,
                error=(
                    AppliedChangeReplayIntegrityError.RECEIPT_INVALID
                ),
            )

        try:
            binding_error = AppliedChangeBindingError(
                raw_binding_error
            )
        except ValueError:
            return _integrity_failure(
                task_id=task_id,
                request_id=request_id,
                result_id=result_id,
                expected_count=expected_count,
                error=(
                    AppliedChangeReplayIntegrityError.RECEIPT_INVALID
                ),
            )

        return AppliedChangeReplayResult(
            state=AppliedChangeReplayState.UNAVAILABLE,
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            expected_count=expected_count,
            binding_error=binding_error,
        )

    if raw_binding_error is not None:
        return _integrity_failure(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            expected_count=expected_count,
            error=(
                AppliedChangeReplayIntegrityError.RECEIPT_INVALID
            ),
        )

    expected_manifest = _manifest_value(
        raw_manifest
    )

    if expected_manifest is None:
        return _integrity_failure(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            expected_count=expected_count,
            error=(
                AppliedChangeReplayIntegrityError.RECEIPT_INVALID
            ),
        )

    try:
        records = store.list_for_result(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
        )
    except Exception:
        # Rich evidence readback must fail closed.
        # Never reconstruct historical state from mutable workspace data.
        return _integrity_failure(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            expected_count=expected_count,
            expected_manifest_sha256=expected_manifest,
            error=(
                AppliedChangeReplayIntegrityError.STORE_READ_FAILED
            ),
        )

    if not records:
        return _integrity_failure(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            expected_count=expected_count,
            expected_manifest_sha256=expected_manifest,
            error=(
                AppliedChangeReplayIntegrityError.RECORD_SET_MISSING
            ),
        )

    binding = (
        task_id,
        request_id,
        result_id,
    )

    if any(
        (
            record.task_id,
            record.request_id,
            record.result_id,
        )
        != binding
        for record in records
    ):
        return _integrity_failure(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            expected_count=expected_count,
            expected_manifest_sha256=expected_manifest,
            error=(
                AppliedChangeReplayIntegrityError.RECORD_BINDING_MISMATCH
            ),
        )

    if len(records) != expected_count:
        return _integrity_failure(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            expected_count=expected_count,
            expected_manifest_sha256=expected_manifest,
            error=(
                AppliedChangeReplayIntegrityError.RECORD_COUNT_MISMATCH
            ),
        )

    try:
        actual_manifest = applied_change_manifest_sha256(
            records
        )
    except ValueError:
        return _integrity_failure(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            expected_count=expected_count,
            expected_manifest_sha256=expected_manifest,
            error=(
                AppliedChangeReplayIntegrityError.RECORD_BINDING_MISMATCH
            ),
        )

    if actual_manifest != expected_manifest:
        return _integrity_failure(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            expected_count=expected_count,
            expected_manifest_sha256=expected_manifest,
            error=(
                AppliedChangeReplayIntegrityError.MANIFEST_MISMATCH
            ),
        )

    return AppliedChangeReplayResult(
        state=AppliedChangeReplayState.AVAILABLE,
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        expected_count=expected_count,
        expected_manifest_sha256=expected_manifest,
        records=records,
    )
