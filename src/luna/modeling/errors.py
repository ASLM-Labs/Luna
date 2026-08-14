"""Structured model-backend failure taxonomy for Phase 13."""

from __future__ import annotations

from enum import StrEnum
from math import isfinite


class ModelBackendErrorCode(StrEnum):
    """Stable provider-neutral backend failure categories."""

    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTHENTICATION = "AUTHENTICATION"
    UNAVAILABLE = "UNAVAILABLE"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    ROLLOUT_BLOCKED = "ROLLOUT_BLOCKED"
    UNKNOWN = "UNKNOWN"


_RETRYABLE_CODES = {
    ModelBackendErrorCode.TIMEOUT,
    ModelBackendErrorCode.RATE_LIMITED,
    ModelBackendErrorCode.UNAVAILABLE,
}


class ModelBackendError(RuntimeError):
    """Safe structured backend error; raw provider bodies are never required."""

    def __init__(
        self,
        *,
        code: ModelBackendErrorCode,
        backend_id: str,
        safe_reason: str,
        retryable: bool | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        if not backend_id.strip():
            raise ValueError("backend_id must not be blank")
        if not safe_reason.strip():
            raise ValueError("safe_reason must not be blank")
        self.code = code
        self.backend_id = backend_id.strip()
        self.safe_reason = safe_reason.strip()
        self.retryable = code in _RETRYABLE_CODES if retryable is None else retryable
        if retry_after_seconds is not None and (
            not isfinite(retry_after_seconds) or retry_after_seconds < 0
        ):
            raise ValueError("retry_after_seconds must be finite and non-negative")
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"{code.value}: {self.safe_reason}")


def http_error_code(status: int) -> tuple[ModelBackendErrorCode, bool]:
    """Map HTTP status to a stable model failure category."""

    if status in {401, 403}:
        return ModelBackendErrorCode.AUTHENTICATION, False
    if status == 429:
        return ModelBackendErrorCode.RATE_LIMITED, True
    if 500 <= status <= 599:
        return ModelBackendErrorCode.UNAVAILABLE, True
    return ModelBackendErrorCode.PROTOCOL_ERROR, False
