from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from luna.parallel_cognition.live import LiveWorkerDraft
from luna.parallel_cognition.native_abi_v2 import NativeTokenUsage
from luna.parallel_cognition.native_real_driver import (
    _load_request,
    _model_request,
    _write_draft,
)


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "request_id": "c011-live-request:sha256:" + "1" * 64,
        "task_id": "91000000-0000-4000-8000-000000000011",
        "assignment_id": "c011-assignment:sha256:" + "2" * 64,
        "attempt_id": "attempt:s5b-real-driver-test",
        "worker_role": "PARALLEL",
        "objective": "Return one concise read-only observation.",
        "deadline_at": "2026-08-30T20:00:00Z",
        "max_output_tokens": 128,
        "context": [
            {
                "source_ref": "repo:s5b-real-driver-test",
                "source_revision": "git:test",
                "manifest_content_sha256": "3" * 64,
                "visible_content_sha256": "3" * 64,
                "manifest_size_bytes": 16,
                "visible_size_bytes": 16,
                "content": "verified context",
                "redactions_applied": [],
            }
        ],
        "available_tools": [],
        "credentials": [],
        "inherited_memory": [],
        "authority": {
            "write": False,
            "network": False,
            "process": False,
            "tool": False,
            "external_action": False,
            "delegation": False,
            "memory_commit": False,
            "state_mutation": False,
            "completion": False,
            "user_facing_voice": False,
        },
        "output_contract": "summary_and_cited_claims_only_no_hidden_reasoning",
    }


def test_real_driver_accepts_only_closed_read_only_request(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_payload()), encoding="utf-8")

    payload = _load_request(request_path)
    request = _model_request(payload)

    assert len(request.messages) == 1
    assert request.available_tools == ()
    assert request.max_output_tokens == 128
    assert "verified context" in request.messages[0].content

    raw = _payload()
    authority = dict(raw["authority"])  # type: ignore[arg-type]
    authority["tool"] = True
    raw["authority"] = authority
    request_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="received authority"):
        _load_request(request_path)


def test_real_driver_writes_final_only_unverified_draft(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    usage = NativeTokenUsage(input_tokens=11, output_tokens=7, total_tokens=18)
    _write_draft(
        result_path,
        final_text="One bounded final observation.",
        usage=usage,
    )

    draft = LiveWorkerDraft.model_validate_json(result_path.read_bytes())
    assert draft.summary == "One bounded final observation."
    assert draft.claims == ()
    assert draft.tokens == 18
    assert draft.native_usage is not None
    assert draft.native_usage.source == "ENGINE_NATIVE_COUNTERS"
    assert draft.native_usage.input_tokens == 11
    assert draft.native_usage.output_tokens == 7
    assert draft.native_usage.total_tokens == 18
    assert draft.uncertainty == (
        "Real model output is an unverified read-only worker draft; "
        "root validation remains required.",
    )

    with pytest.raises(ValueError, match="Harmony control marker"):
        _write_draft(
            result_path,
            final_text="<|channel|>analysis<|message|>secret",
            usage=usage,
        )


def test_real_driver_rejects_invalid_native_usage_before_writing(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="total mismatch"):
        NativeTokenUsage(input_tokens=11, output_tokens=7, total_tokens=19)
    assert not (tmp_path / "result.json").exists()


def test_real_driver_silences_native_stderr_at_the_process_boundary() -> None:
    code = (
        "import os; "
        "from luna.parallel_cognition.native_real_driver import _silence_native_stderr; "
        "sink = _silence_native_stderr(); "
        "os.write(2, b'x' * 20000); "
        "print('STDERR_SILENCED'); "
        "sink.close()"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "STDERR_SILENCED"
    assert completed.stderr == ""
