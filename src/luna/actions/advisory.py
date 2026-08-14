"""Information-aware advisory ranking for model-visible tools."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.planning.judgment import InformationGainPlan, InformationNeedKind
from luna.retrieval.models import KnowledgeSource
from luna.tools.models import ToolCapability, ToolSpec
from luna.verification.strategy import VerificationDepth, VerificationStrategy


class ToolAlternative(LunaContractModel):
    """One already-available tool treated as a ranked information-action alternative."""

    tool_name: str = Field(min_length=1, max_length=300)
    expected_information_gain: int = Field(ge=0, le=100)
    risk_cost: int = Field(ge=0, le=100)
    verification_bonus: int = Field(ge=0, le=100)
    net_score: int = Field(ge=-100, le=200)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    runtime_authority: Literal[False] = False

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("tool alternative reason codes cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("tool alternative reason codes must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_score(self) -> Self:
        expected = self.expected_information_gain + self.verification_bonus - self.risk_cost
        if self.net_score != expected:
            raise ValueError("tool alternative net_score must match its components")
        return self


class ToolAdvice(LunaContractModel):
    """Non-authoritative ordering hint over tools that are already allowed."""

    recommended_tool_names: tuple[str, ...]
    considered_tool_names: tuple[str, ...]
    alternatives: tuple[ToolAlternative, ...] = ()
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
    def validate_subset(self) -> Self:
        considered = set(self.considered_tool_names)
        if not set(self.recommended_tool_names).issubset(considered):
            raise ValueError("tool advice cannot recommend an unavailable tool")
        alternative_names = tuple(item.tool_name for item in self.alternatives)
        if len(alternative_names) != len(set(alternative_names)):
            raise ValueError("tool alternatives must be unique")
        if set(alternative_names) != considered:
            raise ValueError("tool alternatives must cover the considered tool set exactly")
        if self.recommended_tool_names != alternative_names:
            raise ValueError("recommended tool order must match ranked alternatives")
        return self


class InformationAwareToolAdvisor:
    """Rank allowed ToolSpecs by information value without granting execution authority."""

    @staticmethod
    def matches_retrieval_source(spec: ToolSpec, source: KnowledgeSource | None) -> bool:
        """Return whether an already-allowed tool matches the selected retrieval source."""
        if source is None:
            return False
        capabilities = set(spec.capabilities)
        name = spec.name
        if source is KnowledgeSource.WORKSPACE_TOOL:
            return (
                ToolCapability.READ in capabilities
                and ToolCapability.NETWORK not in capabilities
                and (name.startswith("filesystem.") or name.startswith("workspace."))
            )
        if source is KnowledgeSource.RESEARCH_GATEWAY:
            return name.startswith("research.") and ToolCapability.NETWORK in capabilities
        if source is KnowledgeSource.STRUCTURED_API:
            return (
                (name.startswith("api.") or name.startswith("structured_api."))
                and ToolCapability.NETWORK in capabilities
            )
        if source is KnowledgeSource.PROJECT_RAG:
            return (
                (name.startswith("rag.") or name.startswith("project_rag."))
                and ToolCapability.READ in capabilities
            )
        if source is KnowledgeSource.VERIFIED_MEMORY:
            return (
                (name.startswith("memory.") or name.startswith("verified_memory."))
                and ToolCapability.READ in capabilities
            )
        return False

    @staticmethod
    def _alternative(
        spec: ToolSpec,
        *,
        need_kind: InformationNeedKind,
        verification: VerificationStrategy,
    ) -> ToolAlternative:
        capabilities = set(spec.capabilities)
        information_gain = 0
        risk_cost = 0
        verification_bonus = 0
        reasons: list[str] = []

        if need_kind in {
            InformationNeedKind.OBSERVE_STATE,
            InformationNeedKind.RESOLVE_UNCERTAINTY,
        }:
            if ToolCapability.READ in capabilities:
                information_gain += 50
                reasons.append("direct_observation_value")
            if ToolCapability.PROCESS in capabilities:
                information_gain += 20
                risk_cost += 10
                reasons.append("process_observation_value")
            if ToolCapability.WRITE in capabilities:
                risk_cost += 30
                reasons.append("write_risk_penalty")
            if ToolCapability.NETWORK in capabilities:
                risk_cost += 30
                reasons.append("network_risk_penalty")
        elif need_kind is InformationNeedKind.VERIFY_ACCEPTANCE:
            if ToolCapability.PROCESS in capabilities:
                information_gain += 45
                reasons.append("verification_process_value")
            if ToolCapability.READ in capabilities:
                information_gain += 35
                reasons.append("verification_read_value")
            if ToolCapability.WRITE in capabilities:
                risk_cost += 40
                reasons.append("verification_write_penalty")
            if ToolCapability.NETWORK in capabilities:
                risk_cost += 30
                reasons.append("verification_network_penalty")

        if (
            verification.depth is VerificationDepth.REGRESSION
            and ToolCapability.PROCESS in capabilities
        ):
            verification_bonus += 20
            reasons.append("regression_process_bonus")
        elif (
            verification.depth is VerificationDepth.TARGETED
            and ToolCapability.READ in capabilities
        ):
            verification_bonus += 10
            reasons.append("targeted_read_bonus")

        if not reasons:
            reasons.append("neutral_information_value")
        return ToolAlternative(
            tool_name=spec.name,
            expected_information_gain=information_gain,
            risk_cost=risk_cost,
            verification_bonus=verification_bonus,
            net_score=information_gain + verification_bonus - risk_cost,
            reason_codes=tuple(reasons),
        )

    def advise(
        self,
        *,
        available_tools: tuple[ToolSpec, ...],
        information_gain: InformationGainPlan,
        verification: VerificationStrategy,
        retrieval_source: KnowledgeSource | None = None,
    ) -> ToolAdvice:
        selected = next(
            item
            for item in information_gain.needs
            if item.need_id == information_gain.selected_need_id
        )
        by_name = {spec.name: spec for spec in available_tools}
        alternatives = tuple(
            sorted(
                (
                    self._alternative(
                        spec,
                        need_kind=selected.kind,
                        verification=verification,
                    )
                    for spec in available_tools
                ),
                key=lambda item: (
                    0
                    if self.matches_retrieval_source(by_name[item.tool_name], retrieval_source)
                    else 1,
                    -item.net_score,
                    item.tool_name,
                ),
            )
        )
        names = tuple(item.tool_name for item in alternatives)
        source_aligned = retrieval_source is not None and any(
            self.matches_retrieval_source(spec, retrieval_source)
            for spec in available_tools
        )
        reasons = [
            f"information_need:{selected.kind.value}",
            f"verification_depth:{verification.depth.value}",
            (
                "ranked_by_source_gain_risk"
                if source_aligned
                else "ranked_by_information_gain_risk_cost"
            ),
            "advisory_only_no_authority",
        ]
        return ToolAdvice(
            recommended_tool_names=names,
            considered_tool_names=tuple(spec.name for spec in available_tools),
            alternatives=alternatives,
            reason_codes=tuple(reasons),
        )

    def ordered_specs(
        self,
        *,
        available_tools: tuple[ToolSpec, ...],
        advice: ToolAdvice,
    ) -> tuple[ToolSpec, ...]:
        by_name = {spec.name: spec for spec in available_tools}
        return tuple(by_name[name] for name in advice.recommended_tool_names)
