from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from luna.modeling.contracts import MessageRole, ModelMessage, ModelRequest
from luna.neural.cli_worker import (
    NR2A_IPC_VERSION,
    NR2A_MAX_FRAME_CHARS,
    NR2A_READY_SEMANTICS,
    LlamaCliWorkerConfig,
    LunaCliWorker,
    _decode_ipc_frame,
    _encode_ipc_frame,
    _require_expected_sequence,
)
from luna.neural.cli_worker_process import (
    _build_llama_command,
    _extract_assistant_text,
    _render_request,
)
from luna.neural.contracts import NeuralResourceBudget, NeuralWorkerState


def _budget() -> NeuralResourceBudget:
    return NeuralResourceBudget(
        max_vram_mib=0,
        max_gpu_utilization_percent=0,
        cpu_threads=4,
        max_system_ram_mib=24576,
        max_kv_cache_mib=1024,
        max_context_tokens=4096,
        batch_size=256,
        max_parallel_generations=1,
        idle_unload_seconds=0,
        request_priority=50,
        inference_allowed=True,
        model_resident=False,
        background_inference=False,
    )


def _request(*messages: ModelMessage) -> ModelRequest:
    return ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=messages,
        max_output_tokens=64,
        temperature=0.0,
    )


def _command(*, request: ModelRequest, chat_template: str = "gpt-oss") -> list[str]:
    return _build_llama_command(
        cli_path=Path("C:/native/llama-cli.exe"),
        model_path=Path("C:/models/gpt-oss.gguf"),
        gpu_layers=0,
        device=None,
        chat_template=chat_template,
        request=request,
        budget=_budget(),
        prompt_path=Path("C:/temp/prompt.txt"),
        system_prompt_path=None,
    )


def test_config_requires_absolute_paths() -> None:
    with pytest.raises(ValueError):
        LlamaCliWorkerConfig(
            cli_path=Path("llama-cli.exe"),
            model_path=Path("model.gguf"),
        )


def test_render_request_preserves_one_user_and_system_context() -> None:
    request = _request(
        ModelMessage(role=MessageRole.SYSTEM, content="system-a"),
        ModelMessage(role=MessageRole.SYSTEM, content="system-b"),
        ModelMessage(role=MessageRole.USER, content="hello"),
    )
    prompt, system_prompt = _render_request(request)
    assert prompt == "hello"
    assert system_prompt == "system-a\n\nsystem-b"


def test_render_request_rejects_multi_turn_history() -> None:
    request = _request(
        ModelMessage(role=MessageRole.USER, content="first"),
        ModelMessage(role=MessageRole.ASSISTANT, content="reply"),
        ModelMessage(role=MessageRole.USER, content="second"),
    )
    with pytest.raises(ValueError):
        _render_request(request)


def test_llama_command_uses_observed_working_gpt_oss_profile() -> None:
    command = _command(
        request=_request(ModelMessage(role=MessageRole.USER, content="hello"))
    )
    assert "--jinja" in command
    assert command[command.index("--reasoning") + 1] == "auto"
    assert command[command.index("--chat-template-kwargs") + 1] == (
        '{"reasoning_effort":"low"}'
    )
    assert command[command.index("--temperature") + 1] == "1.0"
    assert command[command.index("--top-p") + 1] == "1.0"
    assert "--chat-template" not in command
    assert command[command.index("--file") + 1] == r"C:\temp\prompt.txt"
    assert "--prompt" not in command
    assert "hello" not in command


def test_llama_command_rejects_non_gpt_oss_profile() -> None:
    request = _request(ModelMessage(role=MessageRole.USER, content="hello"))
    with pytest.raises(ValueError, match="gpt-oss compatibility profile"):
        _command(request=request, chat_template="chatml")


def test_llama_command_uses_system_prompt_file_when_system_content_exists() -> None:
    request = _request(
        ModelMessage(role=MessageRole.SYSTEM, content="system"),
        ModelMessage(role=MessageRole.USER, content="hello"),
    )
    command = _build_llama_command(
        cli_path=Path("C:/native/llama-cli.exe"),
        model_path=Path("C:/models/gpt-oss.gguf"),
        gpu_layers=0,
        device=None,
        chat_template="gpt-oss",
        request=request,
        budget=_budget(),
        prompt_path=Path("C:/temp/prompt.txt"),
        system_prompt_path=Path("C:/temp/system-prompt.txt"),
    )
    assert command[command.index("--system-prompt-file") + 1] == (
        r"C:\temp\system-prompt.txt"
    )
    assert "system" not in command
    assert "hello" not in command


def test_llama_command_rejects_gpu_enabled_nr2a_transport() -> None:
    request = _request(ModelMessage(role=MessageRole.USER, content="hello"))
    with pytest.raises(ValueError, match="zero GPU offload"):
        _build_llama_command(
            cli_path=Path("C:/native/llama-cli.exe"),
            model_path=Path("C:/models/gpt-oss.gguf"),
            gpu_layers=1,
            device=None,
            chat_template="gpt-oss",
            request=request,
            budget=_budget(),
            prompt_path=Path("C:/temp/prompt.txt"),
            system_prompt_path=None,
        )


def test_llama_command_rejects_gpu_budget_even_with_zero_layers() -> None:
    request = _request(ModelMessage(role=MessageRole.USER, content="hello"))
    budget = _budget().model_copy(
        update={"max_vram_mib": 1024, "max_gpu_utilization_percent": 20}
    )
    with pytest.raises(ValueError, match="zero GPU offload"):
        _build_llama_command(
            cli_path=Path("C:/native/llama-cli.exe"),
            model_path=Path("C:/models/gpt-oss.gguf"),
            gpu_layers=0,
            device=None,
            chat_template="gpt-oss",
            request=request,
            budget=budget,
            prompt_path=Path("C:/temp/prompt.txt"),
            system_prompt_path=None,
        )


def test_extract_assistant_text_without_reasoning_block() -> None:
    prompt = "hello"
    raw = f"User:\n{prompt}\n\nAssistant:\nReady.\n"
    assert _extract_assistant_text(raw, prompt=prompt) == "Ready."


def test_extract_assistant_text_strips_reasoning_block() -> None:
    prompt = "Merhaba."
    raw = (
        f"User:\n{prompt}\n\nAssistant:\n"
        "[Start thinking]\n"
        "internal diagnostic content\n"
        "[End thinking]\n\n"
        "Hazırım!\n"
    )
    assert _extract_assistant_text(raw, prompt=prompt) == "Hazırım!"


def test_extract_assistant_text_rejects_prompt_mismatch() -> None:
    prompt = "bugün"
    raw = "User:\nbug³n\n\nAssistant:\nHazırım.\n"
    with pytest.raises(RuntimeError, match="transcript contract"):
        _extract_assistant_text(raw, prompt=prompt)


def test_extract_assistant_text_rejects_malformed_reasoning_markers() -> None:
    prompt = "hello"
    raw = f"User:\n{prompt}\n\nAssistant:\n[Start thinking]\nunfinished"
    with pytest.raises(RuntimeError, match="reasoning markers were malformed"):
        _extract_assistant_text(raw, prompt=prompt)


def test_extract_assistant_text_rejects_empty_assistant_segment() -> None:
    prompt = "hello"
    raw = f"User:\n{prompt}\n\nAssistant:\n"
    with pytest.raises(RuntimeError, match="assistant segment was empty"):
        _extract_assistant_text(raw, prompt=prompt)


def test_ipc_frame_round_trip_is_versioned_and_bounded() -> None:
    frame = _encode_ipc_frame({"type": "READY", "readiness": NR2A_READY_SEMANTICS})

    assert frame.endswith("\n")
    assert len(frame[:-1]) <= NR2A_MAX_FRAME_CHARS
    decoded = _decode_ipc_frame(frame)
    assert decoded["protocol_version"] == NR2A_IPC_VERSION
    assert decoded["readiness"] == "TRANSPORT_READY"


def test_ipc_frame_rejects_protocol_version_mismatch() -> None:
    frame = json.dumps(
        {"protocol_version": NR2A_IPC_VERSION + 1, "type": "READY"}
    ) + "\n"

    with pytest.raises(RuntimeError, match="protocol version mismatch"):
        _decode_ipc_frame(frame)


def test_ipc_frame_rejects_oversized_payload() -> None:
    with pytest.raises(RuntimeError, match="exceeds maximum size"):
        _encode_ipc_frame({"type": "DATA", "text": "x" * NR2A_MAX_FRAME_CHARS})


def test_exact_sequence_rejects_gap_and_duplicate() -> None:
    assert _require_expected_sequence(0, 0) == 0
    assert _require_expected_sequence(1, 1) == 1

    with pytest.raises(RuntimeError, match="expected 1, got 2"):
        _require_expected_sequence(2, 1)
    with pytest.raises(RuntimeError, match="expected 1, got 0"):
        _require_expected_sequence(0, 1)


def test_ready_semantics_are_transport_only_without_model_load(tmp_path: Path) -> None:
    fake_model = tmp_path / "not-a-real-model.gguf"
    fake_model.write_bytes(b"transport-readiness-only")

    worker = LunaCliWorker(
        config=LlamaCliWorkerConfig(
            cli_path=Path(sys.executable).resolve(),
            model_path=fake_model.resolve(),
        )
    )
    worker.start(budget=_budget())
    try:
        assert worker.state is NeuralWorkerState.READY
        assert NR2A_READY_SEMANTICS == "TRANSPORT_READY"
    finally:
        worker.stop()


def test_ipc_frame_requires_newline_termination() -> None:
    frame = _encode_ipc_frame({"type": "STOPPED"}).rstrip("\n")

    with pytest.raises(RuntimeError, match="newline terminated"):
        _decode_ipc_frame(frame)
