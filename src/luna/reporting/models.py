"""Final user-report contracts separating action, evidence, uncertainty, and risk."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import CompletionStatus, RiskLevel


class ReportRisk(LunaContractModel):
    """One explicit residual or observed risk in a final report."""

    level: RiskLevel
    summary: str = Field(min_length=1, max_length=2000)
    mitigation: str | None = Field(default=None, max_length=2000)

    @field_validator("mitigation")
    @classmethod
    def validate_mitigation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("risk mitigation cannot be blank")
        return cleaned


class FinalReport(LunaContractModel):
    """Auditable user-facing result derived from the completion gate."""

    final_report_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    verification_report_id: UUID
    completion_decision_id: UUID
    identity_profile_id: UUID
    identity_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    objective: str = Field(min_length=1, max_length=4000)
    completion_status: CompletionStatus
    performed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    verified: tuple[str, ...] = ()
    unverified: tuple[str, ...] = ()
    risks: tuple[ReportRisk, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    generated_at: datetime = Field(default_factory=utc_now)

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("performed", "changed", "verified", "unverified", "evidence_refs")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("final report entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("final report entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_status_content(self) -> FinalReport:
        if self.completion_status is CompletionStatus.VERIFIED_COMPLETE and not self.verified:
            raise ValueError("VERIFIED_COMPLETE final report requires verified items")
        if self.completion_status is not CompletionStatus.VERIFIED_COMPLETE and not self.unverified:
            raise ValueError("non-complete final report must explain what remains unverified")
        return self

    def render_text(self) -> str:
        """Render a concise stable report without exposing private chain-of-thought."""

        def section(title: str, values: tuple[str, ...]) -> list[str]:
            lines = [f"## {title}"]
            if not values:
                lines.append("- Yok.")
            else:
                lines.extend(f"- {value}" for value in values)
            return lines

        risk_lines = tuple(
            f"[{risk.level.value}] {risk.summary}"
            + (f" — Önlem: {risk.mitigation}" if risk.mitigation else "")
            for risk in self.risks
        )
        lines = [
            "# Luna Nihai Raporu",
            "",
            f"Durum: {self.completion_status.value}",
            f"Amaç: {self.objective}",
            "",
        ]
        for title, values in (
            ("Yapılan", self.performed),
            ("Değişen", self.changed),
            ("Doğrulanan", self.verified),
            ("Doğrulanamayan", self.unverified),
            ("Risk", risk_lines),
            ("Kanıt", self.evidence_refs),
        ):
            lines.extend(section(title, values))
            lines.append("")
        return "\n".join(lines).rstrip()
