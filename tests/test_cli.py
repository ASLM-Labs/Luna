from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from luna.audit import AppendOnlyAuditLedger, AuditEventKind
from luna.cli import main


def test_status_command(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["status"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "phase: 14" in output
    assert "tool_dispatcher: deny_by_default" in output
    assert "workspace_writes: snapshot_first_atomic" in output
    assert "shell_parsing: disabled" in output
    assert "network_tools: disabled" in output
    assert "memory_policy: candidate_verify_commit_or_reject" in output
    assert "plaintext_secrets_in_memory: blocked" in output
    assert "identity_profile: versioned_runtime_owned" in output
    assert "final_report: gate_bound_and_audited" in output
    assert "autonomy_levels: 0_1_2_3_4_runtime_enforced" in output
    assert "free_research: separate_expiring_contract_required" in output
    assert "model_authority_escalation: blocked" in output
    assert "fixed_eval_suite: revision_locked_sha256" in output
    assert "regression_runner: deterministic_comparable_metrics" in output
    assert "release_gate: runtime_owned_thresholds" in output
    assert "runtime_request: source_actor_scope_budget_bound" in output
    assert "runtime_budget: read_only_default" in output
    assert "context_layers: active_task_runtime_workspace_verified_memory" in output
    assert "context_budget: per_layer_and_overall_runtime_enforced" in output
    assert "context_unobserved: excluded_never_implied" in output
    assert "context_secrets: blocked_or_redacted_before_model_view" in output
    assert "context_memory: verified_data_only" in output
    assert "context_freshness: explicit_and_deterministic" in output
    assert "action_proposal: untrusted_no_authority" in output
    assert "tool_selection: two_stage_runtime_owned" in output
    assert "structured_denial: blocked_observation" in output
    assert "side_effect_proposals: max_one_per_iteration" in output
    assert "selection_execution_boundary: dispatcher_required" in output
    assert "failure_taxonomy: structured_runtime_owned" in output
    assert "blind_retry: changed_basis_required" in output
    assert "minimal_change: path_and_line_budget_enforced" in output
    assert "scope_creep: observed_change_cannot_expand_approval" in output
    assert "workspace_isolation: snapshot_low_medium_worktree_high_critical" in output
    assert "worktree_downgrade: blocked" in output
    assert "policy_agent_loop: single_identity_authoritative_task_state" in output
    assert "side_effect_journal: write_ahead_sqlite_fence" in output
    assert "runtime_observations: durable_data_only_context" in output
    assert "effective_workspace: isolated_root_persists_across_steps" in output
    assert "safe_control: suspend_cancel_at_runtime_boundaries" in output
    assert "resume_side_effect_replay: ambiguous_started_action_blocked" in output
    assert "completion_handoff: phase12f_gate_bound" in output
    assert "evidence_strength: runtime_owned_weak_moderate_strong_deterministic" in output
    assert "evidence_disagreement: unresolved_conflict_blocks_success" in output
    assert "evidence_store: sqlite_wal_hash_checked" in output
    assert "finalization: gate_report_terminal_checkpoint" in output
    assert "learning_candidates: review_required_no_auto_commit" in output
    assert "runtime_conformance_suite: revision_locked_sha256" in output
    assert "runtime_e2e_cases: 11_critical" in output
    assert "scope_path_preflight: deny_before_dispatch" in output
    assert "phase12_acceptance: component_plus_runtime_e2e" in output
    assert "model_compatibility: required_text_single_tool_json_args" in output
    assert "model_backend_failures: structured_provider_neutral" in output
    assert "model_failure_retry: never_blind" in output
    assert "model_rollout: blocked_shadow_canary_active_runtime_owned" in output
    assert "shadow_authority: none" in output
    assert "canary_allocation: deterministic_task_bucket" in output
    assert "rollout_tripwires: false_success_authority_backend_invalid_turn" in output
    assert "live_probe: loopback_only_no_rollout_authority" in output
    assert "research_gateway: runtime_owned_read_only" in output
    assert "research_network: explicit_runtime_and_policy_authority" in output
    assert "research_domains: allow_deny_fail_closed" in output
    assert "research_budget: request_elapsed_token_bound" in output
    assert "research_provenance: publisher_url_retrieval_sha256" in output
    assert "research_citations: current_claims_source_bound" in output
    assert "research_injection: data_only_no_runtime_control" in output
    assert "research_external_actions: forbidden" in output
    assert "research_memory: review_required_no_auto_commit" in output
    assert "research_document_evidence: moderate_non_terminal" in output


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "Luna 0.1.0"


def test_resolve_intent_command_returns_json(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["resolve-intent", "README.md dosyasını incele"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["kind"] == "CODE_INSPECTION"
    assert payload["referenced_resources"] == ["README.md"]


def test_list_tools(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["list-tools"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "core.echo" in output
    assert "filesystem.read_text" in output
    assert "filesystem.write_text" in output
    assert "workspace.rollback" in output
    assert "process.run_argv" in output


def test_tool_smoke_runs_through_dispatcher(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["tool-smoke", "hello"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["result"]["status"] == "SUCCESS"
    assert payload["result"]["stdout_excerpt"] == "hello"
    assert payload["event"]["decision"] == "EXECUTED"


def test_workspace_smoke_writes_and_rolls_back(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["workspace-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["write_status"] == "SUCCESS"
    assert payload["rollback_status"] == "SUCCESS"
    assert payload["file_exists_after_rollback"] is False
    assert payload["rollback_verified"] is True


def test_process_smoke_uses_shell_false(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["process-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["result"]["status"] == "SUCCESS"
    assert payload["result"]["metadata"]["shell"] is False


def test_audit_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["audit-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["integrity"] is True
    assert payload["event_count"] == 6
    assert payload["secret_absent"] is True


def test_audit_inspect_prints_only_selected_task(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = AppendOnlyAuditLedger(tmp_path)
    selected_task = uuid4()
    other_task = uuid4()
    trace_id = uuid4()
    ledger.append(
        kind=AuditEventKind.OBSERVATION,
        task_id=selected_task,
        trace_id=trace_id,
        subject_id=str(uuid4()),
        payload={"status": "SUCCESS"},
    )
    ledger.append(
        kind=AuditEventKind.OBSERVATION,
        task_id=other_task,
        trace_id=uuid4(),
        subject_id=str(uuid4()),
        payload={"status": "FAILURE"},
    )

    exit_code = main(["audit-inspect", str(tmp_path), str(selected_task)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert len(payload) == 1
    assert payload[0]["task_id"] == str(selected_task)
    assert payload[0]["trace_id"] == str(trace_id)


def test_verify_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["verify-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "VERIFIED_COMPLETE"
    assert payload["audit_integrity"] is True
    assert "VERIFICATION_REPORT" in payload["event_kinds"]
    assert "COMPLETION_DECISION" in payload["event_kinds"]


def test_checkpoint_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["checkpoint-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["resume_status"] == "READY"
    assert payload["resumed_phase"] == "PLANNED"
    assert payload["journal_mode"] == "wal"
    assert payload["integrity"] is True
    assert "CHECKPOINT_CREATED" in payload["event_kinds"]
    assert "RESUME_DECISION" in payload["event_kinds"]


def test_memory_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["memory-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["journal_mode"] == "wal"
    assert payload["integrity"] is True
    assert payload["verified_committed"] == "COMMIT"
    assert payload["model_inference_rejected"] is True
    assert payload["one_off_preference_rejected"] is True
    assert payload["secret_absent_from_persistence"] is True
    assert payload["source_preserved"] is True
    assert "MEMORY_COMMITTED" in payload["event_kinds"]
    assert "MEMORY_RETRIEVAL" in payload["event_kinds"]


def test_phase10_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["phase10-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["identity_name"] == "Luna"
    assert payload["hard_coded_user_absent"] is True
    assert payload["completion_status"] == "VERIFIED_COMPLETE"
    assert payload["report_sections_separated"] is True
    assert payload["final_report_audited"] is True
    assert payload["level_zero_blocked"] is True
    assert payload["level_one_allowed"] is True
    assert payload["free_research_domain_allowed"] is True
    assert payload["audit_integrity"] is True


def test_phase11_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["phase11-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["total_cases"] == 11
    assert payload["passed_cases"] == 11
    assert payload["critical_failures"] == 0
    assert payload["false_verified_complete_count"] == 0
    assert payload["protected_path_violation_count"] == 0
    assert payload["blind_retry_count"] == 0
    assert payload["release_status"] == "PASS"
    assert payload["known_limitations_published"] is True


def test_phase12a_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["phase12a-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["source"] == "TEST"
    assert payload["actor_role"] == "OWNER"
    assert payload["actor_verified"] is True
    assert payload["read_only_default"] is True
    assert payload["request_round_trip"] is True
    assert payload["outcome_round_trip"] is True
    assert payload["stop_reason"] == "COMPLETED"
    assert payload["completion_status"] == "VERIFIED_COMPLETE"


def test_phase12b_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["phase12b-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["layer_order"] == [
        "ACTIVE",
        "TASK",
        "RUNTIME_CONTINUITY",
        "WORKSPACE",
        "VERIFIED_MEMORY",
    ]
    assert payload["ready"] is True
    assert payload["entry_count"] == 4
    assert payload["secret_absent"] is True
    assert payload["redactions_applied"] is True
    assert payload["unverified_memory_blocked"] is True
    assert payload["memory_data_only"] is True
    assert payload["fingerprint_length"] == 64
    assert payload["round_trip"] is True


def test_phase12c_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["phase12c-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["prepared_status"] == "PREPARED"
    assert payload["selected_tool"] == "filesystem.read_text"
    assert payload["dispatcher_required"] is True
    assert payload["denied_status"] == "DENIED"
    assert payload["denial_code"] == "UNKNOWN_PREFERRED_TOOL"
    assert payload["denial_observation"] == "BLOCKED"


def test_phase12d_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["phase12d-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["failure_category"] == "RESOURCE_UNAVAILABLE"
    assert payload["recovery_action"] == "SUSPEND"
    assert payload["minimal_change_allowed"] is True
    assert payload["isolation_mode"] == "WORKTREE"
    assert payload["isolation_allowed"] is False
    assert payload["worktree_required"] is True
    assert payload["no_silent_downgrade"] is True


def test_phase12e_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["phase12e-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["single_policy_agent_loop"] is True
    assert payload["durable_control"] is True
    assert payload["journal_integrity"] is True
    assert payload["journal_schema_version"] == 2
    assert payload["observation_continuity"] == "durable_data_only"
    assert payload["side_effect_replay"] == "write_ahead_fenced"
    assert payload["completion_handoff"] == "VERIFICATION_PENDING"


def test_phase12f_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["phase12f-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["strong_status"] == "VERIFIED_COMPLETE"
    assert payload["strong_strength"] == "DETERMINISTIC"
    assert payload["weak_status"] == "INCONCLUSIVE"
    assert payload["weak_qualifying"] is False
    assert payload["conflict_status"] == "CONFLICTING_EVIDENCE"
    assert payload["disagreement_count"] == 1
    assert payload["evidence_store_integrity"] is True
    assert payload["learning_review_required"] is True
    assert payload["learning_auto_commit"] is False


def test_phase12g_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["phase12g-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["suite_revision"] == "1.0.0"
    assert len(payload["suite_sha256"]) == 64
    assert payload["total_cases"] == 11
    assert payload["passed_cases"] == 11
    assert payload["failed_cases"] == 0
    assert payload["critical_failures"] == 0
    assert payload["verified_completion"] == "COMPLETED"
    assert payload["false_complete_guard"] == "VERIFICATION_PENDING"
    assert payload["scope_denial"] == "PERMISSION_DENIED"
    assert payload["scope_denial_tool_calls"] == 0
    assert payload["worktree_cleanup"] is True
    assert payload["stale_evidence_status"] == "UNVERIFIED"


def test_phase13_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["phase13-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["required_compatibility_pass"] is True
    assert payload["eligible_for_rollout"] is True
    assert len(payload["compatibility_fingerprint"]) == 64
    assert payload["shadow_authorized"] is False
    assert payload["active_authorized"] is True
    assert payload["tripwire_authorized"] is False
    assert payload["live_probe_authority"] == "none"


def test_phase14_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["phase14-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["network_requests"] == 1
    assert payload["admitted_sources"] == 1
    assert payload["publishable_claims"] == 1
    assert payload["citation_count"] == 1
    assert payload["blocked_domain_before_dispatch"] is True
    assert payload["injection_detected"] is True
    assert payload["source_interpretation"] == "DATA_ONLY"
    assert payload["runtime_control_allowed"] is False
    assert payload["external_actions_allowed"] is False
    assert payload["automatic_memory_commit_allowed"] is False
    assert payload["memory_review_required"] is True
