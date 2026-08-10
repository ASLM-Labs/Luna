from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "native" / "neural_bridge" / "bridge_contract.json"
BRIDGE = ROOT / "native" / "neural_bridge" / "luna_nr2b_shim_harmony.cpp"
BUILD_SCRIPT = ROOT / "scripts" / "build_neural_native_bridge.ps1"
RECEIPT = ROOT / "docs" / "NEURAL_NATIVE_BRIDGE_REAL_PROOF_RECEIPT.json"


def _contract() -> dict[str, object]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _receipt() -> dict[str, object]:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_bridge_source_hash_is_locked() -> None:
    contract = _contract()
    digest = hashlib.sha256(BRIDGE.read_bytes()).hexdigest().upper()
    assert digest == "6D130A9B53B6014ECBAE91276E15478E4424DE7EA72CCFC35E087D8DDAFA8FF1"
    assert digest == contract["bridge_source_sha256"]


def test_llama_cpp_revision_is_pinned() -> None:
    contract = _contract()
    llama = contract["llama_cpp"]
    assert isinstance(llama, dict)
    assert llama["tag"] == "b10333"
    assert llama["commit"] == "08659901c43b51de735740f1cf61bb82fbe0c4e4"
    assert llama["vendored"] is False


def test_bridge_abi_surface_is_exact() -> None:
    contract = _contract()
    assert set(contract["required_exports"]) == {
        "luna_nr2b_abi_version",
        "luna_nr2b_engine_create",
        "luna_nr2b_generate",
        "luna_nr2b_engine_destroy",
    }


def test_build_output_guard_is_directory_boundary_aware() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert '$RepoPrefix = $RepoNormalized + [System.IO.Path]::DirectorySeparatorChar' in source
    assert "$OutputNormalized.StartsWith(" in source
    assert "$RepoPrefix," in source
    assert "$OutputDir.StartsWith($RepoFull" not in source
    assert '/Fo`"$ObjectPath`"' in source


def test_no_authority_expansion_is_declared() -> None:
    contract = _contract()
    authority = contract["authority"]
    assert isinstance(authority, dict)
    assert not any(authority.values())


def test_repo_owned_bridge_is_verified_for_scope() -> None:
    contract = _contract()
    assert contract["scope"] == "LUNA_NATIVE_BRIDGE_BUILD_GOVERNANCE"
    assert contract["status"] == "IMPLEMENTED_VERIFIED_FOR_SCOPE"
    verification = contract["verification"]
    assert isinstance(verification, dict)
    assert verification["real_full_chain_proof_locked"] is True
    assert verification["repo_built_bridge_sha256"] == (
        "506D320F0D811E54192B852F81E62330DE9662F26DCEB3C7BEFE788BF9BFADFB"
    )


def test_real_proof_receipt_preserves_nonclaims() -> None:
    receipt = _receipt()
    assert receipt["status"] == "PASS_REPO_OWNED_BRIDGE_LUNANATIVEWORKER_FULL_CHAIN"
    assert receipt["proof_raw_sha256"] == (
        "0A2B8B406F2CFED3C82A81FA4F3CC564701CDDF0C0AF44B56348E71605A60694"
    )
    assert receipt["proof_normalized_sha256"] == (
        "6033E8F60F6A40239545526EADF1B088DB81C2B01FD47FC6B3FDEF7F3C05EE83"
    )
    assert receipt["probe_exit_code"] == 0
    assert receipt["analysis_content_emitted"] is False
    assert receipt["llama_cli_required_for_this_path"] is False
    assert receipt["persistent_residency_claimed"] is False
    assert receipt["gpu_budget_enforcement_claimed"] is False
    assert receipt["primary_path_promoted"] is False
    assert receipt["identity_test_executed"] is False
