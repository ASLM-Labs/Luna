"""C-011-private NR-2B ABI v2 adapter.

This module intentionally does not alter Luna's common NR-2B ABI v1 path.
C-011 real-evidence execution binds an explicit ABI-v2 bridge artifact and
uses only the versioned v2 entrypoints for batch authority and engine-native
measured token usage.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path

from luna.neural.native_worker_process import _extract_harmony_final

NR2B_ABI_V2 = 2
NR2B_USAGE_SOURCE = "ENGINE_NATIVE_COUNTERS"


@dataclass(frozen=True, slots=True)
class NativeTokenUsage:
    """Engine-native token counters returned atomically by ABI v2."""

    input_tokens: int
    output_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        values = (self.input_tokens, self.output_tokens, self.total_tokens)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise RuntimeError("direct native shim returned non-integer token usage")
        if self.input_tokens <= 0 or self.output_tokens < 0 or self.total_tokens <= 0:
            raise RuntimeError("direct native shim returned out-of-range token usage")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise RuntimeError("direct native shim token usage total mismatch")

    def as_ipc_payload(self) -> dict[str, object]:
        return {
            "source": NR2B_USAGE_SOURCE,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class DirectNativeGeneration:
    """Canonical final text paired with its engine-native compute counters."""

    text: str
    usage: NativeTokenUsage


class NativeAbiV2Shim:
    """C-011-only ctypes owner for the versioned NR-2B ABI-v2 surface."""

    def __init__(self, *, shim_path: Path) -> None:
        self._dll = ctypes.CDLL(str(shim_path))
        self._engine = ctypes.c_void_p()
        self._configure_abi()

    def _configure_abi(self) -> None:
        self._dll.luna_nr2b_abi_version.argtypes = []
        self._dll.luna_nr2b_abi_version.restype = ctypes.c_uint32

        self._dll.luna_nr2b_engine_create_v2.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_int32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        self._dll.luna_nr2b_engine_create_v2.restype = ctypes.c_int32

        self._dll.luna_nr2b_generate_v2.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int32,
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        self._dll.luna_nr2b_generate_v2.restype = ctypes.c_int32

        self._dll.luna_nr2b_engine_destroy.argtypes = [ctypes.c_void_p]
        self._dll.luna_nr2b_engine_destroy.restype = None

    def start(
        self,
        *,
        runtime_dir: Path,
        model_path: Path,
        cpu_threads: int,
        max_context_tokens: int,
        batch_size: int,
    ) -> None:
        if self._dll.luna_nr2b_abi_version() != NR2B_ABI_V2:
            raise RuntimeError("C-011 direct native shim ABI version mismatch")

        error = ctypes.create_string_buffer(4096)
        requested_context = min(max_context_tokens, 4096)

        if batch_size < 1 or batch_size > requested_context:
            raise RuntimeError("C-011 direct native shim batch size exceeds context")

        rc = self._dll.luna_nr2b_engine_create_v2(
            str(runtime_dir),
            str(model_path),
            cpu_threads,
            requested_context,
            batch_size,
            ctypes.byref(self._engine),
            error,
            len(error),
        )

        if rc != 0:
            raise RuntimeError("C-011 direct native shim engine creation failed")

    def generate(
        self,
        *,
        prompt: str,
        max_output_tokens: int,
    ) -> DirectNativeGeneration:
        output = ctypes.create_string_buffer(131072)
        output_size = ctypes.c_size_t()
        input_tokens = ctypes.c_uint64()
        output_tokens = ctypes.c_uint64()
        total_tokens = ctypes.c_uint64()
        error = ctypes.create_string_buffer(4096)

        rc = self._dll.luna_nr2b_generate_v2(
            self._engine,
            prompt.encode("utf-8"),
            max_output_tokens,
            output,
            len(output),
            ctypes.byref(output_size),
            ctypes.byref(input_tokens),
            ctypes.byref(output_tokens),
            ctypes.byref(total_tokens),
            error,
            len(error),
        )

        if rc != 0:
            raise RuntimeError("C-011 direct native shim generation failed")

        raw = bytes(output.raw[: output_size.value])
        raw_text = raw.decode("utf-8", errors="strict")

        return DirectNativeGeneration(
            text=_extract_harmony_final(raw_text),
            usage=NativeTokenUsage(
                input_tokens=input_tokens.value,
                output_tokens=output_tokens.value,
                total_tokens=total_tokens.value,
            ),
        )

    def close(self) -> None:
        if self._engine.value is not None:
            self._dll.luna_nr2b_engine_destroy(self._engine)
            self._engine = ctypes.c_void_p()


__all__ = [
    "NR2B_ABI_V2",
    "NR2B_USAGE_SOURCE",
    "DirectNativeGeneration",
    "NativeAbiV2Shim",
    "NativeTokenUsage",
]
