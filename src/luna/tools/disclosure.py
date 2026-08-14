"""Model-visible tool-schema projection without execution authority."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel


class ToolDisclosureDenialCode(StrEnum):
    """Structured non-authoritative disclosure request failures."""

    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    NOT_DEFERRED = "NOT_DEFERRED"
    UNAVAILABLE = "UNAVAILABLE"


class ToolDisclosureDecisionStatus(StrEnum):
    """Outcome of staging schemas for a future model-request boundary."""

    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


class ToolDisclosureDenial(LunaContractModel):
    tool_name: str = Field(min_length=1, max_length=120)
    code: ToolDisclosureDenialCode
    reason: str = Field(min_length=1, max_length=1000)


class ToolDisclosureState(LunaContractModel):
    """Task-scoped visibility state; it carries no permission or execution fields."""

    task_id: UUID
    deferred_tools: tuple[str, ...] = Field(max_length=100)
    disclosed_tools: tuple[str, ...] = Field(default=(), max_length=100)
    pending_tools: tuple[str, ...] = Field(default=(), max_length=32)
    basis_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    revision: int = Field(default=0, ge=0)

    @field_validator("deferred_tools", "disclosed_tools", "pending_tools")
    @classmethod
    def validate_tool_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("disclosure tool names must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("disclosure tool names must be unique")
        if cleaned != tuple(sorted(cleaned)):
            raise ValueError("disclosure tool names must be sorted")
        return cleaned

    @model_validator(mode="after")
    def validate_visibility_sets(self) -> ToolDisclosureState:
        deferred = set(self.deferred_tools)
        if not set(self.disclosed_tools).issubset(deferred):
            raise ValueError("disclosed tools must be configured as deferred")
        if not set(self.pending_tools).issubset(deferred):
            raise ValueError("pending tools must be configured as deferred")
        return self


class ToolDisclosureDecision(LunaContractModel):
    """A staging result; accepted names remain subject to projection and policy."""

    task_id: UUID
    status: ToolDisclosureDecisionStatus
    requested_tools: tuple[str, ...] = Field(min_length=1, max_length=32)
    accepted_pending_tools: tuple[str, ...] = ()
    denials: tuple[ToolDisclosureDenial, ...] = ()
    authority_granted: bool = False
    state: ToolDisclosureState

    @field_validator("requested_tools", "accepted_pending_tools")
    @classmethod
    def validate_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("requested disclosure names must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("requested disclosure names must be unique")
        if cleaned != tuple(sorted(cleaned)):
            raise ValueError("requested disclosure names must be sorted")
        return cleaned

    @model_validator(mode="after")
    def validate_decision(self) -> ToolDisclosureDecision:
        expected = (
            ToolDisclosureDecisionStatus.PENDING
            if self.accepted_pending_tools and not self.denials
            else ToolDisclosureDecisionStatus.PARTIAL
            if self.accepted_pending_tools
            else ToolDisclosureDecisionStatus.REJECTED
        )
        if self.status is not expected:
            raise ValueError("disclosure decision status does not match accepted/denied tools")
        if self.authority_granted:
            raise ValueError("tool disclosure can never grant execution authority")
        if self.task_id != self.state.task_id:
            raise ValueError("disclosure decision task must match state")
        return self


class ToolVisibilityProjection(LunaContractModel):
    """One deterministic model-facing name projection at a safe request boundary."""

    task_id: UUID
    basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_revision: int = Field(ge=0)
    registered_tools: tuple[str, ...]
    policy_allowed_tools: tuple[str, ...]
    visible_tools: tuple[str, ...]
    deferred_tools: tuple[str, ...]
    unavailable_tools: tuple[str, ...] = ()
    policy_denied_tools: tuple[str, ...] = ()

    @field_validator(
        "registered_tools",
        "policy_allowed_tools",
        "visible_tools",
        "deferred_tools",
        "unavailable_tools",
        "policy_denied_tools",
    )
    @classmethod
    def validate_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or values != tuple(sorted(values)):
            raise ValueError("tool visibility projection names must be unique and sorted")
        return values

    @model_validator(mode="after")
    def validate_projection(self) -> ToolVisibilityProjection:
        visible = set(self.visible_tools)
        if not visible.issubset(self.registered_tools):
            raise ValueError("model-visible tools must remain registered")
        if not visible.issubset(self.policy_allowed_tools):
            raise ValueError("model-visible tools must remain ToolPolicy-allowed")
        if visible & set(self.unavailable_tools):
            raise ValueError("unavailable tools cannot remain model-visible")
        if visible & set(self.policy_denied_tools):
            raise ValueError("policy-denied tools cannot remain model-visible")
        return self


class ToolDisclosureProjector:
    """Pure state transitions for schema visibility; never dispatches or authorizes."""

    @staticmethod
    def configure(
        *,
        task_id: UUID,
        deferred_tools: tuple[str, ...],
        registered_tools: tuple[str, ...],
    ) -> ToolDisclosureState:
        if len(deferred_tools) > 100:
            raise ValueError("tool disclosure configuration exceeds the bounded tool count")
        deferred = tuple(sorted(name.strip() for name in deferred_tools))
        if any(not name for name in deferred):
            raise ValueError("deferred tool names must not be blank")
        if len(deferred) != len(set(deferred)):
            raise ValueError("deferred tool names must be unique")
        registered = set(registered_tools)
        missing = tuple(name for name in deferred if name not in registered)
        if missing:
            raise ValueError("deferred tools must be registered: " + ", ".join(missing))
        return ToolDisclosureState(task_id=task_id, deferred_tools=deferred)

    @staticmethod
    def request(
        state: ToolDisclosureState,
        *,
        tool_names: tuple[str, ...],
        registered_tools: tuple[str, ...],
    ) -> ToolDisclosureDecision:
        if not tool_names:
            raise ValueError("tool disclosure request must name at least one tool")
        if len(tool_names) > 32:
            raise ValueError("tool disclosure request exceeds the bounded tool count")
        requested = tuple(sorted(name.strip() for name in tool_names))
        if any(not name for name in requested):
            raise ValueError("requested disclosure names must not be blank")
        if len(requested) != len(set(requested)):
            raise ValueError("requested disclosure names must be unique")

        registered = set(registered_tools)
        deferred = set(state.deferred_tools)
        accepted: list[str] = []
        denials: list[ToolDisclosureDenial] = []
        for name in requested:
            if name not in registered:
                code = (
                    ToolDisclosureDenialCode.UNAVAILABLE
                    if name in deferred
                    else ToolDisclosureDenialCode.UNKNOWN_TOOL
                )
                denials.append(
                    ToolDisclosureDenial(
                        tool_name=name,
                        code=code,
                        reason=(
                            "deferred tool is currently unavailable"
                            if code is ToolDisclosureDenialCode.UNAVAILABLE
                            else "tool is not registered"
                        ),
                    )
                )
                continue
            if name not in deferred:
                denials.append(
                    ToolDisclosureDenial(
                        tool_name=name,
                        code=ToolDisclosureDenialCode.NOT_DEFERRED,
                        reason="registered tool is not configured as deferred",
                    )
                )
                continue
            accepted.append(name)

        pending = tuple(sorted(set(state.pending_tools) | set(accepted)))
        updated = state.model_copy(
            update={
                "pending_tools": pending,
                "revision": state.revision + (1 if pending != state.pending_tools else 0),
            }
        )
        status = (
            ToolDisclosureDecisionStatus.PENDING
            if accepted and not denials
            else ToolDisclosureDecisionStatus.PARTIAL
            if accepted
            else ToolDisclosureDecisionStatus.REJECTED
        )
        return ToolDisclosureDecision(
            task_id=state.task_id,
            status=status,
            requested_tools=requested,
            accepted_pending_tools=tuple(sorted(accepted)),
            denials=tuple(denials),
            state=updated,
        )

    @staticmethod
    def reset(state: ToolDisclosureState) -> ToolDisclosureState:
        changed = bool(state.disclosed_tools or state.pending_tools)
        return state.model_copy(
            update={
                "disclosed_tools": (),
                "pending_tools": (),
                "revision": state.revision + (1 if changed else 0),
            }
        )

    @staticmethod
    def project(
        state: ToolDisclosureState,
        *,
        basis_fingerprint: str,
        registered_tools: tuple[str, ...],
        policy_allowed_tools: tuple[str, ...],
    ) -> tuple[ToolDisclosureState, ToolVisibilityProjection]:
        registered = set(registered_tools)
        allowed = set(policy_allowed_tools)
        deferred = set(state.deferred_tools)
        context_replaced = (
            state.basis_fingerprint is not None
            and state.basis_fingerprint != basis_fingerprint
        )
        candidates = (
            set()
            if context_replaced
            else set(state.disclosed_tools) | set(state.pending_tools)
        )
        eligible_disclosed = candidates & deferred & registered & allowed
        unavailable = deferred - registered
        policy_denied = deferred - allowed
        initially_visible = (registered & allowed) - deferred
        visible = initially_visible | eligible_disclosed
        next_disclosed = tuple(sorted(eligible_disclosed))
        changed = (
            state.basis_fingerprint != basis_fingerprint
            or state.disclosed_tools != next_disclosed
            or bool(state.pending_tools)
        )
        updated = state.model_copy(
            update={
                "basis_fingerprint": basis_fingerprint,
                "disclosed_tools": next_disclosed,
                "pending_tools": (),
                "revision": state.revision + (1 if changed else 0),
            }
        )
        projection = ToolVisibilityProjection(
            task_id=state.task_id,
            basis_fingerprint=basis_fingerprint,
            state_revision=updated.revision,
            registered_tools=tuple(sorted(registered)),
            policy_allowed_tools=tuple(sorted(allowed)),
            visible_tools=tuple(sorted(visible)),
            deferred_tools=state.deferred_tools,
            unavailable_tools=tuple(sorted(unavailable)),
            policy_denied_tools=tuple(sorted(policy_denied)),
        )
        return updated, projection
