"""Structural and behavioral verifier for Luna Phase 11."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from luna.acceptance import ReleaseStatus, run_core_acceptance
from luna.evals import CORE_EVAL_SUITE_SHA256, build_core_eval_suite

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    required_files = (
        ROOT / "src" / "luna" / "evals" / "models.py",
        ROOT / "src" / "luna" / "evals" / "runner.py",
        ROOT / "src" / "luna" / "evals" / "suite.py",
        ROOT / "src" / "luna" / "acceptance" / "executor.py",
        ROOT / "src" / "luna" / "acceptance" / "gate.py",
        ROOT / "src" / "luna" / "acceptance" / "models.py",
        ROOT / "tests" / "test_phase11_evals.py",
        ROOT / "tests" / "test_phase11_acceptance.py",
    )
    missing = tuple(
        path.relative_to(ROOT).as_posix()
        for path in required_files
        if not path.is_file()
    )

    suite = build_core_eval_suite()
    with TemporaryDirectory(prefix="luna-phase11-a-") as first_directory:
        first_report, first_decision = run_core_acceptance(Path(first_directory))
    with TemporaryDirectory(prefix="luna-phase11-b-") as second_directory:
        second_report, second_decision = run_core_acceptance(Path(second_directory))

    metrics = first_report.metrics
    checks = {
        "required_files_present": not missing,
        "suite_revision_locked": suite.revision == "1.0.0",
        "suite_hash_locked": (
            suite.locked_sha256 == CORE_EVAL_SUITE_SHA256
            and suite.computed_sha256() == CORE_EVAL_SUITE_SHA256
        ),
        "fixed_case_count": len(suite.cases) == 11,
        "regression_deterministic": (
            first_report.semantic_signature() == second_report.semantic_signature()
        ),
        "all_cases_passed": (
            metrics.total_cases == 11
            and metrics.passed_cases == 11
            and metrics.failed_cases == 0
        ),
        "critical_failures_zero": metrics.critical_failures == 0,
        "false_verified_complete_zero": metrics.false_verified_complete_count == 0,
        "protected_path_violations_zero": (
            metrics.protected_path_violation_count == 0
        ),
        "blind_retry_zero": metrics.blind_retry_count == 0,
        "rollback_pass": metrics.rollback_pass,
        "restart_resume_pass": metrics.checkpoint_resume_pass,
        "memory_pollution_pass": metrics.memory_pollution_pass,
        "unnecessary_question_pass": metrics.unnecessary_question_pass,
        "scope_creep_pass": metrics.scope_creep_pass,
        "final_report_accuracy_pass": metrics.final_report_accuracy_pass,
        "release_gate_pass": (
            first_decision.status is ReleaseStatus.PASS
            and second_decision.status is ReleaseStatus.PASS
        ),
        "known_limitations_published": bool(first_decision.known_limitations),
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    print(
        json.dumps(
            {
                "phase": 11,
                "suite_revision": suite.revision,
                "suite_sha256": suite.locked_sha256,
                "checks": checks,
                "metrics": metrics.model_dump(mode="json"),
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
