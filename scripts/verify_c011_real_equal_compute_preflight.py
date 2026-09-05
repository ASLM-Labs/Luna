"""Deterministic repository gate for the C-011 real equal-compute preflight."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.capabilities import (  # noqa: E402
    CapabilityStatus,
    build_canonical_capability_registry,
)
from luna.parallel_cognition import (  # noqa: E402
    RealEqualComputeEvidenceClass,
    RealEqualComputeEvidenceReference,
    RealEqualComputeEvidenceState,
    RealEqualComputePreflightDecision,
    RealEqualComputePreflightDisposition,
    RealEqualComputePreflightPolicy,
    RealEqualComputePreflightSnapshot,
    RealEqualComputePrerequisite,
    RealEqualComputePrerequisiteEvidence,
    evaluate_real_equal_compute_preflight,
)

READY = "C011_REAL_EQUAL_COMPUTE_EXTERNAL_EVIDENCE_PREFLIGHT_READY_FOR_REPOSITORY_GATE"
ACCEPTED = "C011_REAL_EQUAL_COMPUTE_EXTERNAL_EVIDENCE_PREFLIGHT_ACCEPTED_BLOCKED"
NEXT_GATE = (
    "C011_REAL_EQUAL_COMPUTE_RUNTIME_ACCOUNTING_CONTRACT_BLOCKED_"
    "PENDING_SEPARATE_OWNER_AUTHORIZATION"
)
BASELINE_COMMIT = "dcc0c25e1e34d7ce4ea8bcb2c77bfa17e7ca64ff"
BASELINE_TREE = "ce68639c9e593b30ee4b3d8405377359d7bfa867"
TARGET_BRANCH = "capability/c011-single-voice-parallel-cognition"
EVALUATED_AT = datetime(2026, 9, 1, 4, 0, 25, tzinfo=UTC)
NATIVE_DRIVER_SHA256 = "5a6361323c8b9c2e4dab1f639c32c097ae7d58873a5611fbb6d5dd6207048e23"
REAL_PROOF_SHA256 = "49d2db4a3fd0074e6a3c12de319ce2a1d4726db854386dfae985bb54f4e8afb0"
S5B_RECEIPT_SHA256 = "75f99933be8780406384bd62d5bc8a646570045d2b901a57adc5c27f63c01a85"
S5C_RECEIPT_SHA256 = "2611e4ca8cfe1b20f660e793b2d76974c1477b19446baad9b0b4009949761bb0"
S5D_RECEIPT_SHA256 = "54d0c16672abb25eed8936ad9794709a276400ec3f4a69b1cb67bc04ba175432"
PREFLIGHT_RECEIPT_SHA256 = "3036e03b916054634723d862f9c35bc79bbd75cfa7e4a683fa2f382fca56e2f2"
RUNTIME_ACCOUNTING_RECEIPT_SHA256 = (
    "4dea09f278fe7603ef9f34eae093c12d92e7ddf99322a5c4109ab5677bb3d449"
)
REQUIRED_FILES = (
    "c011_real_equal_compute_preflight_verification.json",
    "docs/C011_REAL_EQUAL_COMPUTE_PREFLIGHT_REPORT.md",
    "docs/C011_REAL_EQUAL_COMPUTE_PREFLIGHT_UPDATE_MANIFEST.json",
    "scripts/verify_c011_real_equal_compute_preflight.py",
    "src/luna/parallel_cognition/equal_compute_preflight.py",
    "tests/test_c011_real_equal_compute_preflight.py",
)
DECLARED_SCOPE_FILES = frozenset(
    {
        "LUNA_HANDOFF.md",
        "MANIFEST.json",
        "SHA256SUMS.txt",
        "c011_real_equal_compute_preflight_verification.json",
        "docs/C011_REAL_EQUAL_COMPUTE_PREFLIGHT_REPORT.md",
        "docs/C011_REAL_EQUAL_COMPUTE_PREFLIGHT_UPDATE_MANIFEST.json",
        "docs/LUNA_ROADMAP.md",
        "docs/NEURAL_NATIVE_BRIDGE_UPDATE_MANIFEST.json",
        "docs/NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json",
        "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
        "scripts/check.bat",
        "scripts/verify_c011_real_equal_compute_preflight.py",
        "scripts/verify_c011_s4.py",
        "scripts/verify_c011_s5a.py",
        "scripts/verify_c011_s5b.py",
        "scripts/verify_c011_s5b_real_adapter.py",
        "scripts/verify_c011_s5b_real_evidence.py",
        "scripts/verify_c011_s5c.py",
        "scripts/verify_c011_s5d.py",
        "src/luna/parallel_cognition/__init__.py",
        "src/luna/parallel_cognition/equal_compute_preflight.py",
        "tests/test_c011_real_equal_compute_preflight.py",
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


def _canonical_sha256(path: Path) -> str:
    return sha256(_canonical_bytes(path)).hexdigest()


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


def _json(path: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads((ROOT / path).read_text(encoding="utf-8")),
    )


def _reference(
    path: str,
    *,
    digest: str,
    revision: str,
) -> RealEqualComputeEvidenceReference:
    return RealEqualComputeEvidenceReference(
        locator=path,
        content_sha256=digest,
        source_revision=revision,
    )


def _open_item(
    prerequisite: RealEqualComputePrerequisite,
    gap: str,
) -> RealEqualComputePrerequisiteEvidence:
    return RealEqualComputePrerequisiteEvidence(
        prerequisite=prerequisite,
        state=RealEqualComputeEvidenceState.OPEN,
        evidence_class=RealEqualComputeEvidenceClass.NONE,
        limitations=(gap,),
    )


def _observed_item(
    prerequisite: RealEqualComputePrerequisite,
    *,
    state: RealEqualComputeEvidenceState,
    evidence_class: RealEqualComputeEvidenceClass,
    evidence_refs: tuple[RealEqualComputeEvidenceReference, ...],
    limitation: str,
) -> RealEqualComputePrerequisiteEvidence:
    return RealEqualComputePrerequisiteEvidence(
        prerequisite=prerequisite,
        state=state,
        evidence_class=evidence_class,
        evidence_refs=evidence_refs,
        observed_at_utc=EVALUATED_AT,
        provenance_complete=True,
        limitations=(limitation,),
    )


def _policy() -> RealEqualComputePreflightPolicy:
    return RealEqualComputePreflightPolicy(
        target_branch=TARGET_BRANCH,
        target_commit_oid=BASELINE_COMMIT,
        target_tree_oid=BASELINE_TREE,
        evaluated_at_utc=EVALUATED_AT,
    )


def _snapshot() -> RealEqualComputePreflightSnapshot:
    native_ref = _reference(
        "src/luna/parallel_cognition/native_real_driver.py",
        digest=NATIVE_DRIVER_SHA256,
        revision=BASELINE_COMMIT,
    )
    proof_ref = _reference(
        "scripts/prove_c011_s5b_real_adapter.py",
        digest=REAL_PROOF_SHA256,
        revision=BASELINE_COMMIT,
    )
    s5b_ref = _reference(
        "c011_s5b_real_adapter_verification.json",
        digest=S5B_RECEIPT_SHA256,
        revision="C011_S5B_REAL_ADAPTER_EXECUTION_ACCEPTED",
    )
    s5c_ref = _reference(
        "c011_s5c_verification.json",
        digest=S5C_RECEIPT_SHA256,
        revision="C011_S5C_SHADOW_EVALUATION_LEDGER_ACCEPTED",
    )
    return RealEqualComputePreflightSnapshot(
        target_branch=TARGET_BRANCH,
        target_commit_oid=BASELINE_COMMIT,
        target_tree_oid=BASELINE_TREE,
        evaluated_at_utc=EVALUATED_AT,
        items=(
            _observed_item(
                RealEqualComputePrerequisite.CURRENT_ASSET_BINDING,
                state=RealEqualComputeEvidenceState.PARTIAL,
                evidence_class=RealEqualComputeEvidenceClass.REAL_PROVIDER_MEASUREMENT,
                evidence_refs=(s5b_ref,),
                limitation=(
                    "one accepted asset observation is not a current frozen triplet binding"
                ),
            ),
            _observed_item(
                RealEqualComputePrerequisite.MEASURED_TOKEN_ACCOUNTING,
                state=RealEqualComputeEvidenceState.REJECTED,
                evidence_class=RealEqualComputeEvidenceClass.REPOSITORY_SOURCE,
                evidence_refs=(s5b_ref, native_ref),
                limitation=(
                    "the live driver hard-codes zero tokens and the accepted result reports zero"
                ),
            ),
            _open_item(
                RealEqualComputePrerequisite.SOLO_RUNTIME_CONTRACT,
                "a frozen real SOLO runtime contract has not been supplied",
            ),
            _open_item(
                RealEqualComputePrerequisite.ULTRA_SOLO_RUNTIME_CONTRACT,
                "ULTRA_SOLO exists only as an evaluation label",
            ),
            _observed_item(
                RealEqualComputePrerequisite.PARALLEL_RUNTIME_CONTRACT,
                state=RealEqualComputeEvidenceState.REJECTED,
                evidence_class=RealEqualComputeEvidenceClass.REPOSITORY_SOURCE,
                evidence_refs=(s5b_ref, proof_ref),
                limitation=(
                    "the accepted real harness permits only one total and concurrent worker"
                ),
            ),
            _observed_item(
                RealEqualComputePrerequisite.REPRESENTATIVE_FROZEN_SUITE,
                state=RealEqualComputeEvidenceState.PARTIAL,
                evidence_class=RealEqualComputeEvidenceClass.REPOSITORY_RECEIPT,
                evidence_refs=(s5c_ref,),
                limitation=(
                    "the accepted suite is deterministic fixture evidence, not real "
                    "representative evidence"
                ),
            ),
            _open_item(
                RealEqualComputePrerequisite.INDEPENDENT_EVALUATOR_ATTESTATION,
                "independent evaluator attestation has not been supplied",
            ),
            _open_item(
                RealEqualComputePrerequisite.CONTAMINATION_PROVENANCE_ATTESTATION,
                "contamination-provenance attestation has not been supplied",
            ),
            _observed_item(
                RealEqualComputePrerequisite.HARDWARE_RESOURCE_ATTESTATION,
                state=RealEqualComputeEvidenceState.PARTIAL,
                evidence_class=RealEqualComputeEvidenceClass.REPOSITORY_RECEIPT,
                evidence_refs=(s5b_ref,),
                limitation=(
                    "declared process budgets are not external enforceable hardware ceilings"
                ),
            ),
            _observed_item(
                RealEqualComputePrerequisite.SAFETY_CONTAINMENT_ATTESTATION,
                state=RealEqualComputeEvidenceState.PARTIAL,
                evidence_class=RealEqualComputeEvidenceClass.REPOSITORY_RECEIPT,
                evidence_refs=(s5b_ref,),
                limitation=(
                    "independent OS sandbox, credential and race-free containment "
                    "evidence is absent"
                ),
            ),
            _open_item(
                RealEqualComputePrerequisite.EXTERNAL_LEDGER_ANCHOR,
                "an external immutable ledger anchor has not been supplied",
            ),
        ),
    )


def _decision() -> RealEqualComputePreflightDecision:
    return evaluate_real_equal_compute_preflight(
        policy=_policy(),
        snapshot=_snapshot(),
    )


def _source_basis_truth() -> bool:
    native = (ROOT / "src/luna/parallel_cognition/native_real_driver.py").read_text(
        encoding="utf-8"
    )
    proof = (ROOT / "scripts/prove_c011_s5b_real_adapter.py").read_text(encoding="utf-8")
    historical = _json("c011_real_equal_compute_preflight_verification.json")
    runtime = _json("c011_runtime_accounting_verification.json")
    successor = _json("c011_native_abi_v2_verification.json")
    s5b = _json("c011_s5b_real_adapter_verification.json")
    s5c = _json("c011_s5c_verification.json")
    s5d = _json("c011_s5d_verification.json")
    accepted = s5b.get("accepted_proof")
    execution_budget = s5b.get("execution_budget")
    s5c_open = s5c.get("open_stage_boundaries")
    historical_basis = historical.get("source_basis")
    runtime_basis = runtime.get("source_basis")
    successor_basis = successor.get("source_basis")
    predecessor = successor.get("predecessor_gate")
    if (
        not isinstance(historical_basis, dict)
        or not isinstance(runtime_basis, dict)
        or not isinstance(successor_basis, dict)
        or not isinstance(predecessor, dict)
    ):
        return False
    historical_native = historical_basis.get("native_real_driver")
    runtime_preflight = runtime_basis.get("accepted_equal_compute_preflight")
    successor_native = successor_basis.get("native_real_driver")
    if (
        not isinstance(historical_native, dict)
        or not isinstance(runtime_preflight, dict)
        or not isinstance(successor_native, dict)
    ):
        return False
    return bool(
        historical_native.get("canonical_text_lf_sha256") == NATIVE_DRIVER_SHA256
        and historical_native.get("reported_token_assignment") == 0
        and _canonical_sha256(ROOT / "c011_real_equal_compute_preflight_verification.json")
        == PREFLIGHT_RECEIPT_SHA256
        and runtime_preflight.get("canonical_text_lf_sha256") == PREFLIGHT_RECEIPT_SHA256
        and predecessor.get("receipt_canonical_sha256") == RUNTIME_ACCOUNTING_RECEIPT_SHA256
        and successor_native.get("canonical_text_lf_sha256")
        == _canonical_sha256(ROOT / "src/luna/parallel_cognition/native_real_driver.py")
        and "native_usage" in native
        and _canonical_sha256(ROOT / "scripts/prove_c011_s5b_real_adapter.py") == REAL_PROOF_SHA256
        and _canonical_sha256(ROOT / "c011_s5b_real_adapter_verification.json")
        == S5B_RECEIPT_SHA256
        and _canonical_sha256(ROOT / "c011_s5c_verification.json") == S5C_RECEIPT_SHA256
        and _canonical_sha256(ROOT / "c011_s5d_verification.json") == S5D_RECEIPT_SHA256
        and "max_parallel_generations=1," in proof
        and "max_total_workers=1," in proof
        and "max_concurrent_workers=1," in proof
        and isinstance(accepted, dict)
        and accepted.get("reported_tokens") == 0
        and isinstance(execution_budget, dict)
        and execution_budget.get("max_parallel_generations") == 1
        and s5c.get("real_provider_execution") is False
        and s5c.get("equal_compute_non_inferiority_established") is False
        and isinstance(s5c_open, list)
        and any("ULTRA_SOLO" in str(item) for item in s5c_open)
        and s5d.get("stage_status")
        == "C011_S5D_EXTERNAL_EVIDENCE_PROMOTION_DECISION_ACCEPTED_NOT_PROMOTED"
        and s5d.get("decision_disposition") == "BLOCKED_INSUFFICIENT_EVIDENCE"
    )


def _receipt_truth() -> bool:
    receipt = _json("c011_real_equal_compute_preflight_verification.json")
    decision = _decision()
    expected_inventory = [
        {
            "prerequisite": item.prerequisite.value,
            "state": item.state.value,
            "evidence_class": item.evidence_class.value,
            "evidence_id": item.evidence_id,
        }
        for item in _snapshot().items
    ]
    authority = receipt.get("authority")
    return bool(
        receipt.get("stage") == "S5D_E1_REAL_EQUAL_COMPUTE_PREFLIGHT"
        and receipt.get("stage_status") in {READY, ACCEPTED}
        and receipt.get("owner_authorization_recorded") is True
        and receipt.get("owner_authorization_scope") == "BOUNDED_REAL_EQUAL_COMPUTE_EVIDENCE_TEST"
        and receipt.get("baseline_commit") == BASELINE_COMMIT
        and receipt.get("baseline_tree") == BASELINE_TREE
        and receipt.get("target_branch") == TARGET_BRANCH
        and receipt.get("capability_status") == "QUEUED"
        and receipt.get("default_enabled") is False
        and receipt.get("preflight_outcome") == "NOT_EXECUTED_BLOCKED"
        and receipt.get("decision_disposition")
        == RealEqualComputePreflightDisposition.BLOCKED_REJECTED_BASIS.value
        and receipt.get("policy_id") == decision.policy_id
        and receipt.get("snapshot_id") == decision.snapshot_id
        and receipt.get("decision_id") == decision.decision_id
        and receipt.get("evidence_inventory") == expected_inventory
        and receipt.get("rejected_prerequisites")
        == [
            RealEqualComputePrerequisite.MEASURED_TOKEN_ACCOUNTING.value,
            RealEqualComputePrerequisite.PARALLEL_RUNTIME_CONTRACT.value,
        ]
        and receipt.get("execution_attempted") is False
        and receipt.get("provider_execution_during_preflight") is False
        and receipt.get("live_model_execution_during_preflight") is False
        and receipt.get("controlled_c011_execution") is False
        and receipt.get("hidden_chain_of_thought_access") is False
        and isinstance(authority, dict)
        and authority
        and all(value is False for value in authority.values())
        and receipt.get("next_gate") == NEXT_GATE
    )


def _verification_truth() -> bool:
    receipt = _json("c011_real_equal_compute_preflight_verification.json")
    update = _json("docs/C011_REAL_EQUAL_COMPUTE_PREFLIGHT_UPDATE_MANIFEST.json")
    report = (ROOT / "docs/C011_REAL_EQUAL_COMPUTE_PREFLIGHT_REPORT.md").read_text(encoding="utf-8")
    verification = receipt.get("verification")
    if not isinstance(verification, dict) or verification != update.get("verification"):
        return False
    full = verification.get("repository_full_gate")
    if not isinstance(full, dict):
        return False
    stage = receipt.get("stage_status")
    if stage != update.get("stage_status"):
        return False
    if stage == READY:
        repository_gate = bool(
            full.get("status") == "PENDING"
            and full.get("pytest_passed") is None
            and full.get("verifier_and_cli_chain") == "PENDING"
        )
    elif stage == ACCEPTED:
        repository_gate = bool(
            full.get("status") == "PASS"
            and full.get("pytest_passed") == 1476
            and full.get("pytest_skipped_platform") == 1
            and full.get("ruff") == "PASS"
            and full.get("mypy_strict") == "PASS_314_FILES"
            and full.get("verifier_and_cli_chain") == "PASS_58_OF_58"
            and full.get("execution_environment") == "EXACT_STAGED_TREE_SHORT_WINDOWS_TEMP_PATH"
        )
    else:
        return False
    expected_gates = {
        "research_saturation_gate": "NOT_READY",
        "target_spec": "BLOCKED",
        "controlled_execution": "NONE",
    }
    scope_files = update.get("scope_files")
    return bool(
        repository_gate
        and update.get("next_gate") == NEXT_GATE
        and update.get("scope_file_count") == len(DECLARED_SCOPE_FILES)
        and isinstance(scope_files, list)
        and all(isinstance(item, str) for item in scope_files)
        and set(scope_files) == DECLARED_SCOPE_FILES
        and verification.get("focused_contract_and_adversarial_tests") == "PASS_16"
        and verification.get("changed_scope_ruff") == "PASS"
        and verification.get("changed_scope_mypy_strict") == "PASS"
        and verification.get("real_equal_compute_fail_closed_preflight_gate") == "PASS"
        and receipt.get("aslm_gates") == expected_gates
        and update.get("aslm_gates") == expected_gates
        and str(stage) in report
        and NEXT_GATE in report
        and all(label in report for label in ("VERIFIED", "INFERENCE", "OPEN"))
        and "ASLM Research is a separate project" in report
    )


def _implementation_boundary_truth() -> bool:
    source = (ROOT / "src/luna/parallel_cognition/equal_compute_preflight.py").read_text(
        encoding="utf-8"
    )
    runtime_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "src/luna/runtime").glob("*.py")
    )
    decision = _decision()
    return bool(
        "native_real_driver" not in source
        and "subprocess" not in source
        and "http" not in source
        and "equal_compute_preflight" not in runtime_sources
        and decision.disposition is RealEqualComputePreflightDisposition.BLOCKED_REJECTED_BASIS
        and decision.preflight_ready is False
        and decision.owner_authorization_recorded is True
        and decision.execution_attempted is False
        and decision.provider_call_executed is False
        and decision.real_model_execution_completed is False
        and decision.capability_status_after == "QUEUED"
        and decision.rollout_stage_after == "BLOCKED"
        and decision.task_state_authority is False
        and decision.root_context_adoption_authority is False
        and decision.completion_authority is False
        and decision.user_facing_voice_authority is False
        and decision.canary_authority is False
        and decision.active_authority is False
        and decision.promotion_authority is False
    )


def _governance_truth() -> bool:
    documents = tuple(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "LUNA_HANDOFF.md",
            ROOT / "docs/LUNA_ROADMAP.md",
            ROOT / "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
        )
    )
    check = (ROOT / "scripts/check.bat").read_text(encoding="utf-8")
    return bool(
        all(ACCEPTED in document or READY in document for document in documents)
        and all(NEXT_GATE in document for document in documents)
        and all("controlled C-011 execution: NONE" in document for document in documents)
        and all("Research Saturation Gate: NOT_READY" in document for document in documents)
        and all("Target Spec: BLOCKED" in document for document in documents)
        and "scripts\\verify_c011_real_equal_compute_preflight.py" in check
        and "[49/62]" in check
        and "S5D-E1" in check
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    c011 = build_canonical_capability_registry().get("C-011")
    checks = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
        "c011_capability_remains_queued": c011.status is CapabilityStatus.QUEUED,
        "source_basis_content_addressed_and_truthful": _source_basis_truth(),
        "receipt_matches_fail_closed_preflight": _receipt_truth(),
        "scope_verification_and_gates_truthful": _verification_truth(),
        "passive_non_authoritative_boundary": _implementation_boundary_truth(),
        "governance_boundaries_truthful": _governance_truth(),
    }
    print(
        json.dumps(
            {
                "capability": "C-011",
                "stage": "S5D_E1_REAL_EQUAL_COMPUTE_PREFLIGHT",
                "stage_status": _json("c011_real_equal_compute_preflight_verification.json").get(
                    "stage_status"
                ),
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
