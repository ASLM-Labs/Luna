from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_expected_python_version_and_developer() -> None:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]

    assert project["version"] == "0.1.0"
    assert project["requires-python"] == ">=3.12,<3.14"
    assert project["authors"] == [{"name": "Westline Labs"}]


def test_governance_constitution_is_present() -> None:
    constitution = PROJECT_ROOT / "docs" / "governance" / "Luna_0.1_Teknik_Anayasa_v0.1.md"
    assert constitution.is_file()
    assert "ONAYLANDI" in constitution.read_text(encoding="utf-8")


def test_phase_twelve_a_adds_runtime_contracts_without_network_package() -> None:
    package_root = PROJECT_ROOT / "src" / "luna"
    present = {path.name for path in package_root.iterdir() if path.is_dir()}

    assert {
        "workspace",
        "shell",
        "audit",
        "verification",
        "continuity",
        "memory",
        "identity",
        "reporting",
        "autonomy",
        "evals",
        "acceptance",
        "runtime",
    }.issubset(present)
    assert "network" not in present


def test_license_contains_full_apache_terms() -> None:
    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text


def test_phase_twelve_a_rfc_and_source_baseline_are_present() -> None:
    assert (
        PROJECT_ROOT / "docs" / "rfcs" / "RFC-012A_SINGLE_POLICY_AGENT_RUNTIME.md"
    ).is_file()
    assert (
        PROJECT_ROOT / "docs" / "baselines" / "PHASE_11_SOURCE_BASELINE.md"
    ).is_file()


def test_phase_twelve_b_layered_context_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "context" / "composer.py").is_file()
    assert (project_root / "src" / "luna" / "context" / "layered.py").is_file()
    assert (project_root / "scripts" / "verify_phase12b.py").is_file()
    assert (
        project_root / "docs" / "rfcs" / "RFC-012B_LAYERED_CONTEXT_COMPOSER.md"
    ).is_file()


def test_phase_twelve_c_action_selection_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "actions" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "actions" / "selector.py").is_file()
    assert (project_root / "src" / "luna" / "actions" / "resolver.py").is_file()
    assert (project_root / "scripts" / "verify_phase12c.py").is_file()
    assert (
        project_root / "docs" / "rfcs" / "RFC-012C_ACTION_PROPOSAL_TOOL_SELECTION.md"
    ).is_file()


def test_phase_twelve_d_recovery_policy_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "recovery" / "classifier.py").is_file()
    assert (project_root / "src" / "luna" / "recovery" / "policy.py").is_file()
    assert (project_root / "src" / "luna" / "recovery" / "minimal_change.py").is_file()
    assert (project_root / "src" / "luna" / "recovery" / "isolation.py").is_file()
    assert (project_root / "scripts" / "verify_phase12d.py").is_file()
    assert (
        project_root / "docs" / "rfcs" / "RFC-012D_FAILURE_RECOVERY_MINIMAL_CHANGE.md"
    ).is_file()


def test_phase_twelve_e_single_policy_loop_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "runtime" / "loop.py").is_file()
    assert (project_root / "src" / "luna" / "runtime" / "policy_agent.py").is_file()
    assert (project_root / "src" / "luna" / "runtime" / "journal.py").is_file()
    assert (project_root / "src" / "luna" / "runtime" / "isolation.py").is_file()
    assert (project_root / "src" / "luna" / "runtime" / "environment.py").is_file()
    assert (project_root / "scripts" / "verify_phase12e.py").is_file()
    assert (
        project_root / "docs" / "rfcs" / "RFC-012E_SINGLE_POLICY_AGENT_LOOP.md"
    ).is_file()


def test_phase_twelve_f_verification_evidence_learning_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "verification" / "evidence_store.py").is_file()
    assert (project_root / "src" / "luna" / "verification" / "coordinator.py").is_file()
    assert (project_root / "src" / "luna" / "learning" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "learning" / "builder.py").is_file()
    assert (project_root / "scripts" / "verify_phase12f.py").is_file()
    assert (
        project_root
        / "docs"
        / "rfcs"
        / "RFC-012F_VERIFICATION_EVIDENCE_LEARNING.md"
    ).is_file()


def test_phase_twelve_g_runtime_conformance_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "conformance" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "conformance" / "runner.py").is_file()
    assert (project_root / "src" / "luna" / "conformance" / "runtime_executor.py").is_file()
    assert (project_root / "src" / "luna" / "conformance" / "suite.py").is_file()
    assert (project_root / "scripts" / "verify_phase12g.py").is_file()
    assert (
        project_root
        / "docs"
        / "rfcs"
        / "RFC-012G_RUNTIME_E2E_BEHAVIOR_CONFORMANCE.md"
    ).is_file()


def test_phase_thirteen_model_compatibility_and_rollout_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "modeling" / "errors.py").is_file()
    assert (project_root / "src" / "luna" / "modeling" / "compatibility.py").is_file()
    assert (project_root / "src" / "luna" / "modeling" / "rollout.py").is_file()
    assert (project_root / "scripts" / "verify_phase13.py").is_file()
    assert (
        project_root
        / "docs"
        / "rfcs"
        / "RFC-013_REAL_MODEL_COMPATIBILITY_CONTROLLED_ROLLOUT.md"
    ).is_file()


def test_phase_fourteen_research_gateway_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "research" / "gateway.py").is_file()
    assert (project_root / "src" / "luna" / "research" / "policy.py").is_file()
    assert (project_root / "src" / "luna" / "research" / "sources.py").is_file()
    assert (project_root / "src" / "luna" / "research" / "provenance.py").is_file()
    assert (project_root / "src" / "luna" / "research" / "injection_guard.py").is_file()
    assert (project_root / "src" / "luna" / "research" / "evidence_adapter.py").is_file()
    assert (project_root / "scripts" / "verify_phase14.py").is_file()
    assert (
        project_root
        / "docs"
        / "rfcs"
        / "RFC-014_RESEARCH_GATEWAY_EVIDENCE_RAG.md"
    ).is_file()


def test_phase_fifteen_operations_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "operations" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "operations" / "store.py").is_file()
    assert (project_root / "src" / "luna" / "operations" / "queue.py").is_file()
    assert (project_root / "src" / "luna" / "operations" / "resources.py").is_file()
    assert (project_root / "src" / "luna" / "operations" / "scheduler.py").is_file()
    assert (project_root / "src" / "luna" / "operations" / "notifications.py").is_file()
    assert (project_root / "src" / "luna" / "operations" / "coordinator.py").is_file()
    assert (project_root / "scripts" / "verify_phase15.py").is_file()
    assert (
        project_root
        / "docs"
        / "rfcs"
        / "RFC-015_RESOURCE_MANAGER_QUEUE_SCHEDULER_NOTIFICATIONS.md"
    ).is_file()


def test_phase_sixteen_desktop_product_shell_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "desktop" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "desktop" / "gateway.py").is_file()
    assert (project_root / "src" / "luna" / "desktop" / "presenter.py").is_file()
    assert (project_root / "src" / "luna" / "desktop" / "controller.py").is_file()
    assert (project_root / "src" / "luna" / "desktop" / "tk_shell.py").is_file()
    assert (project_root / "scripts" / "verify_phase16.py").is_file()
    assert (
        project_root / "docs" / "rfcs" / "RFC-016_DESKTOP_PRODUCT_SHELL.md"
    ).is_file()


def test_phase_seventeen_discord_gateway_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "discord" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "discord" / "policy.py").is_file()
    assert (project_root / "src" / "luna" / "discord" / "rate_limit.py").is_file()
    assert (project_root / "src" / "luna" / "discord" / "moderation.py").is_file()
    assert (project_root / "src" / "luna" / "discord" / "gateway.py").is_file()
    assert (project_root / "scripts" / "verify_phase17.py").is_file()
    assert (
        project_root / "docs" / "rfcs" / "RFC-017_DISCORD_GATEWAY.md"
    ).is_file()



def test_phase_eighteen_voice_gateway_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "voice" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "voice" / "adapters.py").is_file()
    assert (project_root / "src" / "luna" / "voice" / "confirmation.py").is_file()
    assert (project_root / "src" / "luna" / "voice" / "session.py").is_file()
    assert (project_root / "src" / "luna" / "voice" / "gateway.py").is_file()
    assert (project_root / "scripts" / "verify_phase18.py").is_file()
    assert (project_root / "docs" / "rfcs" / "RFC-018_VOICE_GATEWAY.md").is_file()


def test_phase_nineteen_trace_governance_and_cognitive_quality_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "trajectories" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "trajectories" / "reconstruction.py").is_file()
    assert (project_root / "src" / "luna" / "trajectories" / "normalization.py").is_file()
    assert (project_root / "src" / "luna" / "trajectories" / "split.py").is_file()
    assert (project_root / "src" / "luna" / "trajectories" / "transform.py").is_file()
    assert (project_root / "src" / "luna" / "cognition" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "cognition" / "evaluator.py").is_file()
    assert (project_root / "scripts" / "verify_phase19.py").is_file()
    assert (
        project_root
        / "docs"
        / "rfcs"
        / "RFC-019_TRACE_DATASET_GOVERNANCE_COGNITIVE_QUALITY.md"
    ).is_file()


def test_phase_nineteen_b_evaluation_governance_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "evaluation_governance" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "evaluation_governance" / "suite.py").is_file()
    assert (
        project_root / "src" / "luna" / "evaluation_governance" / "contamination.py"
    ).is_file()
    assert (
        project_root / "src" / "luna" / "evaluation_governance" / "comparison.py"
    ).is_file()
    assert (project_root / "scripts" / "verify_phase19b.py").is_file()
    assert (
        project_root / "docs" / "rfcs" / "RFC-019B_EVALUATION_GOVERNANCE.md"
    ).is_file()


def test_phase_nineteen_c_learning_integrity_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "learning_integrity" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "learning_integrity" / "policy.py").is_file()
    assert (project_root / "src" / "luna" / "learning_integrity" / "audit.py").is_file()
    assert (project_root / "scripts" / "verify_phase19c.py").is_file()
    assert (
        project_root / "docs" / "rfcs" / "RFC-019C_LEARNING_INTEGRITY.md"
    ).is_file()

def test_phase_nineteen_d_counterfactual_analysis_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "counterfactual" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "counterfactual" / "policy.py").is_file()
    assert (project_root / "src" / "luna" / "counterfactual" / "analysis.py").is_file()
    assert (project_root / "scripts" / "verify_phase19d.py").is_file()
    assert (
        project_root / "docs" / "rfcs" / "RFC-019D_COUNTERFACTUAL_ANALYSIS.md"
    ).is_file()


def test_phase_nineteen_e_small_controlled_sft_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "sft" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "sft" / "policy.py").is_file()
    assert (project_root / "src" / "luna" / "sft" / "corpus.py").is_file()
    assert (project_root / "src" / "luna" / "sft" / "candidate.py").is_file()
    assert (project_root / "scripts" / "verify_phase19e.py").is_file()
    assert (
        project_root / "docs" / "rfcs" / "RFC-019E_SMALL_CONTROLLED_SFT.md"
    ).is_file()


def test_phase_nineteen_f_improvement_gate_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "improvement_gate" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "improvement_gate" / "policy.py").is_file()
    assert (project_root / "src" / "luna" / "improvement_gate" / "gate.py").is_file()
    assert (project_root / "scripts" / "verify_phase19f.py").is_file()
    assert (
        project_root / "docs" / "rfcs" / "RFC-019F_IMPROVEMENT_GATE.md"
    ).is_file()


def test_c002_capability_lineage_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "capabilities" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "capabilities" / "registry.py").is_file()
    assert (project_root / "src" / "luna" / "capabilities" / "catalog.py").is_file()
    assert (project_root / "scripts" / "verify_c002.py").is_file()
    assert (project_root / "docs" / "rfcs" / "RFC-C002_CAPABILITY_LINEAGE_MAPPING.md").is_file()
    assert (project_root / "docs" / "C002_CAPABILITY_LINEAGE_REPORT.md").is_file()


def test_c001_adaptive_knowledge_retrieval_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "retrieval" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "retrieval" / "router.py").is_file()
    assert (project_root / "scripts" / "verify_c001.py").is_file()
    assert (
        project_root
        / "docs"
        / "rfcs"
        / "RFC-C001_ADAPTIVE_KNOWLEDGE_RETRIEVAL.md"
    ).is_file()
    assert (
        project_root / "docs" / "C001_ADAPTIVE_KNOWLEDGE_RETRIEVAL_REPORT.md"
    ).is_file()

def test_c003_experience_distillation_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "experience" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "experience" / "distillation.py").is_file()
    assert (project_root / "scripts" / "verify_c003.py").is_file()
    assert (
        project_root / "docs" / "rfcs" / "RFC-C003_EXPERIENCE_DISTILLATION.md"
    ).is_file()
    assert (
        project_root / "docs" / "C003_EXPERIENCE_DISTILLATION_REPORT.md"
    ).is_file()


def test_c007_debugging_capability_transfer_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "debugging" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "debugging" / "evaluator.py").is_file()
    assert (project_root / "scripts" / "verify_c007.py").is_file()
    assert (
        project_root
        / "docs"
        / "rfcs"
        / "RFC-C007_DEBUGGING_CAPABILITY_DECOMPOSITION_TRANSFER.md"
    ).is_file()
    assert (
        project_root / "docs" / "C007_DEBUGGING_CAPABILITY_TRANSFER_REPORT.md"
    ).is_file()

def test_wave2_local_judgment_foundation_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "planning" / "judgment.py").is_file()
    assert (project_root / "src" / "luna" / "actions" / "advisory.py").is_file()
    assert (project_root / "src" / "luna" / "verification" / "strategy.py").is_file()
    assert (project_root / "scripts" / "verify_wave2.py").is_file()

def test_r7b_working_session_continuity_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "sessions" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "sessions" / "store.py").is_file()
    assert (project_root / "src" / "luna" / "sessions" / "service.py").is_file()
    assert (project_root / "scripts" / "verify_r7b.py").is_file()

def test_r7c_resume_compatibility_vector_files_are_present() -> None:
    project_root = PROJECT_ROOT
    assert (project_root / "src" / "luna" / "continuity" / "models.py").is_file()
    assert (project_root / "src" / "luna" / "continuity" / "service.py").is_file()
    assert (project_root / "src" / "luna" / "runtime" / "environment.py").is_file()
    assert (project_root / "src" / "luna" / "runtime" / "journal.py").is_file()
    assert (project_root / "scripts" / "verify_r7c.py").is_file()
    assert (project_root / "tests" / "test_r7c_resume_compatibility.py").is_file()
