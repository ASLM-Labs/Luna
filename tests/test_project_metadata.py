from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_expected_python_version_and_developer() -> None:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]

    assert project["version"] == "0.1.0"
    assert project["requires-python"] == ">=3.12,<3.14"
    assert project["authors"] == [{"name": "Novopic Intelligence"}]


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
