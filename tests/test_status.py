from __future__ import annotations

from luna.capabilities import build_canonical_capability_registry
from luna.console.commands.status import status_lines
from luna.diagnostics.status import STATUS_FACTS, StatusFactKind
from luna.tools import build_phase5_registry


def test_status_contract_is_complete_ordered_and_unique() -> None:
    lines = status_lines()
    keys = tuple(line.split(": ", maxsplit=1)[0] for line in lines)

    assert len(lines) == len(STATUS_FACTS) == 199
    assert len(keys) == len(set(keys))
    assert keys[0:4] == ("phase", "status", "tool_dispatcher", "registered_tools")
    assert keys[-1] == "c007_runtime_training_memory_promotion_authority"


def test_status_derived_facts_follow_authoritative_sources() -> None:
    values = dict(line.split(": ", maxsplit=1) for line in status_lines())
    capabilities = build_canonical_capability_registry()

    assert values["registered_tools"] == str(len(build_phase5_registry().specs()))
    assert values["autonomy_levels"] == "0_1_2_3_4_runtime_enforced"
    assert values["context_layers"] == "active_task_runtime_workspace_verified_memory"
    assert values["runtime_e2e_cases"] == "11_critical"
    assert values["phase19f_critical_regression"] == "zero_tolerance"
    assert values["phase19f_decisions"] == "promote_reject_rollback_or_insufficient"
    assert values["phase19f_runtime_authority"] == "none"
    assert values["c002_capability_lineage"].startswith(
        capabilities.get("C-002").status.value.lower()
    )
    assert values["c001_adaptive_retrieval"].startswith(
        capabilities.get("C-001").status.value.lower()
    )
    assert values["c003_experience_distillation"].startswith(
        capabilities.get("C-003").status.value.lower()
    )
    assert values["c007_debugging_transfer"].startswith(
        capabilities.get("C-007").status.value.lower()
    )


def test_status_manifest_has_explicit_truth_classification() -> None:
    derived_keys = {fact.key for fact in STATUS_FACTS if fact.kind is StatusFactKind.DERIVED}

    assert derived_keys == {
        "registered_tools",
        "autonomy_levels",
        "context_layers",
        "runtime_e2e_cases",
        "phase19f_critical_regression",
        "phase19f_decisions",
        "phase19f_runtime_authority",
        "c002_capability_lineage",
        "c001_adaptive_retrieval",
        "c003_experience_distillation",
        "c007_debugging_transfer",
    }
