"""Deterministic RFC-C011 S3 admission and hierarchical-control gate."""

from __future__ import annotations

import ast
import json
import re
import sqlite3
import sys
import tomllib
from contextlib import closing
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

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
from luna.parallel_cognition import (  # noqa: E402
    AdmittedPlan,
    AgentLifecycleState,
    ClaimResolutionReceipt,
    ControlFencePhase,
    DeterministicReconciler,
    HierarchicalBudgetEnvelope,
    ReconciliationReceipt,
    validate_attempt_transition,
)
from luna.parallel_cognition.store import (  # noqa: E402
    COORDINATION_STORE_SCHEMA_VERSION,
    SQLiteCoordinationStore,
)

REQUIRED_FILES = (
    "src/luna/parallel_cognition/admission.py",
    "src/luna/parallel_cognition/controls.py",
    "src/luna/parallel_cognition/reconciliation.py",
    "src/luna/parallel_cognition/resolution.py",
    "tests/test_c011_s3_admission_controls.py",
    "scripts/verify_c011_s3.py",
    "c011_s3_verification.json",
    "docs/C011_S3_ADMISSION_CONTROLS_REPORT.md",
    "docs/C011_S3_UPDATE_MANIFEST.json",
    "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
)

DECLARED_SCOPE_FILES = frozenset(
    {
        "LUNA_HANDOFF.md",
        "MANIFEST.json",
        "SHA256SUMS.txt",
        "c011_s3_verification.json",
        "docs/C011_S3_ADMISSION_CONTROLS_REPORT.md",
        "docs/C011_S3_UPDATE_MANIFEST.json",
        "docs/LUNA_ROADMAP.md",
        "docs/NEURAL_NATIVE_BRIDGE_UPDATE_MANIFEST.json",
        "docs/NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json",
        "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
        "scripts/check.bat",
        "scripts/verify_c011_s2.py",
        "scripts/verify_c011_s3.py",
        "src/luna/parallel_cognition/__init__.py",
        "src/luna/parallel_cognition/admission.py",
        "src/luna/parallel_cognition/controls.py",
        "src/luna/parallel_cognition/events.py",
        "src/luna/parallel_cognition/models.py",
        "src/luna/parallel_cognition/reconciliation.py",
        "src/luna/parallel_cognition/resolution.py",
        "src/luna/parallel_cognition/store.py",
        "tests/test_c011_s2_durable_recovery.py",
        "tests/test_c011_s3_admission_controls.py",
        "tests/test_project_metadata.py",
    }
)

S3_READY = "C011_S3_READY_FOR_FINAL_GATE"
S3_ACCEPTED = "C011_S3_ADMISSION_CONTROLS_ACCEPTED"
S4_BLOCK = "C011_S4_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION"


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
        manifest.get("phase") != "19F"
        or manifest.get("capability") != "C-007"
        or manifest.get("capability_status") != "IMPLEMENTED_UNVERIFIED"
        or manifest.get("hash_normalization") != "utf8_text_lf_v1"
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


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _package_and_runtime_boundaries() -> tuple[bool, bool, bool]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependency_boundary = project.get("project", {}).get("dependencies") == [
        "pydantic>=2.12,<3"
    ]
    s3_files = tuple(
        ROOT / "src" / "luna" / "parallel_cognition" / name
        for name in ("admission.py", "controls.py", "reconciliation.py", "resolution.py")
    )
    imports = set().union(*(_imported_modules(path) for path in s3_files))
    forbidden_roots = {
        "aiohttp",
        "http",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    forbidden_luna = (
        "luna.agents",
        "luna.cli",
        "luna.desktop",
        "luna.neural",
        "luna.operations",
        "luna.runtime",
    )
    isolated = all(
        module.split(".", 1)[0] not in forbidden_roots
        and not module.startswith(forbidden_luna)
        for module in imports
    )
    runtime_paths = tuple((ROOT / "src" / "luna" / "runtime").glob("*.py"))
    no_runtime_wiring = all(
        "parallel_cognition" not in path.read_text(encoding="utf-8")
        for path in runtime_paths
    )
    facade_text = (
        ROOT / "src" / "luna" / "parallel_cognition" / "__init__.py"
    ).read_text(encoding="utf-8")
    safe_facade = (
        "SQLiteCoordinationStore" not in facade_text
        and "SQLiteCoordinationStore" not in facade.__all__
    )
    return dependency_boundary and isolated, no_runtime_wiring, safe_facade


def _contract_and_store_truth() -> bool:
    now = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)
    budget = HierarchicalBudgetEnvelope(
        max_total_workers=3,
        max_concurrent_workers=3,
        delegation_depth=1,
        max_worker_context_bytes=1,
        max_worker_result_bytes=1,
        max_worker_tokens=1,
        max_worker_runtime_ms=1,
        max_total_context_bytes=3,
        max_total_result_bytes=3,
        max_total_tokens=3,
        max_total_runtime_ms=3,
        overall_deadline_at=now + timedelta(seconds=1),
    )
    rejected_four = False
    try:
        HierarchicalBudgetEnvelope(
            **{
                **budget.model_dump(),
                "max_total_workers": 4,
            }
        )
    except ValidationError:
        rejected_four = True
    authority_fields = (
        *(
            AdmittedPlan.model_fields[name].default
            for name in (
                "write_authority",
                "network_authority",
                "process_authority",
                "tool_authority",
                "delegation_authority",
                "state_mutation_authority",
                "completion_authority",
                "user_facing_voice_authority",
                "live_execution_authority",
                "production_wiring_authority",
            )
        ),
        ClaimResolutionReceipt.model_fields["completion_authority"].default,
        ReconciliationReceipt.model_fields["majority_vote_used"].default,
        ReconciliationReceipt.model_fields["automatically_adopted"].default,
        ReconciliationReceipt.model_fields["completion_authority"].default,
    )
    transition_truth = True
    try:
        validate_attempt_transition(
            AgentLifecycleState.ADMITTED,
            AgentLifecycleState.CANCEL_REQUESTED,
        )
        validate_attempt_transition(
            AgentLifecycleState.CREATED,
            AgentLifecycleState.TIMED_OUT,
        )
    except ValueError:
        transition_truth = False
    with TemporaryDirectory(prefix="luna-c011-s3-verifier-") as temp:
        store = SQLiteCoordinationStore(Path(temp) / "coordination.sqlite3")
        with closing(sqlite3.connect(store.path)) as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 's3_control_artifacts'"
            ).fetchone()
        store.verify_integrity()
    expected_exports = {
        "AdmissionController",
        "ControlFenceController",
        "AuthoritativeResolver",
        "DeterministicReconciler",
        "ReconciliationReceipt",
    }
    return bool(
        budget.delegation_depth == 1
        and rejected_four
        and set(ControlFencePhase)
        == {
            ControlFencePhase.BEFORE_CREATION,
            ControlFencePhase.BEFORE_EXECUTION,
            ControlFencePhase.RESULT_ADMISSION,
            ControlFencePhase.PRE_ADOPTION,
        }
        and all(value is False for value in authority_fields)
        and transition_truth
        and COORDINATION_STORE_SCHEMA_VERSION == 2
        and version == 2
        and table is not None
        and expected_exports.issubset(set(facade.__all__))
        and isinstance(DeterministicReconciler(), DeterministicReconciler)
    )


def _verification_matches(verification: object, *, full_status: str) -> bool:
    if not isinstance(verification, dict):
        return False
    focused = verification.get("new_s3_admission_controls_tests", {})
    combined = verification.get("combined_s1_s2_s3_suite", {})
    full = verification.get("full_local_gate", {})
    if not all(isinstance(item, dict) for item in (focused, combined, full)):
        return False
    common = bool(
        focused.get("status") == "PASS"
        and focused.get("passed") == 24
        and focused.get("failed") == 0
        and combined.get("status") == "PASS"
        and combined.get("passed") == 72
        and combined.get("failed") == 0
        and verification.get("ruff_changed_scope") == "PASS"
        and verification.get("mypy_strict") == "PASS"
        and full.get("status") == full_status
        and full.get("ruff") == full_status
        and full.get("mypy_strict") == full_status
    )
    if full_status == "PENDING":
        return common and full.get("verifier_and_cli_chain") == "PENDING"
    return bool(
        common
        and isinstance(full.get("pytest_passed"), int)
        and full["pytest_passed"] >= 1364
        and full.get("pytest_skipped_platform") == 1
        and full.get("verifier_and_cli_chain") == "PASS_50_OF_50"
    )


def _receipt_report_manifest_truth() -> bool:
    receipt = json.loads(
        (ROOT / "c011_s3_verification.json").read_text(encoding="utf-8")
    )
    update = json.loads(
        (ROOT / "docs" / "C011_S3_UPDATE_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    report = (
        ROOT / "docs" / "C011_S3_ADMISSION_CONTROLS_REPORT.md"
    ).read_text(encoding="utf-8")
    stage = receipt.get("stage_status")
    update_stage = update.get("stage_status")
    if stage == S3_READY and update_stage == S3_READY:
        stage_truth = _verification_matches(
            receipt.get("verification"), full_status="PENDING"
        ) and _verification_matches(update.get("verification"), full_status="PENDING")
    elif stage == S3_ACCEPTED and update_stage == S3_ACCEPTED:
        stage_truth = _verification_matches(
            receipt.get("verification"), full_status="PASS"
        ) and _verification_matches(update.get("verification"), full_status="PASS")
    else:
        stage_truth = False
    properties = receipt.get("s3_properties", {})
    authority = receipt.get("authority", {})
    return bool(
        stage_truth
        and receipt.get("capability") == "C-011"
        and receipt.get("stage") == "S3_ADMISSION_HIERARCHICAL_CONTROLS"
        and receipt.get("capability_status") == "QUEUED"
        and receipt.get("production_behavior_changed") is False
        and receipt.get("live_c011_execution") is False
        and receipt.get("controlled_c011_execution") is False
        and receipt.get("backend_kind") == "DETERMINISTIC_IN_PROCESS_FAKE_ONLY"
        and receipt.get("store_schema_version") == 2
        and properties.get("maximum_workers") == 3
        and properties.get("delegation_depth") == 1
        and properties.get("majority_vote_authority") is False
        and properties.get("automatic_state_adoption") is False
        and properties.get("hidden_chain_of_thought_access") is False
        and all(
            authority.get(name) is False
            for name in (
                "production_runtime_authorship_established",
                "worker_write_authority",
                "worker_network_authority",
                "worker_process_authority",
                "worker_tool_authority",
                "worker_delegation_authority",
                "worker_memory_commit_authority",
                "worker_state_mutation_authority",
                "worker_completion_authority",
                "worker_user_facing_voice_authority",
            )
        )
        and "aslm_gates" not in receipt
        and update.get("capability") == "C-011"
        and update.get("stage") == "S3_ADMISSION_HIERARCHICAL_CONTROLS"
        and update.get("capability_status") == "QUEUED"
        and update.get("next_code_gate") == S4_BLOCK
        and update.get("production_behavior_changed") is False
        and update.get("controlled_c011_execution") is False
        and update.get("scope_file_count") == len(DECLARED_SCOPE_FILES)
        and set(update.get("scope_files", ())) == DECLARED_SCOPE_FILES
        and "aslm_gates" not in update
        and stage in report
        and S4_BLOCK in report
    )


def _governance_truth() -> bool:
    documents = tuple(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "docs" / "rfcs" / "RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
            ROOT / "docs" / "LUNA_ROADMAP.md",
            ROOT / "LUNA_HANDOFF.md",
            ROOT / "docs" / "C011_S3_ADMISSION_CONTROLS_REPORT.md",
        )
    )
    current_gate = S3_READY if S3_READY in documents[-1] else S3_ACCEPTED
    return bool(
        all(current_gate in document for document in documents)
        and all(S4_BLOCK in document for document in documents)
        and all("C-011" in document and "QUEUED" in document for document in documents)
        and "ASLM Research is a separate project" in documents[-1]
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    package_boundary, no_runtime_wiring, safe_facade = _package_and_runtime_boundaries()
    c011 = build_canonical_capability_registry().get("C-011")
    checks = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
        "s3_dependency_and_import_boundary": package_boundary,
        "production_runtime_has_no_c011_wiring": no_runtime_wiring,
        "public_facade_excludes_durable_store": safe_facade,
        "c011_capability_remains_queued": c011.status is CapabilityStatus.QUEUED,
        "s3_contract_and_store_invariants": _contract_and_store_truth(),
        "scoped_s3_receipt_report_manifest_truthful": (
            _receipt_report_manifest_truth()
        ),
        "governance_gates_are_truthful": _governance_truth(),
    }
    output = {
        "capability": "C-011",
        "stage": "S3_ADMISSION_HIERARCHICAL_CONTROLS",
        "checks": checks,
        "missing": missing,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
