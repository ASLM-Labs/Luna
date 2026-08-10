"""Private Luna child process for the direct native shim boundary.

The process owns ctypes/DLL/model lifetime. Raw Harmony analysis text never crosses
the Luna-private IPC boundary; only canonical final text is framed outward.
"""

from __future__ import annotations

import argparse
import ctypes
import re
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from luna.modeling.contracts import MessageRole, ModelRequest
from luna.neural.cli_worker import NR2A_MAX_FRAME_CHARS, _decode_ipc_frame, _encode_ipc_frame
from luna.neural.contracts import NeuralResourceBudget
from luna.neural.native_worker import NR2B_MAX_OUTPUT_TOKENS, NR2B_READY_SEMANTICS

_CHANNEL_RE = re.compile(r"<\|channel\|>(analysis|commentary|final)<\|message\|>")
_SPECIAL_RE = re.compile(r"<\|(?:end|return|call|start|channel)\|>")


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(_encode_ipc_frame(payload))
    sys.stdout.flush()


def _read() -> dict[str, Any] | None:
    line = sys.stdin.readline(NR2A_MAX_FRAME_CHARS + 2)
    if line == "":
        return None
    return _decode_ipc_frame(line)


def _render_direct_request(request: ModelRequest) -> str:
    """Return the one USER prompt supported by the first direct-native slice."""

    if request.available_tools:
        raise ValueError("NR-2B Slice 1 does not support tool proposals")
    if request.max_output_tokens > NR2B_MAX_OUTPUT_TOKENS:
        raise ValueError("NR-2B Slice 1 max_output_tokens exceeds 256")

    if len(request.messages) != 1 or request.messages[0].role is not MessageRole.USER:
        raise ValueError("NR-2B Slice 1 requires exactly one USER message")
    return request.messages[0].content


def _extract_harmony_final(raw_text: str) -> str:
    """Extract only canonical final-channel text without exposing analysis content."""

    matches = list(_CHANNEL_RE.finditer(raw_text))
    final_messages: list[str] = []

    for index, match in enumerate(matches):
        channel = match.group(1)
        start = match.end()
        next_channel = matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
        special = _SPECIAL_RE.search(raw_text, start, next_channel)
        end = special.start() if special is not None else next_channel
        if channel == "final":
            candidate = raw_text[start:end].strip()
            if candidate:
                final_messages.append(candidate)

    if not final_messages:
        raise RuntimeError("direct native generation did not produce a final Harmony channel")

    final_text = final_messages[-1]
    if "<|channel|>" in final_text or "<|message|>" in final_text:
        raise RuntimeError("direct native final Harmony channel was contaminated")
    return final_text


class _DirectShim:
    """Thin ctypes owner for the already-proven Luna narrow C ABI."""

    def __init__(self, *, shim_path: Path) -> None:
        self._dll = ctypes.CDLL(str(shim_path))
        self._engine = ctypes.c_void_p()
        self._configure_abi()

    def _configure_abi(self) -> None:
        self._dll.luna_nr2b_abi_version.argtypes = []
        self._dll.luna_nr2b_abi_version.restype = ctypes.c_uint32

        self._dll.luna_nr2b_engine_create.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_int32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        self._dll.luna_nr2b_engine_create.restype = ctypes.c_int32

        self._dll.luna_nr2b_generate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int32,
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        self._dll.luna_nr2b_generate.restype = ctypes.c_int32

        self._dll.luna_nr2b_engine_destroy.argtypes = [ctypes.c_void_p]
        self._dll.luna_nr2b_engine_destroy.restype = None

    def start(
        self,
        *,
        runtime_dir: Path,
        model_path: Path,
        cpu_threads: int,
        max_context_tokens: int,
    ) -> None:
        if self._dll.luna_nr2b_abi_version() != 1:
            raise RuntimeError("direct native shim ABI version mismatch")

        error = ctypes.create_string_buffer(4096)
        requested_context = min(max_context_tokens, 4096)
        rc = self._dll.luna_nr2b_engine_create(
            str(runtime_dir),
            str(model_path),
            cpu_threads,
            requested_context,
            ctypes.byref(self._engine),
            error,
            len(error),
        )
        if rc != 0:
            raise RuntimeError("direct native shim engine creation failed")

    def generate(self, *, prompt: str, max_output_tokens: int) -> str:
        output = ctypes.create_string_buffer(131072)
        output_size = ctypes.c_size_t()
        error = ctypes.create_string_buffer(4096)

        rc = self._dll.luna_nr2b_generate(
            self._engine,
            prompt.encode("utf-8"),
            max_output_tokens,
            output,
            len(output),
            ctypes.byref(output_size),
            error,
            len(error),
        )
        if rc != 0:
            raise RuntimeError("direct native shim generation failed")

        raw = bytes(output.raw[: output_size.value])
        raw_text = raw.decode("utf-8", errors="strict")
        return _extract_harmony_final(raw_text)

    def close(self) -> None:
        if self._engine.value is not None:
            self._dll.luna_nr2b_engine_destroy(self._engine)
            self._engine = ctypes.c_void_p()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim-path", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    args = parser.parse_args()

    budget: NeuralResourceBudget | None = None
    shim: _DirectShim | None = None

    try:
        while True:
            command = _read()
            if command is None:
                return 0
            command_type = str(command.get("type", ""))

            if command_type == "START":
                try:
                    budget = NeuralResourceBudget.model_validate(command["budget"])
                    if budget.model_resident:
                        raise ValueError("NR-2B Slice 1 remains ephemeral-only")
                    if not budget.inference_allowed:
                        raise ValueError("inference is denied by the active resource budget")
                    if budget.max_vram_mib != 0 or budget.max_gpu_utilization_percent != 0:
                        raise ValueError("NR-2B Slice 1 requires a zero GPU budget")

                    shim = _DirectShim(shim_path=args.shim_path)
                    shim.start(
                        runtime_dir=args.runtime_dir,
                        model_path=args.model_path,
                        cpu_threads=budget.cpu_threads,
                        max_context_tokens=budget.max_context_tokens,
                    )
                    _write({"type": "READY", "readiness": NR2B_READY_SEMANTICS})
                except Exception:
                    if shim is not None:
                        shim.close()
                        shim = None
                    _write(
                        {
                            "type": "ERROR",
                            "sequence": 0,
                            "safe_reason": "direct native worker start rejected",
                        }
                    )
                continue

            if command_type == "GENERATE":
                request_id = command.get("request", {}).get(
                    "request_id",
                    "00000000-0000-0000-0000-000000000000",
                )
                try:
                    if budget is None or shim is None:
                        raise RuntimeError("direct native worker has not reached model-ready state")
                    request = ModelRequest.model_validate(command["request"])
                    prompt = _render_direct_request(request)
                    final_text = shim.generate(
                        prompt=prompt,
                        max_output_tokens=request.max_output_tokens,
                    )
                    _write(
                        {
                            "type": "TEXT_DELTA",
                            "request_id": str(request.request_id),
                            "sequence": 0,
                            "text": final_text,
                        }
                    )
                    _write(
                        {
                            "type": "FINISH",
                            "request_id": str(request.request_id),
                            "sequence": 1,
                            "text": final_text,
                        }
                    )
                except Exception as exc:
                    _write(
                        {
                            "type": "ERROR",
                            "request_id": str(UUID(str(request_id))),
                            "sequence": 0,
                            "safe_reason": str(exc)[:1000],
                        }
                    )
                continue

            if command_type == "SHUTDOWN":
                if shim is not None:
                    shim.close()
                    shim = None
                _write({"type": "STOPPED"})
                return 0

            _write(
                {
                    "type": "ERROR",
                    "sequence": 0,
                    "safe_reason": "unknown direct native worker IPC command",
                }
            )
    finally:
        if shim is not None:
            shim.close()


if __name__ == "__main__":
    raise SystemExit(main())
