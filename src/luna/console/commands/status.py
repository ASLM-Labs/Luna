"""Side-effect-free project status command with explicit truth ownership."""

from __future__ import annotations

import argparse
from collections.abc import Callable

from luna.capabilities import build_canonical_capability_registry
from luna.conformance import build_runtime_conformance_suite
from luna.context import CONTEXT_LAYER_ORDER
from luna.diagnostics.status import STATUS_FACTS, StatusFact, StatusFactKind
from luna.improvement_gate import (
    ImprovementGateDecision,
    build_default_improvement_gate_policy,
)
from luna.tools import AutonomyLevel, build_phase5_registry

DerivedResolver = Callable[[], str]


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "status",
        help="Show the current project phase and capability state.",
    )
    parser.set_defaults(_handler=handle)


def _registered_tools() -> str:
    return str(len(build_phase5_registry().specs()))


def _autonomy_levels() -> str:
    levels = "_".join(level.value.split("_")[1] for level in AutonomyLevel)
    return f"{levels}_runtime_enforced"


def _context_layers() -> str:
    names = (
        "runtime" if layer.value == "RUNTIME_CONTINUITY" else layer.value.lower()
        for layer in CONTEXT_LAYER_ORDER
    )
    return "_".join(names)


def _runtime_e2e_cases() -> str:
    cases = build_runtime_conformance_suite().cases
    classification = "critical" if all(case.critical for case in cases) else "mixed"
    return f"{len(cases)}_{classification}"


def _improvement_gate_decisions() -> str:
    decisions = tuple(
        (
            "insufficient"
            if item is ImprovementGateDecision.INSUFFICIENT_EVIDENCE
            else item.value.lower()
        )
        for item in ImprovementGateDecision
    )
    return f"{'_'.join(decisions[:-1])}_or_{decisions[-1]}"


def _phase19f_critical_regression() -> str:
    policy = build_default_improvement_gate_policy()
    return "zero_tolerance" if policy.critical_regression_zero_tolerance else "tolerance_allowed"


def _phase19f_runtime_authority() -> str:
    policy = build_default_improvement_gate_policy()
    return "granted" if policy.runtime_authority else "none"


def _capability_status(capability_id: str, suffix: str) -> str:
    record = build_canonical_capability_registry().get(capability_id)
    return f"{record.status.value.lower()}_{suffix}"


def _derived_resolvers() -> dict[str, DerivedResolver]:
    return {
        "registered_tools": _registered_tools,
        "autonomy_levels": _autonomy_levels,
        "context_layers": _context_layers,
        "runtime_e2e_cases": _runtime_e2e_cases,
        "phase19f_critical_regression": _phase19f_critical_regression,
        "phase19f_decisions": _improvement_gate_decisions,
        "phase19f_runtime_authority": _phase19f_runtime_authority,
        "c002_capability_lineage": lambda: _capability_status("C-002", "read_only"),
        "c001_adaptive_retrieval": lambda: _capability_status("C-001", "routing_only"),
        "c003_experience_distillation": lambda: _capability_status(
            "C-003", "review_required"
        ),
        "c007_debugging_transfer": lambda: _capability_status("C-007", "paired_heldout"),
    }


def resolve_status_fact(fact: StatusFact) -> str:
    if fact.kind is StatusFactKind.DECLARED:
        if fact.declared_value is None:
            raise RuntimeError(f"declared status fact has no value: {fact.key}")
        return fact.declared_value
    resolver = _derived_resolvers().get(fact.key)
    if resolver is None:
        raise RuntimeError(f"derived status fact has no resolver: {fact.key}")
    return resolver()


def status_lines() -> tuple[str, ...]:
    return tuple(f"{fact.key}: {resolve_status_fact(fact)}" for fact in STATUS_FACTS)


def handle(_args: argparse.Namespace) -> int:
    for line in status_lines():
        print(line)
    return 0
