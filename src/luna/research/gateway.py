"""Runtime-owned read-only Research Gateway for Phase 14."""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.research.evidence_adapter import EvidenceRAGAdapter
from luna.research.injection_guard import ResearchInjectionGuard
from luna.research.policy import ResearchPolicy
from luna.research.provenance import build_research_source
from luna.research.sources import (
    RawResearchSource,
    ResearchBlockCode,
    ResearchBlockedTarget,
    ResearchClaim,
    ResearchResult,
    ResearchResultStatus,
    ResearchSource,
    ResearchTarget,
    ResearchUsage,
    domain_from_url,
)
from luna.runtime import RuntimeRequest


class ResearchFetchRequest(LunaContractModel):
    """Exactly one read-only network request visible to the gateway."""

    request_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    url: str = Field(min_length=1, max_length=4000)
    timeout_seconds: float = Field(gt=0.0, le=300.0)
    max_response_chars: int = Field(ge=1, le=2_000_000)
    method: str = "GET"

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        domain_from_url(value)
        return value

    @field_validator("method")
    @classmethod
    def validate_method(cls, value: str) -> str:
        if value != "GET":
            raise ValueError("Phase 14 research supports read-only GET only")
        return value


class ResearchRequest(LunaContractModel):
    """One bounded evidence-RAG retrieval request."""

    request_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    query: str = Field(min_length=1, max_length=8000)
    targets: tuple[ResearchTarget, ...] = Field(min_length=1, max_length=100)
    claims: tuple[ResearchClaim, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_targets_and_claims(self) -> ResearchRequest:
        urls = tuple(target.url for target in self.targets)
        if len(urls) != len(set(urls)):
            raise ValueError("research target URLs must be unique")
        claim_ids = tuple(claim.claim_id for claim in self.claims)
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("research claim IDs must be unique")
        return self


class ResearchBackend(Protocol):
    """Provider boundary: one gateway-visible GET per call, with no retry semantics."""

    @property
    def backend_id(self) -> str: ...

    def fetch(self, request: ResearchFetchRequest) -> RawResearchSource: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    """Refuse automatic redirects so policy can never be bypassed by urllib."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class _TextExtractor(HTMLParser):
    """Small deterministic HTML-to-text extractor for the standard-library backend."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.parts: list[str] = []
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if lowered == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if not cleaned or self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(cleaned)
        self.parts.append(cleaned)

    @property
    def text(self) -> str:
        return "\n".join(self.parts)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts)


class UrllibResearchBackend:
    """Read-only HTTP(S) backend with redirect refusal and private-address defense."""

    def __init__(self, *, user_agent: str = "Luna/0.1 ResearchGateway") -> None:
        self._user_agent = user_agent
        self._opener = build_opener(_NoRedirectHandler())

    @property
    def backend_id(self) -> str:
        return "stdlib-urllib-readonly"

    @staticmethod
    def _assert_public_resolution(url: str) -> None:
        host = domain_from_url(url)
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise RuntimeError("research DNS resolution failed") from exc
        if not addresses:
            raise RuntimeError("research DNS resolution returned no address")
        for value in addresses:
            address = ipaddress.ip_address(value)
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
            ):
                raise RuntimeError("research host resolved to a private/local address")

    def fetch(self, request: ResearchFetchRequest) -> RawResearchSource:
        self._assert_public_resolution(request.url)
        headers = {
            "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.9,*/*;q=0.1",
            "User-Agent": self._user_agent,
        }
        http_request = Request(request.url, headers=headers, method="GET")
        max_bytes = min(8_000_000, request.max_response_chars * 4 + 4)
        try:
            with self._opener.open(http_request, timeout=request.timeout_seconds) as response:
                final_url = response.geturl()
                if final_url != request.url:
                    raise RuntimeError("automatic redirect is forbidden")
                content_type = response.headers.get_content_type().casefold()
                if not (
                    content_type.startswith("text/")
                    or content_type
                    in {"application/json", "application/xhtml+xml", "application/xml"}
                ):
                    raise RuntimeError("research response content type is not textual")
                payload = response.read(max_bytes + 1)
                if len(payload) > max_bytes:
                    raise RuntimeError("research response exceeded backend byte limit")
                charset = response.headers.get_content_charset() or "utf-8"
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                raise RuntimeError("research redirect refused before follow") from exc
            raise RuntimeError(f"research HTTP failure: {exc.code}") from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise RuntimeError(f"research transport failure: {type(exc).__name__}") from exc

        try:
            decoded = payload.decode(charset, errors="replace")
        except LookupError as exc:
            raise RuntimeError("research response declared an unknown charset") from exc

        title = domain_from_url(request.url)
        content = decoded
        if content_type in {"text/html", "application/xhtml+xml"}:
            parser = _TextExtractor()
            parser.feed(decoded)
            content = parser.text
            title = parser.title or title
        if not content.strip():
            raise RuntimeError("research response contained no readable text")

        domain = domain_from_url(request.url)
        return RawResearchSource(
            request_id=request.request_id,
            requested_url=request.url,
            final_url=request.url,
            title=title,
            publisher=domain,
            source_family=domain,
            content=content[: request.max_response_chars + 1],
        )


class ScriptedResearchBackend:
    """Deterministic backend used by Phase 14 tests and verifier."""

    def __init__(
        self,
        responses: dict[str, RawResearchSource | Exception],
        *,
        backend_id: str = "scripted-research",
    ) -> None:
        self._responses = dict(responses)
        self._backend_id = backend_id
        self.requests: list[ResearchFetchRequest] = []

    @property
    def backend_id(self) -> str:
        return self._backend_id

    def fetch(self, request: ResearchFetchRequest) -> RawResearchSource:
        self.requests.append(request)
        outcome = self._responses.get(request.url)
        if outcome is None:
            raise RuntimeError(f"no scripted research response for {request.url}")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome.model_copy(
            update={
                "request_id": request.request_id,
                "requested_url": request.url,
            }
        )


class ResearchGateway:
    """Enforce network authority, domain policy, budgets, provenance, and citations."""

    def __init__(
        self,
        *,
        injection_guard: ResearchInjectionGuard | None = None,
        rag_adapter: EvidenceRAGAdapter | None = None,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._injection_guard = injection_guard or ResearchInjectionGuard()
        self._rag = rag_adapter or EvidenceRAGAdapter()
        self._clock = clock
        self._monotonic = monotonic

    def run(
        self,
        *,
        request: ResearchRequest,
        runtime_request: RuntimeRequest,
        policy: ResearchPolicy,
        backend: ResearchBackend,
    ) -> ResearchResult:
        if request.task_id != runtime_request.task_id:
            raise ValueError("research request task_id must match runtime request")

        started_at = self._monotonic()
        now = require_utc(self._clock())
        allowed, code, reason, request_limit = policy.runtime_decision(runtime_request, now=now)
        if not allowed:
            assert code is not None
            return ResearchResult(
                task_id=request.task_id,
                status=ResearchResultStatus.DENIED,
                blocked_targets=tuple(
                    ResearchBlockedTarget(
                        target_id=target.target_id,
                        url=target.url,
                        code=code,
                        reason=reason,
                    )
                    for target in request.targets
                ),
                usage=ResearchUsage(),
                generated_at=now,
            )

        admitted: list[ResearchSource] = []
        blocked: list[ResearchBlockedTarget] = []
        network_requests = 0
        admitted_tokens = 0
        budget_hit = False

        for target in request.targets:
            elapsed_seconds = self._monotonic() - started_at
            if elapsed_seconds >= policy.max_elapsed_seconds:
                blocked.append(
                    ResearchBlockedTarget(
                        target_id=target.target_id,
                        url=target.url,
                        code=ResearchBlockCode.ELAPSED_BUDGET,
                        reason="research elapsed-time budget exhausted before request",
                    )
                )
                budget_hit = True
                continue

            if network_requests >= request_limit:
                blocked.append(
                    ResearchBlockedTarget(
                        target_id=target.target_id,
                        url=target.url,
                        code=ResearchBlockCode.REQUEST_BUDGET,
                        reason="research request budget exhausted before dispatch",
                    )
                )
                budget_hit = True
                continue

            domain_allowed, domain_code, domain_reason = policy.domain_decision(target.url)
            if not domain_allowed:
                assert domain_code is not None
                blocked.append(
                    ResearchBlockedTarget(
                        target_id=target.target_id,
                        url=target.url,
                        code=domain_code,
                        reason=domain_reason,
                    )
                )
                continue

            if not policy.level_four_domain_allowed(runtime_request, target.url):
                blocked.append(
                    ResearchBlockedTarget(
                        target_id=target.target_id,
                        url=target.url,
                        code=ResearchBlockCode.FREE_RESEARCH_CONTRACT,
                        reason="target is outside the Level 4 FREE_RESEARCH domain contract",
                    )
                )
                continue

            remaining_seconds = max(0.001, policy.max_elapsed_seconds - elapsed_seconds)
            fetch_request = ResearchFetchRequest(
                task_id=request.task_id,
                url=target.url,
                timeout_seconds=min(remaining_seconds, 300.0),
                max_response_chars=policy.max_source_chars,
            )
            network_requests += 1

            try:
                raw = backend.fetch(fetch_request)
            except Exception as exc:
                blocked.append(
                    ResearchBlockedTarget(
                        target_id=target.target_id,
                        url=target.url,
                        code=ResearchBlockCode.BACKEND_FAILURE,
                        reason=f"research backend failed without retry: {type(exc).__name__}",
                    )
                )
                continue

            if self._monotonic() - started_at >= policy.max_elapsed_seconds:
                blocked.append(
                    ResearchBlockedTarget(
                        target_id=target.target_id,
                        url=target.url,
                        code=ResearchBlockCode.ELAPSED_BUDGET,
                        reason="research elapsed-time budget exhausted after backend response",
                    )
                )
                budget_hit = True
                continue

            if raw.request_id != fetch_request.request_id or raw.requested_url != target.url:
                blocked.append(
                    ResearchBlockedTarget(
                        target_id=target.target_id,
                        url=target.url,
                        code=ResearchBlockCode.RESPONSE_MISMATCH,
                        reason="backend response correlation did not match the dispatched request",
                    )
                )
                continue

            final_allowed, _final_code, final_reason = policy.domain_decision(raw.final_url)
            level_four_final_allowed = policy.level_four_domain_allowed(
                runtime_request, raw.final_url
            )
            if not final_allowed or not level_four_final_allowed:
                blocked.append(
                    ResearchBlockedTarget(
                        target_id=target.target_id,
                        url=target.url,
                        code=ResearchBlockCode.REDIRECT_DOMAIN_BLOCKED,
                        reason=(
                            final_reason
                            if not final_allowed
                            else "redirect escaped the Level 4 FREE_RESEARCH domain contract"
                        ),
                    )
                )
                continue

            if len(raw.content) > policy.max_source_chars:
                blocked.append(
                    ResearchBlockedTarget(
                        target_id=target.target_id,
                        url=target.url,
                        code=ResearchBlockCode.RESPONSE_TOO_LARGE,
                        reason="research response exceeded the per-source character budget",
                    )
                )
                budget_hit = True
                continue

            token_estimate = (len(raw.content) + 3) // 4
            if admitted_tokens + token_estimate > policy.max_total_tokens:
                blocked.append(
                    ResearchBlockedTarget(
                        target_id=target.target_id,
                        url=target.url,
                        code=ResearchBlockCode.TOKEN_BUDGET,
                        reason="research token budget would be exceeded by this source",
                    )
                )
                budget_hit = True
                continue

            retrieved_at = require_utc(self._clock())
            try:
                source = build_research_source(
                    raw,
                    retrieved_at=retrieved_at,
                    request_index=network_requests,
                    injection=self._injection_guard.inspect(raw.content),
                )
            except ValueError:
                blocked.append(
                    ResearchBlockedTarget(
                        target_id=target.target_id,
                        url=target.url,
                        code=ResearchBlockCode.RESPONSE_MISMATCH,
                        reason="research source provenance failed runtime validation",
                    )
                )
                continue
            admitted.append(source)
            admitted_tokens += source.token_estimate

        assessments = self._rag.assess_claims(
            claims=request.claims,
            sources=tuple(admitted),
            max_citations_per_claim=policy.max_citations_per_claim,
        )
        supported = sum(item.status.value == "SUPPORTED" for item in assessments)
        elapsed_ms = max(0, int((self._monotonic() - started_at) * 1000))

        if budget_hit:
            status = ResearchResultStatus.BUDGET_EXHAUSTED
        elif supported == 0:
            status = ResearchResultStatus.NO_SUPPORTED_CLAIMS
        elif blocked or supported < len(assessments):
            status = ResearchResultStatus.PARTIAL
        else:
            status = ResearchResultStatus.COMPLETE

        return ResearchResult(
            task_id=request.task_id,
            status=status,
            sources=tuple(admitted),
            claim_assessments=assessments,
            blocked_targets=tuple(blocked),
            usage=ResearchUsage(
                network_requests=network_requests,
                elapsed_ms=elapsed_ms,
                admitted_sources=len(admitted),
                admitted_tokens=admitted_tokens,
            ),
            generated_at=require_utc(self._clock()),
        )
