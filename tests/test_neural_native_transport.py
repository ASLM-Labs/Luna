from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from luna.modeling.contracts import MessageRole, ModelMessage, ModelRequest
from luna.neural.contracts import NeuralResourceBudget
from luna.neural.native_worker import (
    NR2B_MAX_OUTPUT_TOKENS,
    NR2B_READY_SEMANTICS,
    DirectNativeWorkerConfig,
    LunaNativeWorker,
)
from luna.neural.native_worker_process import _extract_harmony_final, _render_direct_request


def _budget(**updates: object) -> NeuralResourceBudget:
    base = NeuralResourceBudget(
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
    return base.model_copy(update=updates)


def _request(*messages: ModelMessage, max_output_tokens: int = 64) -> ModelRequest:
    return ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=messages,
        max_output_tokens=max_output_tokens,
        temperature=0.0,
    )


def _config(root: Path) -> DirectNativeWorkerConfig:
    return DirectNativeWorkerConfig(
        shim_path=(root / "luna_nr2b_shim.dll").resolve(),
        runtime_dir=(root / "cpu-runtime").resolve(),
        model_path=(root / "model.gguf").resolve(),
    )


def test_config_requires_absolute_paths() -> None:
    with pytest.raises(ValueError):
        DirectNativeWorkerConfig(
            shim_path=Path("shim.dll"),
            runtime_dir=Path("runtime"),
            model_path=Path("model.gguf"),
        )


def test_slice_constants_are_bounded() -> None:
    assert NR2B_READY_SEMANTICS == "MODEL_READY_DIRECT_NATIVE"
    assert NR2B_MAX_OUTPUT_TOKENS == 256


def test_render_direct_request_accepts_exactly_one_user_message() -> None:
    request = _request(ModelMessage(role=MessageRole.USER, content="hello"))
    assert _render_direct_request(request) == "hello"


def test_render_direct_request_rejects_system_or_history() -> None:
    request = _request(
        ModelMessage(role=MessageRole.SYSTEM, content="system"),
        ModelMessage(role=MessageRole.USER, content="hello"),
    )
    with pytest.raises(ValueError, match="exactly one USER"):
        _render_direct_request(request)


def test_render_direct_request_rejects_more_than_256_output_tokens() -> None:
    request = _request(
        ModelMessage(role=MessageRole.USER, content="hello"),
        max_output_tokens=257,
    )
    with pytest.raises(ValueError, match="exceeds 256"):
        _render_direct_request(request)


def test_harmony_parser_returns_only_final_channel() -> None:
    raw = (
        "<|channel|>analysis<|message|>"
        "not-for-user-output"
        "<|end|><|start|>assistant"
        "<|channel|>final<|message|>"
        "Ready."
        "<|return|>"
    )
    assert _extract_harmony_final(raw) == "Ready."


def test_harmony_parser_rejects_analysis_only_output() -> None:
    raw = "<|channel|>analysis<|message|>not-for-user-output"
    with pytest.raises(RuntimeError, match="did not produce a final"):
        _extract_harmony_final(raw)


def test_start_rejects_model_residency_before_touching_paths(tmp_path: Path) -> None:
    worker = LunaNativeWorker(config=_config(tmp_path))
    with pytest.raises(ValueError, match="ephemeral-only"):
        worker.start(budget=_budget(model_resident=True))


def test_start_rejects_gpu_budget_before_touching_paths(tmp_path: Path) -> None:
    worker = LunaNativeWorker(config=_config(tmp_path))
    with pytest.raises(ValueError, match="CPU-only"):
        worker.start(budget=_budget(max_vram_mib=1024))


def test_start_rejects_cuda_runtime_staging(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.runtime_dir.mkdir(parents=True)
    config.shim_path.write_bytes(b"shim-placeholder")
    config.model_path.write_bytes(b"model-placeholder")
    (config.runtime_dir / "ggml-cuda.dll").write_bytes(b"cuda-placeholder")

    worker = LunaNativeWorker(config=config)
    with pytest.raises(ValueError, match="must not stage ggml-cuda"):
        worker.start(budget=_budget())
