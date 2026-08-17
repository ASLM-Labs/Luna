"""Deterministic, causal-safe projection of canonical context into one model window."""

from __future__ import annotations

import json
from collections.abc import Iterable
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from pydantic import Field, model_validator

from luna.context.layered import (
    CONTEXT_LAYER_ORDER,
    ContextInterpretation,
    LayeredContextBundle,
    LayeredContextEntry,
)
from luna.contracts.base import LunaContractModel
from luna.modeling.contracts import ModelMessage
from luna.tools.models import ToolSpec

_LAYER_RANK = {layer: index for index, layer in enumerate(CONTEXT_LAYER_ORDER)}


class ModelWindowProjectionStatus(StrEnum):
    """Result of projecting one canonical context bundle into one model request."""

    DIRECT = "DIRECT"
    COMPACTED = "COMPACTED"
    BLOCKED = "BLOCKED"


class ModelWindowBlockReason(StrEnum):
    """Why no safe model-window projection can be produced."""

    FIXED_INPUT_EXCEEDS_WINDOW = "FIXED_INPUT_EXCEEDS_WINDOW"
    REQUIRED_CONTEXT_EXCEEDS_WINDOW = "REQUIRED_CONTEXT_EXCEEDS_WINDOW"
    TRANSPARENCY_NOTICE_EXCEEDS_WINDOW = "TRANSPARENCY_NOTICE_EXCEEDS_WINDOW"


def estimate_text_tokens(text: str) -> int:
    """Return Luna's deterministic character-based token estimate."""

    return (len(text) + 3) // 4 if text else 0


def estimate_model_message_tokens(
    *,
    role: str,
    content: str,
    name: str | None = None,
) -> int:
    """Estimate one provider-neutral message including its structural envelope."""

    payload: dict[str, object] = {
        "role": role,
        "content": content,
    }
    if name is not None:
        payload["name"] = name
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return estimate_text_tokens(rendered)


def estimate_model_messages_tokens(messages: Iterable[ModelMessage]) -> int:
    """Estimate a complete provider-neutral message sequence."""

    return sum(
        estimate_model_message_tokens(
            role=message.role.value,
            content=message.content,
            name=message.name,
        )
        for message in messages
    )


def estimate_tool_specs_tokens(specs: Iterable[ToolSpec]) -> int:
    """Estimate model-visible tool schemas without changing tool authority."""

    materialized = tuple(specs)
    if not materialized:
        return 0
    rendered = json.dumps(
        {"tools": [spec.model_dump(mode="json") for spec in materialized]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return estimate_text_tokens(rendered)


def render_context_entry(entry: LayeredContextEntry) -> str:
    """Render one whole admitted entry exactly as model-facing context content."""

    excerpt = entry.source.content_excerpt
    if excerpt is None:
        raise ValueError("model context entry unexpectedly lacks content")
    return (
        f"[{entry.layer.value}] {entry.source.kind.value} "
        f"{entry.source.locator}\n{excerpt}"
    )


def estimate_context_entry_tokens(entry: LayeredContextEntry) -> int:
    """Estimate one atomic context entry without splitting its causal content."""

    role = (
        "SYSTEM"
        if entry.interpretation is ContextInterpretation.CONTROL
        else "TOOL"
    )
    return estimate_model_message_tokens(
        role=role,
        name=f"context_{entry.layer.value.lower()}",
        content=render_context_entry(entry),
    )


def projection_notice(omitted_optional_entries: int) -> str:
    """Return bounded truthful metadata about model-window omission."""

    if omitted_optional_entries < 1:
        raise ValueError("projection notice requires at least one omitted entry")
    payload = {
        "context_window_projection": {
            "status": ModelWindowProjectionStatus.COMPACTED.value,
            "omitted_optional_entries": omitted_optional_entries,
            "instruction": (
                "Optional context was omitted from this model request. "
                "Do not infer omitted content; re-observe decision-critical facts."
            ),
        }
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def estimate_projection_notice_tokens(omitted_optional_entries: int) -> int:
    """Estimate the explicit compaction notice inserted beside retained context."""

    return estimate_model_message_tokens(
        role="SYSTEM",
        name="context_window_projection",
        content=projection_notice(omitted_optional_entries),
    )


class ModelWindowProjection(LunaContractModel):
    """Ephemeral projection result; canonical context remains authoritative."""

    task_id: UUID
    source_context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ModelWindowProjectionStatus
    max_estimated_tokens: int = Field(ge=1)
    fixed_estimated_tokens: int = Field(ge=0)
    retained_entries: tuple[LayeredContextEntry, ...] = ()
    omitted_optional_locators: tuple[str, ...] = ()
    blocking_required_locators: tuple[str, ...] = ()
    projection_notice: str | None = Field(default=None, max_length=4000)
    context_estimated_tokens: int = Field(ge=0)
    projection_notice_estimated_tokens: int = Field(ge=0)
    total_estimated_tokens: int = Field(ge=0)
    block_reason: ModelWindowBlockReason | None = None

    @model_validator(mode="after")
    def validate_projection(self) -> ModelWindowProjection:
        retained_locators = tuple(entry.source.locator for entry in self.retained_entries)
        if len(retained_locators) != len(set(retained_locators)):
            raise ValueError("retained context locators must be unique")
        if len(self.omitted_optional_locators) != len(set(self.omitted_optional_locators)):
            raise ValueError("omitted context locators must be unique")
        if set(retained_locators) & set(self.omitted_optional_locators):
            raise ValueError("retained and omitted context cannot overlap")

        expected_context_tokens = sum(
            estimate_context_entry_tokens(entry) for entry in self.retained_entries
        )
        if self.context_estimated_tokens != expected_context_tokens:
            raise ValueError("context projection token estimate mismatch")
        if self.projection_notice is None:
            expected_notice_tokens = 0
        else:
            expected_notice_tokens = estimate_model_message_tokens(
                role="SYSTEM",
                name="context_window_projection",
                content=self.projection_notice,
            )
        if self.projection_notice_estimated_tokens != expected_notice_tokens:
            raise ValueError("projection notice token estimate mismatch")
        expected_total = (
            self.fixed_estimated_tokens
            + self.context_estimated_tokens
            + self.projection_notice_estimated_tokens
        )
        if self.total_estimated_tokens != expected_total:
            raise ValueError("model-window total token estimate mismatch")

        if self.status is ModelWindowProjectionStatus.DIRECT:
            if (
                self.omitted_optional_locators
                or self.blocking_required_locators
                or self.projection_notice is not None
                or self.block_reason is not None
            ):
                raise ValueError("DIRECT projection cannot carry omission or blocking metadata")
        elif self.status is ModelWindowProjectionStatus.COMPACTED:
            if (
                not self.omitted_optional_locators
                or self.blocking_required_locators
                or self.projection_notice is None
                or self.block_reason is not None
            ):
                raise ValueError("COMPACTED projection requires omission metadata only")
        else:
            if self.retained_entries or self.projection_notice is not None:
                raise ValueError("BLOCKED projection cannot expose a partial model context")
            if self.block_reason is None:
                raise ValueError("BLOCKED projection requires a block reason")

        if (
            self.status is not ModelWindowProjectionStatus.BLOCKED
            and self.total_estimated_tokens > self.max_estimated_tokens
        ):
            raise ValueError("usable model-window projection exceeds configured limit")
        return self

    def fingerprint(self) -> str:
        """Return a stable digest for the projection decision and retained surface."""

        payload = {
            "task_id": str(self.task_id),
            "source_context_fingerprint": self.source_context_fingerprint,
            "status": self.status.value,
            "max_estimated_tokens": self.max_estimated_tokens,
            "fixed_estimated_tokens": self.fixed_estimated_tokens,
            "retained": [
                {
                    "locator": entry.source.locator,
                    "content_digest": entry.source.content_digest,
                    "interpretation": entry.interpretation.value,
                    "required": entry.required,
                }
                for entry in self.retained_entries
            ],
            "omitted_optional_locators": list(self.omitted_optional_locators),
            "blocking_required_locators": list(self.blocking_required_locators),
            "projection_notice": self.projection_notice,
            "block_reason": self.block_reason.value if self.block_reason is not None else None,
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(serialized.encode("utf-8")).hexdigest()


class ModelWindowProjector:
    """Project whole context entries without mutating or summarizing canonical context."""

    def project(
        self,
        *,
        bundle: LayeredContextBundle,
        max_estimated_tokens: int,
        fixed_estimated_tokens: int = 0,
    ) -> ModelWindowProjection:
        if max_estimated_tokens < 1:
            raise ValueError("model-window token limit must be at least 1")
        if fixed_estimated_tokens < 0:
            raise ValueError("fixed model input estimate cannot be negative")

        source_fingerprint = bundle.fingerprint()
        entries = bundle.entries()
        required_entries = tuple(entry for entry in entries if entry.required)
        optional_entries = tuple(entry for entry in entries if not entry.required)
        required_locators = tuple(entry.source.locator for entry in required_entries)

        if fixed_estimated_tokens > max_estimated_tokens:
            return self._blocked(
                bundle=bundle,
                source_fingerprint=source_fingerprint,
                max_estimated_tokens=max_estimated_tokens,
                fixed_estimated_tokens=fixed_estimated_tokens,
                block_reason=ModelWindowBlockReason.FIXED_INPUT_EXCEEDS_WINDOW,
                blocking_required_locators=(),
            )

        all_context_tokens = sum(estimate_context_entry_tokens(entry) for entry in entries)
        direct_total = fixed_estimated_tokens + all_context_tokens
        if direct_total <= max_estimated_tokens:
            return ModelWindowProjection(
                task_id=bundle.task_id,
                source_context_fingerprint=source_fingerprint,
                status=ModelWindowProjectionStatus.DIRECT,
                max_estimated_tokens=max_estimated_tokens,
                fixed_estimated_tokens=fixed_estimated_tokens,
                retained_entries=entries,
                context_estimated_tokens=all_context_tokens,
                projection_notice_estimated_tokens=0,
                total_estimated_tokens=direct_total,
            )

        required_tokens = sum(
            estimate_context_entry_tokens(entry) for entry in required_entries
        )
        if fixed_estimated_tokens + required_tokens > max_estimated_tokens:
            return self._blocked(
                bundle=bundle,
                source_fingerprint=source_fingerprint,
                max_estimated_tokens=max_estimated_tokens,
                fixed_estimated_tokens=fixed_estimated_tokens,
                block_reason=ModelWindowBlockReason.REQUIRED_CONTEXT_EXCEEDS_WINDOW,
                blocking_required_locators=required_locators,
            )

        initial_notice_tokens = estimate_projection_notice_tokens(len(optional_entries))
        if (
            fixed_estimated_tokens + required_tokens + initial_notice_tokens
            > max_estimated_tokens
        ):
            return self._blocked(
                bundle=bundle,
                source_fingerprint=source_fingerprint,
                max_estimated_tokens=max_estimated_tokens,
                fixed_estimated_tokens=fixed_estimated_tokens,
                block_reason=ModelWindowBlockReason.TRANSPARENCY_NOTICE_EXCEEDS_WINDOW,
                blocking_required_locators=(),
            )

        ranked_optional = tuple(
            sorted(
                optional_entries,
                key=lambda entry: (
                    _LAYER_RANK[entry.layer],
                    -entry.priority,
                    entry.source.locator.casefold(),
                    entry.source.content_digest or "",
                    entry.source.kind.value,
                ),
            )
        )
        selected_locators: set[str] = set()
        selected_tokens = 0

        for entry in ranked_optional:
            entry_tokens = estimate_context_entry_tokens(entry)
            next_selected_count = len(selected_locators) + 1
            next_omitted_count = len(optional_entries) - next_selected_count
            notice_tokens = (
                estimate_projection_notice_tokens(next_omitted_count)
                if next_omitted_count > 0
                else 0
            )
            candidate_total = (
                fixed_estimated_tokens
                + required_tokens
                + selected_tokens
                + entry_tokens
                + notice_tokens
            )
            if candidate_total <= max_estimated_tokens:
                selected_locators.add(entry.source.locator)
                selected_tokens += entry_tokens

        retained_entries = tuple(
            entry
            for entry in entries
            if entry.required or entry.source.locator in selected_locators
        )
        omitted_locators = tuple(
            entry.source.locator
            for entry in entries
            if not entry.required and entry.source.locator not in selected_locators
        )
        if not omitted_locators:
            raise RuntimeError("overflow projection unexpectedly retained every optional entry")

        notice = projection_notice(len(omitted_locators))
        context_tokens = sum(
            estimate_context_entry_tokens(entry) for entry in retained_entries
        )
        notice_tokens = estimate_projection_notice_tokens(len(omitted_locators))
        total_tokens = fixed_estimated_tokens + context_tokens + notice_tokens
        return ModelWindowProjection(
            task_id=bundle.task_id,
            source_context_fingerprint=source_fingerprint,
            status=ModelWindowProjectionStatus.COMPACTED,
            max_estimated_tokens=max_estimated_tokens,
            fixed_estimated_tokens=fixed_estimated_tokens,
            retained_entries=retained_entries,
            omitted_optional_locators=omitted_locators,
            projection_notice=notice,
            context_estimated_tokens=context_tokens,
            projection_notice_estimated_tokens=notice_tokens,
            total_estimated_tokens=total_tokens,
        )

    @staticmethod
    def _blocked(
        *,
        bundle: LayeredContextBundle,
        source_fingerprint: str,
        max_estimated_tokens: int,
        fixed_estimated_tokens: int,
        block_reason: ModelWindowBlockReason,
        blocking_required_locators: tuple[str, ...],
    ) -> ModelWindowProjection:
        return ModelWindowProjection(
            task_id=bundle.task_id,
            source_context_fingerprint=source_fingerprint,
            status=ModelWindowProjectionStatus.BLOCKED,
            max_estimated_tokens=max_estimated_tokens,
            fixed_estimated_tokens=fixed_estimated_tokens,
            retained_entries=(),
            omitted_optional_locators=(),
            blocking_required_locators=blocking_required_locators,
            projection_notice=None,
            context_estimated_tokens=0,
            projection_notice_estimated_tokens=0,
            total_estimated_tokens=fixed_estimated_tokens,
            block_reason=block_reason,
        )
