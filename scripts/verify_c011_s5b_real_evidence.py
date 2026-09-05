"""Deterministic gate for the C-011 S5B real local-native evidence receipt."""

from __future__ import annotations

import json
import re
import sys
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.capabilities import (  # noqa: E402
    CapabilityStatus,
    build_canonical_capability_registry,
)

STAGE = "C011_S5B_REAL_LOCAL_NATIVE_EVIDENCE_ACCEPTED"
NEXT_GATE = "C011_S5B_REAL_ADAPTER_EXECUTION_PENDING_IMPLEMENTATION"
REQUIRED_FILES = (
    "c011_s5b_real_evidence.json",
    "docs/C011_S5B_REAL_LOCAL_NATIVE_EVIDENCE_REPORT.md",
    "docs/C011_S5B_REAL_EVIDENCE_UPDATE_MANIFEST.json",
    "scripts/verify_c011_s5b_real_evidence.py",
)
DECLARED_SCOPE_FILES = frozenset(
    {
        "LUNA_HANDOFF.md",
        "MANIFEST.json",
        "SHA256SUMS.txt",
        "c011_s5b_real_evidence.json",
        "docs/C011_S5B_REAL_EVIDENCE_UPDATE_MANIFEST.json",
        "docs/C011_S5B_REAL_LOCAL_NATIVE_EVIDENCE_REPORT.md",
        "docs/LUNA_ROADMAP.md",
        "docs/NEURAL_NATIVE_BRIDGE_UPDATE_MANIFEST.json",
        "docs/NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json",
        "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
        "scripts/check.bat",
        "scripts/verify_c011_s4.py",
        "scripts/verify_c011_s5a.py",
        "scripts/verify_c011_s5b.py",
        "scripts/verify_c011_s5b_real_evidence.py",
        "tests/test_project_metadata.py",
    }
)


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


def _receipt() -> dict[str, object]:
    return json.loads((ROOT / "c011_s5b_real_evidence.json").read_text(encoding="utf-8"))


def _asset_and_host_truth() -> bool:
    receipt = _receipt()
    assets = receipt.get("asset_evidence")
    host = receipt.get("host_observation")
    budget = receipt.get("execution_budget")
    if not all(isinstance(item, dict) for item in (assets, host, budget)):
        return False
    assert isinstance(assets, dict)
    assert isinstance(host, dict)
    assert isinstance(budget, dict)
    runtime_files = assets.get("runtime_files")
    if not isinstance(runtime_files, list) or len(runtime_files) != 18:
        return False
    names: list[str] = []
    for item in runtime_files:
        if not isinstance(item, dict):
            return False
        name = item.get("name")
        digest = item.get("sha256")
        size = item.get("size_bytes")
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[0-9a-f]{64}", str(digest)) is None
            or not isinstance(size, int)
            or size <= 0
        ):
            return False
        names.append(name)
    expected_runtime = {
        "ggml-base.dll",
        "ggml.dll",
        "libomp140.x86_64.dll",
        "llama.dll",
    }
    return bool(
        len(names) == len(set(names))
        and expected_runtime.issubset(set(names))
        and all("cuda" not in name.lower() and "cublas" not in name.lower() for name in names)
        and assets.get("model_sha256")
        == "27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901"
        and assets.get("model_size_bytes") == 12109566624
        and assets.get("bridge_sha256")
        == "506d320f0d811e54192b852f81e62330de9662f26dceb3c7befe788bf9bfadfb"
        and assets.get("bridge_abi_version") == 1
        and assets.get("proof_driver_sha256")
        == "5dabf981447e29445934367401cd69bbc123a4ab5321a575329f60f714ed647d"
        and assets.get("pre_post_hashes_match") is True
        and assets.get("cuda_runtime_present") is False
        and host.get("cpu_cores") == 16
        and host.get("cpu_logical_processors") == 24
        and host.get("gpu_adapter_ram_wmi_is_capacity_authority") is False
        and budget.get("cpu_threads") == 8
        and budget.get("max_vram_mib") == 0
        and budget.get("max_gpu_utilization_percent") == 0
        and budget.get("max_parallel_generations") == 1
        and budget.get("max_output_tokens") == 256
        and budget.get("model_resident") is False
    )


def _proof_truth() -> bool:
    receipt = _receipt()
    proof = receipt.get("proof_observation")
    if not isinstance(proof, dict):
        return False
    return bool(
        receipt.get("stage_status") == STAGE
        and receipt.get("capability_status") == "QUEUED"
        and receipt.get("default_enabled") is False
        and receipt.get("real_local_native_inference_executed") is True
        and receipt.get("s5b_adapter_execution_executed") is False
        and receipt.get("controlled_c011_execution") is False
        and proof.get("status") == "PASS_REPO_OWNED_BRIDGE_LUNANATIVEWORKER_FULL_CHAIN"
        and proof.get("exit_code") == 0
        and proof.get("worker_state_before") == "STOPPED"
        and proof.get("worker_state_after") == "STOPPED"
        and proof.get("response_request_id_match") is True
        and proof.get("response_finish_reason") == "STOP"
        and proof.get("stream_event_types") == ["TEXT_DELTA", "FINISH"]
        and proof.get("canonical_final") == "Yes, I'm ready to work today."
        and proof.get("analysis_content_emitted") is False
        and proof.get("persistent_residency_claimed") is False
        and proof.get("primary_path_promoted") is False
    )


def _scope_and_verification_truth() -> bool:
    receipt = _receipt()
    update = json.loads(
        (ROOT / "docs/C011_S5B_REAL_EVIDENCE_UPDATE_MANIFEST.json").read_text(encoding="utf-8")
    )
    report = (ROOT / "docs/C011_S5B_REAL_LOCAL_NATIVE_EVIDENCE_REPORT.md").read_text(
        encoding="utf-8"
    )
    verification = receipt.get("verification")
    update_verification = update.get("verification")
    if not isinstance(verification, dict) or verification != update_verification:
        return False
    full = verification.get("repository_full_gate")
    if not isinstance(full, dict):
        return False
    expected_gates = {
        "research_saturation_gate": "NOT_READY",
        "target_spec": "BLOCKED",
        "controlled_execution": "NONE",
    }
    authority = receipt.get("authority")
    return bool(
        update.get("stage_status") == STAGE
        and update.get("next_code_gate") == NEXT_GATE
        and update.get("scope_file_count") == len(DECLARED_SCOPE_FILES)
        and set(update.get("scope_files", ())) == DECLARED_SCOPE_FILES
        and verification.get("external_asset_pre_post_integrity") == "PASS"
        and verification.get("real_native_probe") == "PASS"
        and full.get("status") == "PASS"
        and full.get("pytest_passed") == 1410
        and full.get("pytest_skipped_platform") == 1
        and full.get("ruff") == "PASS"
        and full.get("mypy_strict") == "PASS"
        and full.get("verifier_and_cli_chain") == "PASS_54_OF_54"
        and receipt.get("aslm_gates") == expected_gates
        and update.get("aslm_gates") == expected_gates
        and isinstance(authority, dict)
        and all(value is False for value in authority.values())
        and STAGE in report
        and NEXT_GATE in report
        and all(label in report for label in ("VERIFIED", "INFERENCE", "OPEN"))
        and "ASLM Research is a separate project" in report
    )


def _governance_and_boundary_truth() -> bool:
    documents = tuple(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "LUNA_HANDOFF.md",
            ROOT / "docs/LUNA_ROADMAP.md",
            ROOT / "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
        )
    )
    adapter = (ROOT / "src/luna/parallel_cognition/native_adapter.py").read_text(encoding="utf-8")
    check = (ROOT / "scripts/check.bat").read_text(encoding="utf-8")
    return bool(
        all(STAGE in document and NEXT_GATE in document for document in documents)
        and all("controlled execution: NONE" in document for document in documents)
        and all("Research Saturation Gate: NOT_READY" in document for document in documents)
        and all("Target Spec: BLOCKED" in document for document in documents)
        and "DETERMINISTIC_FIXTURE" in adapter
        and "fixture profiles" in adapter
        and "scripts\\verify_c011_s5b_real_evidence.py" in check
        and "[45/62]" in check
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    c011 = build_canonical_capability_registry().get("C-011")
    checks = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
        "c011_capability_remains_queued": c011.status is CapabilityStatus.QUEUED,
        "external_asset_and_host_receipt_truthful": _asset_and_host_truth(),
        "real_native_proof_observation_truthful": _proof_truth(),
        "scope_verification_and_authority_truthful": _scope_and_verification_truth(),
        "adapter_boundary_and_governance_truthful": _governance_and_boundary_truth(),
    }
    print(
        json.dumps(
            {
                "capability": "C-011",
                "stage": "S5B_REAL_LOCAL_NATIVE_EVIDENCE",
                "checks": checks,
                "missing": missing,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
