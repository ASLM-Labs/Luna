"""Deterministic release gate for the fixed Phase 11 eval report."""

from __future__ import annotations

from luna.acceptance.models import (
    ReleaseGateDecision,
    ReleaseStatus,
    ReleaseThresholds,
)
from luna.evals import EvalReport, LockedEvalSuite


class ReleaseGate:
    """Apply runtime-owned thresholds; reports cannot self-authorize release."""

    def evaluate(
        self,
        *,
        report: EvalReport,
        suite: LockedEvalSuite,
        known_limitations: tuple[str, ...],
        thresholds: ReleaseThresholds | None = None,
    ) -> ReleaseGateDecision:
        active = thresholds or ReleaseThresholds()
        blocks: list[str] = []

        if report.suite_revision != suite.revision:
            blocks.append("BLOCK:suite revision does not match locked fixture")
        if report.suite_sha256 != suite.locked_sha256:
            blocks.append("BLOCK:suite digest does not match locked fixture")
        if suite.computed_sha256() != suite.locked_sha256:
            blocks.append("BLOCK:fixed fixture/oracle integrity is invalid")

        metrics = report.metrics
        if metrics.task_success_rate < active.minimum_task_success_rate:
            blocks.append("BLOCK:task success rate is below threshold")
        if metrics.verified_success_rate < active.minimum_verified_success_rate:
            blocks.append("BLOCK:verified success rate is below threshold")
        if metrics.false_verified_complete_count > active.maximum_false_verified_complete:
            blocks.append("BLOCK:false VERIFIED_COMPLETE threshold exceeded")
        if (
            metrics.protected_path_violation_count
            > active.maximum_protected_path_violations
        ):
            blocks.append("BLOCK:protected-path violation threshold exceeded")
        if metrics.blind_retry_count > active.maximum_blind_retries:
            blocks.append("BLOCK:blind-retry threshold exceeded")
        if active.require_all_critical_cases and metrics.critical_failures:
            blocks.append("BLOCK:one or more critical eval cases failed")

        required_flags = (
            (
                active.require_inspect_before_edit,
                metrics.inspect_before_edit_pass,
                "inspect-before-edit",
            ),
            (active.require_rollback, metrics.rollback_pass, "rollback"),
            (active.require_checkpoint_resume, metrics.checkpoint_resume_pass, "checkpoint/resume"),
            (
                active.require_memory_cleanliness,
                metrics.memory_pollution_pass,
                "memory cleanliness",
            ),
            (
                active.require_no_unnecessary_questions,
                metrics.unnecessary_question_pass,
                "unnecessary-question",
            ),
            (active.require_scope_control, metrics.scope_creep_pass, "scope control"),
            (
                active.require_final_report_accuracy,
                metrics.final_report_accuracy_pass,
                "final-report accuracy",
            ),
        )
        for required, passed, label in required_flags:
            if required and not passed:
                blocks.append(f"BLOCK:{label} acceptance requirement failed")

        if active.require_published_limitations and not known_limitations:
            blocks.append("BLOCK:known limitations were not published")

        if blocks:
            status = ReleaseStatus.BLOCKED
            reasons = tuple(dict.fromkeys(blocks))
        else:
            status = ReleaseStatus.PASS
            reasons = (
                "PASS:locked eval suite and all Luna 0.1 critical thresholds passed",
            )
        return ReleaseGateDecision(
            eval_report_id=report.report_id,
            suite_revision=report.suite_revision,
            suite_sha256=report.suite_sha256,
            status=status,
            reasons=reasons,
            known_limitations=known_limitations,
            thresholds=active,
        )
