"""Deterministic NR-2A transport verifier; does not load a model."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.modeling.contracts import MessageRole, ModelMessage, ModelRequest  # noqa: E402
from luna.neural.cli_worker import (  # noqa: E402
    NR2A_IPC_VERSION,
    NR2A_MAX_FRAME_CHARS,
    NR2A_READY_SEMANTICS,
    _decode_ipc_frame,
    _encode_ipc_frame,
    _require_expected_sequence,
)
from luna.neural.cli_worker_process import (  # noqa: E402
    _build_llama_command,
    _extract_assistant_text,
)
from luna.neural.contracts import NeuralResourceBudget  # noqa: E402


def main() -> int:
    request = ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="verify"),),
        max_output_tokens=16,
        temperature=0.0,
    )
    budget = NeuralResourceBudget(
        max_vram_mib=0,
        max_gpu_utilization_percent=0,
        cpu_threads=2,
        max_system_ram_mib=24576,
        max_kv_cache_mib=512,
        max_context_tokens=2048,
        batch_size=128,
        max_parallel_generations=1,
        inference_allowed=True,
        model_resident=False,
    )
    command = _build_llama_command(
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
    extraction_probe = (
        "User:\nverify\n\nAssistant:\n"
        "[Start thinking]\ninternal\n[End thinking]\n\nOK\n"
    )
    child_source = (
        ROOT / "src" / "luna" / "neural" / "cli_worker_process.py"
    ).read_text(encoding="utf-8")
    output_artifact_explicit = (
        'command.extend(["--output", str(output_path)])' in child_source
    )
    output_artifact_is_canonical_source = (
        'raw_output = output_path.read_text(encoding="utf-8")' in child_source
        and "_extract_assistant_text(raw_output, prompt=prompt)" in child_source
    )
    protocol_round_trip = _decode_ipc_frame(
        _encode_ipc_frame({"type": "READY", "readiness": NR2A_READY_SEMANTICS})
    )
    protocol_mismatch_rejected = False
    try:
        _decode_ipc_frame(
            json.dumps(
                {"protocol_version": NR2A_IPC_VERSION + 1, "type": "READY"}
            )
            + "\n"
        )
    except RuntimeError:
        protocol_mismatch_rejected = True

    sequence_gap_rejected = False
    try:
        _require_expected_sequence(2, 1)
    except RuntimeError:
        sequence_gap_rejected = True

    checks = {
        "ipc_protocol_version_locked": (
            protocol_round_trip["protocol_version"] == NR2A_IPC_VERSION == 1
        ),
        "ipc_frame_limit_bounded": NR2A_MAX_FRAME_CHARS == 1_048_576,
        "ipc_version_mismatch_rejected": protocol_mismatch_rejected,
        "ipc_sequence_gap_rejected": sequence_gap_rejected,
        "ready_is_transport_only": (
            protocol_round_trip["readiness"] == NR2A_READY_SEMANTICS
            == "TRANSPORT_READY"
        ),
        "embedded_jinja_enabled": "--jinja" in command,
        "explicit_template_override_absent": "--chat-template" not in command,
        "reasoning_auto": command[command.index("--reasoning") + 1] == "auto",
        "reasoning_effort_low": (
            command[command.index("--chat-template-kwargs") + 1]
            == '{"reasoning_effort":"low"}'
        ),
        "gpt_oss_sampling_profile": (
            command[command.index("--temperature") + 1] == "1.0"
            and command[command.index("--top-p") + 1] == "1.0"
        ),
        "engine_autofit_disabled": command[command.index("--fit") + 1] == "off",
        "safe_default_gpu_layers_zero": (
            command[command.index("--gpu-layers") + 1] == "0"
        ),
        "gpu_device_disabled": command[command.index("--device") + 1] == "none",
        "kv_gpu_offload_disabled": "--no-kv-offload" in command,
        "host_op_gpu_offload_disabled": "--no-op-offload" in command,
        "utf8_prompt_file_transport": (
            command[command.index("--file") + 1] == r"C:\temp\prompt.txt"
        ),
        "prompt_content_absent_from_argv": "verify" not in command,
        "reasoning_not_promoted_to_final_text": (
            _extract_assistant_text(extraction_probe, prompt="verify") == "OK"
        ),
        "output_artifact_explicitly_requested": output_artifact_explicit,
        "output_artifact_is_canonical_source": output_artifact_is_canonical_source,
        "no_http_server_boundary": "--server-base" not in command,
    }
    failed = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"{name}: {'PASS' if passed else 'FAIL'}")
    print("NR-2A NATIVE WORKER TRANSPORT:", "PASS" if not failed else "BLOCKED")
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
