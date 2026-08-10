"""Luna-owned neural runtime lifecycle and resource-policy enforcement."""

from __future__ import annotations

from contextlib import suppress

from luna.modeling.contracts import ModelRequest
from luna.neural.contracts import (
    NeuralGenerationResult,
    NeuralResourceBudget,
    NeuralResourceProfile,
    NeuralRuntimeErrorCode,
    NeuralWorkerState,
)
from luna.neural.resources import NeuralResourcePolicy
from luna.neural.worker_protocol import NeuralWorker


class NeuralRuntimeError(RuntimeError):
    """Safe runtime failure that can be normalized at the ModelBackend boundary."""

    def __init__(
        self,
        *,
        code: NeuralRuntimeErrorCode,
        safe_reason: str,
        retryable: bool,
    ) -> None:
        if not safe_reason.strip():
            raise ValueError("safe_reason must not be blank")
        self.code = code
        self.safe_reason = safe_reason.strip()
        self.retryable = retryable
        super().__init__(f"{code.value}: {self.safe_reason}")


class LunaNeuralRuntime:
    """Own worker lifecycle; model/libllama never self-authorize resource expansion."""

    def __init__(
        self,
        *,
        worker: NeuralWorker,
        resource_policy: NeuralResourcePolicy,
    ) -> None:
        self._worker = worker
        self._resource_policy = resource_policy

    @property
    def worker_id(self) -> str:
        return self._worker.worker_id

    @property
    def state(self) -> NeuralWorkerState:
        return self._worker.state

    @property
    def active_profile(self) -> NeuralResourceProfile:
        return self._resource_policy.active_profile

    @property
    def current_budget(self) -> NeuralResourceBudget:
        return self._resource_policy.current_budget

    def transition_profile(
        self,
        profile: NeuralResourceProfile,
        *,
        user_authorized: bool,
    ) -> NeuralResourceBudget:
        budget = self._resource_policy.transition(profile, user_authorized=user_authorized)
        if self._worker.state is not NeuralWorkerState.STOPPED and (
            not budget.inference_allowed or not budget.model_resident
        ):
            self.shutdown()
        return budget

    def generate(self, request: ModelRequest) -> NeuralGenerationResult:
        budget = self._resource_policy.current_budget
        if not budget.inference_allowed:
            raise NeuralRuntimeError(
                code=NeuralRuntimeErrorCode.RESOURCE_DENIED,
                safe_reason="active neural resource profile does not allow inference",
                retryable=True,
            )

        if self._worker.state is NeuralWorkerState.FAILED:
            raise NeuralRuntimeError(
                code=NeuralRuntimeErrorCode.WORKER_UNAVAILABLE,
                safe_reason="neural worker is in failed state",
                retryable=True,
            )

        if self._worker.state is NeuralWorkerState.STOPPED:
            self._start_worker(budget=budget)

        if self._worker.state is not NeuralWorkerState.READY:
            raise NeuralRuntimeError(
                code=NeuralRuntimeErrorCode.WORKER_UNAVAILABLE,
                safe_reason="neural worker did not reach READY state",
                retryable=True,
            )

        ephemeral = not budget.model_resident
        try:
            result = self._worker.generate(request)
        except Exception as exc:
            if ephemeral:
                self._best_effort_stop()
            raise NeuralRuntimeError(
                code=NeuralRuntimeErrorCode.WORKER_FAILURE,
                safe_reason="neural worker generation failed",
                retryable=True,
            ) from exc

        if result.request_id != request.request_id:
            if ephemeral:
                self._best_effort_stop()
            raise NeuralRuntimeError(
                code=NeuralRuntimeErrorCode.WORKER_PROTOCOL,
                safe_reason="neural worker returned a mismatched request_id",
                retryable=False,
            )

        if ephemeral:
            self._stop_after_success()
        return result

    def shutdown(self) -> None:
        if self._worker.state is NeuralWorkerState.STOPPED:
            return
        try:
            self._worker.stop()
        except Exception as exc:
            raise NeuralRuntimeError(
                code=NeuralRuntimeErrorCode.WORKER_FAILURE,
                safe_reason="neural worker shutdown failed",
                retryable=True,
            ) from exc

    def _start_worker(self, *, budget: NeuralResourceBudget) -> None:
        try:
            self._worker.start(budget=budget.model_copy(deep=True))
        except Exception as exc:
            raise NeuralRuntimeError(
                code=NeuralRuntimeErrorCode.WORKER_UNAVAILABLE,
                safe_reason="neural worker start failed",
                retryable=True,
            ) from exc

    def _stop_after_success(self) -> None:
        try:
            self._worker.stop()
        except Exception as exc:
            raise NeuralRuntimeError(
                code=NeuralRuntimeErrorCode.WORKER_FAILURE,
                safe_reason="ephemeral neural worker did not release resources cleanly",
                retryable=True,
            ) from exc

    def _best_effort_stop(self) -> None:
        with suppress(Exception):
            self._worker.stop()
