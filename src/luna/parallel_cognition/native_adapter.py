"""S5B binding for exact fixture and one-shot real local-native profiles.

The adapter composes the accepted S5A profile gate with the accepted S4 interruptible
subprocess boundary.  Real execution is a distinct default-off, single-child evidence
mode; it does not add a production route or grant result authority.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from luna.modeling import ModelCompatibilityReport
from luna.neural import NeuralResourceBudget
from luna.parallel_cognition.live import (
    BackendSafetyCapabilities,
    FocusedContextBundle,
    LiveBackendRequest,
    LiveBackendResult,
    S4RuntimePolicy,
)
from luna.parallel_cognition.models import AgentLifecycleState, C011ContractModel, Sha256
from luna.parallel_cognition.profiles import (
    ProviderProfileDisposition,
    ProviderProfileRegistry,
    ProviderProfileRequest,
    S5ProviderRoutingPolicy,
    WorkerProviderKind,
    WorkerProviderProfile,
)
from luna.parallel_cognition.subprocess_backend import SubprocessWorkerBackend


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _normalized_environment(environment: Mapping[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in environment.items():
        if not key or "=" in key or "\x00" in key or "\x00" in value:
            raise ValueError("S5B driver environment contains an invalid entry")
        cleaned[str(key)] = str(value)
    return dict(sorted(cleaned.items()))


def driver_environment_sha256(environment: Mapping[str, str]) -> str:
    """Digest the exact explicit child environment without persisting its values."""

    payload = _normalized_environment(environment)
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _artifact_sha256(
    path: Path,
    *,
    cancellation_probe: Callable[[], bool] | None = None,
    deadline_at: datetime | None = None,
) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if cancellation_probe is not None and cancellation_probe():
                raise S5BDriverIntegrityError("S5B artifact verification was cancelled")
            if deadline_at is not None and datetime.now(deadline_at.tzinfo) >= deadline_at:
                raise S5BDriverIntegrityError("S5B artifact verification deadline elapsed")
            digest.update(chunk)
    return digest.hexdigest()


def _is_link_or_junction(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


class LocalNativeDriverMode(StrEnum):
    """Strictly separated S5B execution modes."""

    DETERMINISTIC_FIXTURE = "DETERMINISTIC_FIXTURE"
    REAL_EVIDENCE_ONESHOT = "REAL_EVIDENCE_ONESHOT"


class LocalNativeRuntimeArtifact(C011ContractModel):
    """One regular file in the exact flat CPU-runtime allowlist."""

    relative_path: str = Field(min_length=1, max_length=500)
    size_bytes: int = Field(ge=0)
    sha256: Sha256

    @field_validator("relative_path")
    @classmethod
    def normalize_relative_path(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        path = Path(normalized)
        if not normalized or path.is_absolute() or normalized in {".", ".."} or "/" in normalized:
            raise ValueError("S5B runtime artifact must be one flat relative file name")
        return normalized


class LocalNativeDriverResult(LiveBackendResult):
    """S5B result whose content identity binds the exact provider binding."""

    provider_binding_id: str = Field(pattern=r"^c011-native-driver-binding:sha256:[0-9a-f]{64}$")
    driver_mode: LocalNativeDriverMode
    real_provider_execution: bool

    @model_validator(mode="after")
    def validate_measured_execution(self) -> Self:
        real_mode = self.driver_mode is LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT
        if self.real_provider_execution is not real_mode:
            raise ValueError("S5B result real-execution marker does not match driver mode")
        if self.outcome_state is AgentLifecycleState.RESULT_RECEIVED:
            if real_mode and self.native_usage is None:
                raise ValueError("S5B real result requires engine-native usage")
            if not real_mode and self.native_usage is not None:
                raise ValueError("S5B fixture result cannot claim engine-native usage")
        elif self.native_usage is not None:
            raise ValueError("S5B non-result cannot claim engine-native usage")
        return self


class LocalNativeDriverBinding(C011ContractModel):
    """Content-addressed command and artifact identity for one S5B execution."""

    binding_id: str = ""
    profile_id: str = Field(pattern=r"^c011-provider-profile:sha256:[0-9a-f]{64}$")
    backend_id: str = Field(min_length=1, max_length=300)
    provider_kind: WorkerProviderKind
    mode: LocalNativeDriverMode = LocalNativeDriverMode.DETERMINISTIC_FIXTURE
    executable_path: str = Field(min_length=1, max_length=2000)
    driver_artifact_path: str = Field(min_length=1, max_length=2000)
    model_artifact_path: str = Field(min_length=1, max_length=2000)
    shim_artifact_path: str | None = Field(default=None, max_length=2000)
    runtime_directory_path: str | None = Field(default=None, max_length=2000)
    executable_artifact_sha256: Sha256
    driver_artifact_sha256: Sha256
    model_artifact_sha256: Sha256
    shim_artifact_sha256: Sha256 | None = None
    runtime_artifacts: tuple[LocalNativeRuntimeArtifact, ...] = Field(default=(), max_length=128)
    environment_sha256: Sha256
    driver_protocol_version: Literal[1] = 1
    cpu_threads: int | None = Field(default=None, ge=1, le=256)
    max_context_tokens: int | None = Field(default=None, ge=1, le=4096)
    fixture_only: bool = True
    write_authority: Literal[False] = False
    network_authority: Literal[False] = False
    tool_authority: Literal[False] = False
    delegation_authority: Literal[False] = False
    memory_commit_authority: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("backend_id")
    @classmethod
    def normalize_backend_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("S5B backend ID cannot be blank")
        return normalized

    @field_validator(
        "executable_path",
        "driver_artifact_path",
        "model_artifact_path",
        "shim_artifact_path",
        "runtime_directory_path",
    )
    @classmethod
    def normalize_absolute_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        path = Path(normalized)
        if not normalized or not path.is_absolute():
            raise ValueError("S5B driver artifact paths must be absolute")
        return str(path.resolve(strict=False))

    def command_template(self) -> tuple[str, ...]:
        """Return the only argv layout admitted by protocol version one."""

        if self.mode is LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT:
            assert self.shim_artifact_path is not None
            assert self.runtime_directory_path is not None
            assert self.cpu_threads is not None
            assert self.max_context_tokens is not None
            return (
                self.executable_path,
                "-I",
                self.driver_artifact_path,
                "--shim-path",
                self.shim_artifact_path,
                "--runtime-dir",
                self.runtime_directory_path,
                "--model-path",
                self.model_artifact_path,
                "--cpu-threads",
                str(self.cpu_threads),
                "--max-context-tokens",
                str(self.max_context_tokens),
                "--request",
                "{request}",
                "--result",
                "{result}",
                "--cancel",
                "{cancel}",
            )
        return (
            self.executable_path,
            self.driver_artifact_path,
            "--model-path",
            self.model_artifact_path,
            "--request",
            "{request}",
            "--result",
            "{result}",
            "--cancel",
            "{cancel}",
        )

    def _expected_binding_id(self) -> str:
        payload = self.model_dump(mode="json", exclude={"binding_id"})
        basis = {
            "contract_type": f"{type(self).__module__}.{type(self).__qualname__}",
            "schema_version": self.schema_version,
            "payload": payload,
        }
        digest = sha256(_canonical_json(basis).encode("utf-8")).hexdigest()
        return f"c011-native-driver-binding:sha256:{digest}"

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.provider_kind is not WorkerProviderKind.LUNA_NATIVE_NR2B_SLICE1:
            raise ValueError("S5B admits only the bounded NR-2B Slice 1 provider kind")
        file_paths = {
            self.executable_path,
            self.driver_artifact_path,
            self.model_artifact_path,
        }
        if len(file_paths) != 3:
            raise ValueError("S5B executable, driver and model artifacts must be distinct")
        is_real = self.mode is LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT
        if self.fixture_only == is_real:
            raise ValueError("S5B fixture_only must match the selected driver mode")
        if not is_real:
            if (
                any(
                    item is not None
                    for item in (
                        self.shim_artifact_path,
                        self.runtime_directory_path,
                        self.shim_artifact_sha256,
                        self.cpu_threads,
                        self.max_context_tokens,
                    )
                )
                or self.runtime_artifacts
            ):
                raise ValueError("S5B fixture binding cannot carry real runtime artifacts")
        else:
            if (
                any(
                    item is None
                    for item in (
                        self.shim_artifact_path,
                        self.runtime_directory_path,
                        self.shim_artifact_sha256,
                        self.cpu_threads,
                        self.max_context_tokens,
                    )
                )
                or not self.runtime_artifacts
            ):
                raise ValueError("S5B real binding requires the complete native runtime identity")
            assert self.shim_artifact_path is not None
            assert self.runtime_directory_path is not None
            if self.shim_artifact_path in file_paths:
                raise ValueError("S5B shim artifact must be distinct")
            if self.runtime_directory_path in file_paths | {self.shim_artifact_path}:
                raise ValueError("S5B runtime directory must be distinct")
            names = tuple(item.relative_path for item in self.runtime_artifacts)
            if len(names) != len(set(names)):
                raise ValueError("S5B runtime artifact names must be unique")
            forbidden = tuple(name.casefold() for name in names)
            if "ggml-cuda.dll" in forbidden or any(name.startswith("cublas") for name in forbidden):
                raise ValueError("S5B real evidence runtime must remain CPU-only")
        expected = self._expected_binding_id()
        if not self.binding_id:
            object.__setattr__(self, "binding_id", expected)
        elif self.binding_id != expected:
            raise ValueError("S5B binding ID does not match canonical content")
        return self


class S5BDriverPolicy(C011ContractModel):
    """Explicit default-off gate for fixture or one-shot real evidence execution."""

    enabled: bool = False
    kill_switch_engaged: bool = True
    approved_binding_id: str | None = Field(
        default=None,
        pattern=r"^c011-native-driver-binding:sha256:[0-9a-f]{64}$",
    )
    mode: LocalNativeDriverMode = LocalNativeDriverMode.DETERMINISTIC_FIXTURE
    fixture_only: bool = True
    real_provider_execution_authority: bool = False
    real_execution_limit: Literal[1] = 1
    root_context_adoption_authority: Literal[False] = False
    task_state_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.enabled and not self.kill_switch_engaged and self.approved_binding_id is None:
            raise ValueError("active S5B policy requires an approved binding")
        is_real = self.mode is LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT
        if self.fixture_only == is_real:
            raise ValueError("S5B policy fixture_only must match its driver mode")
        if not is_real and self.real_provider_execution_authority:
            raise ValueError("S5B fixture policy cannot carry real execution authority")
        if self.active and is_real and not self.real_provider_execution_authority:
            raise ValueError("active S5B real evidence policy requires explicit authority")
        return self

    @property
    def active(self) -> bool:
        return self.enabled and not self.kill_switch_engaged


class S5BDriverIntegrityError(ValueError):
    """An exact profile, artifact, policy, or result binding failed closed."""


class LocalNativeDriverAdapter:
    """Bind current S5A identity evidence to one exact S4 child boundary."""

    _REAL_ENVIRONMENT_KEYS = frozenset({"PYTHONIOENCODING", "PYTHONUTF8", "SYSTEMROOT"})

    def __init__(
        self,
        *,
        binding: LocalNativeDriverBinding,
        registry: ProviderProfileRegistry,
        driver_policy_provider: Callable[[], S5BDriverPolicy],
        provider_policy_provider: Callable[[], S5ProviderRoutingPolicy],
        compatibility_provider: Callable[[], ModelCompatibilityReport],
        resource_budget_provider: Callable[[], NeuralResourceBudget],
        environment: Mapping[str, str],
    ) -> None:
        self._binding = LocalNativeDriverBinding.model_validate(binding.model_dump(mode="json"))
        self._registry = registry
        self._driver_policy_provider = driver_policy_provider
        self._provider_policy_provider = provider_policy_provider
        self._compatibility_provider = compatibility_provider
        self._resource_budget_provider = resource_budget_provider
        self._environment = _normalized_environment(environment)
        self._real_attempt_lock = Lock()
        self._real_attempt_consumed = False
        if driver_environment_sha256(self._environment) != self._binding.environment_sha256:
            raise S5BDriverIntegrityError("S5B explicit environment digest mismatch")
        self._validate_environment()
        profile = self._registry.profile(self._binding.profile_id)
        if profile is None:
            raise S5BDriverIntegrityError("S5B binding profile is not registered")
        self._validate_profile(profile)
        if self._binding.mode is LocalNativeDriverMode.DETERMINISTIC_FIXTURE:
            self._verify_artifacts()
        self._delegate = SubprocessWorkerBackend(
            command_template=self._binding.command_template(),
            backend_id=self._binding.backend_id,
            profile_id=self._binding.profile_id,
            environment=self._environment,
        )

    @property
    def backend_id(self) -> str:
        return self._binding.backend_id

    @property
    def profile_id(self) -> str:
        return self._binding.profile_id

    @property
    def binding_id(self) -> str:
        return self._binding.binding_id

    @property
    def safety_capabilities(self) -> BackendSafetyCapabilities:
        return self._delegate.safety_capabilities

    @property
    def real_attempt_consumed(self) -> bool:
        return self._real_attempt_consumed

    def _validate_environment(self) -> None:
        if self._binding.mode is not LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT:
            return
        if not set(self._environment).issubset(self._REAL_ENVIRONMENT_KEYS):
            raise S5BDriverIntegrityError("S5B real environment contains an unknown key")
        if self._environment.get("PYTHONIOENCODING") != "utf-8":
            raise S5BDriverIntegrityError("S5B real environment requires UTF-8 IO")
        if self._environment.get("PYTHONUTF8") != "1":
            raise S5BDriverIntegrityError("S5B real environment requires UTF-8 mode")

    def _validate_profile(self, profile: WorkerProviderProfile) -> None:
        if (
            profile.profile_id != self._binding.profile_id
            or profile.backend_id != self._binding.backend_id
            or profile.provider_kind is not self._binding.provider_kind
            or profile.driver_protocol_version != self._binding.driver_protocol_version
            or profile.driver_artifact_sha256 != self._binding.driver_artifact_sha256
            or profile.model_artifact_sha256 != self._binding.model_artifact_sha256
        ):
            raise S5BDriverIntegrityError("S5B binding does not match its exact profile")
        if self._binding.mode is LocalNativeDriverMode.DETERMINISTIC_FIXTURE:
            if not profile.model_identity.startswith("fixture:"):
                raise S5BDriverIntegrityError(
                    "S5B fixture mode admits only explicitly identified fixture profiles"
                )
        else:
            digest_marker = f"sha256:{self._binding.model_artifact_sha256}"
            if (
                profile.model_identity.startswith("fixture:")
                or digest_marker not in profile.model_identity
            ):
                raise S5BDriverIntegrityError(
                    "S5B real profile must bind its exact model content identity"
                )
            budget = profile.resource_budget
            if (
                budget.cpu_threads != self._binding.cpu_threads
                or budget.max_context_tokens != self._binding.max_context_tokens
                or budget.max_vram_mib != 0
                or budget.max_gpu_utilization_percent != 0
                or budget.max_parallel_generations != 1
                or budget.model_resident
                or budget.background_inference
            ):
                raise S5BDriverIntegrityError(
                    "S5B real binding does not match the bounded CPU-only profile"
                )

    def _verify_artifacts(
        self,
        *,
        cancellation_probe: Callable[[], bool] | None = None,
        deadline_at: datetime | None = None,
    ) -> None:
        expected: list[tuple[Path, str]] = [
            (
                Path(self._binding.executable_path),
                self._binding.executable_artifact_sha256,
            ),
            (
                Path(self._binding.driver_artifact_path),
                self._binding.driver_artifact_sha256,
            ),
            (
                Path(self._binding.model_artifact_path),
                self._binding.model_artifact_sha256,
            ),
        ]
        if self._binding.mode is LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT:
            assert self._binding.shim_artifact_path is not None
            assert self._binding.shim_artifact_sha256 is not None
            expected.append(
                (
                    Path(self._binding.shim_artifact_path),
                    self._binding.shim_artifact_sha256,
                )
            )
        for path, expected_sha256 in expected:
            if _is_link_or_junction(path) or not path.is_file():
                raise S5BDriverIntegrityError("S5B artifact is missing or linked")
            if path.resolve(strict=True) != path:
                raise S5BDriverIntegrityError("S5B artifact path is not canonical")
            if path.stat().st_nlink != 1:
                raise S5BDriverIntegrityError("S5B artifact must not be hard-linked")
            if (
                _artifact_sha256(
                    path,
                    cancellation_probe=cancellation_probe,
                    deadline_at=deadline_at,
                )
                != expected_sha256
            ):
                raise S5BDriverIntegrityError("S5B artifact digest mismatch")
        if self._binding.mode is LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT:
            assert self._binding.runtime_directory_path is not None
            root = Path(self._binding.runtime_directory_path)
            if _is_link_or_junction(root) or not root.is_dir():
                raise S5BDriverIntegrityError("S5B runtime directory is missing or linked")
            if root.resolve(strict=True) != root:
                raise S5BDriverIntegrityError("S5B runtime directory is not canonical")
            observed: dict[str, Path] = {}
            for child in root.iterdir():
                if _is_link_or_junction(child) or not child.is_file():
                    raise S5BDriverIntegrityError(
                        "S5B runtime allowlist admits regular flat files only"
                    )
                if child.stat().st_nlink != 1:
                    raise S5BDriverIntegrityError("S5B runtime artifact must not be hard-linked")
                observed[child.name] = child
            expected_runtime = {
                item.relative_path: item for item in self._binding.runtime_artifacts
            }
            if set(observed) != set(expected_runtime):
                raise S5BDriverIntegrityError("S5B runtime allowlist mismatch")
            for name in sorted(observed):
                item = expected_runtime[name]
                path = observed[name]
                if path.stat().st_size != item.size_bytes:
                    raise S5BDriverIntegrityError("S5B runtime artifact size mismatch")
                if (
                    _artifact_sha256(
                        path,
                        cancellation_probe=cancellation_probe,
                        deadline_at=deadline_at,
                    )
                    != item.sha256
                ):
                    raise S5BDriverIntegrityError("S5B runtime artifact digest mismatch")

    def execute(
        self,
        *,
        request: LiveBackendRequest,
        context: FocusedContextBundle,
        policy: S4RuntimePolicy,
        cancellation_probe: Callable[[], bool],
    ) -> LocalNativeDriverResult:
        driver_policy = S5BDriverPolicy.model_validate(
            self._driver_policy_provider().model_dump(mode="json")
        )
        if not driver_policy.active:
            raise S5BDriverIntegrityError("S5B fixture driver policy is disabled or killed")
        if driver_policy.approved_binding_id != self._binding.binding_id:
            raise S5BDriverIntegrityError("S5B active policy selected another binding")
        if driver_policy.mode is not self._binding.mode:
            raise S5BDriverIntegrityError("S5B active policy selected another driver mode")

        profile = self._registry.profile(self._binding.profile_id)
        if profile is None:
            raise S5BDriverIntegrityError("S5B current profile is not registered")
        self._validate_profile(profile)
        selection = self._registry.select(
            request=ProviderProfileRequest.from_assignment(request.assignment),
            policy=self._provider_policy_provider(),
            compatibility=self._compatibility_provider(),
            current_resource_budget=self._resource_budget_provider(),
        )
        if (
            selection.disposition is not ProviderProfileDisposition.SHADOW_ELIGIBLE
            or selection.profile_id != self._binding.profile_id
            or selection.backend_id != self._binding.backend_id
        ):
            raise S5BDriverIntegrityError("S5B current provider selection is not exact")
        if (
            request.attempt.backend_id != self._binding.backend_id
            or request.attempt.profile_id != self._binding.profile_id
        ):
            raise S5BDriverIntegrityError("S5B request selected another backend/profile")

        if self._binding.mode is LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT:
            with self._real_attempt_lock:
                if self._real_attempt_consumed:
                    raise S5BDriverIntegrityError("S5B real evidence attempt was already consumed")
                self._real_attempt_consumed = True

        deadline_at = request.attempt.deadline_at

        def bounded_cancellation_probe() -> bool:
            return cancellation_probe() or datetime.now(deadline_at.tzinfo) >= deadline_at

        real_mode = self._binding.mode is LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT
        self._verify_artifacts(
            cancellation_probe=bounded_cancellation_probe if real_mode else None,
            deadline_at=deadline_at if real_mode else None,
        )
        result = self._delegate.execute(
            request=request,
            context=context,
            policy=policy,
            cancellation_probe=bounded_cancellation_probe,
        )
        self._verify_artifacts(
            cancellation_probe=bounded_cancellation_probe if real_mode else None,
            deadline_at=deadline_at if real_mode else None,
        )
        raw = result.model_dump(mode="json")
        raw.pop("result_id", None)
        raw["provider_binding_id"] = self._binding.binding_id
        raw["driver_mode"] = self._binding.mode
        raw["real_provider_execution"] = (
            self._binding.mode is LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT
        )
        bound = LocalNativeDriverResult.model_validate(raw)
        if (
            bound.state_mutation_authority
            or bound.completion_authority
            or bound.user_facing_voice_authority
        ):
            raise S5BDriverIntegrityError("S5B result attempted to acquire authority")
        return bound


__all__ = [
    "LocalNativeDriverAdapter",
    "LocalNativeDriverBinding",
    "LocalNativeDriverMode",
    "LocalNativeDriverResult",
    "LocalNativeRuntimeArtifact",
    "S5BDriverIntegrityError",
    "S5BDriverPolicy",
    "driver_environment_sha256",
]
