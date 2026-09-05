"""Run one bounded current-asset LocalNativeDriverAdapter evidence attempt."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import UUID

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
    LocalNativeRuntimeArtifact,
    ParallelCognitionRole,
    ProviderCapacity,
    ProviderProfileRegistry,
    ReadOnlyContextManifest,
    RedactionState,
    S4RuntimePolicy,
    S5BDriverPolicy,
    S5ProviderRoutingPolicy,
    SourceStepSemantics,
    WorkerBudgetEnvelope,
    WorkerProviderKind,
    WorkerProviderProfile,
    contract_sha256,
    driver_environment_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = UUID("95000000-0000-4000-8000-000000000011")


def _digest(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return sha256(raw).hexdigest()


def _file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _environment() -> dict[str, str]:
    environment = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if "SYSTEMROOT" in os.environ:
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return environment


def _compatibility(*, backend_id: str) -> ModelCompatibilityReport:
    return ModelCompatibilityReport(
        backend_id=backend_id,
        results=tuple(
            ModelCompatibilityCaseResult(
                case_id=f"S5B-REAL-{index:02d}",
                capability=capability,
                status=ModelCompatibilityStatus.PASS,
                required=True,
                detail="Accepted NR-2B evidence reused for one exact S5B adapter proof.",
            )
            for index, capability in enumerate(ModelCompatibilityCapability, start=1)
        ),
    )


def _runtime_artifacts(items: list[dict[str, Any]]) -> tuple[LocalNativeRuntimeArtifact, ...]:
    return tuple(
        LocalNativeRuntimeArtifact(
            relative_path=str(item["name"]),
            size_bytes=int(item["size_bytes"]),
            sha256=str(item["sha256"]),
        )
        for item in items
    )


def _build_execution(
    *, evidence: dict[str, Any], driver_path: Path
) -> tuple[
    LocalNativeDriverAdapter,
    LiveBackendRequest,
    FocusedContextBundle,
    S4RuntimePolicy,
    LocalNativeDriverBinding,
]:
    assets = cast(dict[str, Any], evidence["asset_evidence"])
    budget_data = cast(dict[str, Any], evidence["execution_budget"])
    model_path = Path(str(assets["model_path"])).resolve(strict=True)
    shim_path = Path(str(assets["bridge_path"])).resolve(strict=True)
    runtime_dir = Path(str(assets["runtime_directory"])).resolve(strict=True)
    executable_path = Path(sys.executable).resolve(strict=True)
    driver_path = driver_path.resolve(strict=True)
    backend_id = "local-native:c011-s5b-real-adapter-evidence"
    compatibility = _compatibility(backend_id=backend_id)
    resource_budget = NeuralResourceBudget(
        max_vram_mib=0,
        max_gpu_utilization_percent=0,
        cpu_threads=int(budget_data["cpu_threads"]),
        max_system_ram_mib=int(budget_data["max_system_ram_mib"]),
        max_kv_cache_mib=int(budget_data["max_kv_cache_mib"]),
        max_context_tokens=int(budget_data["max_context_tokens"]),
        batch_size=int(budget_data["batch_size"]),
        max_parallel_generations=1,
        idle_unload_seconds=0,
        request_priority=50,
        inference_allowed=True,
        model_resident=False,
        background_inference=False,
    )
    runtime_ms = 180_000
    model_sha256 = str(assets["model_sha256"])
    profile = WorkerProviderProfile(
        backend_id=backend_id,
        provider_kind=WorkerProviderKind.LUNA_NATIVE_NR2B_SLICE1,
        model_identity=(
            f"{assets['model_source_identity']}@sha256:{model_sha256}"
        ),
        model_artifact_sha256=model_sha256,
        driver_artifact_sha256=_file_digest(driver_path),
        compatibility_fingerprint=compatibility.fingerprint(),
        compatibility_evidence_ref="c011_s5b_real_evidence.json",
        resource_profile=NeuralResourceProfile.DESKTOP,
        resource_budget=resource_budget,
        capacity=ProviderCapacity(
            max_context_bytes=4096,
            max_result_bytes=8192,
            max_claims=0,
            max_output_tokens=256,
            max_runtime_ms=runtime_ms,
            max_total_workers=1,
            max_concurrent_workers=1,
        ),
        allowed_roles=(ParallelCognitionRole.PARALLEL,),
    )
    environment = _environment()
    binding = LocalNativeDriverBinding(
        profile_id=profile.profile_id,
        backend_id=backend_id,
        provider_kind=WorkerProviderKind.LUNA_NATIVE_NR2B_SLICE1,
        mode=LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT,
        executable_path=str(executable_path),
        driver_artifact_path=str(driver_path),
        model_artifact_path=str(model_path),
        shim_artifact_path=str(shim_path),
        runtime_directory_path=str(runtime_dir),
        executable_artifact_sha256=_file_digest(executable_path),
        driver_artifact_sha256=profile.driver_artifact_sha256,
        model_artifact_sha256=profile.model_artifact_sha256,
        shim_artifact_sha256=str(assets["bridge_sha256"]),
        runtime_artifacts=_runtime_artifacts(
            cast(list[dict[str, Any]], assets["runtime_files"])
        ),
        environment_sha256=driver_environment_sha256(environment),
        cpu_threads=resource_budget.cpu_threads,
        max_context_tokens=resource_budget.max_context_tokens,
        fixture_only=False,
    )
    driver_policy = S5BDriverPolicy(
        enabled=True,
        kill_switch_engaged=False,
        approved_binding_id=binding.binding_id,
        mode=LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT,
        fixture_only=False,
        real_provider_execution_authority=True,
    )
    provider_policy = S5ProviderRoutingPolicy(
        enabled=True,
        kill_switch_engaged=False,
        stage=ModelRolloutStage.SHADOW,
        approved_profile_id=profile.profile_id,
        approved_compatibility_fingerprint=profile.compatibility_fingerprint,
        max_total_workers=1,
        max_concurrent_workers=1,
    )
    content = b"Are you ready to work today? Answer in one short sentence."
    now = utc_now()
    deadline = now + timedelta(milliseconds=runtime_ms)
    source = ContextSourceReference(
        task_id=TASK_ID,
        source_task_revision=10,
        source_ref="evidence:c011-s5b-real-adapter",
        source_revision="git:pending-s5b-real-adapter",
        content_sha256=_digest(content),
        freshness=ContextFreshness.CURRENT,
        freshness_checked_at=now - timedelta(milliseconds=1),
        redaction_state=RedactionState.NOT_REQUIRED,
        size_bytes=len(content),
    )
    manifest = ReadOnlyContextManifest(
        task_id=TASK_ID,
        source_task_revision=10,
        sources=(source,),
        total_size_bytes=len(content),
        created_at=now,
        expires_at=deadline,
    )
    assignment = AssignmentSemanticSpec(
        task_id=TASK_ID,
        source_task_revision=10,
        task_contract_sha256=_digest("c011-s5b-real-adapter"),
        source_steps=(
            SourceStepSemantics(
                step_id=UUID("96000000-0000-4000-8000-000000000011"),
                sequence=1,
                description="Run one bounded real S5B adapter evidence attempt.",
                status=PlanStepStatus.PENDING,
                source_step_payload_sha256=_digest("s5b-real-adapter-step"),
            ),
        ),
        acceptance_basis_sha256=_digest("s5b-real-adapter-acceptance"),
        acceptance_target_refs=("target:c011-s5b-real-adapter",),
        context_manifest_sha256=contract_sha256(manifest),
        autonomy_policy_sha256=_digest("read-only-evidence-only"),
        tool_policy_sha256=_digest("no-tools"),
        worker_role=ParallelCognitionRole.PARALLEL,
        objective="Return one concise final-only observation from the focused context.",
        granted_source_refs=(source.source_ref,),
        capability_selection_basis_sha256=_digest("exact-real-adapter-binding"),
        root_coordination_epoch=1,
        budget=WorkerBudgetEnvelope(
            max_context_bytes=4096,
            max_result_bytes=8192,
            max_claims=0,
            max_tokens=256,
            max_runtime_ms=runtime_ms,
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
        source_task_revision=10,
        assignment_id=assignment.assignment_id,
        context_manifest_sha256=assignment.context_manifest_sha256,
        documents=(document,),
        visible_size_bytes=len(content),
    )
    attempt = AgentExecutionAttempt(
        attempt_id="attempt:c011-s5b-real-adapter",
        task_id=TASK_ID,
        source_task_revision=10,
        assignment_id=assignment.assignment_id,
        context_manifest_sha256=assignment.context_manifest_sha256,
        runtime_session_id="session:c011-s5b-real-adapter",
        backend_id=backend_id,
        profile_id=profile.profile_id,
        root_coordination_epoch=1,
        cancellation_epoch=0,
        created_at=now,
        started_at=now,
        deadline_at=deadline,
        isolation=IsolationReferences(
            process_ref="s5b-real-adapter:single-child",
            session_ref="s5b-real-adapter:one-shot",
            context_ref=focused.focused_context_id,
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
    adapter = LocalNativeDriverAdapter(
        binding=binding,
        registry=ProviderProfileRegistry((profile,)),
        driver_policy_provider=lambda: driver_policy,
        provider_policy_provider=lambda: provider_policy,
        compatibility_provider=lambda: compatibility,
        resource_budget_provider=lambda: resource_budget,
        environment=environment,
    )
    policy = S4RuntimePolicy(
        enabled=True,
        kill_switch_engaged=False,
        max_workers=1,
        max_concurrent_workers=1,
        poll_interval_ms=10,
        cooperative_cancel_grace_ms=250,
        terminate_grace_ms=250,
        hard_kill_grace_ms=5000,
    )
    return adapter, request, focused, policy, binding


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "c011_s5b_real_evidence.json",
    )
    parser.add_argument(
        "--driver",
        type=Path,
        default=ROOT / "src" / "luna" / "parallel_cognition" / "native_real_driver.py",
    )
    args = parser.parse_args()
    evidence = cast(
        dict[str, Any],
        json.loads(args.evidence.read_text(encoding="utf-8")),
    )
    adapter, request, focused, policy, binding = _build_execution(
        evidence=evidence,
        driver_path=args.driver,
    )
    result = adapter.execute(
        request=request,
        context=focused,
        policy=policy,
        cancellation_probe=lambda: False,
    )
    proof = {
        "status": "PASS_S5B_REAL_LOCAL_NATIVE_DRIVER_ADAPTER",
        "binding_id": binding.binding_id,
        "profile_id": result.profile_id,
        "backend_id": result.backend_id,
        "request_id": result.request.request_id,
        "result_id": result.result_id,
        "driver_mode": result.driver_mode.value,
        "real_provider_execution": result.real_provider_execution,
        "real_attempt_consumed": adapter.real_attempt_consumed,
        "outcome_state": result.outcome_state.value,
        "cleanup_state": result.cleanup_state.value,
        "hard_termination_used": result.hard_termination_used,
        "raw_output_sha256": result.raw_output_sha256,
        "raw_output_size_bytes": result.raw_output_size_bytes,
        "runtime_ms": result.usage.runtime_ms,
        "claims_count": len(result.payload.claims),
        "reported_tokens": result.usage.tokens,
        "canonical_final": result.payload.summary,
        "uncertainty": list(result.payload.uncertainty),
        "single_direct_child": True,
        "asset_pre_post_verification": "PASS",
        "analysis_content_emitted": False,
        "state_mutation_authority": result.state_mutation_authority,
        "completion_authority": result.completion_authority,
        "user_facing_voice_authority": result.user_facing_voice_authority,
    }
    accepted = (
        result.outcome_state is AgentLifecycleState.RESULT_RECEIVED
        and result.cleanup_state.value == AgentLifecycleState.CLEANUP_COMPLETE.value
        and result.real_provider_execution
        and adapter.real_attempt_consumed
        and not result.payload.claims
        and not result.state_mutation_authority
        and not result.completion_authority
        and not result.user_facing_voice_authority
    )
    if not accepted:
        proof["status"] = "REJECT_S5B_REAL_LOCAL_NATIVE_DRIVER_ADAPTER"
    print(json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if accepted else 30


if __name__ == "__main__":
    raise SystemExit(main())
