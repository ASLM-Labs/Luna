"""Deterministic secret redaction applied before any persistent audit write."""

from __future__ import annotations

import re
from collections.abc import Iterable

from luna.audit.models import JsonValue, RedactionResult

_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|"
    r"password|passwd|secret|authorization)"
)
_AUTHORIZATION_RE = re.compile(r"(?i)\bAuthorization(\s*[:=]\s*)([^\r\n]+)")
_KEY_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~+/=-]{6,})")
_COMMON_KEY_RE = re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b")


def _marker(label: str) -> str:
    return f"<redacted:{label}>"


class SecretRedactor:
    """Remove explicit and pattern-recognized sensitive values."""

    def __init__(self, explicit_secrets: Iterable[str] = ()) -> None:
        cleaned = tuple(dict.fromkeys(value for value in explicit_secrets if value))
        self._explicit_secrets = tuple(sorted(cleaned, key=len, reverse=True))

    def redact_text(self, text: str) -> RedactionResult:
        redacted = text
        labels: list[str] = []

        for index, secret in enumerate(self._explicit_secrets, start=1):
            if secret in redacted:
                redacted = redacted.replace(secret, _marker(f"explicit_{index}"))
                labels.append(f"explicit_{index}")

        def replace_key_value(match: re.Match[str]) -> str:
            label = match.group(1).casefold().replace("-", "_")
            labels.append(label)
            return f"{match.group(1)}{match.group(2)}{_marker(label)}"

        def replace_bearer(match: re.Match[str]) -> str:
            del match
            labels.append("bearer_token")
            return f"Bearer {_marker('bearer_token')}"

        def replace_common_key(match: re.Match[str]) -> str:
            del match
            labels.append("api_key_pattern")
            return _marker("api_key_pattern")

        redacted = _KEY_VALUE_RE.sub(replace_key_value, redacted)
        redacted = _BEARER_RE.sub(replace_bearer, redacted)
        redacted = _COMMON_KEY_RE.sub(replace_common_key, redacted)
        return RedactionResult(
            text=redacted,
            redactions_applied=tuple(dict.fromkeys(labels)),
        )

    def redact_payload(
        self,
        payload: dict[str, JsonValue],
    ) -> tuple[dict[str, JsonValue], tuple[str, ...]]:
        labels: list[str] = []

        def visit(value: JsonValue, key_name: str | None = None) -> JsonValue:
            if isinstance(value, dict):
                return {key: visit(item, key) for key, item in value.items()}
            if isinstance(value, list):
                return [visit(item, key_name) for item in value]
            if (
                isinstance(value, str)
                and key_name is not None
                and _SENSITIVE_KEY_RE.fullmatch(key_name)
            ):
                label = key_name.casefold().replace("-", "_")
                labels.append(label)
                return _marker(label)
            if isinstance(value, str):
                result = self.redact_text(value)
                labels.extend(result.redactions_applied)
                return result.text
            return value

        redacted = visit(payload)
        if not isinstance(redacted, dict):
            raise TypeError("redacted audit payload must remain an object")
        return redacted, tuple(dict.fromkeys(labels))
