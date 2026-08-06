"""Phase 11 acceptance orchestration."""

from __future__ import annotations

from pathlib import Path

from luna.acceptance.executor import CoreAcceptanceExecutor
from luna.acceptance.gate import ReleaseGate
from luna.acceptance.models import ReleaseGateDecision, ReleaseThresholds
from luna.evals import EvalReport, RegressionRunner, build_core_eval_suite

DEFAULT_KNOWN_LIMITATIONS = (
    "Real network research remains disabled in the Luna 0.1 core.",
    "Voice, Discord, desktop UI, Atlas review, and training integration "
    "require separate RFC gates.",
    "The fixed Phase 11 suite uses a deterministic backend and local filesystem fixtures.",
)


def run_core_acceptance(
    workspace_root: Path,
    *,
    known_limitations: tuple[str, ...] = DEFAULT_KNOWN_LIMITATIONS,
    thresholds: ReleaseThresholds | None = None,
) -> tuple[EvalReport, ReleaseGateDecision]:
    """Run the locked suite against real core components and apply release thresholds."""
    suite = build_core_eval_suite()
    report = RegressionRunner().run(
        suite=suite,
        executor=CoreAcceptanceExecutor(),
        workspace_root=workspace_root,
    )
    decision = ReleaseGate().evaluate(
        report=report,
        suite=suite,
        known_limitations=known_limitations,
        thresholds=thresholds,
    )
    return report, decision
