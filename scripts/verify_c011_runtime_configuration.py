"""Deterministic repository gate for C-011 real runtime configurations."""

from __future__ import annotations

import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.capabilities import CapabilityStatus, build_canonical_capability_registry  # noqa: E402
from luna.parallel_cognition import (  # noqa: E402
    EqualComputeBudget,
    RealNativeAdapterPoolBinding,
    RealRuntimeAssetBinding,
    RuntimeEffortProfile,
    RuntimeTopology,
    ShadowConfiguration,
    build_default_real_runtime_configuration_set,
)

READY = "C011_REAL_RUNTIME_CONFIGURATION_CONTRACTS_READY_FOR_REPOSITORY_GATE"
ACCEPTED = "C011_REAL_RUNTIME_CONFIGURATION_CONTRACTS_ACCEPTED"
NEXT_GATE = "C011_REAL_EQUAL_COMPUTE_RUNNER_AND_FROZEN_SUITE_PENDING_IMPLEMENTATION"
BASELINE_COMMIT = "00a684f600e5dba74ce7e991e4583af6bc8b0bab"
BASELINE_TREE = "d9849cb6e8bcaf44c793ba8417daccf8ab58c55c"
TARGET_BRANCH = "capability/c011-single-voice-parallel-cognition"
PROOF_SHA256 = "2d3dd1e8a9f3a2abc37948ee95b53d457e5a915e99d0d38ef8eb916939e46aca"
PROOF_STATUS = "PASS_C011_REAL_RUNTIME_CONFIGURATION_TWO_LANE_FULL_CHAIN"

REQUIRED_FILES = frozenset(
    {
        "c011_runtime_configuration_verification.json",
        "docs/C011_RUNTIME_CONFIGURATION_CONTRACT_REPORT.md",
        "docs/C011_RUNTIME_CONFIGURATION_REAL_PROOF_RECEIPT.json",
        "docs/C011_RUNTIME_CONFIGURATION_UPDATE_MANIFEST.json",
        "docs/NEURAL_NATIVE_BRIDGE_UPDATE_MANIFEST.json",
        "docs/NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json",
        "scripts/prove_c011_runtime_configuration.py",
        "scripts/verify_c011_runtime_configuration.py",
        "src/luna/parallel_cognition/live.py",
        "src/luna/parallel_cognition/models.py",
        "src/luna/parallel_cognition/native_adapter.py",
        "src/luna/parallel_cognition/native_pool.py",
        "src/luna/parallel_cognition/runtime_configuration.py",
        "src/luna/parallel_cognition/subprocess_backend.py",
        "tests/test_c011_runtime_configuration.py",
        "tests/test_c011_s5b_native_adapter.py",
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


def _meta(path: Path) -> tuple[str, int]:
    value = _canonical_bytes(path)
    return sha256(value).hexdigest(), len(value)


def _raw_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _json(relative: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((ROOT / relative).read_text(encoding="utf-8")),
    )


def _metadata_truth() -> bool:
    manifest = _json("MANIFEST.json")
    files = manifest.get("files")
    if (
        manifest.get("hash_normalization") != "utf8_text_lf_v1"
        or manifest.get("metadata_scope") != "release_artifact_allowlist_v2"
        or not isinstance(files, dict)
    ):
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
        digest, size = _meta(path)
        if metadata != {"sha256": digest, "size_bytes": size}:
            return False
        if sums.get(relative) != digest:
            return False
    return True


def _source_truth(receipt: dict[str, Any]) -> bool:
    basis = receipt.get("source_basis")
    if not isinstance(basis, dict) or len(basis) != 9:
        return False
    for item in basis.values():
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            return False
        path = ROOT / item["path"]
        if not path.is_file():
            return False
        digest, size = _meta(path)
        if item.get("canonical_text_lf_sha256") != digest:
            return False
        if item.get("size_bytes") != size:
            return False
    return True


def _usage_truth(value: object, *, output_ceiling: int) -> bool:
    if not isinstance(value, dict):
        return False
    input_tokens = value.get("input_tokens")
    output_tokens = value.get("output_tokens")
    total_tokens = value.get("total_tokens")
    return bool(
        value.get("source") == "ENGINE_NATIVE_COUNTERS"
        and type(input_tokens) is int
        and type(output_tokens) is int
        and type(total_tokens) is int
        and input_tokens > 0
        and 0 < output_tokens <= output_ceiling
        and total_tokens == input_tokens + output_tokens
    )


def _configuration_truth(proof: dict[str, Any], receipt: dict[str, Any]) -> bool:
    assets = proof.get("assets")
    if not isinstance(assets, dict):
        return False
    asset_binding = RealRuntimeAssetBinding(
        backend_id=cast(str, proof["backend_id"]),
        provider_profile_id=cast(str, proof["profile_id"]),
        provider_binding_id=cast(str, proof["member_binding_id"]),
        model_identity=(f"{assets['model_source_identity']}@sha256:{assets['model_sha256']}"),
        model_artifact_sha256=cast(str, assets["model_sha256"]),
        bridge_artifact_sha256=cast(str, assets["bridge_sha256"]),
        driver_artifact_sha256=cast(str, assets["driver_sha256"]),
        runtime_bundle_sha256=cast(str, assets["runtime_bundle_sha256"]),
        environment_sha256=cast(str, assets["environment_sha256"]),
        sampling_sha256=_digest("greedy:temperature=0:seed=0:abi-v2"),
    )
    budget = EqualComputeBudget(
        max_total_tokens=2048,
        max_tool_calls=0,
        max_compute_units=1000,
        max_context_bytes=32768,
        max_wall_time_ms=240000,
    )
    configuration = build_default_real_runtime_configuration_set(
        asset_binding=asset_binding,
        equal_compute_budget=budget,
        parallel_workers=2,
    )
    three_worker = build_default_real_runtime_configuration_set(
        asset_binding=asset_binding,
        equal_compute_budget=budget,
        parallel_workers=3,
    )
    pool = RealNativeAdapterPoolBinding(
        member_binding_id=cast(str, proof["member_binding_id"]),
        backend_id=cast(str, proof["backend_id"]),
        profile_id=cast(str, proof["profile_id"]),
        member_count=2,
        max_concurrent_members=2,
    )
    return bool(
        asset_binding.asset_binding_id == proof.get("asset_binding_id")
        and asset_binding.asset_binding_id == receipt.get("asset_binding_id")
        and configuration.configuration_set_id == proof.get("configuration_set_id")
        and configuration.configuration_set_id == receipt.get("configuration_set_id")
        and pool.pool_binding_id == proof.get("pool_binding_id")
        and pool.pool_binding_id == receipt.get("pool_binding_id")
        and {arm.configuration.value: arm.configuration_id for arm in configuration.arms}
        == proof.get("runtime_arm_ids")
        and proof.get("runtime_arm_ids") == receipt.get("runtime_arm_ids")
        and tuple(arm.configuration for arm in configuration.arms) == tuple(ShadowConfiguration)
        and tuple(arm.effort_profile for arm in configuration.arms)
        == (
            RuntimeEffortProfile.STANDARD,
            RuntimeEffortProfile.ULTRA,
            RuntimeEffortProfile.ULTRA,
        )
        and tuple(arm.topology for arm in configuration.arms)
        == (
            RuntimeTopology.ROOT_ONLY,
            RuntimeTopology.ROOT_ONLY,
            RuntimeTopology.ROOT_WITH_READ_ONLY_PARALLEL_WORKERS,
        )
        and tuple(arm.generation_count for arm in configuration.arms) == (1, 2, 3)
        and tuple(arm.worker_count for arm in configuration.arms) == (0, 0, 2)
        and {arm.max_total_output_tokens for arm in configuration.arms} == {256}
        and {arm.normalized_compute_units for arm in configuration.arms} == {1000}
        and three_worker.arms[-1].worker_count == 3
        and three_worker.arms[-1].generation_count == 4
        and three_worker.arms[-1].max_total_output_tokens == 256
        and not any(
            (
                configuration.runtime_authority,
                configuration.task_state_authority,
                configuration.root_context_adoption_authority,
                configuration.completion_authority,
                configuration.user_facing_voice_authority,
                configuration.canary_authority,
                configuration.active_authority,
                configuration.promotion_authority,
            )
        )
    )


def _proof_truth(receipt: dict[str, Any]) -> bool:
    proof_path = ROOT / "docs/C011_RUNTIME_CONFIGURATION_REAL_PROOF_RECEIPT.json"
    proof = _json("docs/C011_RUNTIME_CONFIGURATION_REAL_PROOF_RECEIPT.json")
    digest, _ = _meta(proof_path)
    results = proof.get("results")
    assets = proof.get("assets")
    prior = _json("docs/C011_NATIVE_ABI_V2_REAL_PROOF_RECEIPT.json")
    if not isinstance(results, list) or not isinstance(assets, dict):
        return False
    output_ceiling = proof.get("worker_output_token_ceiling")
    return bool(
        digest == PROOF_SHA256
        and receipt.get("real_model_evidence", {}).get("proof_canonical_sha256") == PROOF_SHA256
        and proof.get("scope") == "C011_REAL_RUNTIME_CONFIGURATION_TWO_LANE_PROOF"
        and proof.get("status") == PROOF_STATUS
        and proof.get("baseline_commit") == BASELINE_COMMIT
        and proof.get("parallel_workers") == 2
        and proof.get("provider_calls_executed") == 2
        and proof.get("max_concurrent_observed") == 2
        and proof.get("pool_exhausted_without_replay") is True
        and proof.get("native_usage_survived_result_boundary") is True
        and output_ceiling == 64
        and len(results) == 2
        and len({item.get("request_id") for item in results}) == 2
        and len({item.get("result_id") for item in results}) == 2
        and {item.get("role") for item in results} == {"PARALLEL", "INDEPENDENT_REVIEWER"}
        and all(
            item.get("outcome_state") == "RESULT_RECEIVED"
            and item.get("cleanup_state") == "CLEANUP_COMPLETE"
            and item.get("canonical_final") == "READY."
            and item.get("claims_count") == 0
            and item.get("analysis_content_emitted") is False
            and _usage_truth(item.get("usage"), output_ceiling=64)
            for item in results
        )
        and assets.get("asset_pre_post_integrity") == "PASS"
        and assets.get("bridge_abi_version") == 2
        and assets.get("bridge_sha256") == prior.get("bridge_binary_sha256")
        and assets.get("model_sha256") == prior.get("model_sha256")
        and assets.get("driver_sha256")
        == _raw_sha256(ROOT / "src/luna/parallel_cognition/native_real_driver.py")
        and proof.get("repository_pre_post_status_unchanged") is True
        and proof.get("runtime_configuration_set_constructed") is True
        and proof.get("full_three_arm_runner_executed") is False
        and proof.get("production_runtime_wiring_added") is False
        and proof.get("controlled_c011_execution") is False
        and proof.get("hidden_chain_of_thought_access") is False
        and not any(proof.get("authority", {}).values())
        and proof.get("aslm_gates")
        == {
            "research_saturation_gate": "NOT_READY",
            "target_spec": "BLOCKED",
            "controlled_execution": "NONE",
        }
        and _configuration_truth(proof, receipt)
    )


def _usage_boundary_truth() -> bool:
    live = (ROOT / "src/luna/parallel_cognition/live.py").read_text(encoding="utf-8")
    backend = (ROOT / "src/luna/parallel_cognition/subprocess_backend.py").read_text(
        encoding="utf-8"
    )
    adapter = (ROOT / "src/luna/parallel_cognition/native_adapter.py").read_text(encoding="utf-8")
    models = (ROOT / "src/luna/parallel_cognition/models.py").read_text(encoding="utf-8")
    return bool(
        "native_usage: LiveNativeTokenUsage | None = None" in live
        and "self.native_usage.output_tokens" in live
        and "native_usage.output_tokens" in backend
        and "native_usage=native_usage" in backend
        and "real result requires engine-native usage" in adapter
        and "generated-output ceiling" in models
        and "full input/output/total measurement" in models
    )


def _prerequisite_truth(receipt: dict[str, Any]) -> bool:
    current = receipt.get("preflight_prerequisites_after")
    if not isinstance(current, dict):
        return False
    return bool(
        set(current.get("verified_local", []))
        == {
            "CURRENT_ASSET_BINDING",
            "MEASURED_TOKEN_ACCOUNTING",
            "PARALLEL_RUNTIME_CONTRACT",
            "SOLO_RUNTIME_CONTRACT",
            "ULTRA_SOLO_RUNTIME_CONTRACT",
        }
        and set(current.get("partial", []))
        == {"HARDWARE_RESOURCE_ATTESTATION", "SAFETY_CONTAINMENT_ATTESTATION"}
        and set(current.get("open_external_or_evaluation", []))
        == {
            "CONTAMINATION_PROVENANCE_ATTESTATION",
            "EXTERNAL_LEDGER_ANCHOR",
            "INDEPENDENT_EVALUATOR_ATTESTATION",
            "REPRESENTATIVE_FROZEN_SUITE",
        }
        and current.get("rejected") == []
    )


def _verification_truth(receipt: dict[str, Any], update: dict[str, Any]) -> bool:
    verification = receipt.get("verification")
    if not isinstance(verification, dict) or verification != update.get("verification"):
        return False
    full = verification.get("repository_full_gate")
    stage = receipt.get("stage_status")
    if not isinstance(full, dict) or stage != update.get("stage_status"):
        return False
    if stage == READY:
        full_truth = bool(
            full.get("status") == "PENDING"
            and full.get("pytest_passed") is None
            and full.get("ruff") == "PENDING"
            and full.get("mypy_strict") == "PENDING"
            and full.get("verifier_and_cli_chain") == "PENDING"
        )
    elif stage == ACCEPTED:
        full_truth = bool(
            full.get("status") == "PASS"
            and full.get("pytest_passed") == 1521
            and full.get("pytest_skipped_platform") == 1
            and full.get("ruff") == "PASS"
            and full.get("mypy_strict") == "PASS_317_FILES"
            and full.get("verifier_and_cli_chain") == "PASS_61_OF_61"
            and full.get("execution_environment") == "EXACT_STAGED_TREE_SHORT_WINDOWS_TEMP_PATH"
        )
    else:
        return False
    return bool(
        full_truth
        and verification.get("focused_contract_and_adversarial_tests") == "PASS_256"
        and verification.get("changed_scope_ruff") == "PASS"
        and verification.get("changed_scope_mypy_strict") == "PASS_7_FILES"
        and verification.get("real_two_lane_full_chain") == "PASS_2_OF_2"
    )


def _governance_truth(stage: str) -> bool:
    documents = tuple(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "LUNA_HANDOFF.md",
            ROOT / "docs/LUNA_ROADMAP.md",
            ROOT / "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
            ROOT / "docs/C011_RUNTIME_CONFIGURATION_CONTRACT_REPORT.md",
        )
    )
    check = (ROOT / "scripts/check.bat").read_text(encoding="utf-8")
    return bool(
        all(stage in document and NEXT_GATE in document for document in documents)
        and all("controlled C-011 execution: NONE" in document for document in documents)
        and all("Research Saturation Gate: NOT_READY" in document for document in documents)
        and all("Target Spec: BLOCKED" in document for document in documents)
        and all("chain-of-thought access" in document.lower() for document in documents)
        and "scripts\\verify_c011_runtime_configuration.py" in check
        and "[52/62]" in check
        and "S5D-E4" in check
    )


def main() -> int:
    receipt = _json("c011_runtime_configuration_verification.json")
    update = _json("docs/C011_RUNTIME_CONFIGURATION_UPDATE_MANIFEST.json")
    stage = cast(str, receipt.get("stage_status"))
    scope_files = update.get("scope_files")
    authority = receipt.get("authority")
    c011 = build_canonical_capability_registry().get("C-011")
    checks = {
        "required_files_present": all((ROOT / item).is_file() for item in REQUIRED_FILES),
        "metadata_integrity": _metadata_truth(),
        "receipt_identity": receipt.get("stage") == "S5D_E4_REAL_RUNTIME_CONFIGURATION_CONTRACTS"
        and stage in {READY, ACCEPTED}
        and receipt.get("baseline_commit") == BASELINE_COMMIT
        and receipt.get("baseline_tree") == BASELINE_TREE
        and receipt.get("target_branch") == TARGET_BRANCH,
        "declared_scope_complete": isinstance(scope_files, list)
        and len(scope_files) == len(set(scope_files))
        and REQUIRED_FILES.issubset(scope_files)
        and update.get("scope_file_count") == len(scope_files),
        "c011_remains_queued_default_off": c011.status is CapabilityStatus.QUEUED
        and receipt.get("capability_status") == "QUEUED"
        and receipt.get("default_enabled") is False
        and receipt.get("rollout_stage") == "BLOCKED",
        "source_basis_content_addressed": _source_truth(receipt),
        "runtime_configurations_frozen": _configuration_truth(
            _json("docs/C011_RUNTIME_CONFIGURATION_REAL_PROOF_RECEIPT.json"), receipt
        ),
        "native_usage_boundary_fail_closed": _usage_boundary_truth(),
        "real_two_lane_proof_content_addressed": _proof_truth(receipt),
        "preflight_prerequisites_truthful": _prerequisite_truth(receipt),
        "verification_truthful": _verification_truth(receipt, update),
        "authority_remains_absent": isinstance(authority, dict)
        and authority
        and all(value is False for value in authority.values())
        and receipt.get("controlled_c011_execution") is False
        and receipt.get("production_runtime_wiring_added") is False
        and receipt.get("real_equal_compute_triplet_executed") is False
        and receipt.get("hidden_chain_of_thought_access") is False,
        "aslm_gates_unchanged": receipt.get("aslm_gates")
        == {
            "research_saturation_gate": "NOT_READY",
            "target_spec": "BLOCKED",
            "controlled_execution": "NONE",
        }
        and receipt.get("aslm_gates") == update.get("aslm_gates"),
        "next_gate_locked": receipt.get("next_gate") == NEXT_GATE
        and update.get("next_gate") == NEXT_GATE,
        "governance_boundaries_truthful": _governance_truth(stage),
    }
    print(
        json.dumps(
            {
                "capability": "C-011",
                "stage": "S5D_E4_REAL_RUNTIME_CONFIGURATION_CONTRACTS",
                "stage_status": stage,
                "checks": checks,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
