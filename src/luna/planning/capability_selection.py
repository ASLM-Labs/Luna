"""C6 observable capability selection over existing deterministic policy outputs.

The selector coordinates already-owned capability decisions. It does not execute tools,
override owner policies, or grant runtime, execution, or completion authority.
"""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel


class CapabilityKind(StrEnum):
    """Cognition capability family coordinated by C6 for one policy turn."""

    SPECIFICATION = "SPECIFICATION"
    ACCEPTANCE_JUDGMENT = "ACCEPTANCE_JUDGMENT"
    DECISION_CONTROL = "DECISION_CONTROL"
    VERIFICATION = "VERIFICATION"
    RETRIEVAL = "RETRIEVAL"
    TOOL_ADVICE = "TOOL_ADVICE"


class CapabilityDisposition(StrEnum):
    """Whether a capability remains selected for downstream use in this turn."""

    SELECTED = "SELECTED"
    SKIPPED = "SKIPPED"


class CapabilitySelectionEntry(LunaContractModel):
    """One bounded C6 selection result with explicit dependency and reason state."""

    capability: CapabilityKind
    disposition: CapabilityDisposition
    depends_on: tuple[CapabilityKind, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("depends_on")
    @classmethod
    def validate_dependencies(
        cls,
        values: tuple[CapabilityKind, ...],
    ) -> tuple[CapabilityKind, ...]:
        if len(values) != len(set(values)):
            raise ValueError("capability dependencies must be unique")
        return values

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("capability-selection reason codes cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("capability-selection reason codes must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_no_self_dependency(self) -> Self:
        if self.capability in self.depends_on:
            raise ValueError("capability cannot depend on itself")
        return self


class CapabilitySelectionPlan(LunaContractModel):
    """Evidence-bound, non-authoritative C6 selection state for one policy turn."""

    _ORDER: ClassVar[tuple[CapabilityKind, ...]] = (
        CapabilityKind.SPECIFICATION,
        CapabilityKind.ACCEPTANCE_JUDGMENT,
        CapabilityKind.DECISION_CONTROL,
        CapabilityKind.VERIFICATION,
        CapabilityKind.RETRIEVAL,
        CapabilityKind.TOOL_ADVICE,
    )

    task_id: UUID
    step_id: UUID
    specification_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    acceptance_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_strategy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: tuple[CapabilitySelectionEntry, ...] = Field(min_length=6, max_length=6)
    provenance_refs: tuple[str, ...] = Field(min_length=4)
    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator("provenance_refs")
    @classmethod
    def validate_provenance_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("capability-selection provenance refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("capability-selection provenance refs must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_selection_graph(self) -> Self:
        actual_order = tuple(item.capability for item in self.entries)
        if actual_order != self._ORDER:
            raise ValueError("C6 capability entries must use canonical dependency order")

        by_capability = {item.capability: item for item in self.entries}
        seen: set[CapabilityKind] = set()
        for entry in self.entries:
            if any(dependency not in seen for dependency in entry.depends_on):
                raise ValueError("capability dependency must precede its dependent entry")
            if entry.disposition is CapabilityDisposition.SELECTED and any(
                by_capability[dependency].disposition is CapabilityDisposition.SKIPPED
                for dependency in entry.depends_on
            ):
                raise ValueError("selected capability cannot depend on a skipped capability")
            seen.add(entry.capability)
        return self

    def selected_capabilities(self) -> tuple[CapabilityKind, ...]:
        return tuple(
            item.capability
            for item in self.entries
            if item.disposition is CapabilityDisposition.SELECTED
        )

    def skipped_capabilities(self) -> tuple[CapabilityKind, ...]:
        return tuple(
            item.capability
            for item in self.entries
            if item.disposition is CapabilityDisposition.SKIPPED
        )


class GeneralCapabilitySelector:
    """Coordinate existing owner decisions without replacing or widening their authority."""

    @staticmethod
    def _selection_fingerprint(
        *,
        task_id: UUID,
        step_id: UUID,
        specification_basis_fingerprint: str,
        acceptance_basis_fingerprint: str,
        decision_basis_fingerprint: str,
        retrieval_strategy_fingerprint: str,
        decision_control_action: str,
        retrieval_decision: str,
        verification_depth: str,
        considered_tool_names: tuple[str, ...],
        entries: tuple[CapabilitySelectionEntry, ...],
    ) -> str:
        payload = {
            "acceptance_basis_fingerprint": acceptance_basis_fingerprint,
            "considered_tool_names": considered_tool_names,
            "decision_basis_fingerprint": decision_basis_fingerprint,
            "decision_control_action": decision_control_action,
            "entries": tuple(item.model_dump(mode="json") for item in entries),
            "retrieval_decision": retrieval_decision,
            "retrieval_strategy_fingerprint": retrieval_strategy_fingerprint,
            "specification_basis_fingerprint": specification_basis_fingerprint,
            "step_id": str(step_id),
            "task_id": str(task_id),
            "verification_depth": verification_depth,
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(serialized.encode("utf-8")).hexdigest()

    def select(
        self,
        *,
        task_id: UUID,
        step_id: UUID,
        specification_basis_fingerprint: str,
        acceptance_basis_fingerprint: str,
        decision_basis_fingerprint: str,
        retrieval_strategy_fingerprint: str,
        decision_control_action: str,
        retrieval_decision: str,
        verification_depth: str,
        considered_tool_names: tuple[str, ...],
    ) -> CapabilitySelectionPlan:
        """Return one deterministic selection plan over already-owned capability decisions."""
        if decision_control_action not in {"CONTINUE", "SWITCH", "STOP_VERIFY"}:
            raise ValueError("unknown C6 decision-control action")
        if retrieval_decision not in {"ANSWER_DIRECT", "RETRIEVE", "STOP_REINSPECT"}:
            raise ValueError("unknown C6 retrieval decision")
        if verification_depth not in {"TARGETED", "BROAD", "REGRESSION"}:
            raise ValueError("unknown C6 verification depth")

        cleaned_tools = tuple(name.strip() for name in considered_tool_names)
        if any(not name for name in cleaned_tools):
            raise ValueError("considered C6 tool names cannot be blank")
        if len(cleaned_tools) != len(set(cleaned_tools)):
            raise ValueError("considered C6 tool names must be unique")

        if retrieval_decision == "RETRIEVE":
            retrieval_disposition = CapabilityDisposition.SELECTED
            retrieval_reasons = (
                "retrieval_route_selected",
                "owner_retrieval_decision_preserved",
            )
        elif retrieval_decision == "ANSWER_DIRECT":
            retrieval_disposition = CapabilityDisposition.SKIPPED
            retrieval_reasons = (
                "retrieval_activation_not_required",
                "decision_relevant_evidence_already_sufficient",
            )
        else:
            retrieval_disposition = CapabilityDisposition.SKIPPED
            retrieval_reasons = (
                "retrieval_activation_blocked",
                "stop_reinspect_preserved",
            )

        tool_disposition = (
            CapabilityDisposition.SELECTED
            if cleaned_tools
            else CapabilityDisposition.SKIPPED
        )
        tool_reasons = (
            ("already_allowed_tool_surface_available", "tool_policy_remains_outer_bound")
            if cleaned_tools
            else ("no_already_allowed_tools_available", "tool_policy_remains_outer_bound")
        )

        entries = (
            CapabilitySelectionEntry(
                capability=CapabilityKind.SPECIFICATION,
                disposition=CapabilityDisposition.SELECTED,
                reason_codes=("specification_basis_required",),
            ),
            CapabilitySelectionEntry(
                capability=CapabilityKind.ACCEPTANCE_JUDGMENT,
                disposition=CapabilityDisposition.SELECTED,
                depends_on=(CapabilityKind.SPECIFICATION,),
                reason_codes=("acceptance_basis_required",),
            ),
            CapabilitySelectionEntry(
                capability=CapabilityKind.DECISION_CONTROL,
                disposition=CapabilityDisposition.SELECTED,
                depends_on=(CapabilityKind.ACCEPTANCE_JUDGMENT,),
                reason_codes=(
                    f"decision_control:{decision_control_action}",
                    "owner_decision_control_preserved",
                ),
            ),
            CapabilitySelectionEntry(
                capability=CapabilityKind.VERIFICATION,
                disposition=CapabilityDisposition.SELECTED,
                depends_on=(CapabilityKind.ACCEPTANCE_JUDGMENT,),
                reason_codes=(
                    f"verification_depth:{verification_depth}",
                    "owner_verification_strategy_preserved",
                ),
            ),
            CapabilitySelectionEntry(
                capability=CapabilityKind.RETRIEVAL,
                disposition=retrieval_disposition,
                depends_on=(CapabilityKind.DECISION_CONTROL,),
                reason_codes=retrieval_reasons,
            ),
            CapabilitySelectionEntry(
                capability=CapabilityKind.TOOL_ADVICE,
                disposition=tool_disposition,
                depends_on=(
                    CapabilityKind.DECISION_CONTROL,
                    CapabilityKind.VERIFICATION,
                ),
                reason_codes=tool_reasons,
            ),
        )
        fingerprint = self._selection_fingerprint(
            task_id=task_id,
            step_id=step_id,
            specification_basis_fingerprint=specification_basis_fingerprint,
            acceptance_basis_fingerprint=acceptance_basis_fingerprint,
            decision_basis_fingerprint=decision_basis_fingerprint,
            retrieval_strategy_fingerprint=retrieval_strategy_fingerprint,
            decision_control_action=decision_control_action,
            retrieval_decision=retrieval_decision,
            verification_depth=verification_depth,
            considered_tool_names=cleaned_tools,
            entries=entries,
        )
        return CapabilitySelectionPlan(
            task_id=task_id,
            step_id=step_id,
            specification_basis_fingerprint=specification_basis_fingerprint,
            acceptance_basis_fingerprint=acceptance_basis_fingerprint,
            decision_basis_fingerprint=decision_basis_fingerprint,
            retrieval_strategy_fingerprint=retrieval_strategy_fingerprint,
            selection_basis_fingerprint=fingerprint,
            entries=entries,
            provenance_refs=(
                "c4:specification_basis:" + specification_basis_fingerprint,
                "c5:acceptance_basis:" + acceptance_basis_fingerprint,
                "c2:decision_basis:" + decision_basis_fingerprint,
                "retrieval_strategy:" + retrieval_strategy_fingerprint,
            ),
        )
