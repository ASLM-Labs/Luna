"""Deterministic retrieval-first discovery for registered Luna skill versions."""

from __future__ import annotations

import re

from luna.skills.models import (
    SkillDiscoveryCandidate,
    SkillDiscoveryMatchReason,
    SkillDiscoveryResult,
    SkillScope,
    SkillTrustState,
    SkillVersion,
)

_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


class SkillDiscoveryIndex:
    """Pure bounded search over immutable registry snapshots."""

    @staticmethod
    def _tokens(value: str) -> tuple[str, ...]:
        return tuple(_TOKEN_PATTERN.findall(value.casefold()))

    @classmethod
    def search(
        cls,
        *,
        query: str,
        versions: tuple[SkillVersion, ...],
        allowed_scopes: tuple[SkillScope, ...],
        limit: int = 8,
    ) -> SkillDiscoveryResult:
        if not 1 <= limit <= 16:
            raise ValueError("skill discovery limit must be between 1 and 16")
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("skill discovery query must not be blank")
        if len(cleaned_query) > 512:
            raise ValueError("skill discovery query exceeds 512 characters")
        query_tokens = cls._tokens(cleaned_query)
        if not query_tokens:
            raise ValueError("skill discovery query must contain an alphanumeric token")

        allowed = set(allowed_scopes)
        query_set = set(query_tokens)
        normalized_query = " ".join(query_tokens)
        ranked: list[
            tuple[tuple[int, int, int, int, str, str], SkillDiscoveryCandidate]
        ] = []

        for version in versions:
            if version.trust_state is not SkillTrustState.TRUSTED:
                continue
            if version.scope not in allowed:
                continue
            name_tokens = cls._tokens(version.package.name)
            description_tokens = cls._tokens(version.package.description)
            name_set = set(name_tokens)
            description_set = set(description_tokens)
            exact_name = int(" ".join(name_tokens) == normalized_query)
            all_query_in_name = int(query_set.issubset(name_set))
            name_overlap = len(query_set & name_set)
            description_overlap = len(query_set & description_set)
            if exact_name == 0 and name_overlap == 0 and description_overlap == 0:
                continue
            reasons: list[SkillDiscoveryMatchReason] = []
            if exact_name:
                reasons.append(SkillDiscoveryMatchReason.EXACT_NAME)
            if name_overlap:
                reasons.append(SkillDiscoveryMatchReason.NAME_TOKEN)
            if description_overlap:
                reasons.append(SkillDiscoveryMatchReason.DESCRIPTION_TOKEN)
            candidate = SkillDiscoveryCandidate(
                skill_id=version.skill_id,
                version_id=version.version_id,
                name=version.package.name,
                description=version.package.description[:500],
                scope=version.scope,
                provenance=version.provenance,
                trust_state=version.trust_state,
                match_reasons=tuple(reasons),
            )
            ranked.append(
                (
                    (
                        -exact_name,
                        -all_query_in_name,
                        -name_overlap,
                        -description_overlap,
                        version.package.name,
                        str(version.version_id),
                    ),
                    candidate,
                )
            )

        ranked.sort(key=lambda item: item[0])
        return SkillDiscoveryResult(
            query=cleaned_query,
            candidates=tuple(candidate for _, candidate in ranked[:limit]),
        )
