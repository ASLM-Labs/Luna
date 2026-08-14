from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from luna.context import (
    ContextBudget,
    ContextInterpretation,
    ContextLayer,
    ContextSourceKind,
    LayeredContextCandidate,
    LayeredContextComposer,
    LayeredContextPolicy,
)
from luna.context.window import (
    ModelWindowBlockReason,
    ModelWindowProjectionStatus,
    ModelWindowProjector,
    estimate_context_entry_tokens,
    estimate_tool_specs_tokens,
)
from luna.tools import build_phase5_registry

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def _candidate(
    *,
    layer: ContextLayer,
    locator: str,
    text: str,
    priority: int = 50,
    required: bool = False,
    interpretation: ContextInterpretation = ContextInterpretation.DATA_ONLY,
) -> LayeredContextCandidate:
    return LayeredContextCandidate.from_text(
        layer=layer,
        kind=ContextSourceKind.COMMAND_OUTPUT,
        locator=locator,
        text=text,
        priority=priority,
        required=required,
        interpretation=interpretation,
        verified=True,
        observed_at=NOW,
    )


def _bundle(*candidates: LayeredContextCandidate):
    return LayeredContextComposer().compose(
        task_id=uuid4(),
        candidates=candidates,
        policy=LayeredContextPolicy(
            overall_budget=ContextBudget(
                max_sources=32,
                max_chars=64_000,
                max_estimated_tokens=16_000,
            )
        ),
        as_of=NOW,
    )


def test_direct_projection_preserves_every_entry_and_canonical_bundle() -> None:
    required = _candidate(
        layer=ContextLayer.TASK,
        locator="task://required",
        text="Do not modify protected files.",
        required=True,
        interpretation=ContextInterpretation.CONTROL,
    )
    optional = _candidate(
        layer=ContextLayer.WORKSPACE,
        locator="file://README.md",
        text="Repository documentation.",
    )
    bundle = _bundle(required, optional)
    before = bundle.model_dump(mode="json")
    fixed_tokens = 20
    context_tokens = sum(estimate_context_entry_tokens(entry) for entry in bundle.entries())

    projection = ModelWindowProjector().project(
        bundle=bundle,
        max_estimated_tokens=fixed_tokens + context_tokens,
        fixed_estimated_tokens=fixed_tokens,
    )

    assert projection.status is ModelWindowProjectionStatus.DIRECT
    assert projection.retained_entries == bundle.entries()
    assert projection.omitted_optional_locators == ()
    assert projection.projection_notice is None
    assert projection.source_context_fingerprint == bundle.fingerprint()
    assert bundle.model_dump(mode="json") == before


def test_overflow_omits_only_whole_optional_entries_and_reports_compaction() -> None:
    required = _candidate(
        layer=ContextLayer.TASK,
        locator="task://required",
        text="Preserve the required task constraint.",
        required=True,
        interpretation=ContextInterpretation.CONTROL,
    )
    useful = _candidate(
        layer=ContextLayer.RUNTIME_CONTINUITY,
        locator="runtime://useful",
        text="recent observation",
        priority=100,
    )
    large_optional = _candidate(
        layer=ContextLayer.WORKSPACE,
        locator="file://large",
        text="x" * 4000,
        priority=1,
    )
    bundle = _bundle(required, useful, large_optional)
    required_entry = next(entry for entry in bundle.entries() if entry.required)
    useful_entry = next(
        entry for entry in bundle.entries() if entry.source.locator == "runtime://useful"
    )
    cap = (
        estimate_context_entry_tokens(required_entry)
        + estimate_context_entry_tokens(useful_entry)
        + 200
    )

    projection = ModelWindowProjector().project(
        bundle=bundle,
        max_estimated_tokens=cap,
    )

    assert projection.status is ModelWindowProjectionStatus.COMPACTED
    assert "runtime://useful" in {
        entry.source.locator for entry in projection.retained_entries
    }
    assert projection.omitted_optional_locators == ("file://large",)
    assert projection.projection_notice is not None
    assert "Do not infer omitted content" in projection.projection_notice
    assert all(
        entry.source.locator != "file://large"
        for entry in projection.retained_entries
    )


def test_required_context_beats_higher_layer_optional_context_under_pressure() -> None:
    optional_active = _candidate(
        layer=ContextLayer.ACTIVE,
        locator="active://optional",
        text="optional active detail",
        priority=100,
        interpretation=ContextInterpretation.CONTROL,
    )
    required_task = _candidate(
        layer=ContextLayer.TASK,
        locator="task://required",
        text="required task constraint",
        priority=1,
        required=True,
        interpretation=ContextInterpretation.CONTROL,
    )
    large_workspace = _candidate(
        layer=ContextLayer.WORKSPACE,
        locator="file://large",
        text="y" * 4000,
        priority=100,
    )
    bundle = _bundle(optional_active, required_task, large_workspace)
    required_entry = next(entry for entry in bundle.entries() if entry.required)

    projection = ModelWindowProjector().project(
        bundle=bundle,
        max_estimated_tokens=estimate_context_entry_tokens(required_entry) + 200,
    )

    retained = {entry.source.locator for entry in projection.retained_entries}
    assert projection.status is ModelWindowProjectionStatus.COMPACTED
    assert "task://required" in retained
    assert "file://large" not in retained


def test_required_context_that_cannot_fit_blocks_without_partial_projection() -> None:
    required = _candidate(
        layer=ContextLayer.TASK,
        locator="task://too-large",
        text="required " * 400,
        required=True,
        interpretation=ContextInterpretation.CONTROL,
    )
    bundle = _bundle(required)

    projection = ModelWindowProjector().project(
        bundle=bundle,
        max_estimated_tokens=10,
    )

    assert projection.status is ModelWindowProjectionStatus.BLOCKED
    assert projection.block_reason is ModelWindowBlockReason.REQUIRED_CONTEXT_EXCEEDS_WINDOW
    assert projection.blocking_required_locators == ("task://too-large",)
    assert projection.retained_entries == ()
    assert projection.projection_notice is None


def test_fixed_input_that_alone_exceeds_window_blocks_before_context_projection() -> None:
    optional = _candidate(
        layer=ContextLayer.WORKSPACE,
        locator="file://optional",
        text="optional context",
    )
    bundle = _bundle(optional)

    projection = ModelWindowProjector().project(
        bundle=bundle,
        max_estimated_tokens=50,
        fixed_estimated_tokens=51,
    )

    assert projection.status is ModelWindowProjectionStatus.BLOCKED
    assert projection.block_reason is ModelWindowBlockReason.FIXED_INPUT_EXCEEDS_WINDOW
    assert projection.retained_entries == ()


def test_runtime_observation_entry_is_atomic_and_never_sliced() -> None:
    observation_text = (
        '{"request":{"tool_name":"filesystem.read_text"},'
        '"result":{"stdout":"complete-result"},'
        '"observation":{"status":"SUCCESS"}}'
    )
    observation = _candidate(
        layer=ContextLayer.RUNTIME_CONTINUITY,
        locator="runtime://observation/123",
        text=observation_text,
        priority=95,
    )
    huge_optional = _candidate(
        layer=ContextLayer.WORKSPACE,
        locator="file://huge",
        text="z" * 4000,
    )
    bundle = _bundle(observation, huge_optional)
    observation_entry = next(
        entry
        for entry in bundle.entries()
        if entry.source.locator == "runtime://observation/123"
    )

    projection = ModelWindowProjector().project(
        bundle=bundle,
        max_estimated_tokens=estimate_context_entry_tokens(observation_entry) + 200,
    )

    retained = next(
        entry
        for entry in projection.retained_entries
        if entry.source.locator == "runtime://observation/123"
    )
    assert retained.source.content_excerpt == observation_text
    assert retained.interpretation is ContextInterpretation.DATA_ONLY
    assert bundle.entries()[0].source.content_excerpt in {
        observation_text,
        "z" * 4000,
    }


def test_projection_is_deterministic_for_same_basis() -> None:
    required = _candidate(
        layer=ContextLayer.TASK,
        locator="task://required",
        text="required",
        required=True,
        interpretation=ContextInterpretation.CONTROL,
    )
    optional_a = _candidate(
        layer=ContextLayer.RUNTIME_CONTINUITY,
        locator="runtime://a",
        text="a" * 400,
        priority=90,
    )
    optional_b = _candidate(
        layer=ContextLayer.WORKSPACE,
        locator="file://b",
        text="b" * 4000,
        priority=10,
    )
    bundle = _bundle(required, optional_a, optional_b)
    projector = ModelWindowProjector()

    first = projector.project(
        bundle=bundle,
        max_estimated_tokens=350,
        fixed_estimated_tokens=20,
    )
    second = projector.project(
        bundle=bundle,
        max_estimated_tokens=350,
        fixed_estimated_tokens=20,
    )

    assert first == second
    assert first.fingerprint() == second.fingerprint()
    assert first.source_context_fingerprint == bundle.fingerprint()


def test_model_visible_tool_schemas_have_deterministic_request_cost() -> None:
    specs = build_phase5_registry().specs()

    first = estimate_tool_specs_tokens(specs)
    second = estimate_tool_specs_tokens(specs)

    assert first > 0
    assert first == second
