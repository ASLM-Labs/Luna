"""Deterministic duplicate-task fingerprinting for runtime requests."""

from __future__ import annotations

import json
import unicodedata
from hashlib import sha256

from pydantic import Field

from luna.contracts.base import LunaContractModel
from luna.runtime.models import RuntimeRequest


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").casefold()


class TaskFingerprint(LunaContractModel):
    """Versioned digest used only as a duplicate candidate, never as proof."""

    algorithm: str = Field(
        default="luna-task-fingerprint-v1",
        pattern=r"^luna-task-fingerprint-v1$",
    )
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_goal: str = Field(min_length=1, max_length=32000)
    actor_scope: str = Field(min_length=1, max_length=500)
    workspace_scope: str = Field(min_length=1, max_length=4000)


def build_task_fingerprint(request: RuntimeRequest) -> TaskFingerprint:
    """Create a stable semantic-boundary fingerprint without transient IDs."""
    normalized_goal = _normalize_text(request.raw_request)
    actor_scope = f"{request.actor.role.value}:{request.actor.actor_id.casefold()}"
    workspace_scope = _normalize_path(request.scope.workspace_root)
    payload = {
        "algorithm": "luna-task-fingerprint-v1",
        "goal": normalized_goal,
        "actor_scope": actor_scope,
        "source": request.source.value,
        "workspace_root": workspace_scope,
        "allowed_paths": sorted(_normalize_path(value) for value in request.scope.allowed_paths),
        "protected_paths": sorted(
            _normalize_path(value) for value in request.scope.protected_paths
        ),
        "write_allowed": request.scope.write_allowed,
        "network_allowed": request.scope.network_allowed,
        "process_allowed": request.scope.process_allowed,
        "required_conditions": sorted(
            _normalize_text(value) for value in request.required_conditions
        ),
        "forbidden_outcomes": sorted(
            _normalize_text(value) for value in request.forbidden_outcomes
        ),
        "evidence_required": sorted(
            _normalize_text(value) for value in request.evidence_required
        ),
        "soft_preferences": sorted(
            _normalize_text(value) for value in request.soft_preferences
        ),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return TaskFingerprint(
        digest=sha256(canonical.encode("utf-8")).hexdigest(),
        normalized_goal=normalized_goal,
        actor_scope=actor_scope,
        workspace_scope=workspace_scope,
    )
