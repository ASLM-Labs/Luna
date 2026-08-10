"""Deterministic verifier for the Luna Neural Runtime foundation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.modeling import (  # noqa: E402
    MessageRole,
    ModelBackendError,
    ModelBackendErrorCode,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
)
from luna.modeling.native import NativeModelBackend  # noqa: E402
from luna.neural import (  # noqa: E402
    LunaNeuralRuntime,
    NeuralFinishReason,
    NeuralGenerationResult,
    NeuralResourceBudget,
    NeuralResourcePolicy,
    NeuralResourceProfile,
    NeuralToolCall,
    NeuralUsage,
    NeuralWorkerState,
)

_REQUIRED_FILES = (
    ROOT / "src" / "luna" / "neural" / "__init__.py",
    ROOT / "src" / "luna" / "neural" / "contracts.py",
    ROOT / "src" / "luna" / "neural" / "resources.py",
    ROOT / "src" / "luna" / "neural" / "runtime.py",
    ROOT / "src" / "luna" / "neural" / "worker_protocol.py",
    ROOT / "src" / "luna" / "modeling" / "native.py",
    ROOT / "tests" / "test_neural_runtime_foundation.py",
    ROOT / "tests" / "test_native_model_backend.py",
    ROOT / "docs" / "NEURAL_RUNTIME_FOUNDATION_REPORT.md",
)


class _Worker:
    def __init__(self) -> None:
        self._state = NeuralWorkerState.STOPPED
        self.starts = 0
        self.stops = 0
        self.last_budget: NeuralResourceBudget | None = None

    @property
    def worker_id(self) -> str:
        return "nr1-verifier-worker"

    @property
    def state(self) -> NeuralWorkerState:
        return self._state

    def start(self, *, budget: NeuralResourceBudget) -> None:
        self.starts += 1
        self.last_budget = budget.model_copy(deep=True)
        self._state = NeuralWorkerState.READY

    def generate(self, request: ModelRequest) -> NeuralGenerationResult:
        if request.available_tools:
            return NeuralGenerationResult(
                request_id=request.request_id,
                tool_calls=(
                    NeuralToolCall(
                        call_id="nr1-tool-1",
                        tool_name=request.available_tools[0].name,
                        arguments={},
                    ),
                ),
                finish_reason=NeuralFinishReason.TOOL_CALLS,
                usage=NeuralUsage(input_tokens=10, output_tokens=3),
            )
        return NeuralGenerationResult(
            request_id=request.request_id,
            text="NR1_OK",
            finish_reason=NeuralFinishReason.STOP,
            usage=NeuralUsage(input_tokens=8, output_tokens=2),
        )

    def stop(self) -> None:
        self.stops += 1
        self._state = NeuralWorkerState.STOPPED


def _budget(*, vram: int, resident: bool, inference: bool = True) -> NeuralResourceBudget:
    return NeuralResourceBudget(
        max_vram_mib=vram,
        max_gpu_utilization_percent=60 if inference else 5,
        cpu_threads=8 if inference else 2,
        max_system_ram_mib=8192,
        max_kv_cache_mib=1024 if inference else 0,
        max_context_tokens=4096,
        batch_size=256 if inference else 32,
        max_parallel_generations=1 if inference else 0,
        idle_unload_seconds=60 if resident else 0,
        request_priority=50 if inference else 10,
        inference_allowed=inference,
        model_resident=resident,
        background_inference=False,
    )


def main() -> int:
    missing = tuple(str(path.relative_to(ROOT)) for path in _REQUIRED_FILES if not path.is_file())

    profiles = {
        NeuralResourceProfile.USER_PRIORITY: _budget(
            vram=1024,
            resident=False,
            inference=False,
        ),
        NeuralResourceProfile.BALANCED: _budget(vram=8192, resident=True),
        NeuralResourceProfile.PERFORMANCE: _budget(vram=11000, resident=True),
    }
    policy = NeuralResourcePolicy(
        profiles=profiles,
        active_profile=NeuralResourceProfile.BALANCED,
    )

    automatic_escalation_blocked = False
    try:
        policy.transition(NeuralResourceProfile.PERFORMANCE, user_authorized=False)
    except PermissionError:
        automatic_escalation_blocked = True

    automatic_reduction_allowed = True
    try:
        policy.transition(NeuralResourceProfile.USER_PRIORITY, user_authorized=False)
    except PermissionError:
        automatic_reduction_allowed = False

    denied_worker = _Worker()
    denied_backend = NativeModelBackend(
        runtime=LunaNeuralRuntime(worker=denied_worker, resource_policy=policy)
    )
    request = ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="verify"),),
        max_output_tokens=32,
    )
    denied_normalized = False
    try:
        denied_backend.generate(request)
    except ModelBackendError as exc:
        denied_normalized = (
            exc.code is ModelBackendErrorCode.UNAVAILABLE
            and exc.retryable
            and denied_worker.starts == 0
        )

    policy.transition(NeuralResourceProfile.BALANCED, user_authorized=True)
    worker = _Worker()
    runtime = LunaNeuralRuntime(worker=worker, resource_policy=policy)
    backend = NativeModelBackend(runtime=runtime)
    response = backend.generate(request)
    runtime.transition_profile(
        NeuralResourceProfile.USER_PRIORITY,
        user_authorized=False,
    )

    neural_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _REQUIRED_FILES
        if path.suffix == ".py" and path.is_file()
    ).casefold()

    checks = {
        "required_files_present": not missing,
        "automatic_resource_escalation_blocked": automatic_escalation_blocked,
        "automatic_resource_reduction_allowed": automatic_reduction_allowed,
        "resource_denial_normalized": denied_normalized,
        "existing_model_contract_preserved": (
            response.request_id == request.request_id
            and response.backend_id == "luna-native"
            and response.text == "NR1_OK"
            and response.finish_reason is ModelFinishReason.STOP
            and response.usage.input_tokens == 8
            and response.usage.output_tokens == 2
        ),
        "resident_worker_started_once": (
            worker.starts == 1
            and worker.last_budget is not None
            and worker.last_budget.max_vram_mib == 8192
        ),
        "resource_reduction_releases_worker": (
            worker.state is NeuralWorkerState.STOPPED and worker.stops == 1
        ),
        "no_http_server_boundary_added": "http://" not in neural_sources
        and "https://" not in neural_sources,
        "no_ollama_dependency_added": "ollama" not in neural_sources,
        "worker_has_no_resource_policy_reference": (
            "neuralresourcepolicy" not in (
                ROOT / "src" / "luna" / "neural" / "worker_protocol.py"
            ).read_text(encoding="utf-8").casefold()
        ),
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    print(
        json.dumps(
            {
                "scope": "NEURAL_RUNTIME_FOUNDATION",
                "checks": checks,
                "missing_files": missing,
                "status": status,
                "authority": (
                    "Foundation only; no model load, native library binding, primary-path switch, "
                    "tool authority, memory authority, or promotion authority is granted."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
