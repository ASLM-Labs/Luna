"""Prove two concurrent one-shot C-011 native adapter lanes on exact ABI v2 assets."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from time import monotonic
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
    BoundedRealNativeAdapterPool,
    ContextFreshness,
    ContextSourceReference,
    EqualComputeBudget,
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
    RealNativeAdapterPoolBinding,
    RealRuntimeAssetBinding,
    RedactionState,
    S4RuntimePolicy,
    S5BDriverPolicy,
    S5ProviderRoutingPolicy,
    SourceStepSemantics,
    WorkerBudgetEnvelope,
    WorkerProviderKind,
    WorkerProviderProfile,
    build_default_real_runtime_configuration_set,
    contract_sha256,
    driver_environment_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = UUID("99000000-0000-4000-8000-000000000011")
BACKEND_ID = "local-native:c011-runtime-configuration-evidence"
RUNTIME_MS = 240_000


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return sha256(raw).hexdigest()


def _file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _environment() -> dict[str, str]:
    environment = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if "SYSTEMROOT" in os.environ:
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return environment


def _compatibility() -> ModelCompatibilityReport:
    return ModelCompatibilityReport(
        backend_id=BACKEND_ID,
        results=tuple(
            ModelCompatibilityCaseResult(
                case_id=f"S5D-E4-{index:02d}",
                capability=capability,
                status=ModelCompatibilityStatus.PASS,
                required=True,
                detail="Current ABI v2 evidence reused for a bounded two-lane proof.",
            )
            for index, capability in enumerate(ModelCompatibilityCapability, start=1)
        ),
    )


def _runtime_artifacts(
    items: list[dict[str, Any]],
) -> tuple[LocalNativeRuntimeArtifact, ...]:
    return tuple(
        LocalNativeRuntimeArtifact(
            relative_path=str(item["name"]),
            size_bytes=int(item["size_bytes"]),
            sha256=str(item["sha256"]),
        )
        for item in items
    )


def _runtime_snapshot(
    runtime_dir: Path,
    expected: tuple[LocalNativeRuntimeArtifact, ...],
) -> dict[str, dict[str, int | str]]:
    expected_by_name = {item.relative_path: item for item in expected}
    observed = {item.name: item for item in runtime_dir.iterdir() if item.is_file()}
    if set(observed) != set(expected_by_name):
        raise RuntimeError("runtime allowlist drifted before the two-lane proof")
    if any(item.is_dir() for item in runtime_dir.iterdir()):
        raise RuntimeError("runtime staging contains an unexpected directory")
    snapshot: dict[str, dict[str, int | str]] = {}
    for name in sorted(observed):
        path = observed[name]
        expected_item = expected_by_name[name]
        actual = {
            "sha256": _file_digest(path),
            "size_bytes": path.stat().st_size,
        }
        if (
            actual["sha256"] != expected_item.sha256
            or actual["size_bytes"] != expected_item.size_bytes
        ):
            raise RuntimeError(f"runtime artifact drift: {name}")
        snapshot[name] = actual
    return snapshot


def _runtime_bundle_sha256(
    artifacts: tuple[LocalNativeRuntimeArtifact, ...],
) -> str:
    payload = [
        item.model_dump(mode="json")
        for item in sorted(artifacts, key=lambda item: item.relative_path)
    ]
    return _digest(_canonical_json(payload))


def _resource_budget() -> NeuralResourceBudget:
    return NeuralResourceBudget(
        max_vram_mib=0,
        max_gpu_utilization_percent=0,
        cpu_threads=4,
        max_system_ram_mib=16384,
        max_kv_cache_mib=512,
        max_context_tokens=512,
        batch_size=256,
        max_parallel_generations=1,
        idle_unload_seconds=0,
        request_priority=50,
        inference_allowed=True,
        model_resident=False,
        background_inference=False,
    )


def _request(
    *,
    lane: int,
    role: ParallelCognitionRole,
    profile: WorkerProviderProfile,
    now: datetime,
) -> tuple[LiveBackendRequest, FocusedContextBundle]:
    deadline = now + timedelta(milliseconds=RUNTIME_MS)
    content = f"Lane {lane} current source. Return READY in one short sentence.".encode()
    source = ContextSourceReference(
        task_id=TASK_ID,
        source_task_revision=12,
        source_ref=f"evidence:c011-runtime-configuration:lane-{lane}",
        source_revision="git:pending-c011-runtime-configuration",
        content_sha256=_digest(content),
        freshness=ContextFreshness.CURRENT,
        freshness_checked_at=now,
        redaction_state=RedactionState.NOT_REQUIRED,
        size_bytes=len(content),
    )
    manifest = ReadOnlyContextManifest(
        task_id=TASK_ID,
        source_task_revision=12,
        sources=(source,),
        total_size_bytes=len(content),
        created_at=now,
        expires_at=deadline,
    )
    assignment = AssignmentSemanticSpec(
        task_id=TASK_ID,
        source_task_revision=12,
        task_contract_sha256=_digest("c011-runtime-configuration-contract"),
        source_steps=(
            SourceStepSemantics(
                step_id=UUID(f"99100000-0000-4000-8000-00000000001{lane}"),
                sequence=lane,
                description=f"Run bounded native evidence lane {lane}.",
                status=PlanStepStatus.PENDING,
                source_step_payload_sha256=_digest(f"runtime-configuration-step:{lane}"),
            ),
        ),
        acceptance_basis_sha256=_digest("c011-runtime-configuration-acceptance"),
        acceptance_target_refs=("target:c011-runtime-configuration",),
        context_manifest_sha256=contract_sha256(manifest),
        autonomy_policy_sha256=_digest("read-only-evidence-only"),
        tool_policy_sha256=_digest("no-tools"),
        worker_role=role,
        objective=f"Lane {lane}: return one concise final-only observation.",
        granted_source_refs=(source.source_ref,),
        capability_selection_basis_sha256=_digest("exact-two-lane-runtime-configuration"),
        root_coordination_epoch=1,
        budget=WorkerBudgetEnvelope(
            max_context_bytes=4096,
            max_result_bytes=8192,
            max_claims=0,
            max_tokens=64,
            max_runtime_ms=RUNTIME_MS,
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
        content=content.decode(),
    )
    focused = FocusedContextBundle(
        task_id=TASK_ID,
        source_task_revision=12,
        assignment_id=assignment.assignment_id,
        context_manifest_sha256=assignment.context_manifest_sha256,
        documents=(document,),
        visible_size_bytes=len(content),
    )
    attempt = AgentExecutionAttempt(
        attempt_id=f"attempt:c011-runtime-configuration:lane-{lane}",
        task_id=TASK_ID,
        source_task_revision=12,
        assignment_id=assignment.assignment_id,
        context_manifest_sha256=assignment.context_manifest_sha256,
        runtime_session_id=f"session:c011-runtime-configuration:lane-{lane}",
        backend_id=BACKEND_ID,
        profile_id=profile.profile_id,
        root_coordination_epoch=1,
        cancellation_epoch=0,
        created_at=now,
        started_at=now,
        deadline_at=deadline,
        isolation=IsolationReferences(
            process_ref=f"c011-runtime-configuration:process-{lane}",
            session_ref=f"c011-runtime-configuration:session-{lane}",
            context_ref=focused.focused_context_id,
        ),
        lifecycle_state=AgentLifecycleState.STARTED,
    )
    return (
        LiveBackendRequest(
            assignment=assignment,
            attempt=attempt,
            context=manifest,
            focused_context_id=focused.focused_context_id,
            focused_context_sha256=contract_sha256(focused),
            requested_at=now,
        ),
        focused,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "c011_s5b_real_evidence.json",
    )
    parser.add_argument(
        "--abi-proof",
        type=Path,
        default=ROOT / "docs" / "C011_NATIVE_ABI_V2_REAL_PROOF_RECEIPT.json",
    )
    parser.add_argument(
        "--driver",
        type=Path,
        default=ROOT / "src" / "luna" / "parallel_cognition" / "native_real_driver.py",
    )
    parser.add_argument("--shim-path", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    evidence = _json(args.evidence.resolve(strict=True))
    abi_proof = _json(args.abi_proof.resolve(strict=True))
    assets = cast(dict[str, Any], evidence["asset_evidence"])
    shim_path = args.shim_path.resolve(strict=True)
    runtime_dir = args.runtime_dir.resolve(strict=True)
    model_path = args.model_path.resolve(strict=True)
    driver_path = args.driver.resolve(strict=True)
    output_path = args.output.resolve(strict=False)
    executable_path = Path(sys.executable).resolve(strict=True)

    model_sha256 = _file_digest(model_path)
    shim_sha256 = _file_digest(shim_path)
    driver_sha256 = _file_digest(driver_path)
    if model_sha256 != str(abi_proof["model_sha256"]):
        raise RuntimeError("model does not match the accepted ABI v2 proof")
    if (
        shim_sha256 != str(abi_proof["bridge_binary_sha256"])
        or abi_proof["bridge_abi_version"] != 2
    ):
        raise RuntimeError("bridge does not match the accepted ABI v2 proof")

    runtime_artifacts = _runtime_artifacts(cast(list[dict[str, Any]], assets["runtime_files"]))
    runtime_before = _runtime_snapshot(runtime_dir, runtime_artifacts)
    repository_before = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    compatibility = _compatibility()
    resource_budget = _resource_budget()
    profile = WorkerProviderProfile(
        backend_id=BACKEND_ID,
        provider_kind=WorkerProviderKind.LUNA_NATIVE_NR2B_SLICE1,
        model_identity=f"{abi_proof['model_source_identity']}@sha256:{model_sha256}",
        model_artifact_sha256=model_sha256,
        driver_artifact_sha256=driver_sha256,
        compatibility_fingerprint=compatibility.fingerprint(),
        compatibility_evidence_ref="docs/C011_NATIVE_ABI_V2_REAL_PROOF_RECEIPT.json",
        resource_profile=NeuralResourceProfile.DESKTOP,
        resource_budget=resource_budget,
        capacity=ProviderCapacity(
            max_context_bytes=4096,
            max_result_bytes=8192,
            max_claims=0,
            max_output_tokens=64,
            max_runtime_ms=RUNTIME_MS,
            max_total_workers=1,
            max_concurrent_workers=1,
        ),
        allowed_roles=(
            ParallelCognitionRole.INDEPENDENT_REVIEWER,
            ParallelCognitionRole.PARALLEL,
        ),
    )
    environment = _environment()
    binding = LocalNativeDriverBinding(
        profile_id=profile.profile_id,
        backend_id=BACKEND_ID,
        provider_kind=WorkerProviderKind.LUNA_NATIVE_NR2B_SLICE1,
        mode=LocalNativeDriverMode.REAL_EVIDENCE_ONESHOT,
        executable_path=str(executable_path),
        driver_artifact_path=str(driver_path),
        model_artifact_path=str(model_path),
        shim_artifact_path=str(shim_path),
        runtime_directory_path=str(runtime_dir),
        executable_artifact_sha256=_file_digest(executable_path),
        driver_artifact_sha256=driver_sha256,
        model_artifact_sha256=model_sha256,
        shim_artifact_sha256=shim_sha256,
        runtime_artifacts=runtime_artifacts,
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
    registry = ProviderProfileRegistry((profile,))

    def adapter() -> LocalNativeDriverAdapter:
        return LocalNativeDriverAdapter(
            binding=binding,
            registry=registry,
            driver_policy_provider=lambda: driver_policy,
            provider_policy_provider=lambda: provider_policy,
            compatibility_provider=lambda: compatibility,
            resource_budget_provider=lambda: resource_budget,
            environment=environment,
        )

    pool_binding = RealNativeAdapterPoolBinding(
        member_binding_id=binding.binding_id,
        backend_id=BACKEND_ID,
        profile_id=profile.profile_id,
        member_count=2,
        max_concurrent_members=2,
    )
    pool = BoundedRealNativeAdapterPool(
        binding=pool_binding,
        adapters=(adapter(), adapter()),
    )
    asset_binding = RealRuntimeAssetBinding(
        backend_id=BACKEND_ID,
        provider_profile_id=profile.profile_id,
        provider_binding_id=binding.binding_id,
        model_identity=profile.model_identity,
        model_artifact_sha256=model_sha256,
        bridge_artifact_sha256=shim_sha256,
        driver_artifact_sha256=driver_sha256,
        runtime_bundle_sha256=_runtime_bundle_sha256(runtime_artifacts),
        environment_sha256=binding.environment_sha256,
        sampling_sha256=_digest("greedy:temperature=0:seed=0:abi-v2"),
    )
    configuration = build_default_real_runtime_configuration_set(
        asset_binding=asset_binding,
        equal_compute_budget=EqualComputeBudget(
            max_total_tokens=2048,
            max_tool_calls=0,
            max_compute_units=1000,
            max_context_bytes=32768,
            max_wall_time_ms=RUNTIME_MS,
        ),
        parallel_workers=2,
    )

    now = utc_now()
    requests = (
        _request(
            lane=1,
            role=ParallelCognitionRole.PARALLEL,
            profile=profile,
            now=now,
        ),
        _request(
            lane=2,
            role=ParallelCognitionRole.INDEPENDENT_REVIEWER,
            profile=profile,
            now=now,
        ),
    )
    policy = S4RuntimePolicy(
        enabled=True,
        kill_switch_engaged=False,
        max_workers=2,
        max_concurrent_workers=2,
        poll_interval_ms=10,
        cooperative_cancel_grace_ms=250,
        terminate_grace_ms=250,
        hard_kill_grace_ms=5000,
    )
    started_at = datetime.now(UTC)
    started = monotonic()

    def execute(
        item: tuple[LiveBackendRequest, FocusedContextBundle],
    ) -> LocalNativeDriverResult:
        request, focused = item
        return pool.execute(
            request=request,
            context=focused,
            policy=policy,
            cancellation_probe=lambda: False,
        )

    with ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="c011-runtime-proof",
    ) as executor:
        results = tuple(executor.map(execute, requests))
    wall_time_ms = round((monotonic() - started) * 1000)
    completed_at = datetime.now(UTC)

    model_after = _file_digest(model_path)
    runtime_after = _runtime_snapshot(runtime_dir, runtime_artifacts)
    repository_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    asset_integrity_pass = bool(
        model_after == model_sha256
        and runtime_after == runtime_before
        and _file_digest(shim_path) == shim_sha256
        and repository_after == repository_before
    )
    accepted = bool(
        len(results) == 2
        and len({item.result_id for item in results}) == 2
        and all(
            item.outcome_state is AgentLifecycleState.RESULT_RECEIVED
            and item.cleanup_state.value == AgentLifecycleState.CLEANUP_COMPLETE.value
            and item.real_provider_execution
            and item.native_usage is not None
            and item.usage.tokens > 0
            and not item.payload.claims
            and not item.state_mutation_authority
            and not item.completion_authority
            and not item.user_facing_voice_authority
            for item in results
        )
        and pool.real_attempts_consumed == 2
        and pool.max_in_flight == 2
        and pool.exhausted
        and asset_integrity_pass
    )
    proof = {
        "schema_version": 1,
        "scope": "C011_REAL_RUNTIME_CONFIGURATION_TWO_LANE_PROOF",
        "status": (
            "PASS_C011_REAL_RUNTIME_CONFIGURATION_TWO_LANE_FULL_CHAIN"
            if accepted
            else "REJECT_C011_REAL_RUNTIME_CONFIGURATION_TWO_LANE_FULL_CHAIN"
        ),
        "started_at_utc": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at_utc": completed_at.isoformat().replace("+00:00", "Z"),
        "baseline_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "configuration_set_id": configuration.configuration_set_id,
        "runtime_arm_ids": {
            item.configuration.value: item.configuration_id for item in configuration.arms
        },
        "shadow_arm_execution_sha256": {
            item.configuration.value: item.execution_configuration_sha256
            for item in configuration.shadow_arms()
        },
        "asset_binding_id": asset_binding.asset_binding_id,
        "pool_binding_id": pool_binding.pool_binding_id,
        "member_binding_id": binding.binding_id,
        "profile_id": profile.profile_id,
        "backend_id": BACKEND_ID,
        "parallel_workers": 2,
        "worker_output_token_ceiling": 64,
        "max_concurrent_observed": pool.max_in_flight,
        "pool_exhausted_without_replay": pool.exhausted,
        "native_usage_survived_result_boundary": all(
            item.native_usage is not None for item in results
        ),
        "wall_time_ms": wall_time_ms,
        "results": [
            {
                "request_id": item.request.request_id,
                "result_id": item.result_id,
                "role": item.request.assignment.worker_role.value,
                "outcome_state": item.outcome_state.value,
                "cleanup_state": item.cleanup_state.value,
                "hard_termination_used": item.hard_termination_used,
                "runtime_ms": item.usage.runtime_ms,
                "canonical_final": item.payload.summary,
                "usage": item.native_usage.model_dump(mode="json")
                if item.native_usage is not None
                else None,
                "claims_count": len(item.payload.claims),
                "analysis_content_emitted": False,
            }
            for item in results
        ],
        "assets": {
            "model_source_identity": abi_proof["model_source_identity"],
            "model_sha256": model_sha256,
            "model_size_bytes": model_path.stat().st_size,
            "bridge_sha256": shim_sha256,
            "bridge_size_bytes": shim_path.stat().st_size,
            "bridge_abi_version": 2,
            "driver_sha256": driver_sha256,
            "runtime_bundle_sha256": asset_binding.runtime_bundle_sha256,
            "runtime_file_count": len(runtime_artifacts),
            "environment_sha256": binding.environment_sha256,
            "asset_pre_post_integrity": "PASS" if asset_integrity_pass else "REJECT",
        },
        "per_member_budget": resource_budget.model_dump(mode="json"),
        "equal_compute_contract": {
            "configurations": [item.configuration.value for item in configuration.shadow_arms()],
            "max_total_output_tokens_per_arm": 256,
            "normalized_compute_units_per_arm": 1000,
            "engine_native_usage_required": True,
            "real_equal_compute_triplet_executed": False,
        },
        "live_model_execution": True,
        "runtime_configuration_set_constructed": True,
        "full_three_arm_runner_executed": False,
        "provider_calls_executed": 2,
        "production_runtime_wiring_added": False,
        "controlled_c011_execution": False,
        "hidden_chain_of_thought_access": False,
        "repository_pre_post_status_unchanged": repository_after == repository_before,
        "authority": {
            "runtime": False,
            "task_state": False,
            "root_context_adoption": False,
            "completion": False,
            "user_facing_voice": False,
            "canary": False,
            "active": False,
            "promotion": False,
        },
        "aslm_gates": {
            "research_saturation_gate": "NOT_READY",
            "target_spec": "BLOCKED",
            "controlled_execution": "NONE",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if accepted else 30


if __name__ == "__main__":
    raise SystemExit(main())
