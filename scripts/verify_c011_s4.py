"""Deterministic RFC-C011 S4 bounded live-worker gate."""

from __future__ import annotations

import ast
import json
import re
import sqlite3
import sys
from contextlib import closing
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
from luna.parallel_cognition.live import (  # noqa: E402
    BackendSafetyCapabilities,
    FocusedContextBundle,
    LiveBackendRequest,
    S4RuntimePolicy,
)
from luna.parallel_cognition.live_runtime import S4RootIntegration  # noqa: E402
from luna.parallel_cognition.live_store import (  # noqa: E402
    S4_LIVE_JOURNAL_SCHEMA_VERSION,
    SQLiteLiveInvocationJournal,
)

REQUIRED_FILES = (
    "src/luna/context/extensions.py",
    "src/luna/parallel_cognition/context_broker.py",
    "src/luna/parallel_cognition/live.py",
    "src/luna/parallel_cognition/live_runtime.py",
    "src/luna/parallel_cognition/live_store.py",
    "src/luna/parallel_cognition/subprocess_backend.py",
    "tests/test_c011_s4_live_workers.py",
    "scripts/verify_c011_s4.py",
    "c011_s4_verification.json",
    "docs/C011_S4_LIVE_WORKERS_REPORT.md",
    "docs/C011_S4_UPDATE_MANIFEST.json",
)

DECLARED_SCOPE_FILES = frozenset(
    {
        "LUNA_HANDOFF.md",
        "MANIFEST.json",
        "SHA256SUMS.txt",
        "c011_s4_verification.json",
        "docs/C011_S4_LIVE_WORKERS_REPORT.md",
        "docs/C011_S4_UPDATE_MANIFEST.json",
        "docs/LUNA_ROADMAP.md",
        "docs/NEURAL_NATIVE_BRIDGE_UPDATE_MANIFEST.json",
        "docs/NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json",
        "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
        "scripts/check.bat",
        "scripts/verify_c011_s4.py",
        "src/luna/context/__init__.py",
        "src/luna/context/extensions.py",
        "src/luna/parallel_cognition/__init__.py",
        "src/luna/parallel_cognition/context_broker.py",
        "src/luna/parallel_cognition/controls.py",
        "src/luna/parallel_cognition/events.py",
        "src/luna/parallel_cognition/live.py",
        "src/luna/parallel_cognition/live_runtime.py",
        "src/luna/parallel_cognition/live_store.py",
        "src/luna/parallel_cognition/subprocess_backend.py",
        "src/luna/runtime/dependencies.py",
        "src/luna/runtime/loop.py",
        "tests/test_c011_s4_live_workers.py",
        "tests/test_phase12e_single_policy_loop.py",
        "tests/test_project_metadata.py",
    }
)

S4_READY = "C011_S4_READY_FOR_FINAL_GATE"
S4_ACCEPTED = "C011_S4_LIVE_WORKERS_ACCEPTED"


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


def _runtime_boundary() -> bool:
    runtime_paths = tuple((ROOT / "src" / "luna" / "runtime").glob("*.py"))
    runtime_text = "\n".join(path.read_text(encoding="utf-8") for path in runtime_paths)
    dependencies = (ROOT / "src" / "luna" / "runtime" / "dependencies.py").read_text(
        encoding="utf-8"
    )
    loop = (ROOT / "src" / "luna" / "runtime" / "loop.py").read_text(encoding="utf-8")
    extension = (ROOT / "src" / "luna" / "context" / "extensions.py").read_text(encoding="utf-8")
    return bool(
        "parallel_cognition" not in runtime_text
        and "root_context_extension_provider: RootContextExtensionProvider | None = None"
        in dependencies
        and "provider is None or not provider.enabled" in loop
        and "ContextInterpretation.DATA_ONLY" in loop
        and "class RootContextExtensionProvider(Protocol)" in extension
    )


def _backend_boundary() -> bool:
    path = ROOT / "src" / "luna" / "parallel_cognition" / "subprocess_backend.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    shell_false = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Popen"
        and any(
            keyword.arg == "shell"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is False
            for keyword in node.keywords
        )
        for node in ast.walk(tree)
    )
    markers = (
        "if not executable.is_absolute()",
        "TemporaryDirectory(",
        "process.terminate()",
        "process.kill()",
        "env=dict(self._environment)",
        'available_tools": []',
        'credentials": []',
        'inherited_memory": []',
    )
    return (
        shell_false
        and "subprocess.PIPE" not in source
        and all(marker in source for marker in markers)
    )


def _contracts_and_journal() -> bool:
    policy = S4RuntimePolicy()
    rejected_four = False
    try:
        S4RuntimePolicy(max_workers=4)
    except ValidationError:
        rejected_four = True
    all_capabilities = BackendSafetyCapabilities(
        bounded_driver_calls=True,
        cooperative_cancellation=True,
        hard_termination=True,
        isolated_ephemeral_scratch=True,
        explicit_environment_only=True,
        shell_disabled=True,
    )
    missing_capability = BackendSafetyCapabilities(
        bounded_driver_calls=False,
        cooperative_cancellation=True,
        hard_termination=True,
        isolated_ephemeral_scratch=True,
        explicit_environment_only=True,
        shell_disabled=True,
    )
    authority_defaults = tuple(
        model.model_fields[name].default
        for model in (FocusedContextBundle, LiveBackendRequest, S4RootIntegration)
        for name in (
            "state_mutation_authority",
            "completion_authority",
            "user_facing_voice_authority",
        )
        if name in model.model_fields
    )
    with TemporaryDirectory(prefix="luna-c011-s4-verifier-") as temp:
        journal = SQLiteLiveInvocationJournal(Path(temp) / "live.sqlite3")
        journal.verify_integrity()
        with closing(sqlite3.connect(journal.path)) as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
    required_exports = {
        "FocusedContextBroker",
        "LiveBackendResult",
        "LiveHandoffReuseFenceController",
        "ParallelCognitionRuntimeService",
        "RuntimeKillSwitch",
        "S4RuntimePolicy",
        "SubprocessWorkerBackend",
    }
    forbidden_exports = {
        "SQLiteCoordinationStore",
        "SQLiteLiveInvocationJournal",
    }
    return bool(
        not policy.active
        and not policy.enabled
        and policy.kill_switch_engaged
        and policy.max_workers == 3
        and policy.max_concurrent_workers == 3
        and rejected_four
        and all_capabilities.accepted
        and not missing_capability.accepted
        and all(value is False for value in authority_defaults)
        and S4_LIVE_JOURNAL_SCHEMA_VERSION == 1
        and version == 1
        and tables == {"handoff_reuse_fences", "live_invocations"}
        and required_exports.issubset(set(facade.__all__))
        and forbidden_exports.isdisjoint(set(facade.__all__))
    )


def _verification_matches(verification: object, *, final: bool) -> bool:
    if not isinstance(verification, dict):
        return False
    focused = verification.get("s4_live_worker_tests", {})
    targeted = verification.get("c011_and_solo_targeted_suite", {})
    full = verification.get("full_local_gate", {})
    if not all(isinstance(item, dict) for item in (focused, targeted, full)):
        return False
    expected = "PASS" if final else "PENDING"
    common = bool(
        focused.get("status") == "PASS"
        and focused.get("passed") == 10
        and focused.get("failed") == 0
        and targeted.get("status") == "PASS"
        and targeted.get("passed") == 84
        and targeted.get("failed") == 0
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
        and isinstance(full.get("pytest_passed"), int)
        and full["pytest_passed"] >= 1377
        and full.get("pytest_skipped_platform") == 1
        and full.get("verifier_and_cli_chain") == "PASS_51_OF_51"
    )


def _receipt_report_manifest_truth() -> bool:
    receipt = json.loads((ROOT / "c011_s4_verification.json").read_text(encoding="utf-8"))
    update = json.loads(
        (ROOT / "docs" / "C011_S4_UPDATE_MANIFEST.json").read_text(encoding="utf-8")
    )
    report = (ROOT / "docs" / "C011_S4_LIVE_WORKERS_REPORT.md").read_text(encoding="utf-8")
    stage = receipt.get("stage_status")
    update_stage = update.get("stage_status")
    final = stage == S4_ACCEPTED and update_stage == S4_ACCEPTED
    stage_truth = bool(
        (final or (stage == S4_READY and update_stage == S4_READY))
        and _verification_matches(receipt.get("verification"), final=final)
        and _verification_matches(update.get("verification"), final=final)
    )
    properties = receipt.get("s4_properties", {})
    authority = receipt.get("authority", {})
    expected_gates = {
        "research_saturation_gate": "NOT_READY",
        "target_spec": "BLOCKED",
        "controlled_execution": "NONE",
    }
    return bool(
        stage_truth
        and receipt.get("capability") == "C-011"
        and receipt.get("stage") == "S4_BOUNDED_LIVE_READ_ONLY_WORKERS"
        and receipt.get("capability_status") == "QUEUED"
        and receipt.get("default_enabled") is False
        and receipt.get("live_model_execution") is False
        and receipt.get("controlled_c011_execution") is False
        and receipt.get("deterministic_subprocess_fixture_execution") is True
        and receipt.get("hidden_chain_of_thought_access") is False
        and receipt.get("aslm_gates") == expected_gates
        and properties.get("maximum_workers") == 3
        and properties.get("delegation_depth") == 1
        and properties.get("durable_no_blind_replay") is True
        and properties.get("raw_worker_output_enters_root_context") is False
        and properties.get("generic_runtime_extension_boundary") is True
        and all(
            authority.get(name) is False
            for name in (
                "worker_write_authority",
                "worker_network_authority",
                "worker_process_authority",
                "worker_tool_authority",
                "worker_delegation_authority",
                "worker_memory_commit_authority",
                "worker_state_mutation_authority",
                "worker_completion_authority",
                "worker_user_facing_voice_authority",
                "automatic_handoff_adoption",
            )
        )
        and update.get("capability") == "C-011"
        and update.get("capability_status") == "QUEUED"
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
            ROOT / "docs" / "rfcs" / "RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
            ROOT / "docs" / "LUNA_ROADMAP.md",
            ROOT / "LUNA_HANDOFF.md",
            ROOT / "docs" / "C011_S4_LIVE_WORKERS_REPORT.md",
        )
    )
    stage = S4_READY if S4_READY in documents[-1] else S4_ACCEPTED
    check = (ROOT / "scripts" / "check.bat").read_text(encoding="utf-8")
    return bool(
        all(stage in document for document in documents)
        and all("C-011" in document and "QUEUED" in document for document in documents)
        and all("controlled execution: NONE" in document for document in documents)
        and all("Target Spec: BLOCKED" in document for document in documents)
        and all("Research Saturation Gate: NOT_READY" in document for document in documents)
        and "C011_S4_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION" in documents[0]
        and "scripts\\verify_c011_s4.py" in check
        and "[42/62]" in check
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    c011 = build_canonical_capability_registry().get("C-011")
    checks = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
        "c011_capability_remains_queued": c011.status is CapabilityStatus.QUEUED,
        "runtime_uses_generic_default_off_extension_boundary": _runtime_boundary(),
        "subprocess_backend_is_bounded_and_shell_free": _backend_boundary(),
        "s4_contract_journal_and_facade_invariants": _contracts_and_journal(),
        "scoped_s4_receipt_report_manifest_truthful": (_receipt_report_manifest_truth()),
        "governance_gates_are_truthful": _governance_truth(),
    }
    output = {
        "capability": "C-011",
        "stage": "S4_BOUNDED_LIVE_READ_ONLY_WORKERS",
        "checks": checks,
        "missing": missing,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
