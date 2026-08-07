"""Runtime-owned controlled model rollout gate for Phase 13."""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from pydantic import Field, model_validator

from luna.contracts.base import LunaContractModel
from luna.modeling.backend import ModelBackend
from luna.modeling.compatibility import ModelCompatibilityReport
from luna.modeling.contracts import ModelRequest, ModelResponse
from luna.modeling.errors import ModelBackendError, ModelBackendErrorCode


class ModelRolloutStage(StrEnum):
    BLOCKED = "BLOCKED"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    ACTIVE = "ACTIVE"


class ModelRolloutHealth(LunaContractModel):
    """Owner/runtime supplied health snapshot; model output cannot mutate it."""

    samples: int = Field(default=0, ge=0)
    consecutive_backend_failures: int = Field(default=0, ge=0)
    invalid_policy_turns: int = Field(default=0, ge=0)
    false_successes: int = Field(default=0, ge=0)
    authority_violations: int = Field(default=0, ge=0)


class ModelRolloutPolicy(LunaContractModel):
    backend_id: str = Field(min_length=1, max_length=300)
    approved_compatibility_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: ModelRolloutStage = ModelRolloutStage.BLOCKED
    canary_percent: int = Field(default=0, ge=0, le=100)
    max_consecutive_backend_failures: int = Field(default=2, ge=0, le=100)
    max_invalid_policy_turns: int = Field(default=0, ge=0, le=1000)

    @model_validator(mode="after")
    def validate_stage(self) -> ModelRolloutPolicy:
        if self.stage is ModelRolloutStage.CANARY and self.canary_percent <= 0:
            raise ValueError("CANARY rollout requires canary_percent > 0")
        if self.stage is not ModelRolloutStage.CANARY and self.canary_percent != 0:
            raise ValueError("canary_percent is valid only for CANARY rollout")
        return self


class ModelRolloutDecision(LunaContractModel):
    backend_id: str = Field(min_length=1, max_length=300)
    stage: ModelRolloutStage
    authorized: bool
    reasons: tuple[str, ...] = Field(min_length=1)
    canary_bucket: int | None = Field(default=None, ge=0, le=99)

    @model_validator(mode="after")
    def validate_bucket(self) -> ModelRolloutDecision:
        if self.stage is ModelRolloutStage.CANARY and self.canary_bucket is None:
            raise ValueError("CANARY decision requires canary_bucket")
        if self.stage is not ModelRolloutStage.CANARY and self.canary_bucket is not None:
            raise ValueError("canary_bucket is valid only for CANARY decisions")
        return self


class ModelRolloutGate:
    """Fail-closed deterministic gate for model use in authoritative runtime decisions."""

    @staticmethod
    def _bucket(task_id: UUID, backend_id: str) -> int:
        digest = sha256(f"{task_id}:{backend_id}".encode()).hexdigest()
        return int(digest[:8], 16) % 100

    def decide(
        self,
        *,
        task_id: UUID,
        policy: ModelRolloutPolicy,
        compatibility: ModelCompatibilityReport,
        health: ModelRolloutHealth,
    ) -> ModelRolloutDecision:
        reasons: list[str] = []
        bucket: int | None = None

        if compatibility.backend_id != policy.backend_id:
            reasons.append("compatibility backend_id does not match rollout policy")
        if compatibility.fingerprint() != policy.approved_compatibility_fingerprint:
            reasons.append("compatibility fingerprint is not the runtime-approved fingerprint")
        if not compatibility.eligible_for_rollout:
            reasons.append("required compatibility cases are not all PASS")
        if health.false_successes > 0:
            reasons.append("false-success tripwire requires rollback/block")
        if health.authority_violations > 0:
            reasons.append("authority-violation tripwire requires rollback/block")
        if health.consecutive_backend_failures > policy.max_consecutive_backend_failures:
            reasons.append("backend failure threshold exceeded")
        if health.invalid_policy_turns > policy.max_invalid_policy_turns:
            reasons.append("invalid policy-turn threshold exceeded")

        if policy.stage is ModelRolloutStage.BLOCKED:
            reasons.append("rollout stage is BLOCKED")
        elif policy.stage is ModelRolloutStage.SHADOW:
            reasons.append("SHADOW output cannot drive authoritative runtime decisions")
        elif policy.stage is ModelRolloutStage.CANARY:
            bucket = self._bucket(task_id, policy.backend_id)
            if bucket >= policy.canary_percent:
                reasons.append("task is outside deterministic canary allocation")

        authorized = not reasons
        if authorized:
            reasons.append("runtime-owned rollout gate authorized model decision")

        return ModelRolloutDecision(
            backend_id=policy.backend_id,
            stage=policy.stage,
            authorized=authorized,
            reasons=tuple(reasons),
            canary_bucket=bucket,
        )


class ControlledModelBackend:
    """ModelBackend wrapper that enforces an immutable rollout snapshot per call."""

    def __init__(
        self,
        *,
        backend: ModelBackend,
        compatibility: ModelCompatibilityReport,
        policy: ModelRolloutPolicy,
        health: ModelRolloutHealth | None = None,
        gate: ModelRolloutGate | None = None,
    ) -> None:
        if backend.backend_id != policy.backend_id:
            raise ValueError("backend_id must match rollout policy")
        if compatibility.backend_id != backend.backend_id:
            raise ValueError("compatibility report must match backend")
        self._backend = backend
        self._compatibility = compatibility
        self._policy = policy
        self._health = health or ModelRolloutHealth()
        self._gate = gate or ModelRolloutGate()

    @property
    def backend_id(self) -> str:
        return self._backend.backend_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        decision = self._gate.decide(
            task_id=request.task_id,
            policy=self._policy,
            compatibility=self._compatibility,
            health=self._health,
        )
        if not decision.authorized:
            raise ModelBackendError(
                code=ModelBackendErrorCode.ROLLOUT_BLOCKED,
                backend_id=self.backend_id,
                safe_reason="; ".join(decision.reasons),
                retryable=False,
            )
        return self._backend.generate(request)
