"""Phase 18 provider-neutral local Voice Gateway."""

from luna.voice.adapters import (
    ScriptedSpeechToTextAdapter,
    SpeechToTextAdapter,
    TextToSpeechAdapter,
    UnboundTextToSpeechAdapter,
)
from luna.voice.bootstrap import build_local_voice_gateway
from luna.voice.confirmation import VoiceConfirmationGate
from luna.voice.gateway import VoiceGateway
from luna.voice.models import (
    VoiceActionClass,
    VoiceAuthorityConfig,
    VoiceCaptureMode,
    VoiceConfirmationEvent,
    VoiceIngressDisposition,
    VoiceIngressResult,
    VoiceSessionIdentity,
    VoiceSessionStatus,
    VoiceSynthesisPlan,
    VoiceTranscriptEntry,
    VoiceTranscriptPacket,
    VoiceUtteranceKind,
)
from luna.voice.session import VoiceSessionRegistry

__all__ = [
    "ScriptedSpeechToTextAdapter",
    "SpeechToTextAdapter",
    "TextToSpeechAdapter",
    "UnboundTextToSpeechAdapter",
    "VoiceActionClass",
    "VoiceAuthorityConfig",
    "VoiceCaptureMode",
    "VoiceConfirmationEvent",
    "VoiceConfirmationGate",
    "VoiceGateway",
    "VoiceIngressDisposition",
    "VoiceIngressResult",
    "VoiceSessionIdentity",
    "VoiceSessionRegistry",
    "VoiceSessionStatus",
    "VoiceSynthesisPlan",
    "VoiceTranscriptEntry",
    "VoiceTranscriptPacket",
    "VoiceUtteranceKind",
    "build_local_voice_gateway",
]
