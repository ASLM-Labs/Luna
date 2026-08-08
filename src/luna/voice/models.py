"""Phase 18 Voice Gateway contracts.

Voice transport, transcription and synthesis metadata remain data at this boundary. Spoken
text never grants runtime authority, and high-impact actions require two explicit confirmation
receipts before Luna may even queue a read-only approval-review request.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


class VoiceCaptureMode(StrEnum):
    """How an utterance reached the local Voice Gateway."""

    WAKE_WORD = "WAKE_WORD"
    PUSH_TO_TALK = "PUSH_TO_TALK"


class VoiceUtteranceKind(StrEnum):
    """Transport-visible conversation versus command intent."""

    CHAT = "CHAT"
    COMMAND = "COMMAND"


class VoiceActionClass(StrEnum):
    """Authority-neutral action class used only to choose confirmation depth."""

    CONVERSATION = "CONVERSATION"
    READ_ONLY_COMMAND = "READ_ONLY_COMMAND"
    HIGH_IMPACT = "HIGH_IMPACT"


class VoiceSessionStatus(StrEnum):
    """Local session lifecycle."""

    OPEN = "OPEN"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class VoiceIngressDisposition(StrEnum):
    """Observable result from Voice Gateway ingress or confirmation."""

    QUEUED = "QUEUED"
    QUEUED_FOR_MODEL = "QUEUED_FOR_MODEL"
    QUEUED_FOR_APPROVAL_REVIEW = "QUEUED_FOR_APPROVAL_REVIEW"
    DIRECT_CONFIRMATION_REQUIRED = "DIRECT_CONFIRMATION_REQUIRED"
    DOUBLE_CONFIRMATION_REQUIRED = "DOUBLE_CONFIRMATION_REQUIRED"
    CONFIRMATION_PROGRESS = "CONFIRMATION_PROGRESS"
    DENIED_SESSION = "DENIED_SESSION"
    DENIED_SPEAKER = "DENIED_SPEAKER"
    DENIED_TRANSPORT = "DENIED_TRANSPORT"
    DENIED_CONFIRMATION = "DENIED_CONFIRMATION"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"


class VoiceAuthorityConfig(LunaContractModel):
    """Runtime-owned local Voice Gateway identity configuration."""

    workspace_root: str = Field(min_length=1, max_length=2000)
    owner_actor_id: str = Field(min_length=1, max_length=300)
    allowed_speaker_ids: tuple[str, ...] = Field(min_length=1, max_length=20)

    @field_validator("workspace_root")
    @classmethod
    def normalize_workspace_root(cls, value: str) -> str:
        return str(Path(value).expanduser().resolve())

    @field_validator("owner_actor_id")
    @classmethod
    def normalize_actor_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("voice owner actor ID cannot be blank")
        return cleaned

    @field_validator("allowed_speaker_ids")
    @classmethod
    def normalize_speakers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("voice speaker IDs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("voice speaker IDs must be unique")
        return cleaned


class VoiceSessionIdentity(LunaContractModel):
    """Verified local session + speaker binding; voice biometrics are not an authority grant."""

    session_id: UUID = Field(default_factory=uuid4)
    actor_id: str = Field(min_length=1, max_length=300)
    speaker_id: str = Field(min_length=1, max_length=300)
    session_verified: bool = False
    speaker_verified: bool = False
    verified_at: datetime | None = None
    opened_at: datetime = Field(default_factory=utc_now)
    status: VoiceSessionStatus = VoiceSessionStatus.OPEN

    @field_validator("verified_at", "opened_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_verification(self) -> VoiceSessionIdentity:
        if self.session_verified and self.speaker_verified:
            if self.verified_at is None:
                raise ValueError("verified voice identity requires verified_at")
        elif self.verified_at is not None:
            raise ValueError("unverified voice identity cannot carry verified_at")
        return self


class VoiceTranscriptPacket(LunaContractModel):
    """Final transcript supplied by a transport/STT adapter."""

    utterance_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    speaker_id: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=32_000)
    confidence: float = Field(ge=0.0, le=1.0)
    capture_mode: VoiceCaptureMode
    utterance_kind: VoiceUtteranceKind
    action_class: VoiceActionClass
    transport_verified: bool = False
    received_at: datetime = Field(default_factory=utc_now)

    @field_validator("received_at")
    @classmethod
    def validate_received_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("voice transcript cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_kind(self) -> VoiceTranscriptPacket:
        if self.utterance_kind is VoiceUtteranceKind.CHAT:
            if self.action_class is not VoiceActionClass.CONVERSATION:
                raise ValueError("voice chat must use CONVERSATION action class")
        elif self.action_class is VoiceActionClass.CONVERSATION:
            raise ValueError("voice command cannot use CONVERSATION action class")
        return self

    @property
    def text_sha256(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()


class VoiceConfirmationEvent(LunaContractModel):
    """One explicit confirmation receipt bound to the exact transcript digest."""

    event_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    utterance_id: UUID
    speaker_id: str = Field(min_length=1, max_length=300)
    transcript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_index: int = Field(ge=1, le=2)
    confirmed: bool = True
    transport_verified: bool = False
    occurred_at: datetime = Field(default_factory=utc_now)

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        return require_utc(value)


class VoiceTranscriptEntry(LunaContractModel):
    """Immutable transcript view row exposed to presentation layers."""

    utterance_id: UUID
    session_id: UUID
    speaker_id: str
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    capture_mode: VoiceCaptureMode
    utterance_kind: VoiceUtteranceKind
    action_class: VoiceActionClass
    required_confirmations: int = Field(ge=0, le=2)
    confirmation_count: int = Field(ge=0, le=2)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_confirmation_count(self) -> VoiceTranscriptEntry:
        if self.confirmation_count > self.required_confirmations:
            raise ValueError("voice confirmation count cannot exceed requirement")
        return self


class VoiceSynthesisPlan(LunaContractModel):
    """Provider-neutral TTS request; no voice persona or provider is locked in Phase 18."""

    text: str = Field(min_length=1, max_length=32_000)
    adapter_name: str = Field(min_length=1, max_length=200)
    provider_bound: bool = False
    voice_profile_id: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_provider_boundary(self) -> VoiceSynthesisPlan:
        if self.provider_bound or self.voice_profile_id is not None:
            raise ValueError("Phase 18 TTS plan must remain provider and voice-profile neutral")
        return self


class VoiceIngressResult(LunaContractModel):
    """Gateway result returned to a local voice transport/presentation adapter."""

    disposition: VoiceIngressDisposition
    session_id: UUID
    utterance_id: UUID | None = None
    queue_item_id: UUID | None = None
    request_id: UUID | None = None
    task_id: UUID | None = None
    trace_id: UUID | None = None
    transcript_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    required_confirmations: int = Field(default=0, ge=0, le=2)
    confirmation_count: int = Field(default=0, ge=0, le=2)
    acknowledgment: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)

    @property
    def queued(self) -> bool:
        return self.disposition in {
            VoiceIngressDisposition.QUEUED,
            VoiceIngressDisposition.QUEUED_FOR_MODEL,
            VoiceIngressDisposition.QUEUED_FOR_APPROVAL_REVIEW,
        }
