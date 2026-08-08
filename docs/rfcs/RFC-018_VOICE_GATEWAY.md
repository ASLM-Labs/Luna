# RFC-018 — Voice Gateway

Status: IMPLEMENTED_UNVERIFIED
Phase: 18
Target branch: `phase-18-voice-gateway`

## 1. Purpose

Phase 18 adds a local, provider-neutral Voice Gateway above Luna's already verified desktop,
runtime, durable queue, and audit boundaries. Speech is an input/output transport, not an
authority source.

The phase deliberately does **not** select Luna's final TTS provider, voice profile, accent,
pitch, or persona voice. Those product choices remain separable from the safety boundary.

## 2. Trust boundary

A voice request is accepted only when both the local session and configured speaker identity
are verified. Spoken claims such as "I am the owner" cannot create or raise identity.

Accepted runtime work uses:

- `RequestSource.VOICE`;
- verified local owner session metadata;
- `LEVEL_1_READ_ONLY` autonomy;
- write/process/network disabled scope;
- zero write and network budgets;
- the existing durable queue and append-only audit ledger.

## 3. STT/TTS adapter boundary

`SpeechToTextAdapter` and `TextToSpeechAdapter` are provider-neutral protocols. Phase 18 ships
only deterministic/unbound adapters for tests and product wiring. They perform no microphone,
cloud STT, cloud TTS, or network operation.

TTS planning cannot bind a provider or Luna voice profile in this phase.

## 4. Transcript view

Every accepted utterance is preserved in an explicit session-bound transcript view with:

- speaker/session identity;
- capture mode (`WAKE_WORD` or `PUSH_TO_TALK`);
- chat/command kind;
- action class;
- confidence;
- required and completed confirmation counts.

Audit records store transcript SHA-256 and metadata, not raw spoken content or audio.

## 5. Confirmation policy

Conversation speech may queue as read-only work after final transcription.

A read-only **command** requires one explicit transcript-bound confirmation before queueing.
The confirmation must match the exact session, speaker, utterance, transcript digest, and
confirmation order.

A `HIGH_IMPACT` request requires two distinct confirmations. Even after both confirmations,
Phase 18 queues only a read-only **approval-review** request. Workspace write, delete, deploy,
process/terminal, network, or other external action still requires a separate non-voice
bounded approval path.

Therefore one transcript can never directly trigger a high-impact side effect.

## 6. Interruption and cancellation

Local interruption/cancel wins before dispatch:

- pending confirmations are discarded;
- queued pre-dispatch voice work is cancelled where the durable queue can prove it has not
  crossed the dispatch fence;
- no started side effect is force-replayed or silently cancelled.

This boundary also supports the future product behavior where user speech interrupts active
TTS output without treating interruption as runtime authority.

## 7. Explicit non-goals

Phase 18 does not add:

- a real microphone driver;
- wake-word engine implementation;
- a real STT/TTS provider;
- Luna's final voice/persona sound;
- speaker biometric enrollment;
- direct filesystem write from voice;
- shell/terminal execution from voice;
- deploy/publish/send/network authority from voice;
- silent external actions.

## 8. Acceptance

Phase 18 is acceptable only when deterministic tests/verifier prove:

1. STT/TTS boundaries remain provider-neutral.
2. Session + speaker identity is verified outside transcript text.
3. Transcript view exposes exact confirmation state.
4. Read-only commands require one direct confirmation.
5. High-impact requests require two confirmations.
6. Spoken text cannot raise role, autonomy, write, process, or network authority.
7. High-impact requests remain approval-review only after double confirmation.
8. Model-unavailable conversational work remains durable queued work.
9. Interrupt/cancel removes pending confirmations and safely cancels pre-dispatch queue work.
10. Audit stores transcript digest instead of raw transcript/audio.
11. Phase 17 remains green.
12. Manifest/SHA metadata is current.
