"""Luna-owned child-worker transport backed by a local llama-cli process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import IO
from uuid import UUID

from pydantic import Field, field_validator

from luna.contracts.base import LunaContractModel
from luna.modeling.contracts import ModelRequest
from luna.neural.contracts import (
    NeuralFinishReason,
    NeuralGenerationResult,
    NeuralResourceBudget,
    NeuralUsage,
    NeuralWorkerState,
)
from luna.neural.streaming import NeuralStreamEvent, NeuralStreamEventType, NeuralStreamObserver

NR2A_IPC_VERSION = 1
NR2A_MAX_FRAME_CHARS = 1_048_576
NR2A_READY_SEMANTICS = "TRANSPORT_READY"


def _encode_ipc_frame(payload: dict[str, object]) -> str:
    """Serialize one bounded, versioned Luna-private JSONL IPC frame."""

    framed = dict(payload)
    supplied_version = framed.get("protocol_version")
    if supplied_version is not None and supplied_version != NR2A_IPC_VERSION:
        raise RuntimeError("native worker IPC protocol version mismatch")
    framed["protocol_version"] = NR2A_IPC_VERSION
    encoded = json.dumps(framed, ensure_ascii=True, separators=(",", ":"))
    if len(encoded) > NR2A_MAX_FRAME_CHARS:
        raise RuntimeError("native worker IPC frame exceeds maximum size")
    return encoded + "\n"


def _decode_ipc_frame(line: str) -> dict[str, object]:
    """Validate framing, size, object shape, and protocol version."""

    if len(line) > NR2A_MAX_FRAME_CHARS + 1:
        raise RuntimeError("native worker IPC frame exceeds maximum size")
    if not line.endswith("\n"):
        raise RuntimeError("native worker IPC frame must be newline terminated")

    body = line[:-1]
    if len(body) > NR2A_MAX_FRAME_CHARS:
        raise RuntimeError("native worker IPC frame exceeds maximum size")

    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise RuntimeError("native worker IPC message must be an object")
    if payload.get("protocol_version") != NR2A_IPC_VERSION:
        raise RuntimeError("native worker IPC protocol version mismatch")
    return payload


def _require_expected_sequence(value: object, expected: int) -> int:
    """Require the exact next sequence number; gaps and duplicates fail closed."""

    sequence = _require_sequence(value)
    if sequence != expected:
        raise RuntimeError(
            f"native worker sequence mismatch: expected {expected}, got {sequence}"
        )
    return sequence


def _require_sequence(value: object) -> int:
    """Validate an untrusted IPC sequence value before using it."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError("native worker sequence must be a non-negative integer")
    return value


class LlamaCliWorkerConfig(LunaContractModel):
    """Explicit local paths and fixed engine choices owned by Luna."""

    cli_path: Path
    model_path: Path
    gpu_layers: int = Field(default=0, ge=0, le=999)
    device: str | None = Field(default=None, max_length=120)
    chat_template: str = Field(default="gpt-oss", min_length=1, max_length=120)

    @field_validator("cli_path", "model_path")
    @classmethod
    def require_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("native worker paths must be absolute")
        return value


class LunaCliWorker:
    """Implement NeuralWorker through Luna-private JSONL IPC.

    NR-2A is intentionally ephemeral-only: the Luna child process persists only
    for one runtime generation lifecycle and launches llama-cli for that request.
    Persistent model residency is deferred until a direct libllama/native bridge
    can honor the resource contract without pretending that a CLI process is a KV cache.
    """

    def __init__(
        self,
        *,
        config: LlamaCliWorkerConfig,
        stream_observer: NeuralStreamObserver | None = None,
        worker_id: str = "luna-native-cli",
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
            raise RuntimeError("native CLI worker must be STOPPED before start")
        if budget.model_resident:
            raise ValueError("NR-2A CLI transport is ephemeral-only; model_resident must be false")
        if not budget.inference_allowed:
            raise ValueError("cannot start native CLI worker when inference is denied")
        if (
            self._config.gpu_layers != 0
            or self._config.device is not None
            or budget.max_vram_mib != 0
            or budget.max_gpu_utilization_percent != 0
        ):
            raise ValueError(
                "NR-2A CLI transport allows zero GPU offload only; "
                "GPU-enabled transport requires a later resource gate"
            )
        if budget.max_parallel_generations < 1:
            raise ValueError("active inference budget must allow at least one generation")
        if not self._config.cli_path.is_file():
            raise FileNotFoundError(f"llama-cli not found: {self._config.cli_path}")
        if not self._config.model_path.exists():
            raise FileNotFoundError(f"model path not found: {self._config.model_path}")

        self._state = NeuralWorkerState.STARTING
        env = os.environ.copy()
        src_root = str(Path(__file__).resolve().parents[2])
        current_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            src_root if not current_pythonpath else src_root + os.pathsep + current_pythonpath
        )

        command = [
            sys.executable,
            "-m",
            "luna.neural.cli_worker_process",
            "--cli-path",
            str(self._config.cli_path),
            "--model-path",
            str(self._config.model_path),
            "--gpu-layers",
            str(self._config.gpu_layers),
            "--chat-template",
            self._config.chat_template,
        ]
        if self._config.device is not None:
            command.extend(["--device", self._config.device])

        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            if self._process.stdin is None or self._process.stdout is None:
                raise RuntimeError("native worker IPC pipes were not created")
            self._stdin = self._process.stdin
            self._stdout = self._process.stdout
            self._send(
                {
                    "type": "START",
                    "budget": budget.model_dump(mode="json"),
                }
            )
            message = self._read()
            if (
                message.get("type") != "READY"
                or message.get("readiness") != NR2A_READY_SEMANTICS
            ):
                raise RuntimeError(
                    "native worker did not acknowledge transport-only READY"
                )
            self._state = NeuralWorkerState.READY
        except Exception:
            self._state = NeuralWorkerState.FAILED
            self._terminate_process()
            raise

    def generate(self, request: ModelRequest) -> NeuralGenerationResult:
        if self._state is not NeuralWorkerState.READY:
            raise RuntimeError("native CLI worker is not READY")

        self._send(
            {
                "type": "GENERATE",
                "request": request.model_dump(mode="json"),
            }
        )

        chunks: list[str] = []
        expected_sequence = 0
        while True:
            message = self._read()
            message_type = str(message.get("type", ""))

            if message_type == "TEXT_DELTA":
                request_id = UUID(str(message["request_id"]))
                if request_id != request.request_id:
                    self._state = NeuralWorkerState.FAILED
                    raise RuntimeError("stream event request_id mismatch")
                sequence = _require_expected_sequence(
                    message["sequence"], expected_sequence
                )
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
                    raise RuntimeError("finish event request_id mismatch")
                sequence = _require_expected_sequence(
                    message["sequence"], expected_sequence
                )
                final_text = str(message.get("text", ""))
                if final_text != "".join(chunks):
                    self._state = NeuralWorkerState.FAILED
                    raise RuntimeError("streamed text does not match final worker text")
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
                sequence = _require_expected_sequence(
                    message["sequence"], expected_sequence
                )
                self._state = NeuralWorkerState.FAILED
                self._emit(
                    NeuralStreamEvent(
                        request_id=request.request_id,
                        event_type=NeuralStreamEventType.ERROR,
                        sequence=sequence,
                        text=str(message.get("safe_reason", "native worker generation failed")),
                    )
                )
                raise RuntimeError(
                    str(message.get("safe_reason", "native worker generation failed"))
                )

            self._state = NeuralWorkerState.FAILED
            raise RuntimeError("native worker returned an unknown IPC message")

    def stop(self) -> None:
        if self._state is NeuralWorkerState.STOPPED:
            return
        try:
            if self._process is not None and self._process.poll() is None:
                self._send({"type": "SHUTDOWN"})
                try:
                    message = self._read()
                    if message.get("type") != "STOPPED":
                        raise RuntimeError("native worker did not acknowledge STOPPED")
                finally:
                    self._process.wait(timeout=10)
        finally:
            self._terminate_process()
            self._state = NeuralWorkerState.STOPPED

    def _emit(self, event: NeuralStreamEvent) -> None:
        if self._stream_observer is not None:
            self._stream_observer(event)

    def _send(self, payload: dict[str, object]) -> None:
        if self._stdin is None:
            raise RuntimeError("native worker stdin is unavailable")
        self._stdin.write(_encode_ipc_frame(payload))
        self._stdin.flush()

    def _read(self) -> dict[str, object]:
        if self._stdout is None:
            raise RuntimeError("native worker stdout is unavailable")
        line = self._stdout.readline(NR2A_MAX_FRAME_CHARS + 2)
        if line == "":
            raise RuntimeError("native worker IPC closed unexpectedly")
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
