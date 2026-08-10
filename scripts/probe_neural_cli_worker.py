"""Manual NR-2A native worker probe for canonical assistant text."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.modeling.contracts import MessageRole, ModelMessage, ModelRequest  # noqa: E402
from luna.neural.cli_worker import LlamaCliWorkerConfig, LunaCliWorker  # noqa: E402
from luna.neural.contracts import (  # noqa: E402
    NeuralResourceBudget,
    NeuralResourceProfile,
)
from luna.neural.resources import NeuralResourcePolicy  # noqa: E402
from luna.neural.runtime import LunaNeuralRuntime  # noqa: E402
from luna.neural.streaming import NeuralStreamEventType  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--system-prompt")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--ctx-size", type=int, default=4096)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--max-output-tokens", type=int, default=128)
    args = parser.parse_args()

    def observe(event: object) -> None:
        if getattr(event, "event_type", None) is NeuralStreamEventType.TEXT_DELTA:
            print(getattr(event, "text", ""), end="", flush=True)

    config = LlamaCliWorkerConfig(
        cli_path=args.cli.resolve(),
        model_path=args.model.resolve(),
        gpu_layers=0,
    )
    worker = LunaCliWorker(config=config, stream_observer=observe)
    budget = NeuralResourceBudget(
        max_vram_mib=0,
        max_gpu_utilization_percent=0,
        cpu_threads=args.threads,
        max_system_ram_mib=28672,
        max_kv_cache_mib=2048,
        max_context_tokens=args.ctx_size,
        batch_size=args.batch_size,
        max_parallel_generations=1,
        idle_unload_seconds=0,
        request_priority=50,
        inference_allowed=True,
        model_resident=False,
        background_inference=False,
    )
    policy = NeuralResourcePolicy(
        profiles={NeuralResourceProfile.DESKTOP: budget},
        active_profile=NeuralResourceProfile.DESKTOP,
    )
    runtime = LunaNeuralRuntime(worker=worker, resource_policy=policy)

    messages = []
    if args.system_prompt:
        messages.append(ModelMessage(role=MessageRole.SYSTEM, content=args.system_prompt))
    messages.append(ModelMessage(role=MessageRole.USER, content=args.prompt))
    request = ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=tuple(messages),
        max_output_tokens=args.max_output_tokens,
        temperature=0.0,
    )

    result = runtime.generate(request)
    print()
    print(
        f"[finish={result.finish_reason.value} chars={len(result.text)} "
        f"request_id={result.request_id}]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
