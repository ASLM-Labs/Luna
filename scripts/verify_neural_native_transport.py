"""Deterministic closure verifier for NR-2B Direct Native Worker Slice 1."""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.modeling.contracts import MessageRole, ModelMessage, ModelRequest  # noqa: E402
from luna.neural.native_worker import (  # noqa: E402
    NR2B_MAX_OUTPUT_TOKENS,
    NR2B_READY_SEMANTICS,
)
from luna.neural.native_worker_process import (  # noqa: E402
    _extract_harmony_final,
    _render_direct_request,
)

EXPECTED_PARENT = "639bb5ddead055eec9b04d868370364218496cba"
EXPECTED_PROOF_RAW_SHA = "A10416330716D36E3B8869F5097FEC8DD599F2FC57A68F561A71EF1D957895DE"
EXPECTED_PROOF_NORMALIZED_SHA = (
    "0F3899AABFB8BE52BE1E4380AC43C6E4E55FD5D9ED80CFE126CA40554B4EF654"
)

_REQUIRED_FILES = (
    ROOT / "src" / "luna" / "neural" / "native_worker.py",
    ROOT / "src" / "luna" / "neural" / "native_worker_process.py",
    ROOT / "tests" / "test_neural_native_transport.py",
    ROOT / "scripts" / "verify_neural_native_transport.py",
    ROOT / "docs" / "NEURAL_RUNTIME_NR2B_REPORT.md",
    ROOT / "docs" / "NEURAL_RUNTIME_NR2B_REAL_PROOF_RECEIPT.json",
    ROOT / "docs" / "NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json",
)


def _canonical_bytes(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.encode("utf-8")


def _canonical_metadata(path: Path) -> tuple[str, int]:
    canonical = _canonical_bytes(path)
    return sha256(canonical).hexdigest(), len(canonical)


def _load_sums() -> dict[str, str]:
    result: dict[str, str] = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        result[relative] = digest
    return result


def main() -> int:
    missing = [str(path.relative_to(ROOT)) for path in _REQUIRED_FILES if not path.is_file()]
    if missing:
        raise SystemExit("missing NR-2B Slice 1 files: " + ", ".join(missing))

    request = ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="hello"),),
        max_output_tokens=64,
    )
    if _render_direct_request(request) != "hello":
        raise SystemExit("direct request rendering failed")

    harmony = (
        "<|channel|>analysis<|message|>"
        "not-for-user-output"
        "<|end|><|start|>assistant"
        "<|channel|>final<|message|>"
        "Ready."
        "<|return|>"
    )
    if _extract_harmony_final(harmony) != "Ready.":
        raise SystemExit("Harmony final isolation failed")

    process_source = (
        ROOT / "src" / "luna" / "neural" / "native_worker_process.py"
    ).read_text(encoding="utf-8")
    worker_source = (ROOT / "src" / "luna" / "neural" / "native_worker.py").read_text(
        encoding="utf-8"
    )

    if "subprocess.run(" in process_source or "llama-cli" in process_source:
        raise SystemExit("direct native child must not launch llama-cli")
    if "stderr=subprocess.DEVNULL" not in worker_source:
        raise SystemExit("native child stderr must not be allowed to block IPC")
    if "cwd=str(self._config.runtime_dir)" not in worker_source:
        raise SystemExit("direct native child must launch from CPU runtime staging")
    if "ggml-cuda.dll" not in worker_source:
        raise SystemExit("CPU-only staging guard is missing")

    receipt = json.loads(
        (ROOT / "docs" / "NEURAL_RUNTIME_NR2B_REAL_PROOF_RECEIPT.json").read_text(
            encoding="utf-8"
        )
    )
    receipt_checks = {
        "scope": receipt.get("scope") == "NR2B_DIRECT_NATIVE_WORKER_SLICE1_REAL_PROOF",
        "status": receipt.get("status") == "PASS_LUNA_NATIVE_WORKER_FULL_CHAIN",
        "proof_source": receipt.get("proof_source") == "chat_uploaded_full_chain_proof",
        "proof_raw_sha": receipt.get("proof_raw_sha256") == EXPECTED_PROOF_RAW_SHA,
        "proof_normalized_sha": (
            receipt.get("proof_normalized_sha256") == EXPECTED_PROOF_NORMALIZED_SHA
        ),
        "frozen_basis": receipt.get("frozen_merged_main_basis") == EXPECTED_PARENT,
        "request_id": receipt.get("response_request_id_match") is True,
        "finish": receipt.get("response_finish_reason") == "STOP",
        "released": receipt.get("worker_state_after") == "STOPPED",
        "events": receipt.get("stream_event_types") == ["TEXT_DELTA", "FINISH"],
        "analysis_hidden": receipt.get("analysis_content_emitted") is False,
        "no_cli": receipt.get("llama_cli_required_for_this_path") is False,
        "ephemeral_nonclaim": receipt.get("persistent_residency_claimed") is False,
        "gpu_nonclaim": receipt.get("gpu_budget_enforcement_claimed") is False,
        "primary_nonclaim": receipt.get("primary_path_promoted") is False,
        "identity_nonclaim": receipt.get("identity_test_executed") is False,
        "exit": receipt.get("probe_exit_code") == 0,
    }
    failed_receipt = [name for name, passed in receipt_checks.items() if not passed]
    if failed_receipt:
        raise SystemExit("NR-2B proof receipt failed: " + ", ".join(failed_receipt))

    scoped = json.loads(
        (ROOT / "docs" / "NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    if scoped.get("hash_normalization") != "utf8_text_lf_v1":
        raise SystemExit("NR-2B scoped manifest hash normalization mismatch")
    if scoped.get("scope") != "NR-2B_DIRECT_NATIVE_WORKER_SLICE1":
        raise SystemExit("NR-2B scoped manifest scope mismatch")
    if scoped.get("status") != "IMPLEMENTED_VERIFIED_FOR_SCOPE":
        raise SystemExit("NR-2B scoped manifest status mismatch")
    if scoped.get("frozen_head") != EXPECTED_PARENT:
        raise SystemExit("NR-2B scoped manifest frozen head mismatch")

    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    sums = _load_sums()

    for relative, expected in scoped["files"].items():
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"NR-2B scoped file missing: {relative}")
        digest, size = _canonical_metadata(path)
        if expected.get("sha256") != digest or expected.get("size_bytes") != size:
            raise SystemExit(f"NR-2B scoped metadata mismatch: {relative}")
        global_entry = manifest.get("files", {}).get(relative)
        if global_entry != expected:
            raise SystemExit(f"global MANIFEST mismatch for NR-2B file: {relative}")
        if sums.get(relative) != digest:
            raise SystemExit(f"SHA256SUMS mismatch for NR-2B file: {relative}")

    scoped_relative = "docs/NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json"
    scoped_digest, scoped_size = _canonical_metadata(ROOT / scoped_relative)
    if manifest.get("files", {}).get(scoped_relative) != {
        "sha256": scoped_digest,
        "size_bytes": scoped_size,
    }:
        raise SystemExit("global MANIFEST mismatch for NR-2B scoped manifest")
    if sums.get(scoped_relative) != scoped_digest:
        raise SystemExit("SHA256SUMS mismatch for NR-2B scoped manifest")

    result = {
        "scope": "NR2B_DIRECT_NATIVE_WORKER_SLICE1",
        "ready_semantics": NR2B_READY_SEMANTICS,
        "max_output_tokens": NR2B_MAX_OUTPUT_TOKENS,
        "direct_child_process": True,
        "llama_cli_required": False,
        "cpu_only": True,
        "ephemeral_only": True,
        "one_user_turn_only": True,
        "harmony_final_only": True,
        "raw_analysis_emission": False,
        "real_full_chain_proof_locked": True,
        "persistent_residency_claimed": False,
        "gpu_budget_enforcement_claimed": False,
        "primary_path_promoted": False,
        "identity_test_executed": False,
        "status": "IMPLEMENTED_VERIFIED_FOR_SCOPE",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
