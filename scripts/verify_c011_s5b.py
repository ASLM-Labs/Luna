"""Deterministic RFC-C011 S5B fixture-first local-native adapter gate."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import luna.parallel_cognition as facade  # noqa: E402
from luna.capabilities import (  # noqa: E402
    CapabilityStatus,
    build_canonical_capability_registry,
)
from luna.modeling import (  # noqa: E402
    ModelCompatibilityCapability,
    ModelCompatibilityCaseResult,
    ModelCompatibilityReport,
    ModelCompatibilityStatus,
)
from luna.neural import NeuralResourceBudget, NeuralResourceProfile  # noqa: E402
from luna.parallel_cognition import (  # noqa: E402
    LocalNativeDriverAdapter,
    LocalNativeDriverBinding,
    LocalNativeDriverResult,
    ParallelCognitionRole,
    ProviderCapacity,
    ProviderProfileRegistry,
    S5BDriverPolicy,
    S5ProviderRoutingPolicy,
    WorkerProviderKind,
    WorkerProviderProfile,
    driver_environment_sha256,
)

REQUIRED_FILES = (
    "src/luna/parallel_cognition/native_adapter.py",
    "tests/test_c011_s5b_native_adapter.py",
    "scripts/verify_c011_s5b.py",
    "c011_s5b_verification.json",
    "docs/C011_S5B_LOCAL_NATIVE_DRIVER_ADAPTER_REPORT.md",
    "docs/C011_S5B_UPDATE_MANIFEST.json",
)

DECLARED_SCOPE_FILES = frozenset(
    {
        "LUNA_HANDOFF.md",
        "MANIFEST.json",
        "SHA256SUMS.txt",
        "c011_s5b_verification.json",
        "docs/C011_S5B_LOCAL_NATIVE_DRIVER_ADAPTER_REPORT.md",
        "docs/C011_S5B_UPDATE_MANIFEST.json",
        "docs/LUNA_ROADMAP.md",
        "docs/NEURAL_NATIVE_BRIDGE_UPDATE_MANIFEST.json",
        "docs/NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json",
        "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
        "scripts/check.bat",
        "scripts/verify_c011_s4.py",
        "scripts/verify_c011_s5a.py",
        "scripts/verify_c011_s5b.py",
        "src/luna/parallel_cognition/__init__.py",
        "src/luna/parallel_cognition/native_adapter.py",
        "tests/test_c011_s5b_native_adapter.py",
        "tests/test_project_metadata.py",
    }
)

S5B_READY = "C011_S5B_READY_FOR_FINAL_GATE"
S5B_ACCEPTED = "C011_S5B_LOCAL_NATIVE_DRIVER_ADAPTER_ACCEPTED"
NEXT_EVIDENCE_GATE = "C011_S5B_REAL_LOCAL_NATIVE_EXECUTION_BLOCKED_PENDING_EXTERNAL_EVIDENCE"


def _canonical_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return raw
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _metadata_integrity() -> bool:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    if (
        manifest.get("hash_normalization") != "utf8_text_lf_v1"
        or manifest.get("metadata_scope") != "release_artifact_allowlist_v2"
    ):
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False
    sums: dict[str, str] = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            return False
        digest, relative = line.split("  ", 1)
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            return False
        sums[relative] = digest
    if set(sums) != set(files):
        return False
    for relative, metadata in files.items():
        if not isinstance(relative, str) or not isinstance(metadata, dict):
            return False
        path = ROOT / relative
        if not path.is_file():
            return False
        canonical = _canonical_bytes(path)
        digest = sha256(canonical).hexdigest()
        if (
            metadata.get("sha256") != digest
            or metadata.get("size_bytes") != len(canonical)
            or sums.get(relative) != digest
        ):
            return False
    return True


def _compatibility() -> ModelCompatibilityReport:
    results = tuple(
        ModelCompatibilityCaseResult(
            case_id=f"S5B-{index:02d}",
            capability=capability,
            status=ModelCompatibilityStatus.PASS,
            required=True,
            detail="deterministic S5B verifier evidence",
        )
        for index, capability in enumerate(ModelCompatibilityCapability, start=1)
    )
    return ModelCompatibilityReport(
        report_id=UUID("8d4e4f95-cb1f-49b6-9177-b3de88617403"),
        backend_id="luna-native-s5b-fixture",
        results=results,
        created_at=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
    )


def _resource_budget() -> NeuralResourceBudget:
    return NeuralResourceBudget(
        max_vram_mib=0,
        max_gpu_utilization_percent=0,
        cpu_threads=2,
        max_system_ram_mib=4096,
        max_kv_cache_mib=0,
        max_context_tokens=2048,
        batch_size=1,
        max_parallel_generations=1,
        inference_allowed=True,
        model_resident=False,
        background_inference=False,
    )


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _adapter_contract_gate() -> bool:
    compatibility = _compatibility()
    environment = {"PYTHONDONTWRITEBYTECODE": "1"}
    with TemporaryDirectory(prefix="luna-c011-s5b-verifier-") as temp:
        temp_path = Path(temp).resolve()
        driver = temp_path / "fixture_driver.py"
        model = temp_path / "fixture_model.bin"
        driver.write_text("# deterministic verifier fixture\n", encoding="utf-8")
        model.write_bytes(b"deterministic-s5b-model")
        executable = Path(sys.executable).resolve(strict=True)
        profile = WorkerProviderProfile(
            backend_id=compatibility.backend_id,
            provider_kind=WorkerProviderKind.LUNA_NATIVE_NR2B_SLICE1,
            model_identity="fixture:s5b-verifier",
            model_artifact_sha256=_file_sha256(model),
            driver_artifact_sha256=_file_sha256(driver),
            compatibility_fingerprint=compatibility.fingerprint(),
            compatibility_evidence_ref="fixture:s5b-verifier",
            resource_profile=NeuralResourceProfile.DESKTOP,
            resource_budget=_resource_budget(),
            capacity=ProviderCapacity(
                max_context_bytes=4096,
                max_result_bytes=4096,
                max_claims=2,
                max_output_tokens=64,
                max_runtime_ms=5000,
                max_total_workers=1,
                max_concurrent_workers=1,
            ),
            allowed_roles=(ParallelCognitionRole.PARALLEL,),
        )
        binding = LocalNativeDriverBinding(
            profile_id=profile.profile_id,
            backend_id=profile.backend_id,
            provider_kind=profile.provider_kind,
            executable_path=str(executable),
            driver_artifact_path=str(driver),
            model_artifact_path=str(model),
            executable_artifact_sha256=_file_sha256(executable),
            driver_artifact_sha256=profile.driver_artifact_sha256,
            model_artifact_sha256=profile.model_artifact_sha256,
            environment_sha256=driver_environment_sha256(environment),
        )
        registry = ProviderProfileRegistry((profile,))
        adapter = LocalNativeDriverAdapter(
            binding=binding,
            registry=registry,
            driver_policy_provider=S5BDriverPolicy,
            provider_policy_provider=S5ProviderRoutingPolicy,
            compatibility_provider=lambda: compatibility,
            resource_budget_provider=_resource_budget,
            environment=environment,
        )
        active = S5BDriverPolicy(
            enabled=True,
            kill_switch_engaged=False,
            approved_binding_id=binding.binding_id,
        )
        tampered = binding.model_dump(mode="json")
        tampered["model_artifact_sha256"] = "0" * 64
        tamper_rejected = False
        missing_approval_rejected = False
        try:
            LocalNativeDriverBinding.model_validate(tampered)
        except ValidationError:
            tamper_rejected = True
        try:
            S5BDriverPolicy(enabled=True, kill_switch_engaged=False)
        except ValidationError:
            missing_approval_rejected = True

    default_policy = S5BDriverPolicy()
    required_exports = {
        "LocalNativeDriverAdapter",
        "LocalNativeDriverBinding",
        "LocalNativeDriverMode",
        "LocalNativeDriverResult",
        "S5BDriverIntegrityError",
        "S5BDriverPolicy",
        "driver_environment_sha256",
    }
    authority_fields = (
        "real_provider_execution_authority",
        "root_context_adoption_authority",
        "task_state_authority",
        "completion_authority",
        "promotion_authority",
    )
    return bool(
        binding.fixture_only
        and binding.binding_id.startswith("c011-native-driver-binding:sha256:")
        and adapter.binding_id == binding.binding_id
        and adapter.safety_capabilities.accepted
        and not default_policy.active
        and not default_policy.enabled
        and default_policy.kill_switch_engaged
        and active.active
        and all(getattr(active, name) is False for name in authority_fields)
        and tamper_rejected
        and missing_approval_rejected
        and "provider_binding_id" in LocalNativeDriverResult.model_fields
        and required_exports.issubset(set(facade.__all__))
    )


def _source_boundary() -> bool:
    adapter = (ROOT / "src/luna/parallel_cognition/native_adapter.py").read_text(encoding="utf-8")
    live = (ROOT / "src/luna/parallel_cognition/live.py").read_text(encoding="utf-8")
    forbidden = (
        "subprocess.Popen",
        "import socket",
        "import urllib",
        "ParallelCognitionRuntimeService",
        "luna.runtime",
    )
    required = (
        "SubprocessWorkerBackend(",
        "env",
        "_verify_artifacts()",
        "SHADOW_ELIGIBLE",
        "fixture profiles",
        "provider_binding_id",
    )
    return bool(
        all(marker not in adapter for marker in forbidden)
        and all(marker in adapter for marker in required)
        and "provider_binding_id" not in live
    )


def _verification_matches(verification: object, *, final: bool) -> bool:
    if not isinstance(verification, dict):
        return False
    focused = verification.get("s5b_native_adapter_tests", {})
    full = verification.get("full_local_gate", {})
    if not isinstance(focused, dict) or not isinstance(full, dict):
        return False
    expected = "PASS" if final else "PENDING"
    common = bool(
        focused.get("status") == "PASS"
        and focused.get("passed") == 13
        and focused.get("failed") == 0
        and verification.get("ruff_changed_scope") == "PASS"
        and verification.get("mypy_strict") == "PASS"
        and full.get("status") == expected
        and full.get("ruff") == expected
        and full.get("mypy_strict") == expected
    )
    if not final:
        return common and full.get("verifier_and_cli_chain") == "PENDING"
    return bool(
        common
        and full.get("pytest_passed") == 1409
        and full.get("pytest_skipped_platform") == 1
        and full.get("verifier_and_cli_chain") == "PASS_53_OF_53"
    )


def _receipt_report_manifest_truth() -> bool:
    receipt = json.loads((ROOT / "c011_s5b_verification.json").read_text(encoding="utf-8"))
    update = json.loads((ROOT / "docs/C011_S5B_UPDATE_MANIFEST.json").read_text(encoding="utf-8"))
    report = (ROOT / "docs/C011_S5B_LOCAL_NATIVE_DRIVER_ADAPTER_REPORT.md").read_text(
        encoding="utf-8"
    )
    stage = receipt.get("stage_status")
    final = stage == S5B_ACCEPTED and update.get("stage_status") == S5B_ACCEPTED
    stage_truth = bool(
        (final or (stage == S5B_READY and update.get("stage_status") == S5B_READY))
        and _verification_matches(receipt.get("verification"), final=final)
        and _verification_matches(update.get("verification"), final=final)
    )
    expected_gates = {
        "research_saturation_gate": "NOT_READY",
        "target_spec": "BLOCKED",
        "controlled_execution": "NONE",
    }
    authority = receipt.get("authority", {})
    return bool(
        stage_truth
        and receipt.get("capability") == "C-011"
        and receipt.get("capability_status") == "QUEUED"
        and receipt.get("default_enabled") is False
        and receipt.get("fixture_child_process_executed") is True
        and receipt.get("provider_call_executed") is False
        and receipt.get("live_model_execution") is False
        and receipt.get("controlled_c011_execution") is False
        and receipt.get("hidden_chain_of_thought_access") is False
        and receipt.get("aslm_gates") == expected_gates
        and all(value is False for value in authority.values())
        and update.get("scope_file_count") == len(DECLARED_SCOPE_FILES)
        and set(update.get("scope_files", ())) == DECLARED_SCOPE_FILES
        and update.get("next_evidence_gate") == NEXT_EVIDENCE_GATE
        and update.get("aslm_gates") == expected_gates
        and stage in report
        and NEXT_EVIDENCE_GATE in report
        and "VERIFIED" in report
        and "INFERENCE" in report
        and "OPEN" in report
        and "ASLM Research is a separate project" in report
    )


def _governance_truth() -> bool:
    documents = tuple(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
            ROOT / "docs/LUNA_ROADMAP.md",
            ROOT / "LUNA_HANDOFF.md",
            ROOT / "docs/C011_S5B_LOCAL_NATIVE_DRIVER_ADAPTER_REPORT.md",
        )
    )
    stage = S5B_READY if S5B_READY in documents[-1] else S5B_ACCEPTED
    check = (ROOT / "scripts/check.bat").read_text(encoding="utf-8")
    return bool(
        all(stage in document for document in documents)
        and all("C-011" in document and "QUEUED" in document for document in documents)
        and all("controlled execution: NONE" in document for document in documents)
        and all("Target Spec: BLOCKED" in document for document in documents)
        and all("Research Saturation Gate: NOT_READY" in document for document in documents)
        and "scripts\\verify_c011_s5b.py" in check
        and "[44/62]" in check
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    c011 = build_canonical_capability_registry().get("C-011")
    checks = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
        "c011_capability_remains_queued": c011.status is CapabilityStatus.QUEUED,
        "s5b_adapter_has_no_production_runtime_or_direct_provider_boundary": (_source_boundary()),
        "fixture_binding_policy_and_s4_compatibility": _adapter_contract_gate(),
        "scoped_s5b_receipt_report_manifest_truthful": (_receipt_report_manifest_truth()),
        "governance_gates_are_truthful": _governance_truth(),
    }
    output = {
        "capability": "C-011",
        "stage": "S5B_LOCAL_NATIVE_DRIVER_ADAPTER",
        "checks": checks,
        "missing": missing,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
