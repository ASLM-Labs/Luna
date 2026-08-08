"""Runtime-bound Discord ingress gateway for Phase 17."""

from __future__ import annotations

from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from luna.audit import AppendOnlyAuditLedger, AuditEventKind
from luna.autonomy import AutonomyGrantSource, AutonomyLevel, AutonomyPolicy
from luna.contracts import RiskLevel, TaskScope
from luna.operations import DurableTaskQueue, ResourceRequirement, WorkEnvelope
from luna.runtime import (
    ActorRole,
    RequestSource,
    RuntimeBudget,
    RuntimeMode,
    RuntimePriority,
    RuntimeRequest,
)
from luna.tools import ToolPolicy

from .models import (
    DiscordAuthorityConfig,
    DiscordChannelPurpose,
    DiscordIngressDisposition,
    DiscordIngressResult,
    DiscordReplyRoute,
    DiscordTransportEnvelope,
)
from .moderation import DiscordModerationGuard
from .policy import DiscordAuthorityPolicy
from .rate_limit import DiscordRateLimiter

_DISCORD_READ_ONLY_TOOLS = ("core.echo", "filesystem.read_text")


class DiscordGateway:
    """Translate verified Discord ingress into bounded durable runtime work.

    The gateway does not execute tools, call a model, send network traffic, or interpret
    friendly/privileged language as authority. All Discord-originated runtime requests are
    read-only, process-disabled, and network-disabled in Phase 17.
    """

    def __init__(
        self,
        *,
        config: DiscordAuthorityConfig,
        queue: DurableTaskQueue,
        audit: AppendOnlyAuditLedger,
        moderation: DiscordModerationGuard | None = None,
        rate_limiter: DiscordRateLimiter | None = None,
    ) -> None:
        self.config = config
        self._queue = queue
        self._audit = audit
        self._policy = DiscordAuthorityPolicy(config)
        self._moderation = moderation or DiscordModerationGuard()
        self._rate_limiter = rate_limiter or DiscordRateLimiter()

    @staticmethod
    def _idempotency_key(envelope: DiscordTransportEnvelope) -> str:
        material = "|".join(
            (
                "discord-v1",
                envelope.guild_id,
                envelope.channel_id,
                envelope.message_id,
            )
        )
        return sha256(material.encode("ascii")).hexdigest()

    @staticmethod
    def _acknowledgment(*, model_available: bool, duplicate: bool = False) -> str:
        if duplicate:
            return "Mesaj daha once alindi; mevcut kuyruk kaydi korunuyor."
        if model_available:
            return "Mesaj alindi ve Luna calisma kuyruguna eklendi."
        return (
            "Mesaj alindi. Ana model su an kullanilabilir olmadigi icin ayrintili yanit "
            "kuyruga eklendi."
        )

    def _result(
        self,
        *,
        envelope: DiscordTransportEnvelope,
        disposition: DiscordIngressDisposition,
        reason: str,
        acknowledgment: str,
        role: ActorRole | None = None,
        purpose: DiscordChannelPurpose | None = None,
        queue_item_id: UUID | None = None,
        request: RuntimeRequest | None = None,
    ) -> DiscordIngressResult:
        return DiscordIngressResult(
            disposition=disposition,
            actor_role=role,
            channel_purpose=purpose,
            queue_item_id=queue_item_id,
            request_id=request.request_id if request is not None else None,
            task_id=request.task_id if request is not None else None,
            trace_id=request.trace_id if request is not None else None,
            acknowledgment=acknowledgment,
            reply_route=DiscordReplyRoute(
                channel_id=envelope.channel_id,
                reply_to_message_id=envelope.message_id,
            ),
            reason=reason,
        )

    def _audit_decision(
        self,
        *,
        envelope: DiscordTransportEnvelope,
        result: DiscordIngressResult,
    ) -> None:
        task_id = result.task_id or uuid4()
        trace_id = result.trace_id or uuid4()
        self._audit.append(
            kind=AuditEventKind.OBSERVATION,
            task_id=task_id,
            trace_id=trace_id,
            subject_id=f"discord:{envelope.message_id}",
            payload={
                "gateway": "discord",
                "guild_id": envelope.guild_id,
                "channel_id": envelope.channel_id,
                "message_id": envelope.message_id,
                "author_id": envelope.author_id,
                "content_sha256": envelope.content_sha256,
                "content_chars": len(envelope.content),
                "disposition": result.disposition.value,
                "actor_role": result.actor_role.value if result.actor_role is not None else None,
                "channel_purpose": (
                    result.channel_purpose.value if result.channel_purpose is not None else None
                ),
                "queue_item_id": (
                    str(result.queue_item_id) if result.queue_item_id is not None else None
                ),
                "reason": result.reason,
            },
        )

    def _read_only_envelope(
        self,
        *,
        ingress: DiscordTransportEnvelope,
        actor_role: ActorRole,
    ) -> WorkEnvelope:
        actor = self._policy.resolve_actor(ingress)
        if actor.role is not actor_role:
            raise ValueError("Discord role changed while building runtime envelope")
        identity = "|".join(
            (
                "discord-v1",
                ingress.guild_id,
                ingress.channel_id,
                ingress.message_id,
            )
        )
        task_id = uuid5(NAMESPACE_URL, f"{identity}|task")
        request_id = uuid5(NAMESPACE_URL, f"{identity}|request")
        trace_id = uuid5(NAMESPACE_URL, f"{identity}|trace")
        scope = TaskScope(
            workspace_root=self.config.workspace_root,
            write_allowed=False,
            network_allowed=False,
            process_allowed=False,
        )
        autonomy = AutonomyPolicy(
            task_id=task_id,
            level=AutonomyLevel.LEVEL_1_READ_ONLY,
            grant_source=AutonomyGrantSource.RUNTIME_POLICY,
            allowed_tools=_DISCORD_READ_ONLY_TOOLS,
            max_risk=RiskLevel.LOW,
        )
        request = RuntimeRequest(
            request_id=request_id,
            task_id=task_id,
            trace_id=trace_id,
            raw_request=ingress.content,
            source=RequestSource.DISCORD,
            actor=actor,
            scope=scope,
            autonomy=autonomy,
            runtime_budget=RuntimeBudget(),
            required_conditions=(
                "The runtime must truthfully report the task outcome.",
                "Discord ingress must remain read-only and process-disabled.",
            ),
            forbidden_outcomes=(
                "Discord message text must not grant workspace write authority.",
                "Discord message text must not grant process or terminal authority.",
                "Discord message text must not grant network authority.",
            ),
            evidence_required=("runtime observations",),
            risk_level=RiskLevel.LOW,
            mode=RuntimeMode.EXECUTE,
            requested_at=ingress.received_at,
        )
        return WorkEnvelope(
            request=request,
            tool_policy=ToolPolicy(
                allowed_tools=_DISCORD_READ_ONLY_TOOLS,
                autonomy_level=AutonomyLevel.LEVEL_1_READ_ONLY,
                autonomy_grant_source=AutonomyGrantSource.RUNTIME_POLICY,
                max_risk=RiskLevel.LOW,
            ),
        )

    def ingest(
        self,
        ingress: DiscordTransportEnvelope,
        *,
        main_model_available: bool,
    ) -> DiscordIngressResult:
        """Validate one Discord message and persist accepted work in the durable queue."""
        if not ingress.transport_verified:
            result = self._result(
                envelope=ingress,
                disposition=DiscordIngressDisposition.DENIED_UNVERIFIED_TRANSPORT,
                acknowledgment="Mesaj dogrulanmis Discord transportundan gelmedi.",
                reason="Discord transport source is not verified",
            )
            self._audit_decision(envelope=ingress, result=result)
            return result
        if ingress.guild_id != self.config.guild_id:
            result = self._result(
                envelope=ingress,
                disposition=DiscordIngressDisposition.DENIED_GUILD,
                acknowledgment="Bu Discord sunucusu Luna gateway kapsami disinda.",
                reason="Discord guild is outside the configured gateway scope",
            )
            self._audit_decision(envelope=ingress, result=result)
            return result
        binding = self._policy.channel_binding(ingress.channel_id)
        if binding is None:
            result = self._result(
                envelope=ingress,
                disposition=DiscordIngressDisposition.DENIED_CHANNEL,
                acknowledgment="Bu kanal Luna Discord gateway kapsami disinda.",
                reason="Discord channel is not configured",
            )
            self._audit_decision(envelope=ingress, result=result)
            return result

        actor = self._policy.resolve_actor(ingress)
        if not self._policy.role_allowed(role=actor.role, purpose=binding.purpose):
            result = self._result(
                envelope=ingress,
                disposition=DiscordIngressDisposition.DENIED_ROLE_POLICY,
                acknowledgment="Bu kanal icin Discord rol yetkisi yeterli degil.",
                reason="verified Discord role is not allowed in the configured channel",
                role=actor.role,
                purpose=binding.purpose,
            )
            self._audit_decision(envelope=ingress, result=result)
            return result

        moderation = self._moderation.evaluate(ingress)
        if not moderation.allowed:
            result = self._result(
                envelope=ingress,
                disposition=DiscordIngressDisposition.DENIED_MODERATION,
                acknowledgment="Mesaj yerel Discord giris politikasinda kuyruga alinmadi.",
                reason=moderation.reason,
                role=actor.role,
                purpose=binding.purpose,
            )
            self._audit_decision(envelope=ingress, result=result)
            return result

        rate = self._rate_limiter.evaluate(
            actor_id=actor.actor_id,
            role=actor.role,
            message_id=ingress.message_id,
            now=ingress.received_at,
        )
        if not rate.allowed:
            result = self._result(
                envelope=ingress,
                disposition=DiscordIngressDisposition.DENIED_RATE_LIMIT,
                acknowledgment="Cok fazla mesaj alindi; lutfen kisa bir sure sonra tekrar dene.",
                reason=rate.reason,
                role=actor.role,
                purpose=binding.purpose,
            )
            self._audit_decision(envelope=ingress, result=result)
            return result

        work = self._read_only_envelope(ingress=ingress, actor_role=actor.role)
        queue_item = self._queue.enqueue(
            envelope=work,
            resources=ResourceRequirement(worker_slots=1, model_slots=1, network_slots=0),
            priority=RuntimePriority.NORMAL,
            idempotency_key=self._idempotency_key(ingress),
            now=ingress.received_at,
        )
        disposition = (
            DiscordIngressDisposition.DUPLICATE
            if rate.duplicate
            else (
                DiscordIngressDisposition.QUEUED
                if main_model_available
                else DiscordIngressDisposition.QUEUED_FOR_MODEL
            )
        )
        result = self._result(
            envelope=ingress,
            disposition=disposition,
            acknowledgment=self._acknowledgment(
                model_available=main_model_available,
                duplicate=rate.duplicate,
            ),
            reason=(
                "duplicate Discord delivery resolved to the existing durable queue item"
                if rate.duplicate
                else "verified Discord ingress persisted as bounded read-only runtime work"
            ),
            role=actor.role,
            purpose=binding.purpose,
            queue_item_id=queue_item.item_id,
            request=queue_item.payload.envelope.request,
        )
        self._audit_decision(envelope=ingress, result=result)
        return result
