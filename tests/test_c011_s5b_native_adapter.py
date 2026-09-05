from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from luna.contracts.base import utc_now
from luna.contracts.enums import PlanStepStatus
from luna.modeling import (
    ModelCompatibilityCapability,
    ModelCompatibilityCaseResult,
    ModelCompatibilityReport,
    ModelCompatibilityStatus,
    ModelRolloutStage,
)
from luna.neural import NeuralResourceBudget, NeuralResourceProfile
from luna.parallel_cognition import (
    AgentExecutionAttempt,
    AgentLifecycleState,
    AssignmentSemanticSpec,
    ContextFreshness,
    ContextSourceReference,
    FocusedContextBundle,
    FocusedContextDocument,
    IsolationReferences,
    LiveBackendRequest,
    LocalNativeDriverAdapter,
    LocalNativeDriverBinding,
    LocalNativeDriverMode,
    LocalNativeDriverResult,
    LocalNativeRuntimeArtifact,
    ParallelCognitionRole,
    ProviderCapacity,
    ProviderProfileRegistry,
    ReadOnlyContextManifest,
    RedactionState,
    S4RuntimePolicy,
    S5BDriverIntegrityError,
    S5BDriverPolicy,
    S5ProviderRoutingPolicy,
    SourceStepSemantics,
    WorkerBudgetEnvelope,
    WorkerProviderKind,
    WorkerProviderProfile,
    contract_sha256,
    driver_environment_sha256,
)

TASK_ID = UUID("91000000-0000-4000-8000-000000000011")


def _digest(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return sha256(raw).hexdigest()


def _file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _resource_budget(
    *, cpu_threads: int = 8, max_context_tokens: int = 8192
) -> NeuralResourceBudget:
    return NeuralResourceBudget(
        max_vram_mib=0,
        max_gpu_utilization_percent=0,
        cpu_threads=cpu_threads,
        max_system_ram_mib=32768,
        max_kv_cache_mib=0,
        max_context_tokens=max_context_tokens,
        batch_size=128,
        max_parallel_generations=1,
        inference_allowed=True,
        model_resident=False,
        background_inference=False,
    )


def _compatibility(*, backend_id: str) -> ModelCompatibilityReport:
    return ModelCompatibilityReport(
        backend_id=backend_id,
        results=tuple(
            ModelCompatibilityCaseResult(
                case_id=f"S5B-{index:02d}",
                capability=capability,
                status=ModelCompatibilityStatus.PASS,
                required=True,
                detail="deterministic S5B fixture evidence",
            )
            for index, capability in enumerate(ModelCompatibilityCapability, start=1)
        ),
    )


def _driver_script(root: Path, *, mode: str) -> Path:
    path = (root / f"s5b_driver_{mode}.py").resolve()
    path.write_text(
        f"""
import argparse
import json
import os
from pathlib import Path
import time

parser = argparse.ArgumentParser()
parser.add_argument("--model-path", required=True)
parser.add_argument("--shim-path")
parser.add_argument("--runtime-dir")
parser.add_argument("--cpu-threads")
parser.add_argument("--max-context-tokens")
parser.add_argument("--request", required=True)
parser.add_argument("--result", required=True)
parser.add_argument("--cancel", required=True)
args = parser.parse_args()
model = Path(args.model_path)
request = json.loads(Path(args.request).read_text(encoding="utf-8"))
result = Path(args.result)
cancel = Path(args.cancel)
mode = {mode!r}
if not model.is_file():
    raise SystemExit(8)
if mode == "cooperative":
    while not cancel.exists():
        time.sleep(0.005)
elif mode == "hang":
    while True:
        time.sleep(0.01)
else:
    source_ref = request["context"][0]["source_ref"]
    result.write_text(
        json.dumps(
            {{
                "summary": "s5b:" + os.environ.get("LUNA_S5B_SECRET", "not-inherited"),
                "claims": [
                    {{
                        "claim_key": "claim:s5b",
                        "statement": "The exact fixture profile inspected the source.",
                        "source_refs": [source_ref],
                    }}
                ],
                "tokens": 134 if mode == "real-success" else 12,
                "native_usage": (
                    {{
                        "source": "ENGINE_NATIVE_COUNTERS",
                        "input_tokens": 129,
                        "output_tokens": 5,
                        "total_tokens": 134,
                    }}
                    if mode == "real-success"
                    else None
                ),
            }},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    if mode == "mutate-driver":
        Path(__file__).write_text(
            Path(__file__).read_text(encoding="utf-8") + "\\n# changed\\n",
            encoding="utf-8",
        )
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


@dataclass
class _CurrentState:
    driver_policy: S5BDriverPolicy
    provider_policy: S5ProviderRoutingPolicy
    compatibility: ModelCompatibilityReport
    resource_budget: NeuralResourceBudget


@dataclass(frozen=True)
class _AdapterFixture:
    adapter: LocalNativeDriverAdapter
    binding: LocalNativeDriverBinding
    profile: WorkerProviderProfile
    state: _CurrentState
    request: LiveBackendRequest
    context: FocusedContextBundle
    driver_path: Path
    model_path: Path
    shim_path: Path | None
    runtime_dir: Path | None


def _environment() -> dict[str, str]:
    environment = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if "SYSTEMROOT" in os.environ:
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return environment


def _active_s4_policy(**updates: object) -> S4RuntimePolicy:
    return S4RuntimePolicy.model_validate(
        {
            "enabled": True,
            "kill_switch_engaged": False,
            "poll_interval_ms": 5,
            "cooperative_cancel_grace_ms": 20,
            "terminate_grace_ms": 20,
            "hard_kill_grace_ms": 500,
            **updates,
        }
    )


def _adapter_fixture(
    tmp_path: Path,
    *,
    mode: str = "success",
    model_identity: str | None = None,
    max_runtime_ms: int = 2000,
    driver_mode: LocalNativeDriverMode = LocalNativeDriverMode.DETERMINISTIC_FIXTURE,
    environment_updates: dict[str, str] | None = None,
) -> _AdapterFixture:
    real_mode = driver_mode is LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT
    driver_fixture_mode = "real-success" if real_mode and mode == "success" else mode
    driver_path = _driver_script(tmp_path, mode=driver_fixture_mode)
    model_path = (tmp_path / f"model_{mode}.fixture").resolve()
    model_path.write_bytes(b"deterministic-model-fixture\n")
    executable_path = Path(sys.executable).resolve()
    backend_id = (
        "local-native:s5b-real-contract-fixture" if real_mode else "local-native:s5b-fixture"
    )
    compatibility = _compatibility(backend_id=backend_id)
    resource_budget = _resource_budget(max_context_tokens=512 if real_mode else 8192)
    model_digest = _file_digest(model_path)
    selected_model_identity = model_identity or (
        f"test-real-contract@sha256:{model_digest}" if real_mode else "fixture:s5b-local-native"
    )
    profile = WorkerProviderProfile(
        backend_id=backend_id,
        provider_kind=WorkerProviderKind.LUNA_NATIVE_NR2B_SLICE1,
        model_identity=selected_model_identity,
        model_artifact_sha256=model_digest,
        driver_artifact_sha256=_file_digest(driver_path),
        compatibility_fingerprint=compatibility.fingerprint(),
        compatibility_evidence_ref="tests/test_c011_s5b_native_adapter.py",
        resource_profile=NeuralResourceProfile.DESKTOP,
        resource_budget=resource_budget,
        capacity=ProviderCapacity(
            max_context_bytes=4096,
            max_result_bytes=8192,
            max_claims=4,
            max_output_tokens=256,
            max_runtime_ms=max_runtime_ms,
            max_total_workers=1,
            max_concurrent_workers=1,
        ),
        allowed_roles=(ParallelCognitionRole.PARALLEL,),
    )
    environment = _environment()
    environment.update(environment_updates or {})
    shim_path: Path | None = None
    runtime_dir: Path | None = None
    runtime_artifacts: tuple[LocalNativeRuntimeArtifact, ...] = ()
    if real_mode:
        shim_path = (tmp_path / "luna_neural_bridge.dll").resolve()
        shim_path.write_bytes(b"deterministic-shim-contract-fixture\n")
        runtime_dir = (tmp_path / "cpu-runtime").resolve()
        runtime_dir.mkdir()
        runtime_file = runtime_dir / "ggml.dll"
        runtime_file.write_bytes(b"deterministic-runtime-contract-fixture\n")
        runtime_artifacts = (
            LocalNativeRuntimeArtifact(
                relative_path=runtime_file.name,
                size_bytes=runtime_file.stat().st_size,
                sha256=_file_digest(runtime_file),
            ),
        )
    binding = LocalNativeDriverBinding(
        profile_id=profile.profile_id,
        backend_id=backend_id,
        provider_kind=WorkerProviderKind.LUNA_NATIVE_NR2B_SLICE1,
        executable_path=str(executable_path),
        driver_artifact_path=str(driver_path),
        model_artifact_path=str(model_path),
        executable_artifact_sha256=_file_digest(executable_path),
        driver_artifact_sha256=profile.driver_artifact_sha256,
        model_artifact_sha256=profile.model_artifact_sha256,
        mode=driver_mode,
        shim_artifact_path=None if shim_path is None else str(shim_path),
        runtime_directory_path=None if runtime_dir is None else str(runtime_dir),
        shim_artifact_sha256=(None if shim_path is None else _file_digest(shim_path)),
        runtime_artifacts=runtime_artifacts,
        cpu_threads=resource_budget.cpu_threads if real_mode else None,
        max_context_tokens=resource_budget.max_context_tokens if real_mode else None,
        fixture_only=not real_mode,
        environment_sha256=driver_environment_sha256(environment),
    )
    state = _CurrentState(
        driver_policy=S5BDriverPolicy(
            enabled=True,
            kill_switch_engaged=False,
            approved_binding_id=binding.binding_id,
            mode=driver_mode,
            fixture_only=not real_mode,
            real_provider_execution_authority=real_mode,
        ),
        provider_policy=S5ProviderRoutingPolicy(
            enabled=True,
            kill_switch_engaged=False,
            stage=ModelRolloutStage.SHADOW,
            approved_profile_id=profile.profile_id,
            approved_compatibility_fingerprint=profile.compatibility_fingerprint,
            max_total_workers=1,
            max_concurrent_workers=1,
        ),
        compatibility=compatibility,
        resource_budget=resource_budget,
    )
    content = b"verified S5B context"
    now = utc_now()
    deadline = now + timedelta(seconds=10)
    source = ContextSourceReference(
        task_id=TASK_ID,
        source_task_revision=9,
        source_ref="repo:s5b",
        source_revision="git:s5b-fixture",
        content_sha256=_digest(content),
        freshness=ContextFreshness.CURRENT,
        freshness_checked_at=now - timedelta(milliseconds=1),
        redaction_state=RedactionState.NOT_REQUIRED,
        size_bytes=len(content),
    )
    manifest = ReadOnlyContextManifest(
        task_id=TASK_ID,
        source_task_revision=9,
        sources=(source,),
        total_size_bytes=len(content),
        created_at=now,
        expires_at=deadline,
    )
    assignment = AssignmentSemanticSpec(
        task_id=TASK_ID,
        source_task_revision=9,
        task_contract_sha256=_digest("task"),
        source_steps=(
            SourceStepSemantics(
                step_id=UUID("92000000-0000-4000-8000-000000000022"),
                sequence=1,
                description="Inspect one exact S5B fixture lane.",
                status=PlanStepStatus.PENDING,
                source_step_payload_sha256=_digest("step"),
            ),
        ),
        acceptance_basis_sha256=_digest("acceptance"),
        acceptance_target_refs=("target:s5b",),
        context_manifest_sha256=contract_sha256(manifest),
        autonomy_policy_sha256=_digest("autonomy"),
        tool_policy_sha256=_digest("tools"),
        worker_role=ParallelCognitionRole.PARALLEL,
        objective="Return one concise cited fixture result.",
        granted_source_refs=("repo:s5b",),
        capability_selection_basis_sha256=_digest("capability"),
        root_coordination_epoch=1,
        budget=WorkerBudgetEnvelope(
            max_context_bytes=4096,
            max_result_bytes=8192,
            max_claims=4,
            max_tokens=128,
            max_runtime_ms=max_runtime_ms,
            deadline_at=deadline,
        ),
    )
    document = FocusedContextDocument(
        source_ref=source.source_ref,
        source_revision=source.source_revision,
        manifest_content_sha256=source.content_sha256,
        visible_content_sha256=source.content_sha256,
        manifest_size_bytes=len(content),
        visible_size_bytes=len(content),
        content=content.decode("utf-8"),
    )
    focused = FocusedContextBundle(
        task_id=TASK_ID,
        source_task_revision=9,
        assignment_id=assignment.assignment_id,
        context_manifest_sha256=assignment.context_manifest_sha256,
        documents=(document,),
        visible_size_bytes=len(content),
    )
    attempt = AgentExecutionAttempt(
        attempt_id="attempt:s5b-fixture",
        task_id=TASK_ID,
        source_task_revision=9,
        assignment_id=assignment.assignment_id,
        context_manifest_sha256=assignment.context_manifest_sha256,
        runtime_session_id="session:s5b-fixture",
        backend_id=backend_id,
        profile_id=profile.profile_id,
        root_coordination_epoch=1,
        cancellation_epoch=0,
        created_at=now,
        started_at=now,
        deadline_at=deadline,
        isolation=IsolationReferences(
            process_ref="s5b-process:fixture",
            session_ref="s5b-session:fixture",
            context_ref="s5b-context:fixture",
        ),
        lifecycle_state=AgentLifecycleState.STARTED,
    )
    request = LiveBackendRequest(
        assignment=assignment,
        attempt=attempt,
        context=manifest,
        focused_context_id=focused.focused_context_id,
        focused_context_sha256=contract_sha256(focused),
        requested_at=now,
    )
    registry = ProviderProfileRegistry((profile,))
    adapter = LocalNativeDriverAdapter(
        binding=binding,
        registry=registry,
        driver_policy_provider=lambda: state.driver_policy,
        provider_policy_provider=lambda: state.provider_policy,
        compatibility_provider=lambda: state.compatibility,
        resource_budget_provider=lambda: state.resource_budget,
        environment=environment,
    )
    return _AdapterFixture(
        adapter=adapter,
        binding=binding,
        profile=profile,
        state=state,
        request=request,
        context=focused,
        driver_path=driver_path,
        model_path=model_path,
        shim_path=shim_path,
        runtime_dir=runtime_dir,
    )


def test_binding_is_content_addressed_fixture_only_and_tamper_evident(
    tmp_path: Path,
) -> None:
    fixture = _adapter_fixture(tmp_path)

    assert fixture.binding.binding_id.startswith("c011-native-driver-binding:sha256:")
    assert fixture.binding.mode is LocalNativeDriverMode.DETERMINISTIC_FIXTURE
    assert fixture.binding.fixture_only
    assert fixture.binding.command_template()[0] == str(Path(sys.executable).resolve())

    raw = fixture.binding.model_dump(mode="json")
    raw["model_artifact_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="canonical content"):
        LocalNativeDriverBinding.model_validate(raw)


def test_driver_policy_is_default_off_and_requires_exact_approval() -> None:
    policy = S5BDriverPolicy()
    assert not policy.active
    assert policy.kill_switch_engaged
    assert not policy.real_provider_execution_authority
    with pytest.raises(ValidationError, match="approved binding"):
        S5BDriverPolicy(enabled=True, kill_switch_engaged=False)


def test_exact_fixture_executes_without_ambient_secret_and_binds_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUNA_S5B_SECRET", "must-not-cross")
    fixture = _adapter_fixture(tmp_path)

    result = fixture.adapter.execute(
        request=fixture.request,
        context=fixture.context,
        policy=_active_s4_policy(),
        cancellation_probe=lambda: False,
    )

    assert isinstance(result, LocalNativeDriverResult)
    assert result.outcome_state is AgentLifecycleState.RESULT_RECEIVED
    assert result.payload.summary == "s5b:not-inherited"
    assert result.payload.claims[0].source_refs == ("repo:s5b",)
    assert result.provider_binding_id == fixture.binding.binding_id
    assert result.native_usage is None
    assert not result.state_mutation_authority
    assert not result.completion_authority
    assert not result.user_facing_voice_authority


def test_default_s5b_policy_denies_before_process_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _adapter_fixture(tmp_path)
    fixture.state.driver_policy = S5BDriverPolicy()

    def forbidden_popen(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("process creation must not occur")

    monkeypatch.setattr(
        "luna.parallel_cognition.subprocess_backend.subprocess.Popen",
        forbidden_popen,
    )
    with pytest.raises(S5BDriverIntegrityError, match="disabled or killed"):
        fixture.adapter.execute(
            request=fixture.request,
            context=fixture.context,
            policy=_active_s4_policy(),
            cancellation_probe=lambda: False,
        )


@pytest.mark.parametrize("drift", ["provider-kill", "compatibility", "resource"])
def test_current_provider_or_resource_drift_denies_before_fixture_execution(
    tmp_path: Path,
    drift: str,
) -> None:
    fixture = _adapter_fixture(tmp_path)
    if drift == "provider-kill":
        fixture.state.provider_policy = fixture.state.provider_policy.model_copy(
            update={"kill_switch_engaged": True}
        )
    elif drift == "compatibility":
        fixture.state.compatibility = _compatibility(backend_id="stale-backend")
    else:
        fixture.state.resource_budget = _resource_budget(cpu_threads=7)

    with pytest.raises(S5BDriverIntegrityError, match="selection is not exact"):
        fixture.adapter.execute(
            request=fixture.request,
            context=fixture.context,
            policy=_active_s4_policy(),
            cancellation_probe=lambda: False,
        )


def test_binding_policy_mismatch_denies(tmp_path: Path) -> None:
    fixture = _adapter_fixture(tmp_path)
    fixture.state.driver_policy = fixture.state.driver_policy.model_copy(
        update={"approved_binding_id": "c011-native-driver-binding:sha256:" + "0" * 64}
    )
    with pytest.raises(S5BDriverIntegrityError, match="another binding"):
        fixture.adapter.execute(
            request=fixture.request,
            context=fixture.context,
            policy=_active_s4_policy(),
            cancellation_probe=lambda: False,
        )


def test_artifact_drift_after_construction_denies_before_spawn(tmp_path: Path) -> None:
    fixture = _adapter_fixture(tmp_path)
    fixture.model_path.write_bytes(b"changed\n")

    with pytest.raises(S5BDriverIntegrityError, match="digest mismatch"):
        fixture.adapter.execute(
            request=fixture.request,
            context=fixture.context,
            policy=_active_s4_policy(),
            cancellation_probe=lambda: False,
        )


@pytest.mark.parametrize(
    ("mode", "cancel", "expected"),
    [
        ("cooperative", True, AgentLifecycleState.CANCELLED),
        ("hang", False, AgentLifecycleState.TIMED_OUT),
    ],
)
def test_s4_cancellation_timeout_and_cleanup_survive_s5b_binding(
    tmp_path: Path,
    mode: str,
    cancel: bool,
    expected: AgentLifecycleState,
) -> None:
    fixture = _adapter_fixture(tmp_path, mode=mode, max_runtime_ms=80)

    result = fixture.adapter.execute(
        request=fixture.request,
        context=fixture.context,
        policy=_active_s4_policy(cooperative_cancel_grace_ms=300),
        cancellation_probe=lambda: cancel,
    )

    assert result.outcome_state is expected
    assert result.cleanup_state.value == AgentLifecycleState.CLEANUP_COMPLETE.value
    assert result.provider_binding_id == fixture.binding.binding_id


def test_post_execution_driver_drift_stops_without_returning_result(tmp_path: Path) -> None:
    fixture = _adapter_fixture(tmp_path, mode="mutate-driver")

    with pytest.raises(S5BDriverIntegrityError, match="digest mismatch"):
        fixture.adapter.execute(
            request=fixture.request,
            context=fixture.context,
            policy=_active_s4_policy(),
            cancellation_probe=lambda: False,
        )


def test_non_fixture_profile_is_rejected_before_adapter_creation(tmp_path: Path) -> None:
    with pytest.raises(S5BDriverIntegrityError, match="fixture profiles"):
        _adapter_fixture(tmp_path, model_identity="real-model-not-proven")


def test_real_mode_requires_explicit_authority() -> None:
    with pytest.raises(ValidationError, match="explicit authority"):
        S5BDriverPolicy(
            enabled=True,
            kill_switch_engaged=False,
            approved_binding_id="c011-native-driver-binding:sha256:" + "0" * 64,
            mode=LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT,
            fixture_only=False,
        )


def test_real_mode_contract_executes_once_and_binds_exact_identity(
    tmp_path: Path,
) -> None:
    fixture = _adapter_fixture(
        tmp_path,
        driver_mode=LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT,
    )

    result = fixture.adapter.execute(
        request=fixture.request,
        context=fixture.context,
        policy=_active_s4_policy(),
        cancellation_probe=lambda: False,
    )

    assert result.outcome_state is AgentLifecycleState.RESULT_RECEIVED
    assert result.driver_mode is LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT
    assert result.real_provider_execution
    assert result.provider_binding_id == fixture.binding.binding_id
    assert result.native_usage is not None
    assert result.native_usage.source == "ENGINE_NATIVE_COUNTERS"
    assert result.native_usage.input_tokens == 129
    assert result.native_usage.output_tokens == 5
    assert result.native_usage.total_tokens == 134
    assert result.usage.tokens == 5
    assert fixture.adapter.real_attempt_consumed

    without_usage = result.model_dump(mode="json")
    without_usage.update({"result_id": "", "native_usage": None})
    with pytest.raises(ValidationError, match="requires engine-native usage"):
        LocalNativeDriverResult.model_validate(without_usage)
    with pytest.raises(S5BDriverIntegrityError, match="already consumed"):
        fixture.adapter.execute(
            request=fixture.request,
            context=fixture.context,
            policy=_active_s4_policy(),
            cancellation_probe=lambda: False,
        )


def test_real_mode_unknown_environment_is_rejected_before_artifact_scan(
    tmp_path: Path,
) -> None:
    with pytest.raises(S5BDriverIntegrityError, match="unknown key"):
        _adapter_fixture(
            tmp_path,
            driver_mode=LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT,
            environment_updates={"HTTP_PROXY": "must-not-cross"},
        )


def test_real_mode_runtime_allowlist_drift_fails_closed(tmp_path: Path) -> None:
    fixture = _adapter_fixture(
        tmp_path,
        driver_mode=LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT,
    )
    assert fixture.runtime_dir is not None
    (fixture.runtime_dir / "unexpected.dll").write_bytes(b"unexpected\n")

    with pytest.raises(S5BDriverIntegrityError, match="allowlist mismatch"):
        fixture.adapter.execute(
            request=fixture.request,
            context=fixture.context,
            policy=_active_s4_policy(),
            cancellation_probe=lambda: False,
        )
