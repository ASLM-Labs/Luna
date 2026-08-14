"""Runtime-owned, evidence-bound retry planning for model providers."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from time import monotonic, sleep
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.enums import ObservationStatus
from luna.modeling.errors import ModelBackendErrorCode
from luna.planning import (
    AttemptBasis,
    AttemptRecord,
    RetryDecision,
    RetryGuard,
    RetryReason,
)


class ProviderRetryBasisKind(StrEnum):
    """Observable transient condition that changes a provider attempt basis."""

    EXPONENTIAL_BACKOFF = "EXPONENTIAL_BACKOFF"
    RETRY_AFTER = "RETRY_AFTER"


class ProviderRetryEvidence(LunaContractModel):
    """Structured proof authorizing exactly one subsequent provider call."""

    failure_ref: UUID
    failed_attempt: int = Field(ge=1)
    next_attempt: int = Field(ge=2)
    backend_id: str = Field(min_length=1, max_length=300)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    error_code: ModelBackendErrorCode
    basis_kind: ProviderRetryBasisKind
    delay_seconds: float = Field(ge=0.0)
    retry_reason: RetryReason
    changed_dimensions: tuple[str, ...] = Field(min_length=1)
    basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("delay_seconds")
    @classmethod
    def validate_delay(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("provider retry delay must be finite")
        return value

    @model_validator(mode="after")
    def validate_retry_authority(self) -> ProviderRetryEvidence:
        if self.next_attempt != self.failed_attempt + 1:
            raise ValueError("provider retry evidence must authorize the next bounded attempt")
        if self.retry_reason is not RetryReason.CHANGED_BASIS:
            raise ValueError("provider retry evidence requires a changed basis")
        return self


@dataclass(frozen=True, slots=True)
class ProviderRetryPolicy:
    """Small immutable bound for one provider generation decision."""

    max_attempts: int = 3
    initial_backoff_seconds: float = 0.1
    max_backoff_seconds: float = 2.0
    cancellation_poll_seconds: float = 0.05

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("provider max_attempts must be between 1 and 10")
        if not isfinite(self.initial_backoff_seconds) or self.initial_backoff_seconds <= 0:
            raise ValueError("provider initial backoff must be positive and finite")
        if (
            not isfinite(self.max_backoff_seconds)
            or self.max_backoff_seconds < self.initial_backoff_seconds
        ):
            raise ValueError("provider max backoff must be finite and at least the initial delay")
        if (
            not isfinite(self.cancellation_poll_seconds)
            or self.cancellation_poll_seconds <= 0
        ):
            raise ValueError("provider cancellation poll must be positive and finite")


@dataclass(frozen=True, slots=True)
class ProviderRetryPlan:
    """One retry-guard result plus the basis it evaluated."""

    decision: RetryDecision
    failed_attempt: AttemptRecord
    candidate_basis: AttemptBasis
    evidence: ProviderRetryEvidence | None


_TRANSIENT_CODES = frozenset(
    {
        ModelBackendErrorCode.TIMEOUT,
        ModelBackendErrorCode.RATE_LIMITED,
        ModelBackendErrorCode.UNAVAILABLE,
    }
)


class ProviderRetryCoordinator:
    """Plan bounded provider retries; it never executes tools or grants authority."""

    def __init__(
        self,
        *,
        policy: ProviderRetryPolicy | None = None,
        retry_guard: RetryGuard | None = None,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self.policy = policy or ProviderRetryPolicy()
        self._retry_guard = retry_guard or RetryGuard()
        self._clock = clock
        self._sleeper = sleeper

    @staticmethod
    def is_retryable(*, code: ModelBackendErrorCode, classified_retryable: bool) -> bool:
        """Require both provider classification and Luna's semantic allowlist."""

        return classified_retryable and code in _TRANSIENT_CODES

    @staticmethod
    def initial_basis(
        *,
        backend_id: str,
        request_fingerprint: str,
        scope_fingerprint: str,
        assumption_revision: int,
    ) -> AttemptBasis:
        return AttemptBasis(
            action_key=f"model_provider:{backend_id}:{request_fingerprint}",
            context_fingerprint=request_fingerprint,
            assumption_revision=assumption_revision,
            execution_strategy="provider_generation",
            verification_strategy="structured_model_response",
            scope_fingerprint=scope_fingerprint,
        )

    def plan(
        self,
        *,
        task_id: UUID,
        step_id: UUID,
        attempt_number: int,
        code: ModelBackendErrorCode,
        backend_id: str,
        request_fingerprint: str,
        retry_after_seconds: float | None,
        failure_ref: UUID,
        current_basis: AttemptBasis,
        history: Iterable[AttemptRecord],
    ) -> ProviderRetryPlan:
        failed = AttemptRecord(
            task_id=task_id,
            step_id=step_id,
            basis=current_basis,
            observation_id=failure_ref,
            outcome=ObservationStatus.FAILURE,
        )
        basis_kind, delay = self._delay(
            attempt_number=attempt_number,
            retry_after_seconds=retry_after_seconds,
        )
        evidence_ref = f"provider_failure:{failure_ref}"
        candidate = current_basis.model_copy(
            update={
                "evidence_refs": tuple(
                    dict.fromkeys((*current_basis.evidence_refs, evidence_ref))
                ),
                "execution_strategy": (
                    f"provider_generation_after:{basis_kind.value}:{delay:.6f}"
                ),
            }
        )
        decision = self._retry_guard.evaluate(candidate, (*tuple(history), failed))
        evidence = None
        if decision.allowed and decision.reason is RetryReason.CHANGED_BASIS:
            evidence = ProviderRetryEvidence(
                failure_ref=failure_ref,
                failed_attempt=attempt_number,
                next_attempt=attempt_number + 1,
                backend_id=backend_id,
                request_fingerprint=request_fingerprint,
                error_code=code,
                basis_kind=basis_kind,
                delay_seconds=delay,
                retry_reason=decision.reason,
                changed_dimensions=decision.changed_dimensions,
                basis_fingerprint=candidate.fingerprint(),
            )
        return ProviderRetryPlan(
            decision=decision,
            failed_attempt=failed,
            candidate_basis=candidate,
            evidence=evidence,
        )

    def wait(
        self,
        delay_seconds: float,
        *,
        cancellation_probe: Callable[[], str | None],
    ) -> str | None:
        """Wait cooperatively and return the first observed cancellation reason."""

        deadline = self._clock() + delay_seconds
        while True:
            cancellation = cancellation_probe()
            if cancellation is not None:
                return cancellation
            remaining = deadline - self._clock()
            if remaining <= 0:
                return cancellation_probe()
            self._sleeper(min(remaining, self.policy.cancellation_poll_seconds))

    def _delay(
        self,
        *,
        attempt_number: int,
        retry_after_seconds: float | None,
    ) -> tuple[ProviderRetryBasisKind, float]:
        if retry_after_seconds is not None:
            if not isfinite(retry_after_seconds) or retry_after_seconds < 0:
                raise ValueError("Retry-After delay must be finite and non-negative")
            return ProviderRetryBasisKind.RETRY_AFTER, retry_after_seconds
        delay = min(
            self.policy.initial_backoff_seconds * (2 ** (attempt_number - 1)),
            self.policy.max_backoff_seconds,
        )
        return ProviderRetryBasisKind.EXPONENTIAL_BACKOFF, delay
