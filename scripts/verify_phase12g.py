"""Deterministic Phase 12G runtime E2E and behavior-conformance gate."""

from __future__ import annotations

import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.acceptance import ReleaseStatus, run_core_acceptance  # noqa: E402
from luna.conformance import (  # noqa: E402
    RUNTIME_CONFORMANCE_SUITE_SHA256,
    ConformanceDomain,
    ConformanceRunner,
    RuntimeBehaviorExecutor,
    build_runtime_conformance_suite,
)

REQUIRED_FILES = (
    "src/luna/conformance/__init__.py",
    "src/luna/conformance/models.py",
    "src/luna/conformance/runner.py",
    "src/luna/conformance/runtime_executor.py",
    "src/luna/conformance/suite.py",
    "tests/test_phase12g_runtime_e2e_conformance.py",
    "scripts/verify_phase12g.py",
    "docs/rfcs/RFC-012G_RUNTIME_E2E_BEHAVIOR_CONFORMANCE.md",
    "docs/PHASE_12G_REPORT.md",
    "phase_12g_verification.json",
)

EXPECTED_CASE_IDS = (
    "L12G-01-verified-completion",
    "L12G-02-no-false-complete",
    "L12G-03-weak-evidence-resumable",
    "L12G-04-conflicting-evidence",
    "L12G-05-multi-action-blocked",
    "L12G-06-cancel-safe-boundary",
    "L12G-07-started-side-effect-no-replay",
    "L12G-08-scope-denial-no-dispatch",
    "L12G-09-high-risk-worktree",
    "L12G-10-tool-budget-pre-dispatch",
    "L12G-11-stale-evidence-rejected",
)


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
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    phase = manifest.get("phase")
    if not isinstance(phase, str):
        return False
    match = re.fullmatch(r"(\d+)([A-Z]?)", phase)
    if match is None:
        return False
    phase_number = int(match.group(1))
    phase_suffix = match.group(2)
    if phase_number < 12 or (phase_number == 12 and phase_suffix < "G"):
        return False
    if manifest.get("hash_normalization") != "utf8_text_lf_v1":
        return False
    if manifest.get("metadata_scope") != "release_artifact_allowlist_v2":
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False
    if any(str(relative).endswith(".log") for relative in files):
        return False

    sums: dict[str, str] = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
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


def _scope_preflight_is_bound() -> bool:
    source = (ROOT / "src/luna/tools/policy.py").read_text(encoding="utf-8")
    required = (
        "path_is_allowed",
        '"path_scope"',
        '"tool path is outside allowed_paths"',
        "canonical_workspace_path",
    )
    return all(item in source for item in required)


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {
        "required_files_present": not missing,
    }

    suite = build_runtime_conformance_suite()
    checks["suite_revision_locked"] = (
        suite.revision == "1.0.0"
        and suite.locked_sha256 == RUNTIME_CONFORMANCE_SUITE_SHA256
        and suite.computed_sha256() == RUNTIME_CONFORMANCE_SUITE_SHA256
        and tuple(case.case_id for case in suite.cases) == EXPECTED_CASE_IDS
        and all(case.critical for case in suite.cases)
    )
    checks["all_conformance_domains_covered"] = (
        {case.domain for case in suite.cases} == set(ConformanceDomain)
    )

    with TemporaryDirectory(prefix="luna-phase12g-verifier-") as temp:
        root = Path(temp)
        runner = ConformanceRunner()
        report = runner.run(
            suite=suite,
            executor=RuntimeBehaviorExecutor(),
            workspace_root=root / "runtime-e2e",
        )
        by_id = {item.case_id: item for item in report.results}

        checks["runtime_e2e_all_critical_pass"] = (
            report.total_cases == 11
            and report.passed_cases == 11
            and report.failed_cases == 0
            and report.critical_failures == 0
            and report.all_passed
        )
        checks["verified_completion_requires_verification"] = (
            by_id["L12G-01-verified-completion"].actual["first_stop"]
            == "VERIFICATION_PENDING"
            and by_id["L12G-01-verified-completion"].actual["final_stop"]
            == "COMPLETED"
            and by_id["L12G-02-no-false-complete"].actual["stop_reason"]
            == "VERIFICATION_PENDING"
        )
        checks["evidence_gap_and_conflict_remain_nonterminal"] = (
            by_id["L12G-03-weak-evidence-resumable"].actual["terminal"] is False
            and by_id["L12G-04-conflicting-evidence"].actual["terminal"] is False
            and by_id["L12G-11-stale-evidence-rejected"].actual["terminal"] is False
        )
        checks["multi_action_and_budget_deny_before_dispatch"] = (
            by_id["L12G-05-multi-action-blocked"].actual["tool_calls"] == 0
            and by_id["L12G-10-tool-budget-pre-dispatch"].actual["tool_calls"] == 0
        )
        checks["cancel_wins_at_safe_boundary"] = (
            by_id["L12G-06-cancel-safe-boundary"].actual["model_calls"] == 0
            and by_id["L12G-06-cancel-safe-boundary"].actual["tool_calls"] == 0
        )
        checks["started_side_effect_never_blind_replays"] = (
            by_id["L12G-07-started-side-effect-no-replay"].actual[
                "initial_dispatch_calls"
            ]
            == 1
            and by_id["L12G-07-started-side-effect-no-replay"].actual[
                "resume_tool_calls"
            ]
            == 0
        )
        checks["scope_denial_prevents_dispatch"] = (
            by_id["L12G-08-scope-denial-no-dispatch"].actual["stop_reason"]
            == "PERMISSION_DENIED"
            and by_id["L12G-08-scope-denial-no-dispatch"].actual["tool_calls"] == 0
            and by_id["L12G-08-scope-denial-no-dispatch"].actual[
                "outside_file_created"
            ]
            is False
        )
        high_risk_actual = by_id["L12G-09-high-risk-worktree"].actual
        checks["high_risk_worktree_isolation_holds"] = (
            high_risk_actual.get("isolation_mode") == "WORKTREE"
            and high_risk_actual.get("original_preserved") is True
            and high_risk_actual.get("cleanup_verified") is True
        )
        checks["bounded_worktree_path_holds"] = (
            high_risk_actual.get("bounded_worktree_path") is True
        )

        repeated = runner.run(
            suite=suite,
            executor=RuntimeBehaviorExecutor(),
            workspace_root=root / "repeat",
        )
        checks["runtime_semantics_repeatable"] = (
            report.semantic_signature() == repeated.semantic_signature()
        )

        phase11_report, phase11_decision = run_core_acceptance(root / "phase11")
        checks["phase11_locked_acceptance_still_green"] = (
            phase11_report.metrics.total_cases == 11
            and phase11_report.metrics.passed_cases == 11
            and phase11_report.metrics.critical_failures == 0
            and phase11_decision.status is ReleaseStatus.PASS
        )

    checks["scope_path_preflight_bound"] = _scope_preflight_is_bound()
    checks["metadata_hashes_current"] = _metadata_integrity()

    payload = {
        "phase": "12G",
        "suite_revision": suite.revision,
        "suite_sha256": suite.locked_sha256,
        "checks": checks,
        "missing_files": missing,
        "status": "PASS" if all(checks.values()) else "BLOCKED",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
