"""Conservative prompt-injection detection for untrusted research text."""

from __future__ import annotations

import re

from luna.research.sources import InjectionAssessment

_SIGNAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "IGNORE_PRIOR_INSTRUCTIONS",
        re.compile(r"\b(ignore|disregard|forget)\b.{0,48}\b(instruction|prompt|rule)s?\b", re.I),
    ),
    (
        "SYSTEM_OR_DEVELOPER_PROMPT",
        re.compile(r"\b(system|developer)\s+(message|prompt|instruction)s?\b", re.I),
    ),
    (
        "TOOL_OR_COMMAND_EXECUTION",
        re.compile(r"\b(run|execute|invoke|call)\b.{0,48}\b(tool|command|shell|terminal)\b", re.I),
    ),
    (
        "AUTHORITY_ESCALATION",
        re.compile(
            r"\b(grant|elevate|override|bypass)\b.{0,48}"
            r"\b(permission|authority|policy|safety)\b",
            re.I,
        ),
    ),
    (
        "SECRET_EXFILTRATION",
        re.compile(
            r"\b(reveal|print|send|upload|exfiltrate)\b.{0,48}"
            r"\b(secret|token|password|credential)\b",
            re.I,
        ),
    ),
)


class ResearchInjectionGuard:
    """Label injection-like text without ever promoting it to control context."""

    def inspect(self, content: str) -> InjectionAssessment:
        signals = tuple(name for name, pattern in _SIGNAL_PATTERNS if pattern.search(content))
        return InjectionAssessment(detected=bool(signals), signals=signals)
