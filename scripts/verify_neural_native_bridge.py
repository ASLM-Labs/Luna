# Deterministic verifier for Luna repository-owned native bridge governance.

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "native" / "neural_bridge" / "bridge_contract.json"
BRIDGE_SOURCE = ROOT / "native" / "neural_bridge" / "luna_nr2b_shim_harmony.cpp"
BUILD_SCRIPT = ROOT / "scripts" / "build_neural_native_bridge.ps1"
NATIVE_PROCESS = ROOT / "src" / "luna" / "neural" / "native_worker_process.py"
RECEIPT = ROOT / "docs" / "NEURAL_NATIVE_BRIDGE_REAL_PROOF_RECEIPT.json"
REPORT = ROOT / "docs" / "NEURAL_NATIVE_BRIDGE_REPORT.md"
UPDATE_MANIFEST = ROOT / "docs" / "NEURAL_NATIVE_BRIDGE_UPDATE_MANIFEST.json"

EXPECTED_SCOPE = "LUNA_NATIVE_BRIDGE_BUILD_GOVERNANCE"
EXPECTED_STATUS = "IMPLEMENTED_VERIFIED_FOR_SCOPE"
EXPECTED_SOURCE_SHA = "6D130A9B53B6014ECBAE91276E15478E4424DE7EA72CCFC35E087D8DDAFA8FF1"
EXPECTED_EXTERNAL_SOURCE_SHA = "EE88E17E52565FA0B12634E41CFC1F908F9C2898677B3F67745116B178562804"
EXPECTED_BINARY_SHA = "506D320F0D811E54192B852F81E62330DE9662F26DCEB3C7BEFE788BF9BFADFB"
EXPECTED_PROOF_RAW_SHA = "0A2B8B406F2CFED3C82A81FA4F3CC564701CDDF0C0AF44B56348E71605A60694"
EXPECTED_PROOF_NORMALIZED_SHA = "6033E8F60F6A40239545526EADF1B088DB81C2B01FD47FC6B3FDEF7F3C05EE83"
EXPECTED_LLAMA_COMMIT = "08659901c43b51de735740f1cf61bb82fbe0c4e4"
EXPECTED_LLAMA_TAG = "b10333"

EXPECTED_EXPORTS = {
    "luna_nr2b_abi_version",
    "luna_nr2b_engine_create",
    "luna_nr2b_generate",
    "luna_nr2b_engine_destroy",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _normalized_meta(path: Path) -> tuple[str, int]:
    text = path.read_bytes().decode("utf-8-sig")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    data = text.encode("utf-8")
    return hashlib.sha256(data).hexdigest(), len(data)


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    update_manifest = json.loads(UPDATE_MANIFEST.read_text(encoding="utf-8"))

    source_hash = _sha256(BRIDGE_SOURCE)
    if source_hash != EXPECTED_SOURCE_SHA:
        raise SystemExit("bridge source hash mismatch")
    if contract["bridge_source_sha256"] != EXPECTED_SOURCE_SHA:
        raise SystemExit("contract source hash mismatch")
    if contract["schema_version"] != 1:
        raise SystemExit("bridge contract schema mismatch")
    if contract["scope"] != EXPECTED_SCOPE:
        raise SystemExit("bridge contract scope mismatch")
    if contract["status"] != EXPECTED_STATUS:
        raise SystemExit("bridge contract status mismatch")

    provenance = contract["bridge_source_provenance"]
    if provenance["external_proof_source_sha256"] != EXPECTED_EXTERNAL_SOURCE_SHA:
        raise SystemExit("external proof-source provenance mismatch")
    if provenance["normalization"] != "append_final_lf_if_missing_only":
        raise SystemExit("unexpected bridge-source normalization")
    if provenance["byte_changes_other_than_final_lf"] is not False:
        raise SystemExit("bridge-source provenance permits extra byte changes")

    if set(contract["required_exports"]) != EXPECTED_EXPORTS:
        raise SystemExit("bridge ABI export contract mismatch")
    if contract["llama_cpp"]["commit"] != EXPECTED_LLAMA_COMMIT:
        raise SystemExit("llama.cpp commit mismatch")
    if contract["llama_cpp"]["tag"] != EXPECTED_LLAMA_TAG:
        raise SystemExit("llama.cpp tag mismatch")
    if contract["llama_cpp"]["vendored"] is not False:
        raise SystemExit("llama.cpp vendoring boundary changed")
    if contract["runtime_assets"]["vendored"] is not False:
        raise SystemExit("runtime-asset vendoring boundary changed")
    if any(contract["authority"].values()):
        raise SystemExit("native bridge contract expanded authority")

    verification = contract["verification"]
    if verification["real_full_chain_proof_locked"] is not True:
        raise SystemExit("real full-chain proof is not locked")
    if verification["repo_built_bridge_sha256"] != EXPECTED_BINARY_SHA:
        raise SystemExit("repo-built bridge binary SHA mismatch")
    if verification["proof_raw_sha256"] != EXPECTED_PROOF_RAW_SHA:
        raise SystemExit("proof raw SHA mismatch in contract")
    if verification["proof_normalized_sha256"] != EXPECTED_PROOF_NORMALIZED_SHA:
        raise SystemExit("proof normalized SHA mismatch in contract")

    if receipt["status"] != "PASS_REPO_OWNED_BRIDGE_LUNANATIVEWORKER_FULL_CHAIN":
        raise SystemExit("real proof receipt status mismatch")
    if receipt["proof_raw_sha256"] != EXPECTED_PROOF_RAW_SHA:
        raise SystemExit("real proof raw SHA mismatch")
    if receipt["proof_normalized_sha256"] != EXPECTED_PROOF_NORMALIZED_SHA:
        raise SystemExit("real proof normalized SHA mismatch")
    if receipt["bridge_source_sha256"] != EXPECTED_SOURCE_SHA:
        raise SystemExit("receipt bridge source SHA mismatch")
    if receipt["repo_built_bridge_sha256"] != EXPECTED_BINARY_SHA:
        raise SystemExit("receipt repo-built DLL SHA mismatch")
    if receipt["probe_exit_code"] != 0:
        raise SystemExit("real proof exit code mismatch")
    if receipt["analysis_content_emitted"] is not False:
        raise SystemExit("receipt claims analysis emission")
    if receipt["llama_cli_required_for_this_path"] is not False:
        raise SystemExit("receipt unexpectedly requires llama-cli")
    if receipt["persistent_residency_claimed"] is not False:
        raise SystemExit("receipt claims persistent residency")
    if receipt["gpu_budget_enforcement_claimed"] is not False:
        raise SystemExit("receipt claims GPU budget enforcement")
    if receipt["primary_path_promoted"] is not False:
        raise SystemExit("receipt claims primary-path promotion")
    if receipt["identity_test_executed"] is not False:
        raise SystemExit("receipt claims identity test execution")
    if receipt["exact_6_path_package_preserved"] is not True:
        raise SystemExit("proof did not preserve the exact six-path package")
    if receipt["package_file_hashes_unchanged"] is not True:
        raise SystemExit("proof package hashes were not stable")
    if receipt["unexpected_repo_byproducts"] != 0:
        raise SystemExit("proof observed unexpected repo byproducts")

    native_source = NATIVE_PROCESS.read_text(encoding="utf-8")
    for export in EXPECTED_EXPORTS:
        if export not in native_source:
            raise SystemExit(f"Python native binding missing ABI symbol: {export}")

    build_source = BUILD_SCRIPT.read_text(encoding="utf-8")
    required_build_markers = (
        '/Fo`"$ObjectPath`"',
        "OutputDir must be outside the Luna repository.",
        '$RepoPrefix = $RepoNormalized + [System.IO.Path]::DirectorySeparatorChar',
        "$OutputNormalized.StartsWith(",
        "PASS_REPO_OWNED_NATIVE_BRIDGE_BUILD",
        "bridge_contract.json",
        "dumpbin.exe /nologo /exports",
        "lib.exe /nologo /machine:x64",
        "cl.exe /nologo /std:c++17",
    )
    for marker in required_build_markers:
        if marker not in build_source:
            raise SystemExit(f"build contract marker missing: {marker}")
    if "$OutputDir.StartsWith($RepoFull" in build_source:
        raise SystemExit("unsafe raw string-prefix path guard returned")

    if update_manifest["scope"] != EXPECTED_SCOPE:
        raise SystemExit("update manifest scope mismatch")
    if update_manifest["status"] != EXPECTED_STATUS:
        raise SystemExit("update manifest status mismatch")
    for relative, expected in update_manifest["files"].items():
        actual_sha, actual_size = _normalized_meta(ROOT / relative)
        if actual_sha != expected["sha256"]:
            raise SystemExit(f"update manifest hash mismatch: {relative}")
        if actual_size != expected["size_bytes"]:
            raise SystemExit(f"update manifest size mismatch: {relative}")

    report_text = REPORT.read_text(encoding="utf-8")
    required_report_markers = (
        "IMPLEMENTED_VERIFIED_FOR_SCOPE",
        "PENDING_FINAL_WINDOWS_GATE_AND_MERGE",
        "PASS_REPO_OWNED_BRIDGE_LUNANATIVEWORKER_FULL_CHAIN",
        "No primary-path promotion",
    )
    for marker in required_report_markers:
        if marker not in report_text:
            raise SystemExit(f"closure report marker missing: {marker}")

    print(
        json.dumps(
            {
                "scope": EXPECTED_SCOPE,
                "status": EXPECTED_STATUS,
                "bridge_source_sha256": source_hash,
                "external_proof_source_sha256": EXPECTED_EXTERNAL_SOURCE_SHA,
                "repo_built_bridge_sha256": EXPECTED_BINARY_SHA,
                "proof_raw_sha256": EXPECTED_PROOF_RAW_SHA,
                "proof_normalized_sha256": EXPECTED_PROOF_NORMALIZED_SHA,
                "llama_cpp_commit": EXPECTED_LLAMA_COMMIT,
                "llama_cpp_tag": EXPECTED_LLAMA_TAG,
                "abi_version": contract["abi_version"],
                "required_exports": sorted(EXPECTED_EXPORTS),
                "object_output_is_build_scoped": True,
                "path_containment_boundary_safe": True,
                "real_full_chain_proof_locked": True,
                "raw_analysis_emission": False,
                "llama_cli_required": False,
                "persistent_residency_claimed": False,
                "gpu_budget_enforcement_claimed": False,
                "primary_path_promoted": False,
                "identity_test_executed": False,
                "authority_expansion": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
