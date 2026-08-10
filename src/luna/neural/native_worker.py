"""Luna-owned direct-native child-worker transport.

NR-2B Slice 1 deliberately stays narrow:
- private bounded/versioned JSONL IPC inherited from NR-2A;
- direct child process, no HTTP server and no llama-cli subprocess;
- CPU-only runtime staging;
- ephemeral model lifecycle only;
- exactly one USER message;
- at most 256 generated tokens.

The worker gains no tool, memory, evidence, training, promotion, or resource authority.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import IO
from uuid import UUID

from pydantic import field_validator

from luna.contracts.base import LunaContractModel
from luna.modeling.contracts import ModelRequest
from luna.neural.cli_worker import (
    NR2A_MAX_FRAME_CHARS,
    _decode_ipc_frame,
    _encode_ipc_frame,
    _require_expected_sequence,
)
from luna.neural.contracts import (
    NeuralFinishReason,
    NeuralGenerationResult,
    NeuralResourceBudget,
    NeuralUsage,
    NeuralWorkerState,
)
from luna.neural.streaming import NeuralStreamEvent, NeuralStreamEventType, NeuralStreamObserver

NR2B_READY_SEMANTICS = "MODEL_READY_DIRECT_NATIVE"
NR2B_MAX_OUTPUT_TOKENS = 256


class DirectNativeWorkerConfig(LunaContractModel):
    """Explicit paths for the Luna-owned narrow shim and canonical local model."""

    shim_path: Path
    runtime_dir: Path
    model_path: Path

    @field_validator("shim_path", "runtime_dir", "model_path")
    @classmethod
    def require_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("direct native worker paths must be absolute")
        return value


class LunaNativeWorker:
    """Implement NeuralWorker through Luna-private IPC and a direct native shim child."""

    def __init__(
        self,
        *,
        config: DirectNativeWorkerConfig,
        stream_observer: NeuralStreamObserver | None = None,
        worker_id: str = "luna-direct-native",
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        self._config = config.model_copy(deep=True)
        self._stream_observer = stream_observer
        self._worker_id = worker_id.strip()
        self._state = NeuralWorkerState.STOPPED
        self._process: subprocess.Popen[str] | None = None
        self._stdout: IO[str] | None = None
        self._stdin: IO[str] | None = None

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def state(self) -> NeuralWorkerState:
        return self._state

    def start(self, *, budget: NeuralResourceBudget) -> None:
        if self._state is not NeuralWorkerState.STOPPED:
            raise RuntimeError("direct native worker must be STOPPED before start")
        if not budget.inference_allowed:
            raise ValueError("cannot start direct native worker when inference is denied")
        if budget.model_resident:
            raise ValueError("NR-2B Slice 1 remains ephemeral-only; model_resident must be false")
        if budget.max_vram_mib != 0 or budget.max_gpu_utilization_percent != 0:
            raise ValueError("NR-2B Slice 1 allows CPU-only zero-GPU-budget execution")
        if budget.max_parallel_generations < 1:
            raise ValueError("active inference budget must allow at least one generation")
        if not self._config.shim_path.is_file():
            raise FileNotFoundError(f"direct native shim not found: {self._config.shim_path}")
        if not self._config.runtime_dir.is_dir():
            raise FileNotFoundError(
                "direct native runtime directory not found: "
                f"{self._config.runtime_dir}"
            )
        if not self._config.model_path.is_file():
            raise FileNotFoundError(f"direct native model not found: {self._config.model_path}")
        if (self._config.runtime_dir / "ggml-cuda.dll").exists():
            raise ValueError("NR-2B Slice 1 CPU-only runtime must not stage ggml-cuda.dll")
        if any(self._config.runtime_dir.glob("cublas*.dll")):
            raise ValueError("NR-2B Slice 1 CPU-only runtime must not stage cuBLAS")

        self._state = NeuralWorkerState.STARTING
        env = os.environ.copy()
        src_root = str(Path(__file__).resolve().parents[2])
        current_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            src_root if not current_pythonpath else src_root + os.pathsep + current_pythonpath
        )
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        command = [
            sys.executable,
            "-m",
            "luna.neural.native_worker_process",
            "--shim-path",
            str(self._config.shim_path),
            "--runtime-dir",
            str(self._config.runtime_dir),
            "--model-path",
            str(self._config.model_path),
        ]

        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="strict",
                bufsize=1,
                cwd=str(self._config.runtime_dir),
                env=env,
            )
            if self._process.stdin is None or self._process.stdout is None:
                raise RuntimeError("direct native worker IPC pipes were not created")
            self._stdin = self._process.stdin
            self._stdout = self._process.stdout
            self._send({"type": "START", "budget": budget.model_dump(mode="json")})
            message = self._read()
            if (
                message.get("type") != "READY"
                or message.get("readiness") != NR2B_READY_SEMANTICS
            ):
                safe_reason = str(
                    message.get(
                        "safe_reason",
                        "direct native worker did not acknowledge model-ready state",
                    )
                )
                raise RuntimeError(safe_reason)
            self._state = NeuralWorkerState.READY
        except Exception:
            self._state = NeuralWorkerState.FAILED
            self._terminate_process()
            raise

    def generate(self, request: ModelRequest) -> NeuralGenerationResult:
        if self._state is not NeuralWorkerState.READY:
            raise RuntimeError("direct native worker is not READY")

        self._send({"type": "GENERATE", "request": request.model_dump(mode="json")})

        chunks: list[str] = []
        expected_sequence = 0
        while True:
            message = self._read()
            message_type = str(message.get("type", ""))

            if message_type == "TEXT_DELTA":
                request_id = UUID(str(message["request_id"]))
                if request_id != request.request_id:
                    self._state = NeuralWorkerState.FAILED
                    raise RuntimeError("direct native stream event request_id mismatch")
                sequence = _require_expected_sequence(message["sequence"], expected_sequence)
                text = str(message.get("text", ""))
                chunks.append(text)
                self._emit(
                    NeuralStreamEvent(
                        request_id=request.request_id,
                        event_type=NeuralStreamEventType.TEXT_DELTA,
                        sequence=sequence,
                        text=text,
                    )
                )
                expected_sequence += 1
                continue

            if message_type == "FINISH":
                request_id = UUID(str(message["request_id"]))
                if request_id != request.request_id:
                    self._state = NeuralWorkerState.FAILED
                    raise RuntimeError("direct native finish event request_id mismatch")
                sequence = _require_expected_sequence(message["sequence"], expected_sequence)
                final_text = str(message.get("text", ""))
                if final_text != "".join(chunks):
                    self._state = NeuralWorkerState.FAILED
                    raise RuntimeError(
                        "direct native streamed text does not match final worker text"
                    )
                self._emit(
                    NeuralStreamEvent(
                        request_id=request.request_id,
                        event_type=NeuralStreamEventType.FINISH,
                        sequence=sequence,
                        text=final_text,
                    )
                )
                return NeuralGenerationResult(
                    request_id=request.request_id,
                    text=final_text,
                    finish_reason=NeuralFinishReason.STOP,
                    usage=NeuralUsage(),
                )

            if message_type == "ERROR":
                sequence = _require_expected_sequence(message["sequence"], expected_sequence)
                self._state = NeuralWorkerState.FAILED
                safe_reason = str(message.get("safe_reason", "direct native worker failed"))
                self._emit(
                    NeuralStreamEvent(
                        request_id=request.request_id,
                        event_type=NeuralStreamEventType.ERROR,
                        sequence=sequence,
                        text=safe_reason,
                    )
                )
                raise RuntimeError(safe_reason)

            self._state = NeuralWorkerState.FAILED
            raise RuntimeError("direct native worker returned an unknown IPC message")

    def stop(self) -> None:
        if self._state is NeuralWorkerState.STOPPED:
            return
        try:
            if self._process is not None and self._process.poll() is None:
                self._send({"type": "SHUTDOWN"})
                try:
                    message = self._read()
                    if message.get("type") != "STOPPED":
                        raise RuntimeError("direct native worker did not acknowledge STOPPED")
                finally:
                    self._process.wait(timeout=30)
        finally:
            self._terminate_process()
            self._state = NeuralWorkerState.STOPPED

    def _emit(self, event: NeuralStreamEvent) -> None:
        if self._stream_observer is not None:
            self._stream_observer(event)

    def _send(self, payload: dict[str, object]) -> None:
        if self._stdin is None:
            raise RuntimeError("direct native worker stdin is unavailable")
        self._stdin.write(_encode_ipc_frame(payload))
        self._stdin.flush()

    def _read(self) -> dict[str, object]:
        if self._stdout is None:
            raise RuntimeError("direct native worker stdout is unavailable")
        line = self._stdout.readline(NR2A_MAX_FRAME_CHARS + 2)
        if line == "":
            raise RuntimeError("direct native worker IPC closed unexpectedly")
        return _decode_ipc_frame(line)

    def _terminate_process(self) -> None:
        process = self._process
        self._stdin = None
        self._stdout = None
        self._process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
