"""Single-child S5B real-evidence driver for the accepted NR-2B ABI v2.

The S4 subprocess boundary owns this process directly.  This module loads the exact
CPU-only ABI shim in-process, emits only a closed ``LiveWorkerDraft``, and never exposes
raw Harmony analysis or model-authored claims.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import IO, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from luna.modeling.contracts import MessageRole, ModelMessage, ModelRequest
from luna.parallel_cognition.live import LiveNativeTokenUsage, LiveWorkerDraft
from luna.parallel_cognition.native_abi_v2 import (
    NativeAbiV2Shim,
    NativeTokenUsage,
)

_OUTPUT_CONTRACT = "summary_and_cited_claims_only_no_hidden_reasoning"
_UNVERIFIED_DRAFT_NOTICE = (
    "Real model output is an unverified read-only worker draft; root validation remains required."
)
_HARMONY_MARKERS = (
    "<|channel|>",
    "<|message|>",
    "<|start|>",
    "<|end|>",
    "<|return|>",
)
_AUTHORITY = {
    "write": False,
    "network": False,
    "process": False,
    "tool": False,
    "external_action": False,
    "delegation": False,
    "memory_commit": False,
    "state_mutation": False,
    "completion": False,
    "user_facing_voice": False,
}
_NATIVE_DRIVER_BATCH_SIZE = 256


def _as_object(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"S5B real driver {field} must be an object")
    return cast(dict[str, object], value)


def _validate_request_payload(raw: object) -> dict[str, object]:
    payload = _as_object(raw, field="request")
    if payload.get("schema_version") != 1:
        raise ValueError("S5B real driver request schema mismatch")
    if payload.get("output_contract") != _OUTPUT_CONTRACT:
        raise ValueError("S5B real driver output contract mismatch")
    if payload.get("authority") != _AUTHORITY:
        raise ValueError("S5B real driver received authority")
    for empty_field in ("available_tools", "credentials", "inherited_memory"):
        if payload.get(empty_field) != []:
            raise ValueError(f"S5B real driver {empty_field} must remain empty")
    max_output_tokens = payload.get("max_output_tokens")
    if (
        isinstance(max_output_tokens, bool)
        or not isinstance(max_output_tokens, int)
        or not 1 <= max_output_tokens <= 256
    ):
        raise ValueError("S5B real driver output budget must be within 1..256")
    UUID(str(payload.get("task_id", "")))
    if not str(payload.get("request_id", "")).startswith("c011-live-request:sha256:"):
        raise ValueError("S5B real driver request identity is not canonical")
    objective = payload.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        raise ValueError("S5B real driver objective cannot be blank")
    context = payload.get("context")
    if not isinstance(context, list) or not context:
        raise ValueError("S5B real driver requires focused context")
    for item in context:
        document = _as_object(item, field="context document")
        if not isinstance(document.get("source_ref"), str) or not isinstance(
            document.get("content"), str
        ):
            raise ValueError("S5B real driver context document is malformed")
    return payload


def _load_request(path: Path) -> dict[str, object]:
    return _validate_request_payload(json.loads(path.read_text(encoding="utf-8")))


def _render_prompt(payload: dict[str, object]) -> str:
    context = cast(list[object], payload["context"])
    sections: list[str] = [
        "You are a read-only parallel analysis worker.",
        "Use only the focused context below.",
        "Return only a concise final answer. Do not expose hidden reasoning or propose tools.",
        f"Objective: {cast(str, payload['objective']).strip()}",
    ]
    for item in context:
        document = _as_object(item, field="context document")
        source_ref = cast(str, document["source_ref"])
        content = cast(str, document["content"])
        sections.append(f"Source {source_ref}:\n{content}")
    prompt = "\n\n".join(sections)
    if len(prompt) > 200_000:
        raise ValueError("S5B real driver prompt exceeds the model contract")
    return prompt


def _model_request(payload: dict[str, object]) -> ModelRequest:
    request_identity = cast(str, payload["request_id"])
    return ModelRequest(
        request_id=uuid5(NAMESPACE_URL, request_identity),
        task_id=UUID(cast(str, payload["task_id"])),
        trace_id=uuid5(NAMESPACE_URL, f"trace:{request_identity}"),
        messages=(
            ModelMessage(role=MessageRole.USER, content=_render_prompt(payload)),
        ),
        max_output_tokens=cast(int, payload["max_output_tokens"]),
        temperature=0.0,
    )


def _write_draft(
    path: Path,
    *,
    final_text: str,
    usage: NativeTokenUsage,
) -> None:
    if not final_text.strip() or len(final_text) > 8000:
        raise ValueError("S5B real driver final text is outside the closed result contract")
    if any(marker in final_text for marker in _HARMONY_MARKERS):
        raise ValueError("S5B real driver final text contains a Harmony control marker")
    draft = LiveWorkerDraft(
        summary=final_text.strip(),
        claims=(),
        uncertainty=(_UNVERIFIED_DRAFT_NOTICE,),
        tokens=usage.total_tokens,
        native_usage=LiveNativeTokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
        ),
    )
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(draft.model_dump_json(), encoding="utf-8")
    temporary.replace(path)


def _silence_native_stderr() -> IO[bytes]:
    """Mirror the accepted NR-2B child boundary's native stderr DEVNULL route."""

    sink = open(os.devnull, "wb", buffering=0)  # noqa: SIM115 - kept for process lifetime
    os.dup2(sink.fileno(), 2)
    return sink


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim-path", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--cpu-threads", required=True, type=int)
    parser.add_argument("--max-context-tokens", required=True, type=int)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--cancel", required=True, type=Path)
    args = parser.parse_args()

    shim_path = args.shim_path.resolve(strict=True)
    runtime_dir = args.runtime_dir.resolve(strict=True)
    model_path = args.model_path.resolve(strict=True)
    request_path = args.request.resolve(strict=True)
    result_path = args.result.resolve(strict=False)
    cancel_path = args.cancel.resolve(strict=False)

    if cancel_path.exists():
        return 10
    try:
        payload = _load_request(request_path)
        request = _model_request(payload)
    except Exception:
        return 21

    stderr_sink = _silence_native_stderr()
    add_dll_directory = getattr(os, "add_dll_directory", None)
    dll_directory = None
    shim: NativeAbiV2Shim | None = None
    try:
        # The accepted NR-2B child uses the CPU runtime as its working directory.
        # Keep that loader contract while every request/result path remains absolute.
        os.chdir(runtime_dir)
        dll_directory = (
            add_dll_directory(str(runtime_dir)) if add_dll_directory is not None else None
        )
        shim = NativeAbiV2Shim(shim_path=shim_path)
    except Exception:
        if dll_directory is not None:
            dll_directory.close()
        stderr_sink.close()
        return 22

    try:
        shim.start(
            runtime_dir=runtime_dir,
            model_path=model_path,
            cpu_threads=args.cpu_threads,
            max_context_tokens=args.max_context_tokens,
            batch_size=min(_NATIVE_DRIVER_BATCH_SIZE, args.max_context_tokens),
        )
    except Exception:
        try:
            shim.close()
        finally:
            if dll_directory is not None:
                dll_directory.close()
            stderr_sink.close()
        return 23

    try:
        try:
            generation = shim.generate(
                prompt=request.messages[0].content,
                max_output_tokens=request.max_output_tokens,
            )
        finally:
            shim.close()
            if dll_directory is not None:
                dll_directory.close()
            stderr_sink.close()
    except Exception:
        return 24
    if cancel_path.exists():
        return 11
    try:
        _write_draft(
            result_path,
            final_text=generation.text,
            usage=generation.usage,
        )
    except Exception:
        return 25
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
