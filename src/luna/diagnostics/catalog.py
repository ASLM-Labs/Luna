"""Authoritative metadata for migrated Luna smoke diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from luna.diagnostics.models import SmokeReport
from luna.diagnostics.scenarios import (
    c001,
    foundational,
    learning,
    model_research,
    phase12f,
    product,
    runtime,
)
from luna.diagnostics.scenarios import capabilities as capability_scenarios


class SmokeGroup(StrEnum):
    CAPABILITY = "CAPABILITY"
    PHASE = "PHASE"
    FOUNDATION = "FOUNDATION"
    TOOL = "TOOL"


@dataclass(frozen=True, slots=True)
class SmokeSpec:
    scenario_id: str
    legacy_name: str
    help: str
    runner: Callable[[], SmokeReport]
    group: SmokeGroup = SmokeGroup.PHASE
    ensure_ascii: bool = False
    sort_keys: bool = False
    indent: int | None = 2


_SMOKE_SPECS = (
    SmokeSpec(
        scenario_id="c001",
        legacy_name="c001-smoke",
        help="Verify deterministic C-001 adaptive knowledge source routing.",
        runner=c001.run,
        group=SmokeGroup.CAPABILITY,
        ensure_ascii=True,
        sort_keys=True,
    ),
    SmokeSpec(
        scenario_id="phase12f",
        legacy_name="phase12f-smoke",
        help="Verify Phase 12F evidence strength, disagreement, and learning boundary.",
        runner=phase12f.run,
    ),
    SmokeSpec(
        scenario_id="workspace",
        legacy_name="workspace-smoke",
        help="Create a temporary file through the dispatcher, then restore its snapshot.",
        runner=foundational.run_workspace,
        group=SmokeGroup.FOUNDATION,
    ),
    SmokeSpec(
        scenario_id="process",
        legacy_name="process-smoke",
        help="Run the exact approved Python --version argv through the dispatcher.",
        runner=foundational.run_process,
        group=SmokeGroup.FOUNDATION,
        indent=None,
    ),
    SmokeSpec(
        scenario_id="audit",
        legacy_name="audit-smoke",
        help="Verify redacted append-only Phase 6 audit.",
        runner=foundational.run_audit,
    ),
    SmokeSpec(
        scenario_id="verify",
        legacy_name="verify-smoke",
        help="Run the deterministic Phase 7 completion gate.",
        runner=foundational.run_verify,
    ),
    SmokeSpec(
        scenario_id="checkpoint",
        legacy_name="checkpoint-smoke",
        help="Persist and resume a Phase 8 SQLite WAL checkpoint.",
        runner=foundational.run_checkpoint,
    ),
    SmokeSpec(
        scenario_id="memory",
        legacy_name="memory-smoke",
        help="Verify Phase 9 memory policy, safe storage, and scoped retrieval.",
        runner=foundational.run_memory,
    ),
    SmokeSpec(
        scenario_id="phase10",
        legacy_name="phase10-smoke",
        help="Verify Phase 10 identity, final reporting, and autonomy enforcement.",
        runner=runtime.run_phase10,
    ),
    SmokeSpec(
        scenario_id="phase11",
        legacy_name="phase11-smoke",
        help="Run the locked Phase 11 eval suite and release gate.",
        runner=runtime.run_phase11,
    ),
    SmokeSpec(
        scenario_id="phase12a",
        legacy_name="phase12a-smoke",
        help="Verify Phase 12A runtime request, fingerprint, and outcome contracts.",
        runner=runtime.run_phase12a,
    ),
    SmokeSpec(
        scenario_id="phase12b",
        legacy_name="phase12b-smoke",
        help="Verify Phase 12B layered, budgeted, secret-safe context composition.",
        runner=runtime.run_phase12b,
    ),
    SmokeSpec(
        scenario_id="phase12c",
        legacy_name="phase12c-smoke",
        help="Verify Phase 12C action proposal, tool selection, and structured denial.",
        runner=runtime.run_phase12c,
    ),
    SmokeSpec(
        scenario_id="phase12d",
        legacy_name="phase12d-smoke",
        help="Verify Phase 12D failure recovery, minimal-change, and isolation policy.",
        runner=runtime.run_phase12d,
    ),
    SmokeSpec(
        scenario_id="phase12e",
        legacy_name="phase12e-smoke",
        help="Verify Phase 12E durable control and single-loop runtime boundary.",
        runner=runtime.run_phase12e,
    ),
    SmokeSpec(
        scenario_id="phase12g",
        legacy_name="phase12g-smoke",
        help="Run the locked Phase 12G runtime E2E behavior-conformance suite.",
        runner=runtime.run_phase12g,
    ),
    SmokeSpec(
        scenario_id="c003",
        legacy_name="c003-smoke",
        help="Verify governed C-003 experience distillation and authority boundaries.",
        runner=capability_scenarios.run_c003,
        group=SmokeGroup.CAPABILITY,
        ensure_ascii=True,
        sort_keys=True,
    ),
    SmokeSpec(
        scenario_id="c007",
        legacy_name="c007-smoke",
        help="Verify governed C-007 debugging decomposition and held-out transfer evaluation.",
        runner=capability_scenarios.run_c007,
        group=SmokeGroup.CAPABILITY,
        ensure_ascii=True,
        sort_keys=True,
    ),
    SmokeSpec(
        scenario_id="phase13",
        legacy_name="phase13-smoke",
        help="Verify Phase 13 model compatibility and controlled rollout gates.",
        runner=model_research.run_phase13,
    ),
    SmokeSpec(
        scenario_id="phase14",
        legacy_name="phase14-smoke",
        help="Verify Phase 14 research policy, provenance, citations, and injection boundary.",
        runner=model_research.run_phase14,
    ),
    SmokeSpec(
        scenario_id="phase15",
        legacy_name="phase15-smoke",
        help="Verify Phase 15 durable queue, scheduler, resource, and notification boundaries.",
        runner=product.run_phase15,
    ),
    SmokeSpec(
        scenario_id="phase16",
        legacy_name="phase16-smoke",
        help="Verify Phase 16 desktop shell presentation and runtime-bound command gateway.",
        runner=product.run_phase16,
        ensure_ascii=True,
    ),
    SmokeSpec(
        scenario_id="phase17",
        legacy_name="phase17-smoke",
        help="Verify Phase 17 verified Discord ingress, queue, role, and audit boundaries.",
        runner=product.run_phase17,
        ensure_ascii=True,
    ),
    SmokeSpec(
        scenario_id="phase18",
        legacy_name="phase18-smoke",
        help="Verify Phase 18 voice transcript, confirmation, session, and queue boundaries.",
        runner=product.run_phase18,
        ensure_ascii=True,
    ),
    SmokeSpec(
        scenario_id="phase19",
        legacy_name="phase19-smoke",
        help=(
            "Verify Phase 19 trace governance, leak-free split, cognitive baseline, "
            "uncertainty, and self-correction boundaries."
        ),
        runner=learning.run_phase19,
        ensure_ascii=True,
    ),
    SmokeSpec(
        scenario_id="phase19b",
        legacy_name="phase19b-smoke",
        help=(
            "Verify Phase 19B frozen held-out/OOD suites, contamination checks, "
            "evaluator independence, and release comparison boundaries."
        ),
        runner=learning.run_phase19b,
        ensure_ascii=True,
    ),
    SmokeSpec(
        scenario_id="phase19c",
        legacy_name="phase19c-smoke",
        help=(
            "Verify Phase 19C shortcut, gaming, overfitting, proxy, confirmation, "
            "and self-confirmation integrity boundaries."
        ),
        runner=learning.run_phase19c,
        ensure_ascii=True,
    ),
    SmokeSpec(
        scenario_id="phase19d",
        legacy_name="phase19d-smoke",
        help=(
            "Verify Phase 19D controlled replay, evidence independence, "
            "counterfactual comparison, and non-authority boundaries."
        ),
        runner=learning.run_phase19d,
        ensure_ascii=True,
    ),
    SmokeSpec(
        scenario_id="phase19e",
        legacy_name="phase19e-smoke",
        help=(
            "Verify Phase 19E normalized train-only corpus governance, frozen "
            "training specification, receipt boundary, and non-promotion rules."
        ),
        runner=learning.run_phase19e,
        ensure_ascii=True,
    ),
    SmokeSpec(
        scenario_id="phase19f",
        legacy_name="phase19f-smoke",
        help=(
            "Verify Phase 19F frozen improvement thresholds, confidence-aware "
            "decision boundary, and no-false-promotion behavior."
        ),
        runner=learning.run_phase19f,
        ensure_ascii=True,
    ),
    SmokeSpec(
        scenario_id="tool",
        legacy_name="tool-smoke",
        help="Run the controlled core.echo tool through the dispatcher.",
        runner=foundational.run_tool,
        group=SmokeGroup.TOOL,
        indent=None,
    ),
)


def validate_smoke_specs(specs: tuple[SmokeSpec, ...]) -> None:
    scenario_ids = tuple(spec.scenario_id for spec in specs)
    legacy_names = tuple(spec.legacy_name for spec in specs)
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ValueError("duplicate smoke scenario id")
    if len(legacy_names) != len(set(legacy_names)):
        raise ValueError("duplicate legacy smoke command name")
    reserved = {"all", "list"}
    if reserved.intersection(scenario_ids):
        raise ValueError("reserved smoke scenario id")


validate_smoke_specs(_SMOKE_SPECS)


def all_smoke_specs() -> tuple[SmokeSpec, ...]:
    return _SMOKE_SPECS


def get_smoke_spec(scenario_id: str) -> SmokeSpec:
    for spec in _SMOKE_SPECS:
        if spec.scenario_id == scenario_id:
            return spec
    raise KeyError(f"unknown smoke scenario: {scenario_id}")


def find_smoke_spec_by_legacy_name(legacy_name: str) -> SmokeSpec | None:
    for spec in _SMOKE_SPECS:
        if spec.legacy_name == legacy_name:
            return spec
    return None


def smoke_specs_for_group(group: SmokeGroup) -> tuple[SmokeSpec, ...]:
    return tuple(spec for spec in _SMOKE_SPECS if spec.group is group)
