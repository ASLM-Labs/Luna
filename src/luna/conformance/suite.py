"""Locked Phase 12G cross-layer runtime behavior suite."""

from __future__ import annotations

from luna.conformance.models import (
    ConformanceCase,
    ConformanceDomain,
    LockedConformanceSuite,
)

RUNTIME_CONFORMANCE_SUITE_SHA256 = (
    "52346f987ad274b02b265c431d309be0dd83e2bc100fb497634474f294ab644e"
)


def _cases() -> tuple[ConformanceCase, ...]:
    return (
        ConformanceCase(
            case_id="L12G-01-verified-completion",
            title="Current deterministic evidence is required before runtime completion",
            domain=ConformanceDomain.COMPLETION_TRUTH,
            scenario="verified_completion",
            oracle={
                "first_stop": "VERIFICATION_PENDING",
                "final_stop": "COMPLETED",
                "completion_status": "VERIFIED_COMPLETE",
                "closed": True,
                "final_report_bound": True,
                "terminal_checkpoint": True,
            },
            tags=("runtime-e2e", "verification", "continuity"),
        ),
        ConformanceCase(
            case_id="L12G-02-no-false-complete",
            title="No evidence cannot become a successful completion claim",
            domain=ConformanceDomain.COMPLETION_TRUTH,
            scenario="no_evidence_pending",
            oracle={
                "stop_reason": "VERIFICATION_PENDING",
                "completion_status": None,
                "closed": False,
                "final_report_bound": False,
            },
            tags=("runtime-e2e", "false-success"),
        ),
        ConformanceCase(
            case_id="L12G-03-weak-evidence-resumable",
            title="Weak evidence yields an explicit resumable inconclusive state",
            domain=ConformanceDomain.EVIDENCE_DISCIPLINE,
            scenario="weak_evidence_resumable",
            oracle={
                "stop_reason": "INCONCLUSIVE",
                "completion_status": "INCONCLUSIVE",
                "checkpointed": True,
                "terminal": False,
                "resume_phase": "VERIFYING",
            },
            tags=("runtime-e2e", "evidence", "resume"),
        ),
        ConformanceCase(
            case_id="L12G-04-conflicting-evidence",
            title="Equal deterministic PASS and FAIL evidence remains unresolved",
            domain=ConformanceDomain.EVIDENCE_DISCIPLINE,
            scenario="conflicting_evidence",
            oracle={
                "stop_reason": "CONFLICTING_EVIDENCE",
                "completion_status": "CONFLICTING_EVIDENCE",
                "closed": False,
                "terminal": False,
            },
            tags=("runtime-e2e", "evidence", "conflict"),
        ),
        ConformanceCase(
            case_id="L12G-05-multi-action-blocked",
            title="One policy turn cannot dispatch multiple actions",
            domain=ConformanceDomain.POLICY_BOUNDARY,
            scenario="multiple_actions_blocked",
            oracle={
                "stop_reason": "BLOCKED",
                "model_calls": 1,
                "tool_calls": 0,
                "observation_count": 0,
                "invalid_turn_visible": True,
            },
            tags=("runtime-e2e", "single-action", "model-boundary"),
        ),
        ConformanceCase(
            case_id="L12G-06-cancel-safe-boundary",
            title="Owner cancellation wins before model or tool execution",
            domain=ConformanceDomain.SAFE_CONTROL,
            scenario="cancel_safe_boundary",
            oracle={
                "stop_reason": "CANCELLED",
                "model_calls": 0,
                "tool_calls": 0,
                "control_acknowledged": True,
            },
            tags=("runtime-e2e", "cancel", "control"),
        ),
        ConformanceCase(
            case_id="L12G-07-started-side-effect-no-replay",
            title="Ambiguous STARTED side effects are never blindly replayed after restart",
            domain=ConformanceDomain.SIDE_EFFECT_REPLAY,
            scenario="started_side_effect_no_replay",
            oracle={
                "fence_stage": "STARTED",
                "initial_dispatch_calls": 1,
                "resume_stop": "INTERRUPTED",
                "resume_model_calls": 0,
                "resume_tool_calls": 0,
                "file_created": False,
                "replay_forbidden_visible": True,
            },
            tags=("runtime-e2e", "idempotency", "restart"),
        ),
        ConformanceCase(
            case_id="L12G-08-scope-denial-no-dispatch",
            title="Out-of-scope mutation is denied before dispatcher execution",
            domain=ConformanceDomain.SCOPE_INTEGRITY,
            scenario="scope_denial_no_dispatch",
            oracle={
                "stop_reason": "PERMISSION_DENIED",
                "model_calls": 1,
                "tool_calls": 0,
                "outside_file_created": False,
                "denial_observed": True,
            },
            tags=("runtime-e2e", "scope", "deny-before-execute"),
        ),
        ConformanceCase(
            case_id="L12G-09-high-risk-worktree",
            title="High-risk writes stay isolated and observations feed the next turn",
            domain=ConformanceDomain.ISOLATION,
            scenario="high_risk_worktree",
            oracle={
                "stop_reason": "VERIFICATION_PENDING",
                "isolation_mode": "WORKTREE",
                "original_preserved": True,
                "isolated_changed": True,
                "bounded_worktree_path": True,
                "second_turn_saw_observation": True,
                "proposal_secret_not_replayed": True,
                "cleanup_verified": True,
            },
            tags=("runtime-e2e", "worktree", "observation"),
        ),
        ConformanceCase(
            case_id="L12G-10-tool-budget-pre-dispatch",
            title="Zero tool-call budget blocks before dispatcher execution",
            domain=ConformanceDomain.BUDGET,
            scenario="tool_budget_pre_dispatch",
            oracle={
                "stop_reason": "BLOCKED",
                "model_calls": 1,
                "tool_calls": 0,
                "budget_reason_visible": True,
            },
            tags=("runtime-e2e", "budget", "deny-before-execute"),
        ),
        ConformanceCase(
            case_id="L12G-11-stale-evidence-rejected",
            title="Deterministic evidence from an old revision cannot complete the current task",
            domain=ConformanceDomain.EVIDENCE_DISCIPLINE,
            scenario="stale_evidence_rejected",
            oracle={
                "stop_reason": "UNVERIFIED",
                "completion_status": "UNVERIFIED",
                "closed": False,
                "terminal": False,
                "resume_phase": "VERIFYING",
            },
            tags=("runtime-e2e", "revision", "evidence"),
        ),
    )


def build_runtime_conformance_suite() -> LockedConformanceSuite:
    """Return the revision-locked Phase 12G runtime suite."""
    return LockedConformanceSuite(
        suite_name="Luna 0.1 Runtime Behavior Conformance",
        revision="1.0.0",
        cases=_cases(),
        locked_sha256=RUNTIME_CONFORMANCE_SUITE_SHA256,
    )
