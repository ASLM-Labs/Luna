"""Deterministic RFC-C011 S1 immutable-contract and metadata gate."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.capabilities import (  # noqa: E402
    CapabilityStatus,
    build_canonical_capability_registry,
)
from luna.contracts.enums import PlanStepStatus  # noqa: E402
from luna.parallel_cognition import (  # noqa: E402
    AdoptionReceipt,
    AgentExecutionAttempt,
    AgentExecutionReceipt,
    AgentPayload,
    AssignmentSemanticSpec,
    ClaimRecord,
    ContextFreshness,
    ContextSourceReference,
    DistilledHandoff,
    ParallelCognitionRole,
    ReadOnlyContextManifest,
    RedactionState,
    SourceStepSemantics,
    WorkerBudgetEnvelope,
    canonical_contract_json,
    contract_sha256,
    reconstruct_contract,
)

REQUIRED_FILES = (
    "src/luna/parallel_cognition/__init__.py",
    "src/luna/parallel_cognition/models.py",
    "tests/test_c011_contracts.py",
    "scripts/verify_c011_s1.py",
    "c011_s1_verification.json",
    "docs/C011_S1_CONTRACT_STATE_REPORT.md",
    "docs/C011_S1_UPDATE_MANIFEST.json",
    "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
)

PRIMARY_MODELS = (
    AssignmentSemanticSpec,
    AgentExecutionAttempt,
    ReadOnlyContextManifest,
    AgentPayload,
    AgentExecutionReceipt,
    ClaimRecord,
    DistilledHandoff,
    AdoptionReceipt,
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
    if manifest.get("phase") != "19F":
        return False
    if manifest.get("capability") != "C-007":
        return False
    if manifest.get("capability_status") != "IMPLEMENTED_UNVERIFIED":
        return False
    if manifest.get("hash_normalization") != "utf8_text_lf_v1":
        return False
    if manifest.get("metadata_scope") != "release_artifact_allowlist_v2":
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
        if metadata.get("sha256") != digest:
            return False
        if metadata.get("size_bytes") != len(canonical):
            return False
        if sums.get(relative) != digest:
            return False
    return True


def _contract_integrity_fixture() -> bool:
    task_id = UUID("11111111-1111-4111-8111-111111111111")
    step_id = UUID("22222222-2222-4222-8222-222222222222")
    now = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
    deadline = now + timedelta(minutes=5)
    context = ReadOnlyContextManifest(
        task_id=task_id,
        source_task_revision=7,
        sources=(
            ContextSourceReference(
                task_id=task_id,
                source_task_revision=7,
                source_ref="repo:src",
                source_revision="git:09a5dcc",
                content_sha256="a" * 64,
                freshness=ContextFreshness.CURRENT,
                freshness_checked_at=now - timedelta(seconds=1),
                redaction_state=RedactionState.REDACTED,
                size_bytes=10,
            ),
        ),
        total_size_bytes=10,
        created_at=now,
        expires_at=deadline,
    )
    assignment = AssignmentSemanticSpec(
        task_id=task_id,
        source_task_revision=7,
        task_contract_sha256="b" * 64,
        source_steps=(
            SourceStepSemantics(
                step_id=step_id,
                sequence=1,
                description="Verify immutable S1 contracts.",
                status=PlanStepStatus.PENDING,
                source_step_payload_sha256="c" * 64,
            ),
        ),
        acceptance_basis_sha256="d" * 64,
        acceptance_target_refs=("target:s1",),
        context_manifest_sha256=contract_sha256(context),
        autonomy_policy_sha256="e" * 64,
        tool_policy_sha256="f" * 64,
        worker_role=ParallelCognitionRole.PARALLEL,
        objective="Verify one read-only S1 contract lane.",
        granted_source_refs=("repo:src",),
        capability_selection_basis_sha256="0" * 64,
        root_coordination_epoch=3,
        budget=WorkerBudgetEnvelope(
            max_context_bytes=100,
            max_result_bytes=1000,
            max_claims=1,
            max_tokens=100,
            max_runtime_ms=1000,
            deadline_at=deadline,
        ),
    )
    encoded = canonical_contract_json(assignment)
    restored = reconstruct_contract(AssignmentSemanticSpec, encoded)
    if restored != assignment or canonical_contract_json(restored) != encoded:
        return False

    tampered = assignment.model_dump(mode="json")
    tampered["objective"] = "Tampered while retaining the old assignment ID."
    try:
        AssignmentSemanticSpec.model_validate(tampered)
    except ValidationError:
        return True
    return False


def _authority_and_boundary_checks() -> tuple[bool, bool, bool]:
    all_frozen = all(model.model_config.get("frozen") is True for model in PRIMARY_MODELS)
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "luna" / "runtime").glob("*.py")
    )
    no_runtime_wiring = "parallel_cognition" not in runtime_text
    models_text = (ROOT / "src" / "luna" / "parallel_cognition" / "models.py").read_text(
        encoding="utf-8"
    )
    isolated_imports = all(
        marker not in models_text
        for marker in ("luna.runtime", "luna.tools", "subprocess", "socket")
    )
    return all_frozen, no_runtime_wiring, isolated_imports


def _receipt_truth() -> bool:
    receipt = json.loads(
        (ROOT / "c011_s1_verification.json").read_text(encoding="utf-8")
    )
    stage_status = receipt.get("stage_status")
    full_gate = receipt.get("verification", {}).get("full_local_gate", {})
    stage_truth = (
        stage_status == "C011_S1_READY_FOR_FINAL_GATE"
        and full_gate.get("status") == "PENDING"
    ) or (
        stage_status == "C011_S1_CONTRACTS_ACCEPTED"
        and full_gate.get("status") == "PASS"
    )
    return bool(
        stage_truth
        and receipt.get("capability") == "C-011"
        and receipt.get("stage") == "S1_CONTRACT_STATE_PACKAGE"
        and receipt.get("capability_status") == "QUEUED"
        and receipt.get("production_behavior_changed") is False
        and receipt.get("live_c011_execution") is False
        and receipt.get("runtime_authorship_established") is False
        and receipt.get("aslm_gates")
        == {
            "research_saturation_gate": "NOT_READY",
            "target_spec": "BLOCKED",
            "controlled_execution": "NONE",
        }
    )


def _governance_truth() -> bool:
    rfc = (ROOT / "docs" / "rfcs" / "RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md").read_text(
        encoding="utf-8"
    )
    handoff = (ROOT / "LUNA_HANDOFF.md").read_text(encoding="utf-8")
    required = (
        "C011_S2_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION",
        "Research Saturation Gate: NOT_READY",
        "Target Spec: BLOCKED",
        "controlled execution: NONE",
    )
    current_gate_present = any(
        item in rfc
        for item in (
            "C011_S1_CONTRACTS_AUTHORIZED",
            "C011_S1_CONTRACTS_ACCEPTED",
        )
    )
    return current_gate_present and all(item in rfc for item in required) and all(
        item in handoff for item in required[:1]
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    frozen, no_runtime_wiring, isolated_imports = _authority_and_boundary_checks()
    c011 = build_canonical_capability_registry().get("C-011")
    checks = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
        "primary_contracts_frozen": frozen,
        "canonical_roundtrip_and_tamper_rejection": _contract_integrity_fixture(),
        "parallel_cognition_package_has_no_live_dependencies": isolated_imports,
        "production_runtime_has_no_c011_wiring": no_runtime_wiring,
        "c011_capability_remains_queued": c011.status is CapabilityStatus.QUEUED,
        "scoped_s1_receipt_is_truthful": _receipt_truth(),
        "governance_gates_are_truthful": _governance_truth(),
    }
    output = {
        "capability": "C-011",
        "stage": "S1_CONTRACT_STATE_PACKAGE",
        "checks": checks,
        "missing": missing,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
