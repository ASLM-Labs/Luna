"""Focused, read-only S4 context materialization from an admitted S3 manifest."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from luna.audit.redaction import SecretRedactor
from luna.parallel_cognition.live import FocusedContextBundle, FocusedContextDocument
from luna.parallel_cognition.models import (
    AssignmentSemanticSpec,
    ContextFreshness,
    ContextSourceReference,
    ReadOnlyContextManifest,
    RedactionState,
    contract_sha256,
)


class FocusedContextError(ValueError):
    """Fail-closed focused-context materialization error."""


class FocusedContextMaterialProvider(Protocol):
    """Root-owned resolver that returns content, never a worker-visible handle."""

    def read_source(self, source: ContextSourceReference) -> str | bytes:
        """Read the exact source version named by the admitted manifest."""


class FocusedContextBroker:
    """Resolve, verify, redact, and copy only explicitly granted source content."""

    def __init__(
        self,
        *,
        provider: FocusedContextMaterialProvider,
        explicit_secrets: tuple[str, ...] = (),
    ) -> None:
        self._provider = provider
        self._redactor = SecretRedactor(explicit_secrets)

    def materialize(
        self,
        *,
        assignment: AssignmentSemanticSpec,
        manifest: ReadOnlyContextManifest,
    ) -> FocusedContextBundle:
        """Build one ephemeral bundle or reject the entire assignment."""

        current_manifest = ReadOnlyContextManifest.model_validate(
            manifest.model_dump(mode="json")
        )
        current_assignment = AssignmentSemanticSpec.model_validate(
            assignment.model_dump(mode="json")
        )
        manifest_sha256 = contract_sha256(current_manifest)
        if (
            current_assignment.task_id != current_manifest.task_id
            or current_assignment.source_task_revision
            != current_manifest.source_task_revision
            or current_assignment.context_manifest_sha256 != manifest_sha256
        ):
            raise FocusedContextError("assignment does not bind the context manifest")
        refs = tuple(item.source_ref for item in current_manifest.sources)
        if current_assignment.granted_source_refs != refs:
            raise FocusedContextError("assignment grants do not exactly match the manifest")
        if current_manifest.total_size_bytes > current_assignment.budget.max_context_bytes:
            raise FocusedContextError("manifest exceeds the assignment context budget")

        documents: list[FocusedContextDocument] = []
        for source in current_manifest.sources:
            if source.freshness is not ContextFreshness.CURRENT:
                raise FocusedContextError("focused context requires current sources")
            if source.redaction_state is RedactionState.UNKNOWN:
                raise FocusedContextError("focused context rejects unknown redaction state")
            try:
                material = self._provider.read_source(source)
            except Exception as exc:
                raise FocusedContextError("focused context source could not be read") from exc
            if isinstance(material, bytes):
                raw = material
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise FocusedContextError(
                        "focused context source is not valid UTF-8"
                    ) from exc
            elif isinstance(material, str):
                text = material
                raw = material.encode("utf-8")
            else:
                raise FocusedContextError("focused context provider returned invalid content")
            if "\x00" in text:
                raise FocusedContextError("focused context rejects NUL content")
            if len(raw) != source.size_bytes:
                raise FocusedContextError("focused context source size changed")
            if sha256(raw).hexdigest() != source.content_sha256:
                raise FocusedContextError("focused context source digest changed")

            redaction = self._redactor.redact_text(text)
            if (
                redaction.redactions_applied
                and source.redaction_state is RedactionState.NOT_REQUIRED
            ):
                raise FocusedContextError(
                    "source declared redaction unnecessary but secret material was detected"
                )
            visible = redaction.text.encode("utf-8")
            documents.append(
                FocusedContextDocument(
                    source_ref=source.source_ref,
                    source_revision=source.source_revision,
                    manifest_content_sha256=source.content_sha256,
                    visible_content_sha256=sha256(visible).hexdigest(),
                    manifest_size_bytes=source.size_bytes,
                    visible_size_bytes=len(visible),
                    content=redaction.text,
                    redactions_applied=redaction.redactions_applied,
                )
            )

        return FocusedContextBundle(
            task_id=current_manifest.task_id,
            source_task_revision=current_manifest.source_task_revision,
            assignment_id=current_assignment.assignment_id,
            context_manifest_sha256=manifest_sha256,
            documents=tuple(documents),
            visible_size_bytes=sum(item.visible_size_bytes for item in documents),
        )


__all__ = [
    "FocusedContextBroker",
    "FocusedContextError",
    "FocusedContextMaterialProvider",
]
