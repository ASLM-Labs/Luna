"""Deterministic intent resolver used before a model backend is connected."""

from __future__ import annotations

import re
from collections.abc import Iterable
from hashlib import sha256
from typing import Protocol

from luna.intent.models import IntentKind, IntentResolution, RequestedAction


_SPACE_RE = re.compile(r"\s+")
_QUOTED_RE = re.compile(r'["\']([^"\']+)["\']')
_PATH_TOKEN_RE = re.compile(
    r"(?<!\w)(?:[A-Za-z]:\\[^\s]+|(?:[\w.-]+[/\\])+[\w.-]+|[\w.-]+\.[A-Za-z0-9]{1,8})(?!\w)"
)

_CODE_NOUNS = {
    "bug",
    "class",
    "code",
    "dosya",
    "fonksiyon",
    "hata",
    "kod",
    "modül",
    "modul",
    "proje",
    "python",
    "repo",
    "repository",
    "script",
    "test",
}
_CHANGE_TERMS = {
    "değiştir",
    "degistir",
    "düzelt",
    "duzelt",
    "ekle",
    "güncelle",
    "guncelle",
    "implement",
    "refactor",
    "uygula",
    "yaz",
}
_CREATE_TERMS = {"oluştur", "olustur", "kur", "yarat"}
_DELETE_TERMS = {"kaldır", "kaldir", "sil"}
_INSPECT_TERMS = {
    "analiz",
    "bak",
    "incele",
    "kontrol",
    "review",
    "tara",
}
_EXECUTE_TERMS = {
    "çalıştır",
    "calistir",
    "denetle",
    "run",
    "test et",
}
_RESEARCH_TERMS = {
    "araştır",
    "arastir",
    "github",
    "internet",
    "kaynak",
    "karşılaştır",
    "karsilastir",
    "web",
}
_EXPLAIN_TERMS = {"açıkla", "acikla", "anlat", "neden", "nasıl", "nasil"}
_FILE_TERMS = {"dosya", "klasör", "klasor", "zip"}
_EXTERNAL_SIDE_EFFECT_TERMS = {
    "deploy",
    "gönder",
    "gonder",
    "publish",
    "push",
    "yayınla",
    "yayinla",
}
_SYSTEM_RISK_TERMS = {
    "format",
    "registry",
    "sistem",
    "tümünü sil",
    "tumunu sil",
    "yetki",
}


class IntentResolver(Protocol):
    """Interface implemented by all Luna intent resolvers."""

    def resolve(self, request: str) -> IntentResolution:
        """Resolve one user request without performing side effects."""


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


class DeterministicIntentResolver:
    """Transparent rule baseline; not a substitute for later model reasoning."""

    @staticmethod
    def normalize(request: str) -> str:
        normalized = _SPACE_RE.sub(" ", request).strip()
        if not normalized:
            raise ValueError("request must not be empty")
        return normalized

    @staticmethod
    def _extract_resources(normalized: str) -> tuple[str, ...]:
        resources: list[str] = []
        for quoted in _QUOTED_RE.findall(normalized):
            if "/" in quoted or "\\" in quoted or "." in quoted:
                resources.append(quoted.strip())
        resources.extend(
            match.group(0).rstrip(".,;:")
            for match in _PATH_TOKEN_RE.finditer(normalized)
        )
        return _dedupe(resources)

    @staticmethod
    def _actions(lowered: str) -> tuple[RequestedAction, ...]:
        actions: list[RequestedAction] = []
        if _contains_any(lowered, _INSPECT_TERMS):
            actions.append(RequestedAction.INSPECT)
        if _contains_any(lowered, _CHANGE_TERMS):
            actions.append(RequestedAction.MODIFY)
        if _contains_any(lowered, _CREATE_TERMS):
            actions.append(RequestedAction.CREATE)
        if _contains_any(lowered, _DELETE_TERMS):
            actions.append(RequestedAction.DELETE)
        if _contains_any(lowered, _EXECUTE_TERMS):
            actions.append(RequestedAction.EXECUTE)
        if _contains_any(lowered, _RESEARCH_TERMS):
            actions.append(RequestedAction.RESEARCH)
        if _contains_any(lowered, _EXPLAIN_TERMS) or lowered.endswith("?"):
            actions.append(RequestedAction.EXPLAIN)
        return tuple(dict.fromkeys(actions))

    @staticmethod
    def _kind(
        lowered: str,
        actions: tuple[RequestedAction, ...],
    ) -> tuple[IntentKind, float]:
        code_related = _contains_any(lowered, _CODE_NOUNS)
        if RequestedAction.RESEARCH in actions:
            return IntentKind.RESEARCH, 0.92
        if code_related and any(
            action in actions
            for action in (
                RequestedAction.MODIFY,
                RequestedAction.CREATE,
                RequestedAction.DELETE,
            )
        ):
            return IntentKind.CODE_CHANGE, 0.94
        if code_related and RequestedAction.INSPECT in actions:
            return IntentKind.CODE_INSPECTION, 0.92
        if _contains_any(lowered, _FILE_TERMS):
            return IntentKind.FILE_OPERATION, 0.82
        if lowered.endswith("?") or RequestedAction.EXPLAIN in actions:
            return IntentKind.QUESTION, 0.78
        if not actions:
            return IntentKind.CONVERSATION, 0.65
        return IntentKind.UNKNOWN, 0.45

    def resolve(self, request: str) -> IntentResolution:
        normalized = self.normalize(request)
        lowered = normalized.casefold()
        actions = self._actions(lowered)
        kind, confidence = self._kind(lowered, actions)
        resources = self._extract_resources(normalized)

        unknowns: list[str] = []
        risk_signals: list[str] = []

        write_actions = {
            RequestedAction.MODIFY,
            RequestedAction.CREATE,
            RequestedAction.DELETE,
        }
        if write_actions.intersection(actions) and not resources:
            unknowns.append("target_scope")

        if len(normalized.split()) <= 2 and kind is not IntentKind.CONVERSATION:
            unknowns.append("success_criteria")

        if RequestedAction.DELETE in actions:
            risk_signals.append("destructive_change_requested")
        if _contains_any(lowered, _EXTERNAL_SIDE_EFFECT_TERMS):
            risk_signals.append("external_side_effect_requested")
        if _contains_any(lowered, _SYSTEM_RISK_TERMS):
            risk_signals.append("system_level_risk_signal")

        blocking_unknowns = {"target_scope", "success_criteria"}
        requires_clarification = bool(blocking_unknowns.intersection(unknowns))

        return IntentResolution(
            request_fingerprint=sha256(normalized.encode("utf-8")).hexdigest(),
            raw_request=request,
            normalized_request=normalized,
            kind=kind,
            objective=normalized,
            actions=actions,
            referenced_resources=resources,
            unknowns=_dedupe(unknowns),
            risk_signals=_dedupe(risk_signals),
            confidence=confidence,
            requires_clarification=requires_clarification,
        )
