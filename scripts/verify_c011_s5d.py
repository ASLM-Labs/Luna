"""Deterministic repository gate for the C-011 S5D promotion decision."""

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
    S5DEvidenceClass,
    S5DEvidenceItem,
    S5DEvidenceReference,
    S5DEvidenceRequirement,
    S5DEvidenceState,
    S5DExternalEvidenceSnapshot,
    S5DPromotionDecision,
    S5DPromotionDisposition,
    S5DPromotionPolicy,
    S5DRequestedTransition,
    evaluate_s5d_promotion,
)

READY = "C011_S5D_EXTERNAL_EVIDENCE_PROMOTION_DECISION_READY_FOR_REPOSITORY_GATE"
ACCEPTED = "C011_S5D_EXTERNAL_EVIDENCE_PROMOTION_DECISION_ACCEPTED_NOT_PROMOTED"
NEXT_GATE = "C011_REAL_EQUAL_COMPUTE_EXTERNAL_EVIDENCE_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION"
BASELINE_COMMIT = "a0b75112341c296f03b519624c5aa8ec68bbf7bf"
BASELINE_TREE = "f17e4c64b7e4d62d0b45f400dc46282a75979ec2"
TARGET_BRANCH = "capability/c011-single-voice-parallel-cognition"
EVALUATED_AT = datetime(2026, 9, 1, 12, tzinfo=UTC)
S5B_RECEIPT_SHA256 = "75f99933be8780406384bd62d5bc8a646570045d2b901a57adc5c27f63c01a85"
S5C_RECEIPT_SHA256 = "2611e4ca8cfe1b20f660e793b2d76974c1477b19446baad9b0b4009949761bb0"
REQUIRED_FILES = (
    "c011_s5d_verification.json",
    "docs/C011_S5D_EXTERNAL_EVIDENCE_PROMOTION_DECISION_REPORT.md",
    "docs/C011_S5D_UPDATE_MANIFEST.json",
    "scripts/verify_c011_s5d.py",
    "src/luna/parallel_cognition/promotion_decision.py",
    "tests/test_c011_s5d_promotion_decision.py",
)
DECLARED_SCOPE_FILES = frozenset(
    {
        "LUNA_HANDOFF.md",
        "MANIFEST.json",
        "SHA256SUMS.txt",
        "c011_s5d_verification.json",
        "docs/C011_S5D_EXTERNAL_EVIDENCE_PROMOTION_DECISION_REPORT.md",
        "docs/C011_S5D_UPDATE_MANIFEST.json",
        "docs/LUNA_ROADMAP.md",
        "docs/NEURAL_NATIVE_BRIDGE_UPDATE_MANIFEST.json",
        "docs/NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json",
        "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
        "scripts/check.bat",
        "scripts/verify_c011_s4.py",
        "scripts/verify_c011_s5a.py",
        "scripts/verify_c011_s5b.py",
        "scripts/verify_c011_s5b_real_adapter.py",
        "scripts/verify_c011_s5b_real_evidence.py",
        "scripts/verify_c011_s5c.py",
        "scripts/verify_c011_s5d.py",
        "src/luna/parallel_cognition/__init__.py",
        "src/luna/parallel_cognition/promotion_decision.py",
        "tests/test_c011_s5d_promotion_decision.py",
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


def _reference(path: str, *, digest: str, revision: str) -> S5DEvidenceReference:
    return S5DEvidenceReference(
        locator=path,
        content_sha256=digest,
        source_revision=revision,
    )


def _open_item(
    requirement: S5DEvidenceRequirement,
    gap: str,
) -> S5DEvidenceItem:
    return S5DEvidenceItem(
        requirement=requirement,
        state=S5DEvidenceState.OPEN,
        evidence_class=S5DEvidenceClass.NONE,
        limitations=(gap,),
    )


def _policy() -> S5DPromotionPolicy:
    return S5DPromotionPolicy(
        target_branch=TARGET_BRANCH,
        target_commit_oid=BASELINE_COMMIT,
        target_tree_oid=BASELINE_TREE,
        evaluated_at_utc=EVALUATED_AT,
    )


def _snapshot() -> S5DExternalEvidenceSnapshot:
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
    return S5DExternalEvidenceSnapshot(
        target_branch=TARGET_BRANCH,
        target_commit_oid=BASELINE_COMMIT,
        target_tree_oid=BASELINE_TREE,
        evaluated_at_utc=EVALUATED_AT,
        items=(
            S5DEvidenceItem(
                requirement=S5DEvidenceRequirement.REAL_PROVIDER_EXECUTION,
                state=S5DEvidenceState.VERIFIED,
                evidence_class=S5DEvidenceClass.REAL_PROVIDER_OBSERVATION,
                evidence_refs=(s5b_ref,),
                observed_at_utc=datetime(2026, 8, 30, tzinfo=UTC),
                provenance_complete=True,
            ),
            S5DEvidenceItem(
                requirement=S5DEvidenceRequirement.HARDWARE_RESOURCE_ATTESTATION,
                state=S5DEvidenceState.PARTIAL,
                evidence_class=S5DEvidenceClass.REPOSITORY_RECEIPT,
                evidence_refs=(s5b_ref,),
                observed_at_utc=datetime(2026, 8, 30, tzinfo=UTC),
                provenance_complete=True,
                limitations=(
                    "declared process budgets are not enforceable external hardware ceilings",
                ),
            ),
            S5DEvidenceItem(
                requirement=S5DEvidenceRequirement.SAFETY_CONTAINMENT_ATTESTATION,
                state=S5DEvidenceState.PARTIAL,
                evidence_class=S5DEvidenceClass.REPOSITORY_RECEIPT,
                evidence_refs=(s5b_ref,),
                observed_at_utc=datetime(2026, 8, 30, tzinfo=UTC),
                provenance_complete=True,
                limitations=(
                    "OS sandbox credential and race-free containment attestation is absent",
                ),
            ),
            S5DEvidenceItem(
                requirement=S5DEvidenceRequirement.S5C_LEDGER_INTEGRITY,
                state=S5DEvidenceState.VERIFIED,
                evidence_class=S5DEvidenceClass.REPOSITORY_RECEIPT,
                evidence_refs=(s5c_ref,),
                observed_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
                provenance_complete=True,
            ),
            _open_item(
                S5DEvidenceRequirement.REAL_EQUAL_COMPUTE_NON_INFERIORITY,
                "representative real equal-compute triplets have not been supplied",
            ),
            _open_item(
                S5DEvidenceRequirement.EVALUATOR_INDEPENDENCE_ATTESTATION,
                "external evaluator-independence attestation has not been supplied",
            ),
            _open_item(
                S5DEvidenceRequirement.CONTAMINATION_PROVENANCE_ATTESTATION,
                "external contamination provenance attestation has not been supplied",
            ),
            _open_item(
                S5DEvidenceRequirement.EXTERNAL_LEDGER_ANCHOR,
                "an external immutable ledger anchor has not been supplied",
            ),
        ),
    )


def _decision() -> S5DPromotionDecision:
    return evaluate_s5d_promotion(
        policy=_policy(),
        snapshot=_snapshot(),
        requested_transition=S5DRequestedTransition.CANARY,
    )


def _source_receipts_truth() -> bool:
    s5b = _json("c011_s5b_real_adapter_verification.json")
    s5c = _json("c011_s5c_verification.json")
    accepted = s5b.get("accepted_proof")
    return bool(
        _canonical_sha256(ROOT / "c011_s5b_real_adapter_verification.json") == S5B_RECEIPT_SHA256
        and _canonical_sha256(ROOT / "c011_s5c_verification.json") == S5C_RECEIPT_SHA256
        and s5b.get("stage_status") == "C011_S5B_REAL_ADAPTER_EXECUTION_ACCEPTED"
        and s5b.get("live_model_execution_completed") is True
        and isinstance(accepted, dict)
        and accepted.get("reported_tokens") == 0
        and s5c.get("stage_status") == "C011_S5C_SHADOW_EVALUATION_LEDGER_ACCEPTED"
        and s5c.get("real_provider_execution") is False
        and s5c.get("equal_compute_non_inferiority_established") is False
    )


def _receipt_truth() -> bool:
    receipt = _json("c011_s5d_verification.json")
    decision = _decision()
    inventory = receipt.get("evidence_inventory")
    expected_inventory = [
        {
            "requirement": item.requirement.value,
            "state": item.state.value,
            "evidence_class": item.evidence_class.value,
        }
        for item in _snapshot().items
    ]
    authority = receipt.get("authority")
    return bool(
        receipt.get("stage") == "S5D_EXTERNAL_EVIDENCE_PROMOTION_DECISION"
        and receipt.get("stage_status") in {READY, ACCEPTED}
        and receipt.get("baseline_commit") == BASELINE_COMMIT
        and receipt.get("baseline_tree") == BASELINE_TREE
        and receipt.get("target_branch") == TARGET_BRANCH
        and receipt.get("capability_status") == "QUEUED"
        and receipt.get("default_enabled") is False
        and receipt.get("promotion_outcome") == "NOT_PROMOTED"
        and receipt.get("requested_transition") == "CANARY"
        and receipt.get("decision_disposition")
        == S5DPromotionDisposition.BLOCKED_INSUFFICIENT_EVIDENCE.value
        and receipt.get("policy_id") == decision.policy_id
        and receipt.get("snapshot_id") == decision.snapshot_id
        and receipt.get("decision_id") == decision.decision_id
        and inventory == expected_inventory
        and receipt.get("provider_execution_during_s5d") is False
        and receipt.get("live_model_execution_during_s5d") is False
        and receipt.get("controlled_c011_execution") is False
        and receipt.get("hidden_chain_of_thought_access") is False
        and isinstance(authority, dict)
        and authority
        and all(value is False for value in authority.values())
        and receipt.get("next_gate") == NEXT_GATE
    )


def _verification_truth() -> bool:
    receipt = _json("c011_s5d_verification.json")
    update = _json("docs/C011_S5D_UPDATE_MANIFEST.json")
    report = (ROOT / "docs/C011_S5D_EXTERNAL_EVIDENCE_PROMOTION_DECISION_REPORT.md").read_text(
        encoding="utf-8"
    )
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
            and full.get("pytest_passed") == 1459
            and full.get("pytest_skipped_platform") == 1
            and full.get("ruff") == "PASS"
            and full.get("mypy_strict") == "PASS_313_FILES"
            and full.get("verifier_and_cli_chain") == "PASS_57_OF_57"
            and full.get("execution_environment") == "EXACT_STAGED_TREE_SHORT_WINDOWS_TEMP_PATH"
        )
    else:
        return False
    expected_gates = {
        "research_saturation_gate": "NOT_READY",
        "target_spec": "BLOCKED",
        "controlled_execution": "NONE",
    }
    return bool(
        repository_gate
        and update.get("next_gate") == NEXT_GATE
        and update.get("scope_file_count") == len(DECLARED_SCOPE_FILES)
        and set(update.get("scope_files", ())) == DECLARED_SCOPE_FILES
        and verification.get("focused_contract_and_adversarial_tests") == "PASS_18"
        and verification.get("changed_scope_ruff") == "PASS"
        and verification.get("changed_scope_mypy_strict") == "PASS"
        and verification.get("s5d_fail_closed_decision_gate") == "PASS"
        and receipt.get("aslm_gates") == expected_gates
        and update.get("aslm_gates") == expected_gates
        and str(stage) in report
        and NEXT_GATE in report
        and all(label in report for label in ("VERIFIED", "INFERENCE", "OPEN"))
        and "ASLM Research is a separate project" in report
    )


def _implementation_boundary_truth() -> bool:
    source = (ROOT / "src/luna/parallel_cognition/promotion_decision.py").read_text(
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
        and "promotion_decision" not in runtime_sources
        and decision.disposition is S5DPromotionDisposition.BLOCKED_INSUFFICIENT_EVIDENCE
        and decision.owner_review_ready is False
        and decision.transition_applied is False
        and decision.provider_call_executed is False
        and decision.capability_status_after == "QUEUED"
        and decision.rollout_stage_after == "BLOCKED"
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
        and "scripts\\verify_c011_s5d.py" in check
        and "[48/62]" in check
        and "S5D" in check
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    c011 = build_canonical_capability_registry().get("C-011")
    checks = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
        "c011_capability_remains_queued": c011.status is CapabilityStatus.QUEUED,
        "source_receipts_content_addressed_and_truthful": _source_receipts_truth(),
        "receipt_matches_fail_closed_decision": _receipt_truth(),
        "scope_verification_and_gates_truthful": _verification_truth(),
        "passive_non_authoritative_boundary": _implementation_boundary_truth(),
        "governance_boundaries_truthful": _governance_truth(),
    }
    print(
        json.dumps(
            {
                "capability": "C-011",
                "stage": "S5D_EXTERNAL_EVIDENCE_PROMOTION_DECISION",
                "stage_status": _json("c011_s5d_verification.json").get("stage_status"),
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
