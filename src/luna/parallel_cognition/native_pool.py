"""Bounded one-shot pool for concurrent C-011 real-evidence adapters."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from hashlib import sha256
from queue import Empty, SimpleQueue
from threading import Lock
from typing import ClassVar, Literal, Protocol, Self

from pydantic import Field, model_validator

from luna.parallel_cognition.live import (
    BackendSafetyCapabilities,
    FocusedContextBundle,
    LiveBackendRequest,
    S4RuntimePolicy,
)
from luna.parallel_cognition.models import C011ContractModel
from luna.parallel_cognition.native_adapter import (
    LocalNativeDriverResult,
    S5BDriverIntegrityError,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class _PoolContentAddressedContract(C011ContractModel):
    _identity_field: ClassVar[str]
    _identity_prefix: ClassVar[str]

    @model_validator(mode="after")
    def validate_content_identity(self) -> Self:
        basis = {
            "contract_type": f"{type(self).__module__}.{type(self).__qualname__}",
            "schema_version": self.schema_version,
            "payload": self.model_dump(mode="json", exclude={self._identity_field}),
        }
        expected = (
            self._identity_prefix + sha256(_canonical_json(basis).encode("utf-8")).hexdigest()
        )
        supplied = getattr(self, self._identity_field)
        if not supplied:
            object.__setattr__(self, self._identity_field, expected)
        elif supplied != expected:
            raise ValueError(f"{self._identity_field} does not match canonical contract content")
        return self


class RealNativeAdapterPoolBinding(_PoolContentAddressedContract):
    """Aggregate two or three identical one-shot adapter lanes without widening them."""

    pool_binding_id: str = ""
    member_binding_id: str = Field(pattern=r"^c011-native-driver-binding:sha256:[0-9a-f]{64}$")
    backend_id: str = Field(min_length=1, max_length=300)
    profile_id: str = Field(pattern=r"^c011-provider-profile:sha256:[0-9a-f]{64}$")
    member_count: int = Field(ge=2, le=3)
    max_concurrent_members: int = Field(ge=2, le=3)
    evidence_only: Literal[True] = True
    adapter_reuse: Literal[False] = False
    runtime_authority: Literal[False] = False
    task_state_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    _identity_field = "pool_binding_id"
    _identity_prefix = "c011-native-adapter-pool:sha256:"

    @model_validator(mode="after")
    def validate_capacity(self) -> Self:
        if self.member_count != self.max_concurrent_members:
            raise ValueError("real adapter pool must expose every bounded member concurrently")
        return self


class OneShotRealAdapter(Protocol):
    @property
    def backend_id(self) -> str: ...

    @property
    def profile_id(self) -> str: ...

    @property
    def binding_id(self) -> str: ...

    @property
    def safety_capabilities(self) -> BackendSafetyCapabilities: ...

    @property
    def real_attempt_consumed(self) -> bool: ...

    def execute(
        self,
        *,
        request: LiveBackendRequest,
        context: FocusedContextBundle,
        policy: S4RuntimePolicy,
        cancellation_probe: Callable[[], bool],
    ) -> LocalNativeDriverResult: ...


class BoundedRealNativeAdapterPool:
    """Expose several exact one-shot adapters as one non-replayable S4 backend."""

    def __init__(
        self,
        *,
        binding: RealNativeAdapterPoolBinding,
        adapters: Sequence[OneShotRealAdapter],
    ) -> None:
        current_binding = RealNativeAdapterPoolBinding.model_validate(
            binding.model_dump(mode="json")
        )
        members = tuple(adapters)
        if len(members) != current_binding.member_count:
            raise S5BDriverIntegrityError("real adapter pool member count mismatch")
        if len({id(member) for member in members}) != len(members):
            raise S5BDriverIntegrityError("real adapter pool members must be distinct")
        if any(member.real_attempt_consumed for member in members):
            raise S5BDriverIntegrityError("real adapter pool member was already consumed")
        for member in members:
            if (
                member.backend_id != current_binding.backend_id
                or member.profile_id != current_binding.profile_id
                or member.binding_id != current_binding.member_binding_id
            ):
                raise S5BDriverIntegrityError("real adapter pool member identity mismatch")
            if not member.safety_capabilities.accepted:
                raise S5BDriverIntegrityError("real adapter pool member safety is incomplete")

        self._binding = current_binding
        self._safety = BackendSafetyCapabilities.model_validate(
            members[0].safety_capabilities.model_dump(mode="json")
        )
        self._available: SimpleQueue[OneShotRealAdapter] = SimpleQueue()
        for member in members:
            self._available.put(member)
        self._lock = Lock()
        self._real_attempts_consumed = 0
        self._in_flight = 0
        self._max_in_flight = 0

    @property
    def backend_id(self) -> str:
        return self._binding.backend_id

    @property
    def profile_id(self) -> str:
        return self._binding.profile_id

    @property
    def binding_id(self) -> str:
        return self._binding.pool_binding_id

    @property
    def member_binding_id(self) -> str:
        return self._binding.member_binding_id

    @property
    def safety_capabilities(self) -> BackendSafetyCapabilities:
        return self._safety.model_copy(deep=True)

    @property
    def real_attempts_consumed(self) -> int:
        with self._lock:
            return self._real_attempts_consumed

    @property
    def max_in_flight(self) -> int:
        with self._lock:
            return self._max_in_flight

    @property
    def exhausted(self) -> bool:
        return self.real_attempts_consumed == self._binding.member_count

    def execute(
        self,
        *,
        request: LiveBackendRequest,
        context: FocusedContextBundle,
        policy: S4RuntimePolicy,
        cancellation_probe: Callable[[], bool],
    ) -> LocalNativeDriverResult:
        try:
            member = self._available.get_nowait()
        except Empty as exc:
            raise S5BDriverIntegrityError(
                "real adapter pool is exhausted; replay is forbidden"
            ) from exc

        with self._lock:
            self._real_attempts_consumed += 1
            self._in_flight += 1
            self._max_in_flight = max(self._max_in_flight, self._in_flight)
        try:
            return member.execute(
                request=request,
                context=context,
                policy=policy,
                cancellation_probe=cancellation_probe,
            )
        finally:
            with self._lock:
                self._in_flight -= 1


__all__ = [
    "BoundedRealNativeAdapterPool",
    "OneShotRealAdapter",
    "RealNativeAdapterPoolBinding",
]
