"""Information-aware advisory ranking for model-visible tools."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.planning.judgment import InformationGainPlan, InformationNeedKind
from luna.tools.models import ToolCapability, ToolSpec
from luna.verification.strategy import VerificationDepth, VerificationStrategy


class ToolAdvice(LunaContractModel):
    """Non-authoritative ordering hint over tools that are already allowed."""

    recommended_tool_names: tuple[str, ...]
    considered_tool_names: tuple[str, ...]
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("recommended_tool_names", "considered_tool_names", "reason_codes")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("tool advice entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("tool advice entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_subset(self) -> ToolAdvice:
        if not set(self.recommended_tool_names).issubset(self.considered_tool_names):
            raise ValueError("tool advice cannot recommend an unavailable tool")
        return self


class InformationAwareToolAdvisor:
    """Rank allowed ToolSpecs by information value without granting execution authority."""

    @staticmethod
    def _score(
        spec: ToolSpec,
        *,
        need_kind: InformationNeedKind,
        verification: VerificationStrategy,
    ) -> tuple[int, str]:
        capabilities = set(spec.capabilities)
        score = 0

        if need_kind in {
            InformationNeedKind.OBSERVE_STATE,
            InformationNeedKind.RESOLVE_UNCERTAINTY,
        }:
            if ToolCapability.READ in capabilities:
                score += 50
            if capabilities & {ToolCapability.WRITE, ToolCapability.NETWORK}:
                score -= 30
        elif need_kind is InformationNeedKind.VERIFY_ACCEPTANCE:
            if ToolCapability.PROCESS in capabilities:
                score += 45
            if ToolCapability.READ in capabilities:
                score += 35
            if ToolCapability.WRITE in capabilities:
                score -= 40

        if (
            verification.depth is VerificationDepth.REGRESSION
            and ToolCapability.PROCESS in capabilities
        ):
            score += 20
        elif (
            verification.depth is VerificationDepth.TARGETED
            and ToolCapability.READ in capabilities
        ):
            score += 10

        return (-score, spec.name)

    def advise(
        self,
        *,
        available_tools: tuple[ToolSpec, ...],
        information_gain: InformationGainPlan,
        verification: VerificationStrategy,
    ) -> ToolAdvice:
        selected = next(
            item
            for item in information_gain.needs
            if item.need_id == information_gain.selected_need_id
        )
        ordered = tuple(
            sorted(
                available_tools,
                key=lambda spec: self._score(
                    spec,
                    need_kind=selected.kind,
                    verification=verification,
                ),
            )
        )
        names = tuple(spec.name for spec in ordered)
        return ToolAdvice(
            recommended_tool_names=names,
            considered_tool_names=tuple(spec.name for spec in available_tools),
            reason_codes=(
                f"information_need:{selected.kind.value}",
                f"verification_depth:{verification.depth.value}",
                "advisory_only_no_authority",
            ),
        )

    def ordered_specs(
        self,
        *,
        available_tools: tuple[ToolSpec, ...],
        advice: ToolAdvice,
    ) -> tuple[ToolSpec, ...]:
        by_name = {spec.name: spec for spec in available_tools}
        return tuple(by_name[name] for name in advice.recommended_tool_names)
