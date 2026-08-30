"""Serializable contracts for Phase 12C action proposals and selection outcomes."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.enums import ObservationStatus
from luna.contracts.observation import Observation
from luna.tools.models import ToolArgumentValue, ToolCapability, ToolOrigin, ToolSpec


class ActionKind(StrEnum):
    """High-level action intent proposed to the runtime."""

    READ = "READ"
    WRITE = "WRITE"
    ROLLBACK = "ROLLBACK"
    PROCESS = "PROCESS"
    UTILITY = "UTILITY"


class ActionTargetKind(StrEnum):
    """Target shape used for deterministic routing without inventing tool names."""

    NONE = "NONE"
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"
    SNAPSHOT = "SNAPSHOT"
    PROCESS = "PROCESS"


class ToolFamily(StrEnum):
    """Runtime-owned tool families used by selection stage one."""

    CORE = "CORE"
    FILESYSTEM = "FILESYSTEM"
    WORKSPACE = "WORKSPACE"
    PROCESS = "PROCESS"


class ActionDenialStage(StrEnum):
    """Stage that produced a structured denial."""

    PROPOSAL = "PROPOSAL"
    FAMILY_SELECTION = "FAMILY_SELECTION"
    TOOL_SELECTION = "TOOL_SELECTION"
    ARGUMENT_VALIDATION = "ARGUMENT_VALIDATION"
    POLICY_PREFLIGHT = "POLICY_PREFLIGHT"


class ActionDenialCode(StrEnum):
    """Stable machine-readable reasons for refusing an action before execution."""

    MULTIPLE_SIDE_EFFECTS = "MULTIPLE_SIDE_EFFECTS"
    INVALID_FAMILY = "INVALID_FAMILY"
    NO_MATCHING_TOOL = "NO_MATCHING_TOOL"
    AMBIGUOUS_TOOL = "AMBIGUOUS_TOOL"
    UNKNOWN_PREFERRED_TOOL = "UNKNOWN_PREFERRED_TOOL"
    PREFERRED_TOOL_MISMATCH = "PREFERRED_TOOL_MISMATCH"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    POLICY_DENIED = "POLICY_DENIED"


_SIDE_EFFECT_CAPABILITIES = {
    ToolCapability.WRITE,
    ToolCapability.NETWORK,
    ToolCapability.PROCESS,
}


class ActionProposal(LunaContractModel):
    """Untrusted action proposal; it expresses intent but grants no authority."""

    proposal_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    trace_id: UUID
    kind: ActionKind
    target_kind: ActionTargetKind = ActionTargetKind.NONE
    summary: str = Field(min_length=1, max_length=2000)
    arguments: dict[str, ToolArgumentValue] = Field(default_factory=dict)
    required_capabilities: tuple[ToolCapability, ...] = ()
    preferred_tool_name: str | None = Field(default=None, max_length=120)
    working_directory: str | None = Field(default=None, max_length=4000)
    timeout_ms: int | None = Field(default=None, ge=1, le=120000)
    max_output_chars: int | None = Field(default=None, ge=1, le=1000000)
    expectation_id: UUID | None = None
    origin: ToolOrigin = ToolOrigin.MODEL

    @field_validator("required_capabilities")
    @classmethod
    def validate_capabilities(
        cls,
        values: tuple[ToolCapability, ...],
    ) -> tuple[ToolCapability, ...]:
        if len(values) != len(set(values)):
            raise ValueError("required capabilities must be unique")
        return values

    @field_validator("preferred_tool_name")
    @classmethod
    def validate_preferred_tool_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or "." not in value:
            raise ValueError("preferred tool name must be a namespaced tool name")
        return value

    @model_validator(mode="after")
    def validate_kind_contract(self) -> ActionProposal:
        required = set(self.required_capabilities)
        minimums = {
            ActionKind.READ: {ToolCapability.READ},
            ActionKind.WRITE: {ToolCapability.WRITE},
            ActionKind.ROLLBACK: {ToolCapability.WRITE},
            ActionKind.PROCESS: {ToolCapability.PROCESS},
            ActionKind.UTILITY: set(),
        }
        expected = minimums[self.kind]
        if not expected.issubset(required):
            missing = ", ".join(sorted(capability.value for capability in expected - required))
            raise ValueError(f"action kind requires capabilities: {missing}")
        if self.kind is ActionKind.READ and required & _SIDE_EFFECT_CAPABILITIES:
            raise ValueError("READ action cannot request side-effect capabilities")
        if self.kind is ActionKind.UTILITY and required:
            raise ValueError("UTILITY action cannot request tool capabilities")
        return self

    @property
    def has_side_effects(self) -> bool:
        """Return whether this proposal can cause an external or workspace effect."""
        return bool(set(self.required_capabilities) & _SIDE_EFFECT_CAPABILITIES)


class ActionProposalBatch(LunaContractModel):
    """One policy-agent iteration worth of proposals."""

    iteration_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    trace_id: UUID
    proposals: tuple[ActionProposal, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_iteration_boundary(self) -> ActionProposalBatch:
        for proposal in self.proposals:
            if proposal.task_id != self.task_id or proposal.trace_id != self.trace_id:
                raise ValueError("proposal task_id and trace_id must match batch")
        side_effect_count = sum(proposal.has_side_effects for proposal in self.proposals)
        if side_effect_count > 1:
            raise ValueError("one iteration may contain at most one side-effect proposal")
        return self


class ToolRoute(LunaContractModel):
    """Runtime-owned selection metadata linking an intent shape to one registered tool."""

    tool_name: str = Field(min_length=1, max_length=120)
    family: ToolFamily
    action_kinds: tuple[ActionKind, ...] = Field(min_length=1)
    target_kinds: tuple[ActionTargetKind, ...] = Field(min_length=1)
    default_for_shape: bool = True

    @field_validator("action_kinds")
    @classmethod
    def validate_action_kinds(
        cls,
        values: tuple[ActionKind, ...],
    ) -> tuple[ActionKind, ...]:
        if len(values) != len(set(values)):
            raise ValueError("tool route action kinds must be unique")
        return values

    @field_validator("target_kinds")
    @classmethod
    def validate_target_kinds(
        cls,
        values: tuple[ActionTargetKind, ...],
    ) -> tuple[ActionTargetKind, ...]:
        if len(values) != len(set(values)):
            raise ValueError("tool route target kinds must be unique")
        return values


class ActionDenial(LunaContractModel):
    """Structured refusal returned to the policy-agent as observable data."""

    denial_id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    task_id: UUID
    trace_id: UUID
    stage: ActionDenialStage
    code: ActionDenialCode
    reason: str = Field(min_length=1, max_length=4000)
    checks: tuple[str, ...] = Field(min_length=1)
    selected_family: ToolFamily | None = None
    selected_tool_name: str | None = Field(default=None, max_length=120)
    retryable: bool = False
    requires_replan: bool = True

    @field_validator("checks")
    @classmethod
    def validate_checks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("denial checks must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("denial checks must be unique")
        return cleaned

    def to_observation(self) -> Observation:
        """Normalize a pre-execution denial into model-visible observation data."""
        return Observation(
            trace_id=self.trace_id,
            status=ObservationStatus.BLOCKED,
            errors=(f"ACTION_DENIED[{self.code.value}]: {self.reason}",),
            measured_values={
                "proposal_id": str(self.proposal_id),
                "denial_stage": self.stage.value,
                "denial_code": self.code.value,
                "requires_replan": self.requires_replan,
                "retryable": self.retryable,
            },
        )


class ActionResolutionStatus(StrEnum):
    """Result of selection and deterministic policy preflight."""

    PREPARED = "PREPARED"
    DENIED = "DENIED"


class ActionResolution(LunaContractModel):
    """Selection result; PREPARED still requires ToolDispatcher re-authorization."""

    resolution_id: UUID = Field(default_factory=uuid4)
    status: ActionResolutionStatus
    proposal: ActionProposal
    selected_family: ToolFamily | None = None
    selected_tool: ToolSpec | None = None
    request_id: UUID | None = None
    policy_checks: tuple[str, ...] = ()
    denial: ActionDenial | None = None
    observation: Observation | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> ActionResolution:
        if self.status is ActionResolutionStatus.PREPARED:
            if (
                self.selected_family is None
                or self.selected_tool is None
                or self.request_id is None
            ):
                raise ValueError("prepared action requires family, selected tool, and request_id")
            if self.denial is not None or self.observation is not None:
                raise ValueError("prepared action cannot carry denial data")
            if not self.policy_checks:
                raise ValueError("prepared action requires policy preflight checks")
        else:
            if self.denial is None or self.observation is None:
                raise ValueError("denied action requires denial and observation")
            if self.request_id is not None:
                raise ValueError("denied action cannot expose an executable request_id")
            if self.observation.status is not ObservationStatus.BLOCKED:
                raise ValueError("denied action observation must be BLOCKED")
        return self
