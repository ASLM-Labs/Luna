"""Deterministic RFC-C011 S5A provider/profile control-plane gate."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    ModelRolloutStage,
)
from luna.neural import NeuralResourceBudget, NeuralResourceProfile  # noqa: E402
from luna.parallel_cognition import (  # noqa: E402
    ParallelCognitionRole,
    ProviderCapacity,
    ProviderProfileDisposition,
    ProviderProfileRegistry,
    ProviderProfileRequest,
    S5ProviderRoutingPolicy,
    WorkerBudgetEnvelope,
    WorkerProviderKind,
    WorkerProviderProfile,
)

REQUIRED_FILES = (
    "src/luna/parallel_cognition/profiles.py",
    "tests/test_c011_s5_provider_profiles.py",
    "scripts/verify_c011_s5a.py",
    "c011_s5a_verification.json",
    "docs/C011_S5A_PROVIDER_PROFILE_CONTROL_PLANE_REPORT.md",
    "docs/C011_S5A_UPDATE_MANIFEST.json",
)

DECLARED_SCOPE_FILES = frozenset(
    {
        "LUNA_HANDOFF.md",
        "MANIFEST.json",
        "SHA256SUMS.txt",
        "c011_s5a_verification.json",
        "docs/C011_S5A_PROVIDER_PROFILE_CONTROL_PLANE_REPORT.md",
        "docs/C011_S5A_UPDATE_MANIFEST.json",
        "docs/LUNA_ROADMAP.md",
        "docs/NEURAL_NATIVE_BRIDGE_UPDATE_MANIFEST.json",
        "docs/NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json",
        "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
        "scripts/check.bat",
        "scripts/verify_c011_s4.py",
        "scripts/verify_c011_s5a.py",
        "src/luna/parallel_cognition/__init__.py",
        "src/luna/parallel_cognition/profiles.py",
        "tests/test_c011_s5_provider_profiles.py",
        "tests/test_project_metadata.py",
    }
)

S5A_READY = "C011_S5A_READY_FOR_FINAL_GATE"
S5A_ACCEPTED = "C011_S5A_PROVIDER_PROFILE_CONTROL_PLANE_ACCEPTED"


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
        digest = __import__("hashlib").sha256(canonical).hexdigest()
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
            case_id=f"S5A-{index:02d}",
            capability=capability,
            status=ModelCompatibilityStatus.PASS,
            required=True,
            detail="deterministic S5A verifier evidence",
        )
        for index, capability in enumerate(ModelCompatibilityCapability, start=1)
    )
    return ModelCompatibilityReport(
        report_id=UUID("f63be18c-5e27-4646-8be3-b042e78ff16c"),
        backend_id="luna-native-s5",
        results=results,
        created_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )


def _resource_budget(*, cpu_threads: int = 8) -> NeuralResourceBudget:
    return NeuralResourceBudget(
        max_vram_mib=0,
        max_gpu_utilization_percent=0,
        cpu_threads=cpu_threads,
        max_system_ram_mib=32768,
        max_kv_cache_mib=0,
        max_context_tokens=8192,
        batch_size=128,
        max_parallel_generations=1,
        inference_allowed=True,
        model_resident=False,
        background_inference=False,
    )


def _profile(compatibility: ModelCompatibilityReport) -> WorkerProviderProfile:
    return WorkerProviderProfile(
        backend_id=compatibility.backend_id,
        provider_kind=WorkerProviderKind.LUNA_NATIVE_NR2B_SLICE1,
        model_identity="verifier-native-model",
        model_artifact_sha256="a" * 64,
        driver_artifact_sha256="b" * 64,
        compatibility_fingerprint=compatibility.fingerprint(),
        compatibility_evidence_ref="docs/NEURAL_RUNTIME_NR2B_REAL_PROOF_RECEIPT.json",
        resource_profile=NeuralResourceProfile.DESKTOP,
        resource_budget=_resource_budget(),
        capacity=ProviderCapacity(
            max_context_bytes=65536,
            max_result_bytes=32768,
            max_claims=8,
            max_output_tokens=256,
            max_runtime_ms=30000,
            max_total_workers=1,
            max_concurrent_workers=1,
        ),
        allowed_roles=(ParallelCognitionRole.PARALLEL,),
    )


def _request() -> ProviderProfileRequest:
    return ProviderProfileRequest(
        task_id=UUID("58a6fb62-5740-40f1-9b0f-b48d273a3847"),
        assignment_id=f"c011-assignment:sha256:{'c' * 64}",
        worker_role=ParallelCognitionRole.PARALLEL,
        budget=WorkerBudgetEnvelope(
            max_context_bytes=32768,
            max_result_bytes=16384,
            max_claims=4,
            max_tokens=128,
            max_runtime_ms=15000,
            deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        ),
    )


def _source_boundary() -> bool:
    source = (ROOT / "src/luna/parallel_cognition/profiles.py").read_text(encoding="utf-8")
    forbidden = (
        "import os",
        "import socket",
        "import subprocess",
        "import urllib",
        "from pathlib",
        "open(",
        ".generate(",
        "ParallelCognitionRuntimeService",
        "SubprocessWorkerBackend",
    )
    return all(marker not in source for marker in forbidden)


def _contract_gate() -> bool:
    compatibility = _compatibility()
    profile = _profile(compatibility)
    registry = ProviderProfileRegistry((profile,))
    request = _request()
    denied = registry.select(
        request=request,
        policy=S5ProviderRoutingPolicy(),
        compatibility=compatibility,
        current_resource_budget=profile.resource_budget,
    )
    policy = S5ProviderRoutingPolicy(
        enabled=True,
        kill_switch_engaged=False,
        stage=ModelRolloutStage.SHADOW,
        approved_profile_id=profile.profile_id,
        approved_compatibility_fingerprint=profile.compatibility_fingerprint,
        max_total_workers=1,
        max_concurrent_workers=1,
    )
    eligible = registry.select(
        request=request,
        policy=policy,
        compatibility=compatibility,
        current_resource_budget=profile.resource_budget,
    )
    drift = registry.select(
        request=request,
        policy=policy,
        compatibility=compatibility,
        current_resource_budget=_resource_budget(cpu_threads=7),
    )
    tampered = profile.model_dump(mode="json")
    tampered["model_identity"] = "tampered"
    tamper_rejected = False
    active_rejected = False
    try:
        WorkerProviderProfile.model_validate(tampered)
    except ValidationError:
        tamper_rejected = True
    try:
        S5ProviderRoutingPolicy(stage=ModelRolloutStage.ACTIVE)
    except ValidationError:
        active_rejected = True
    required_exports = {
        "ProviderCapacity",
        "ProviderProfileRegistry",
        "ProviderProfileSelection",
        "S5ProviderRoutingPolicy",
        "WorkerProviderProfile",
    }
    authority_values = (
        eligible.provider_call_executed,
        eligible.provider_execution_authority,
        eligible.root_context_adoption_authority,
        eligible.task_state_authority,
        eligible.completion_authority,
        eligible.user_facing_voice_authority,
        eligible.promotion_authority,
    )
    return bool(
        denied.disposition is ProviderProfileDisposition.DENY
        and eligible.disposition is ProviderProfileDisposition.SHADOW_ELIGIBLE
        and drift.disposition is ProviderProfileDisposition.DENY
        and all(value is False for value in authority_values)
        and tamper_rejected
        and active_rejected
        and required_exports.issubset(set(facade.__all__))
    )


def _verification_matches(verification: object, *, final: bool) -> bool:
    if not isinstance(verification, dict):
        return False
    focused = verification.get("s5a_provider_profile_tests", {})
    full = verification.get("full_local_gate", {})
    if not isinstance(focused, dict) or not isinstance(full, dict):
        return False
    expected = "PASS" if final else "PENDING"
    common = bool(
        focused.get("status") == "PASS"
        and focused.get("passed") == 17
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
        and full.get("pytest_passed") == 1395
        and full.get("pytest_skipped_platform") == 1
        and full.get("verifier_and_cli_chain") == "PASS_52_OF_52"
    )


def _receipt_report_manifest_truth() -> bool:
    receipt = json.loads((ROOT / "c011_s5a_verification.json").read_text(encoding="utf-8"))
    update = json.loads((ROOT / "docs/C011_S5A_UPDATE_MANIFEST.json").read_text(encoding="utf-8"))
    report = (ROOT / "docs/C011_S5A_PROVIDER_PROFILE_CONTROL_PLANE_REPORT.md").read_text(
        encoding="utf-8"
    )
    stage = receipt.get("stage_status")
    final = stage == S5A_ACCEPTED and update.get("stage_status") == S5A_ACCEPTED
    stage_truth = bool(
        (final or (stage == S5A_READY and update.get("stage_status") == S5A_READY))
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
        and receipt.get("provider_call_executed") is False
        and receipt.get("live_model_execution") is False
        and receipt.get("controlled_c011_execution") is False
        and receipt.get("hidden_chain_of_thought_access") is False
        and receipt.get("aslm_gates") == expected_gates
        and all(value is False for value in authority.values())
        and update.get("scope_file_count") == len(DECLARED_SCOPE_FILES)
        and set(update.get("scope_files", ())) == DECLARED_SCOPE_FILES
        and update.get("aslm_gates") == expected_gates
        and stage in report
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
            ROOT / "docs/C011_S5A_PROVIDER_PROFILE_CONTROL_PLANE_REPORT.md",
        )
    )
    stage = S5A_READY if S5A_READY in documents[-1] else S5A_ACCEPTED
    check = (ROOT / "scripts/check.bat").read_text(encoding="utf-8")
    return bool(
        all(stage in document for document in documents)
        and all("C-011" in document and "QUEUED" in document for document in documents)
        and all("controlled execution: NONE" in document for document in documents)
        and all("Target Spec: BLOCKED" in document for document in documents)
        and all("Research Saturation Gate: NOT_READY" in document for document in documents)
        and "scripts\\verify_c011_s5a.py" in check
        and "[43/62]" in check
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    c011 = build_canonical_capability_registry().get("C-011")
    checks = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
        "c011_capability_remains_queued": c011.status is CapabilityStatus.QUEUED,
        "profile_module_has_no_provider_or_runtime_io": _source_boundary(),
        "profile_contract_and_fail_closed_selection": _contract_gate(),
        "scoped_s5a_receipt_report_manifest_truthful": (_receipt_report_manifest_truth()),
        "governance_gates_are_truthful": _governance_truth(),
    }
    output = {
        "capability": "C-011",
        "stage": "S5A_PROVIDER_PROFILE_CONTROL_PLANE",
        "checks": checks,
        "missing": missing,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
