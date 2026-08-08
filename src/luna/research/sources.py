"""Research source, claim, citation, and result contracts for Phase 14."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


def normalize_domain(value: str) -> str:
    """Normalize a bare host name for exact/subdomain policy matching."""
    cleaned = value.strip().casefold().rstrip(".")
    if not cleaned or "/" in cleaned or ":" in cleaned or "@" in cleaned:
        raise ValueError("domain must be a bare host name")
    return cleaned


def domain_from_url(value: str) -> str:
    """Return a normalized HTTP(S) host while rejecting userinfo and invalid URLs."""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("research URLs must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("research URLs cannot contain userinfo")
    if parsed.hostname is None:
        raise ValueError("research URL requires a host")
    return normalize_domain(parsed.hostname)


class ResearchResultStatus(StrEnum):
    """Authoritative gateway outcome without implying claim truth."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    NO_SUPPORTED_CLAIMS = "NO_SUPPORTED_CLAIMS"


class ResearchBlockCode(StrEnum):
    """Stable fail-closed reasons at the research boundary."""

    NETWORK_DISABLED = "NETWORK_DISABLED"
    RUNTIME_NETWORK_DENIED = "RUNTIME_NETWORK_DENIED"
    DOMAIN_NOT_ALLOWED = "DOMAIN_NOT_ALLOWED"
    DOMAIN_DENIED = "DOMAIN_DENIED"
    PRIVATE_OR_LOCAL_ADDRESS = "PRIVATE_OR_LOCAL_ADDRESS"
    REQUEST_BUDGET = "REQUEST_BUDGET"
    ELAPSED_BUDGET = "ELAPSED_BUDGET"
    TOKEN_BUDGET = "TOKEN_BUDGET"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    REDIRECT_DOMAIN_BLOCKED = "REDIRECT_DOMAIN_BLOCKED"
    FREE_RESEARCH_CONTRACT = "FREE_RESEARCH_CONTRACT"
    BACKEND_FAILURE = "BACKEND_FAILURE"
    RESPONSE_MISMATCH = "RESPONSE_MISMATCH"


class ResearchClaimStatus(StrEnum):
    """Whether a requested claim has a provenance-bound citation."""

    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class ResearchTarget(LunaContractModel):
    """One explicit read-only web target selected before retrieval."""

    target_id: UUID = Field(default_factory=uuid4)
    url: str = Field(min_length=1, max_length=4000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        domain_from_url(value)
        return value

    @property
    def domain(self) -> str:
        return domain_from_url(self.url)


class RawResearchSource(LunaContractModel):
    """Untrusted backend response before policy/provenance admission."""

    request_id: UUID
    requested_url: str = Field(min_length=1, max_length=4000)
    final_url: str = Field(min_length=1, max_length=4000)
    title: str = Field(min_length=1, max_length=1000)
    publisher: str = Field(min_length=1, max_length=500)
    source_family: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=2_000_000)
    published_at: datetime | None = None

    @field_validator("requested_url", "final_url")
    @classmethod
    def validate_urls(cls, value: str) -> str:
        domain_from_url(value)
        return value

    @field_validator("published_at")
    @classmethod
    def validate_published_at(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @field_validator("source_family")
    @classmethod
    def validate_source_family(cls, value: str) -> str:
        cleaned = value.strip().casefold()
        if not cleaned:
            raise ValueError("source_family cannot be blank")
        return cleaned


class InjectionAssessment(LunaContractModel):
    """Prompt-injection scan result; external text is always data-only."""

    detected: bool
    signals: tuple[str, ...] = ()
    interpretation: Literal["DATA_ONLY"] = "DATA_ONLY"
    runtime_control_allowed: Literal[False] = False

    @field_validator("signals")
    @classmethod
    def validate_signals(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("injection signals cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("injection signals must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_detection(self) -> InjectionAssessment:
        if self.detected != bool(self.signals):
            raise ValueError("injection detection must match signal presence")
        return self


class ResearchSource(LunaContractModel):
    """Admitted web source with immutable provenance and untrusted content."""

    source_id: UUID = Field(default_factory=uuid4)
    requested_url: str = Field(min_length=1, max_length=4000)
    final_url: str = Field(min_length=1, max_length=4000)
    domain: str = Field(min_length=1, max_length=253)
    title: str = Field(min_length=1, max_length=1000)
    publisher: str = Field(min_length=1, max_length=500)
    source_family: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=2_000_000)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None
    request_index: int = Field(ge=1)
    token_estimate: int = Field(ge=1)
    injection: InjectionAssessment
    interpretation: Literal["DATA_ONLY"] = "DATA_ONLY"
    runtime_control_allowed: Literal[False] = False
    external_action_allowed: Literal[False] = False

    @field_validator("requested_url", "final_url")
    @classmethod
    def validate_urls(cls, value: str) -> str:
        domain_from_url(value)
        return value

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        return normalize_domain(value)

    @field_validator("retrieved_at", "published_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_provenance(self) -> ResearchSource:
        if self.domain != domain_from_url(self.final_url):
            raise ValueError("research source domain must match final_url")
        digest = sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_sha256 != digest:
            raise ValueError("research source content_sha256 mismatch")
        expected_tokens = (len(self.content) + 3) // 4
        if self.token_estimate != expected_tokens:
            raise ValueError("research source token_estimate mismatch")
        if self.published_at is not None and self.published_at > self.retrieved_at:
            raise ValueError("published_at cannot be later than retrieved_at")
        return self


class ResearchClaim(LunaContractModel):
    """A claim that may become publishable only after deterministic citation linkage."""

    claim_id: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=4000)
    match_terms: tuple[str, ...] = Field(min_length=1, max_length=32)
    current_factual: bool = True

    @field_validator("claim_id")
    @classmethod
    def validate_claim_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("claim_id cannot be blank")
        return cleaned

    @field_validator("match_terms")
    @classmethod
    def validate_match_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("claim match terms cannot be blank")
        normalized = tuple(value.casefold() for value in cleaned)
        if len(normalized) != len(set(normalized)):
            raise ValueError("claim match terms must be unique")
        return cleaned


class ResearchCitation(LunaContractModel):
    """Exact source excerpt linked to one claim and content digest."""

    citation_id: UUID = Field(default_factory=uuid4)
    claim_id: str = Field(min_length=1, max_length=300)
    source_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_url: str = Field(min_length=1, max_length=4000)
    quoted_text: str = Field(min_length=1, max_length=4000)
    quoted_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    publisher: str = Field(min_length=1, max_length=500)
    retrieved_at: datetime

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        domain_from_url(value)
        return value

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieved_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_quote_digest(self) -> ResearchCitation:
        digest = sha256(self.quoted_text.encode("utf-8")).hexdigest()
        if self.quoted_text_sha256 != digest:
            raise ValueError("citation quote digest mismatch")
        return self


class ResearchClaimAssessment(LunaContractModel):
    """Claim/citation result suitable for evidence-RAG consumers."""

    claim: ResearchClaim
    status: ResearchClaimStatus
    citations: tuple[ResearchCitation, ...] = ()
    reasons: tuple[str, ...] = ()

    @field_validator("reasons")
    @classmethod
    def validate_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("claim assessment reasons cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("claim assessment reasons must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_status(self) -> ResearchClaimAssessment:
        if self.status is ResearchClaimStatus.SUPPORTED and not self.citations:
            raise ValueError("SUPPORTED research claim requires at least one citation")
        if self.status is ResearchClaimStatus.UNSUPPORTED and self.citations:
            raise ValueError("UNSUPPORTED research claim cannot carry citations")
        if any(citation.claim_id != self.claim.claim_id for citation in self.citations):
            raise ValueError("citation claim_id must match the assessed claim")
        return self


class ResearchUsage(LunaContractModel):
    """Gateway-owned retrieval usage; every backend call is counted."""

    network_requests: int = Field(default=0, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)
    admitted_sources: int = Field(default=0, ge=0)
    admitted_tokens: int = Field(default=0, ge=0)


class ResearchBlockedTarget(LunaContractModel):
    """One target refused or excluded with a stable reason."""

    target_id: UUID
    url: str = Field(min_length=1, max_length=4000)
    code: ResearchBlockCode
    reason: str = Field(min_length=1, max_length=2000)


class ResearchResult(LunaContractModel):
    """Evidence-RAG output that never grants policy, action, or memory authority."""

    result_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    status: ResearchResultStatus
    sources: tuple[ResearchSource, ...] = ()
    claim_assessments: tuple[ResearchClaimAssessment, ...] = ()
    blocked_targets: tuple[ResearchBlockedTarget, ...] = ()
    usage: ResearchUsage = Field(default_factory=ResearchUsage)
    generated_at: datetime = Field(default_factory=utc_now)
    external_actions_allowed: Literal[False] = False
    runtime_policy_mutation_allowed: Literal[False] = False
    automatic_memory_commit_allowed: Literal[False] = False
    memory_review_required: Literal[True] = True

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_links(self) -> ResearchResult:
        source_by_id = {source.source_id: source for source in self.sources}
        if len(source_by_id) != len(self.sources):
            raise ValueError("research result source IDs must be unique")
        for assessment in self.claim_assessments:
            for citation in assessment.citations:
                source = source_by_id.get(citation.source_id)
                if source is None:
                    raise ValueError("citation must reference an admitted source")
                if citation.source_sha256 != source.content_sha256:
                    raise ValueError("citation source digest must match admitted source")
                if citation.source_url != source.final_url:
                    raise ValueError("citation URL must match admitted source")
                if citation.publisher != source.publisher:
                    raise ValueError("citation publisher must match admitted source")
                if citation.retrieved_at != source.retrieved_at:
                    raise ValueError("citation retrieval timestamp must match admitted source")
                if citation.quoted_text not in source.content:
                    raise ValueError("citation quote must be an exact source substring")
                source_text = citation.quoted_text.casefold()
                if not all(term.casefold() in source_text for term in assessment.claim.match_terms):
                    raise ValueError("citation quote does not satisfy claim match terms")
        if self.usage.admitted_sources != len(self.sources):
            raise ValueError("admitted source usage must match source count")
        if self.usage.admitted_tokens != sum(source.token_estimate for source in self.sources):
            raise ValueError("admitted token usage must match sources")
        return self

    @property
    def publishable_claims(self) -> tuple[ResearchClaimAssessment, ...]:
        """Return only citation-backed claims; source-less current claims stay excluded."""
        return tuple(
            item for item in self.claim_assessments if item.status is ResearchClaimStatus.SUPPORTED
        )
