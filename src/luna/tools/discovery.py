"""Deterministic metadata-only discovery for deferred Luna tools."""

from __future__ import annotations

import re
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.enums import RiskLevel
from luna.tools.models import ToolCapability, ToolSpec

_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


class ToolDiscoveryMatchReason(StrEnum):
    """Explain why one non-authoritative tool candidate matched."""

    EXACT_NAME = "EXACT_NAME"
    NAME_TOKEN = "NAME_TOKEN"
    DESCRIPTION_TOKEN = "DESCRIPTION_TOKEN"
    CAPABILITY_TOKEN = "CAPABILITY_TOKEN"


class ToolDiscoveryCandidate(LunaContractModel):
    """Bounded metadata projection for one discoverable deferred tool."""

    tool_name: str = Field(
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
        max_length=120,
    )
    tool_version: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    description: str = Field(min_length=1, max_length=500)
    risk_level: RiskLevel
    capabilities: tuple[ToolCapability, ...] = ()
    match_reasons: tuple[ToolDiscoveryMatchReason, ...] = Field(min_length=1)
    authority_granted: bool = False

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(
        cls,
        values: tuple[ToolCapability, ...],
    ) -> tuple[ToolCapability, ...]:
        if len(values) != len(set(values)):
            raise ValueError("discovery candidate capabilities must be unique")
        return values

    @field_validator("match_reasons")
    @classmethod
    def validate_match_reasons(
        cls,
        values: tuple[ToolDiscoveryMatchReason, ...],
    ) -> tuple[ToolDiscoveryMatchReason, ...]:
        if len(values) != len(set(values)):
            raise ValueError("discovery match reasons must be unique")
        return values

    @model_validator(mode="after")
    def validate_non_authority(self) -> ToolDiscoveryCandidate:
        if self.authority_granted:
            raise ValueError("tool discovery can never grant execution authority")
        return self


class ToolDiscoveryResult(LunaContractModel):
    """One bounded, metadata-only search result for a task."""

    task_id: UUID
    query: str = Field(min_length=1, max_length=512)
    disclosure_state_revision: int = Field(ge=0)
    candidates: tuple[ToolDiscoveryCandidate, ...] = Field(max_length=16)
    authority_granted: bool = False

    @model_validator(mode="after")
    def validate_result(self) -> ToolDiscoveryResult:
        names = tuple(candidate.tool_name for candidate in self.candidates)
        if len(names) != len(set(names)):
            raise ValueError("tool discovery candidates must have unique names")
        if self.authority_granted:
            raise ValueError("tool discovery can never grant execution authority")
        return self


class ToolDiscoveryIndex:
    """Pure deterministic search over a bounded ToolSpec snapshot."""

    @staticmethod
    def _tokens(value: str) -> tuple[str, ...]:
        return tuple(_TOKEN_PATTERN.findall(value.casefold()))

    @classmethod
    def search(
        cls,
        *,
        task_id: UUID,
        query: str,
        disclosure_state_revision: int,
        deferred_tools: tuple[str, ...],
        specs: tuple[ToolSpec, ...],
        policy_allowed_tools: tuple[str, ...],
        limit: int = 8,
    ) -> ToolDiscoveryResult:
        if not 1 <= limit <= 16:
            raise ValueError("tool discovery limit must be between 1 and 16")

        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("tool discovery query must not be blank")
        if len(cleaned_query) > 512:
            raise ValueError("tool discovery query exceeds 512 characters")

        query_tokens = cls._tokens(cleaned_query)
        if not query_tokens:
            raise ValueError(
                "tool discovery query must contain at least one alphanumeric token"
            )

        names = tuple(spec.name for spec in specs)
        if len(names) != len(set(names)):
            raise ValueError("tool discovery specs must have unique names")

        deferred = set(deferred_tools)
        allowed = set(policy_allowed_tools)
        normalized_query = " ".join(query_tokens)
        ranked: list[
            tuple[
                tuple[int, int, int, int, int, str],
                ToolDiscoveryCandidate,
            ]
        ] = []

        for spec in specs:
            if spec.name not in deferred or spec.name not in allowed:
                continue

            name_tokens = cls._tokens(spec.name)
            description_tokens = cls._tokens(spec.description)
            capability_tokens = tuple(
                token
                for capability in spec.capabilities
                for token in cls._tokens(capability.value)
            )

            name_set = set(name_tokens)
            description_set = set(description_tokens)
            capability_set = set(capability_tokens)
            query_set = set(query_tokens)

            exact_name = int(" ".join(name_tokens) == normalized_query)
            all_query_in_name = int(query_set.issubset(name_set))
            name_overlap = len(query_set & name_set)
            description_overlap = len(query_set & description_set)
            capability_overlap = len(query_set & capability_set)

            if (
                exact_name == 0
                and name_overlap == 0
                and description_overlap == 0
                and capability_overlap == 0
            ):
                continue

            reasons: list[ToolDiscoveryMatchReason] = []
            if exact_name:
                reasons.append(ToolDiscoveryMatchReason.EXACT_NAME)
            if name_overlap:
                reasons.append(ToolDiscoveryMatchReason.NAME_TOKEN)
            if description_overlap:
                reasons.append(ToolDiscoveryMatchReason.DESCRIPTION_TOKEN)
            if capability_overlap:
                reasons.append(ToolDiscoveryMatchReason.CAPABILITY_TOKEN)

            candidate = ToolDiscoveryCandidate(
                tool_name=spec.name,
                tool_version=spec.version,
                description=spec.description[:500],
                risk_level=spec.risk_level,
                capabilities=spec.capabilities,
                match_reasons=tuple(reasons),
            )
            sort_key = (
                -exact_name,
                -all_query_in_name,
                -name_overlap,
                -description_overlap,
                -capability_overlap,
                spec.name,
            )
            ranked.append((sort_key, candidate))

        ranked.sort(key=lambda item: item[0])
        return ToolDiscoveryResult(
            task_id=task_id,
            query=cleaned_query,
            disclosure_state_revision=disclosure_state_revision,
            candidates=tuple(candidate for _, candidate in ranked[:limit]),
        )
