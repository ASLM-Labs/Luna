"""Deterministic Phase 12D failure recovery and minimal-change verification."""

from __future__ import annotations

import ast
import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.actions import ActionDenial, ActionDenialCode, ActionDenialStage  # noqa: E402
from luna.contracts import RiskLevel, TaskContract, TaskScope  # noqa: E402
from luna.planning import RetryDecision, RetryReason  # noqa: E402
from luna.recovery import (  # noqa: E402
    ChangeEstimate,
    FailureCategory,
    FailureClassifier,
    IsolationMode,
    MinimalChangeDenialCode,
    MinimalChangePolicy,
    RecoveryAction,
    RecoveryPolicy,
    WorkspaceIsolationPolicy,
)
from luna.runtime import RuntimeBudget  # noqa: E402
from luna.tools import ToolResult, ToolResultStatus  # noqa: E402

_ZERO = sha256(b"").hexdigest()


def _task(*, risk: RiskLevel = RiskLevel.LOW) -> TaskContract:
    return TaskContract(
        objective="Verify Phase 12D recovery boundaries.",
        required_conditions=("Recovery policy cannot invent runtime authority.",),
        evidence_required=("Structured Phase 12D decisions",),
        scope=TaskScope(
            workspace_root=".",
            allowed_paths=("src", "tests"),
            protected_paths=("src/luna/protected.py",),
            write_allowed=True,
        ),
        risk_level=risk,
        owner="user",
    )


def _denial(code: ActionDenialCode) -> ActionDenial:
    return ActionDenial(
        proposal_id=uuid4(),
        task_id=uuid4(),
        trace_id=uuid4(),
        stage=ActionDenialStage.POLICY_PREFLIGHT,
        code=code,
        reason="phase12d verifier denial",
        checks=("fixture:FAIL",),
    )


def _transient_result() -> ToolResult:
    return ToolResult(
        request_id=uuid4(),
        tool_name="process.run_argv",
        status=ToolResultStatus.FAILURE,
        stdout_digest=_ZERO,
        stderr_digest=_ZERO,
        output_chars=0,
        duration_ms=1,
        error_class="TimeoutError",
    )


def _recovery_has_no_hidden_execution() -> bool:
    forbidden_calls = {"dispatch", "execute", "rollback", "write_text"}
    forbidden_imports = {
        "luna.tools.dispatcher",
        "luna.workspace.mutator",
        "subprocess",
    }
    for relative in (
        Path("src/luna/recovery/classifier.py"),
        Path("src/luna/recovery/policy.py"),
        Path("src/luna/recovery/minimal_change.py"),
        Path("src/luna/recovery/isolation.py"),
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in forbidden_imports:
                return False
            if isinstance(node, ast.Import) and any(
                alias.name in forbidden_imports for alias in node.names
            ):
                return False
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in forbidden_calls:
                    return False
                if isinstance(func, ast.Name) and func.id in forbidden_calls:
                    return False
    return True


def _canonical_metadata_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return raw
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _metadata_integrity() -> bool:
    manifest_path = ROOT / "MANIFEST.json"
    sums_path = ROOT / "SHA256SUMS.txt"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    phase = manifest.get("phase")
    if not isinstance(phase, str):
        return False
    match = re.fullmatch(r"(\d+)([A-Z]?)", phase)
    if match is None:
        return False
    phase_number = int(match.group(1))
    phase_suffix = match.group(2)
    if phase_number < 12 or (phase_number == 12 and phase_suffix < "D"):
        return False
    if manifest.get("hash_normalization") != "utf8_text_lf_v1":
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False

    sums: dict[str, str] = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            return False
        digest, relative = line.split("  ", 1)
        sums[relative] = digest

    if set(sums) != set(files):
        return False

    for relative, metadata in files.items():
        if not isinstance(relative, str) or not isinstance(metadata, dict):
            return False
        target = ROOT / relative
        if not target.is_file():
            return False
        canonical = _canonical_metadata_bytes(target)
        digest = sha256(canonical).hexdigest()
        if metadata.get("sha256") != digest:
            return False
        if metadata.get("size_bytes") != len(canonical):
            return False
        if sums.get(relative) != digest:
            return False
    return True


def main() -> int:
    required_files = (
        "src/luna/recovery/__init__.py",
        "src/luna/recovery/models.py",
        "src/luna/recovery/classifier.py",
        "src/luna/recovery/policy.py",
        "src/luna/recovery/minimal_change.py",
        "src/luna/recovery/isolation.py",
        "tests/test_phase12d_recovery_policy.py",
        "docs/rfcs/RFC-012D_FAILURE_RECOVERY_MINIMAL_CHANGE.md",
        "docs/PHASE_12D_REPORT.md",
    )
    missing = [relative for relative in required_files if not (ROOT / relative).is_file()]

    classifier = FailureClassifier(transient_error_classes=("TimeoutError",))
    policy = RecoveryPolicy()

    invalid = classifier.from_action_denial(_denial(ActionDenialCode.INVALID_ARGUMENTS))
    invalid_decision = policy.decide(failure=invalid)

    permission = classifier.from_action_denial(_denial(ActionDenialCode.POLICY_DENIED))
    permission_decision = policy.decide(failure=permission)

    task_id = uuid4()
    trace_id = uuid4()
    transient = classifier.from_tool_result(
        task_id=task_id,
        trace_id=trace_id,
        result=_transient_result(),
    )
    blind_retry = policy.decide(failure=transient)
    changed_retry = policy.decide(
        failure=transient,
        retry_decision=RetryDecision(
            allowed=True,
            reason=RetryReason.CHANGED_BASIS,
            matching_attempt_id=uuid4(),
            changed_dimensions=("evidence",),
        ),
    )

    stale = classifier.stale_state(
        task_id=task_id,
        trace_id=trace_id,
        reason="workspace revision changed",
    )
    verification = classifier.verification_failure(
        task_id=task_id,
        trace_id=trace_id,
        reason="post-write verification failed",
    )
    integrity = classifier.integrity_failure(
        task_id=task_id,
        trace_id=trace_id,
        reason="audit hash chain mismatch",
    )

    task = _task()
    budget = RuntimeBudget.controlled_write(
        max_changed_files=2,
        max_added_lines=50,
        max_deleted_lines=20,
    )
    approved = ChangeEstimate(
        touched_paths=("src/luna/recovery/policy.py",),
        added_lines=12,
        deleted_lines=2,
    )
    minimal = MinimalChangePolicy().evaluate_declared(
        estimate=approved,
        scope=task.scope,
        budget=budget,
    )
    protected = MinimalChangePolicy().evaluate_declared(
        estimate=ChangeEstimate(
            touched_paths=("src/luna/protected.py",),
            added_lines=1,
        ),
        scope=task.scope,
        budget=budget,
    )
    scope_creep = MinimalChangePolicy().evaluate_observed(
        approved=approved,
        observed=ChangeEstimate(
            touched_paths=("src/luna/recovery/policy.py", "tests/extra.py"),
            added_lines=12,
            deleted_lines=2,
        ),
        scope=task.scope,
        budget=RuntimeBudget.controlled_write(
            max_changed_files=3,
            max_added_lines=100,
            max_deleted_lines=100,
        ),
    )

    low_isolation = WorkspaceIsolationPolicy().plan(
        task_contract=task,
        change=approved,
        worktree_available=False,
    )
    high_isolation = WorkspaceIsolationPolicy().plan(
        task_contract=_task(risk=RiskLevel.HIGH),
        change=approved,
        worktree_available=False,
    )

    checks = {
        "required_files_present": not missing,
        "invalid_action_replans": (
            invalid.category is FailureCategory.INVALID_ACTION
            and invalid_decision.action is RecoveryAction.REPLAN
        ),
        "permission_denial_never_retries": (
            permission.category is FailureCategory.PERMISSION_OR_SCOPE_DENIED
            and permission_decision.action is RecoveryAction.REQUEST_APPROVAL
        ),
        "transient_label_alone_cannot_retry": blind_retry.action is RecoveryAction.REPLAN,
        "changed_basis_allows_transient_retry": (
            changed_retry.action is RecoveryAction.RETRY
            and changed_retry.changed_dimensions == ("evidence",)
        ),
        "stale_state_requires_reinspect": (
            policy.decide(failure=stale).action is RecoveryAction.REINSPECT
        ),
        "verification_failure_requires_rollback": (
            policy.decide(failure=verification, mutation_active=True).action
            is RecoveryAction.ROLLBACK
        ),
        "integrity_failure_stops": (
            policy.decide(failure=integrity).action is RecoveryAction.STOP
        ),
        "minimal_change_budget_passes": minimal.allowed,
        "protected_path_blocked": (
            protected.denial_code is MinimalChangeDenialCode.PROTECTED_PATH
        ),
        "scope_creep_blocked": (
            scope_creep.denial_code is MinimalChangeDenialCode.UNDECLARED_SCOPE_GROWTH
        ),
        "low_risk_uses_snapshot": (
            low_isolation.allowed and low_isolation.mode is IsolationMode.SNAPSHOT
        ),
        "high_risk_requires_worktree": (
            not high_isolation.allowed
            and high_isolation.mode is IsolationMode.WORKTREE
            and high_isolation.worktree_required
        ),
        "worktree_has_no_silent_snapshot_downgrade": (
            high_isolation.mode is not IsolationMode.SNAPSHOT
        ),
        "recovery_has_no_hidden_execution": _recovery_has_no_hidden_execution(),
        "contracts_round_trip": (
            type(transient).from_json(transient.to_json()) == transient
            and type(changed_retry).from_json(changed_retry.to_json()) == changed_retry
        ),
        "metadata_hashes_current": _metadata_integrity(),
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    print(
        json.dumps(
            {
                "phase": "12D",
                "checks": checks,
                "missing_files": missing,
                "status": status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
