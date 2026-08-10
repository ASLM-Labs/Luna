"""Private Luna child process that frames llama-cli output as JSONL IPC."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

from luna.modeling.contracts import MessageRole, ModelRequest
from luna.neural.cli_worker import (
    NR2A_MAX_FRAME_CHARS,
    NR2A_READY_SEMANTICS,
    _decode_ipc_frame,
    _encode_ipc_frame,
)
from luna.neural.contracts import NeuralResourceBudget


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(_encode_ipc_frame(payload))
    sys.stdout.flush()


def _read() -> dict[str, Any] | None:
    line = sys.stdin.readline(NR2A_MAX_FRAME_CHARS + 2)
    if line == "":
        return None
    return _decode_ipc_frame(line)


def _render_request(request: ModelRequest) -> tuple[str, str | None]:
    if request.available_tools:
        raise ValueError("NR-2A CLI transport does not support tool proposals yet")

    system_parts: list[str] = []
    user_parts: list[str] = []
    for message in request.messages:
        if message.role is MessageRole.SYSTEM:
            system_parts.append(message.content)
        elif message.role is MessageRole.USER:
            user_parts.append(message.content)
        else:
            raise ValueError("NR-2A CLI transport supports only SYSTEM and USER messages")

    if len(user_parts) != 1:
        raise ValueError("NR-2A CLI transport requires exactly one USER message")

    system_prompt = "\n\n".join(system_parts).strip() or None
    return user_parts[0], system_prompt


def _build_llama_command(
    *,
    cli_path: Path,
    model_path: Path,
    gpu_layers: int,
    device: str | None,
    chat_template: str,
    request: ModelRequest,
    budget: NeuralResourceBudget,
    prompt_path: Path,
    system_prompt_path: Path | None,
) -> list[str]:
    _, system_prompt = _render_request(request)

    if system_prompt is None and system_prompt_path is not None:
        raise ValueError("system prompt path provided without SYSTEM content")
    if system_prompt is not None and system_prompt_path is None:
        raise ValueError("SYSTEM content requires a system prompt file")

    if chat_template != "gpt-oss":
        raise ValueError(
            "NR-2A CLI transport supports only the gpt-oss compatibility profile"
        )

    if (
        gpu_layers != 0
        or device is not None
        or budget.max_vram_mib != 0
        or budget.max_gpu_utilization_percent != 0
    ):
        raise ValueError(
            "NR-2A CLI transport allows zero GPU offload only; "
            "GPU-enabled transport requires a later resource gate"
        )
    if budget.max_parallel_generations < 1:
        raise ValueError("active inference budget must allow at least one generation")

    command = [
        str(cli_path),
        "--model",
        str(model_path),
        "--offline",
        "--simple-io",
        "--single-turn",
        "--no-display-prompt",
        "--no-show-timings",
        "--log-disable",
        "--color",
        "off",
        "--jinja",
        "--reasoning",
        "auto",
        "--chat-template-kwargs",
        '{"reasoning_effort":"low"}',
        "--fit",
        "off",
        "--gpu-layers",
        "0",
        "--device",
        "none",
        "--no-kv-offload",
        "--no-op-offload",
        "--ctx-size",
        str(budget.max_context_tokens),
        "--batch-size",
        str(budget.batch_size),
        "--parallel",
        "1",
        "--threads",
        str(budget.cpu_threads),
        "--predict",
        str(request.max_output_tokens),
        "--temperature",
        "1.0",
        "--top-p",
        "1.0",
        "--file",
        str(prompt_path),
    ]
    if system_prompt_path is not None:
        command.extend(["--system-prompt-file", str(system_prompt_path)])
    return command


def _extract_assistant_text(raw_output: str, *, prompt: str) -> str:
    normalized = raw_output.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.startswith("\ufeff"):
        normalized = normalized[1:]

    expected_prefix = f"User:\n{prompt}\n\nAssistant:\n"
    if not normalized.startswith(expected_prefix):
        raise RuntimeError(
            "llama-cli output did not match the observed one-turn transcript contract"
        )

    payload = normalized[len(expected_prefix):].rstrip("\n")
    if not payload:
        raise RuntimeError("llama-cli assistant segment was empty")

    start_marker = "[Start thinking]"
    end_marker = "[End thinking]"

    if payload.startswith(start_marker):
        if payload.count(start_marker) != 1 or payload.count(end_marker) != 1:
            raise RuntimeError("llama-cli reasoning markers were malformed")
        end_index = payload.index(end_marker)
        final_text = payload[end_index + len(end_marker):].strip("\n")
        if not final_text:
            raise RuntimeError("llama-cli final assistant segment was empty")
        if start_marker in final_text or end_marker in final_text:
            raise RuntimeError("llama-cli reasoning markers leaked into final text")
        return final_text

    if start_marker in payload or end_marker in payload:
        raise RuntimeError("llama-cli reasoning markers were malformed")

    return payload


def _generate(
    *,
    cli_path: Path,
    model_path: Path,
    gpu_layers: int,
    device: str | None,
    chat_template: str,
    request: ModelRequest,
    budget: NeuralResourceBudget,
) -> None:
    with TemporaryDirectory(prefix="luna-nr2a-") as temp_dir:
        temp_root = Path(temp_dir)
        prompt_path = temp_root / "prompt.txt"
        system_prompt_path = temp_root / "system-prompt.txt"
        output_path = temp_root / "generation.txt"

        prompt, system_prompt = _render_request(request)
        prompt_path.write_bytes(prompt.encode("utf-8"))
        if system_prompt is not None:
            system_prompt_path.write_bytes(system_prompt.encode("utf-8"))
            active_system_prompt_path: Path | None = system_prompt_path
        else:
            active_system_prompt_path = None

        command = _build_llama_command(
            cli_path=cli_path,
            model_path=model_path,
            gpu_layers=gpu_layers,
            device=device,
            chat_template=chat_template,
            request=request,
            budget=budget,
            prompt_path=prompt_path,
            system_prompt_path=active_system_prompt_path,
        )
        command.extend(["--output", str(output_path)])

        process = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )

        stdout_text = process.stdout.decode("utf-8", errors="replace")
        stderr_text = process.stderr.decode("utf-8", errors="replace")

        if process.returncode != 0:
            diagnostic = (stderr_text + "\n" + stdout_text).strip()
            raise RuntimeError(
                "llama-cli failed with a non-zero exit code"
                + f" ({process.returncode})"
                + (
                    ": " + diagnostic[-500:].replace("\n", " ")
                    if diagnostic
                    else ""
                )
            )

        if not output_path.is_file():
            raise RuntimeError("llama-cli did not create the output artifact")

        raw_output = output_path.read_text(encoding="utf-8")
        final_text = _extract_assistant_text(raw_output, prompt=prompt)

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli-path", required=True, type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--gpu-layers", required=True, type=int)
    parser.add_argument("--device")
    parser.add_argument("--chat-template", required=True)
    args = parser.parse_args()

    budget: NeuralResourceBudget | None = None

    while True:
        command = _read()
        if command is None:
            return 0
        command_type = str(command.get("type", ""))

        if command_type == "START":
            try:
                budget = NeuralResourceBudget.model_validate(command["budget"])
                if budget.model_resident:
                    raise ValueError("NR-2A CLI transport is ephemeral-only")
                if not budget.inference_allowed:
                    raise ValueError("inference is denied by the active resource budget")
                if not args.cli_path.is_file():
                    raise FileNotFoundError("configured llama-cli path does not exist")
                if not args.model_path.exists():
                    raise FileNotFoundError("configured model path does not exist")
                _write(
                    {"type": "READY", "readiness": NR2A_READY_SEMANTICS}
                )
            except Exception:
                _write(
                    {
                        "type": "ERROR",
                        "sequence": 0,
                        "safe_reason": "native worker start rejected",
                    }
                )
            continue

        if command_type == "GENERATE":
            request_id = command.get("request", {}).get(
                "request_id",
                "00000000-0000-0000-0000-000000000000",
            )
            try:
                if budget is None:
                    raise RuntimeError("worker has not received START")
                request = ModelRequest.model_validate(command["request"])
                _generate(
                    cli_path=args.cli_path,
                    model_path=args.model_path,
                    gpu_layers=args.gpu_layers,
                    device=args.device,
                    chat_template=args.chat_template,
                    request=request,
                    budget=budget,
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
            _write({"type": "STOPPED"})
            return 0

        _write({"type": "ERROR", "sequence": 0, "safe_reason": "unknown worker IPC command"})


if __name__ == "__main__":
    raise SystemExit(main())
