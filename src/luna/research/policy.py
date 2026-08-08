"""Fail-closed network/domain/budget policy for Phase 14 research."""

from __future__ import annotations

import ipaddress
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from luna.autonomy import AutonomyLevel
from luna.contracts.base import LunaContractModel, require_utc
from luna.research.sources import ResearchBlockCode, domain_from_url, normalize_domain
from luna.runtime import RuntimeRequest


class ResearchPolicy(LunaContractModel):
    """Explicit research authorization layered under the runtime request boundary."""

    network_enabled: bool = False
    allowed_domains: tuple[str, ...] = ()
    denied_domains: tuple[str, ...] = ()
    max_requests: int = Field(default=4, ge=1, le=1000)
    max_elapsed_seconds: int = Field(default=60, ge=1, le=86400)
    max_total_tokens: int = Field(default=8000, ge=1, le=1_000_000)
    max_source_chars: int = Field(default=32000, ge=1, le=2_000_000)
    max_citations_per_claim: int = Field(default=3, ge=1, le=20)
    allow_private_networks: Literal[False] = False
    require_citations: Literal[True] = True
    external_actions_allowed: Literal[False] = False
    runtime_policy_mutation_allowed: Literal[False] = False
    automatic_memory_commit_allowed: Literal[False] = False

    @field_validator("allowed_domains", "denied_domains")
    @classmethod
    def validate_domains(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(normalize_domain(value) for value in values)
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("research policy domains must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_network_boundary(self) -> ResearchPolicy:
        if self.network_enabled and not self.allowed_domains:
            raise ValueError("network-enabled research requires an explicit domain allowlist")
        return self

    def domain_decision(self, url: str) -> tuple[bool, ResearchBlockCode | None, str]:
        """Apply deny-first exact/subdomain matching and private-address rejection."""
        domain = domain_from_url(url)
        if _is_private_or_local(domain):
            return (
                False,
                ResearchBlockCode.PRIVATE_OR_LOCAL_ADDRESS,
                "private/local hosts are blocked",
            )
        if _matches_domain(domain, self.denied_domains):
            return False, ResearchBlockCode.DOMAIN_DENIED, "domain is explicitly denied"
        if not _matches_domain(domain, self.allowed_domains):
            return False, ResearchBlockCode.DOMAIN_NOT_ALLOWED, "domain is outside the allowlist"
        return True, None, "domain allowed"

    def runtime_decision(
        self,
        request: RuntimeRequest,
        *,
        now: datetime,
    ) -> tuple[bool, ResearchBlockCode | None, str, int]:
        """Bind research to runtime network authority and compute the effective request cap."""
        current = require_utc(now)
        if not self.network_enabled:
            return False, ResearchBlockCode.NETWORK_DISABLED, "research network is disabled", 0
        if not request.scope.network_allowed or request.runtime_budget.max_network_requests <= 0:
            return (
                False,
                ResearchBlockCode.RUNTIME_NETWORK_DENIED,
                "runtime request does not authorize network access",
                0,
            )

        effective_limit = min(self.max_requests, request.runtime_budget.max_network_requests)
        if request.autonomy.level is AutonomyLevel.LEVEL_4_FREE_RESEARCH:
            contract = request.autonomy.free_research_contract
            if contract is None or not contract.active_at(current):
                return (
                    False,
                    ResearchBlockCode.FREE_RESEARCH_CONTRACT,
                    "Level 4 research requires an active FREE_RESEARCH contract",
                    0,
                )
            remaining = max(0, contract.max_requests - request.autonomy.free_research_requests_used)
            effective_limit = min(effective_limit, remaining)
            if effective_limit <= 0 or not request.autonomy.research_window_active(current):
                return (
                    False,
                    ResearchBlockCode.FREE_RESEARCH_CONTRACT,
                    "FREE_RESEARCH request or duration budget is exhausted",
                    0,
                )
        return True, None, "runtime research authority verified", effective_limit

    def level_four_domain_allowed(self, request: RuntimeRequest, url: str) -> bool:
        """Apply the pre-existing Level 4 domain contract in addition to this policy."""
        if request.autonomy.level is not AutonomyLevel.LEVEL_4_FREE_RESEARCH:
            return True
        contract = request.autonomy.free_research_contract
        return bool(contract is not None and contract.allows_domain(url))


def _matches_domain(host: str, allowed: tuple[str, ...]) -> bool:
    return any(host == item or host.endswith(f".{item}") for item in allowed)


def _is_private_or_local(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return True
    parsed = urlsplit(f"https://{host}")
    candidate = parsed.hostname or host
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
