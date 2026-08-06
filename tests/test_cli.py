from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from luna.audit import AppendOnlyAuditLedger, AuditEventKind
from luna.cli import main


def test_status_command(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["status"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "phase: 8" in output
    assert "tool_dispatcher: deny_by_default" in output
    assert "workspace_writes: snapshot_first_atomic" in output
    assert "shell_parsing: disabled" in output
    assert "network_tools: disabled" in output


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "Luna 0.1.0"


def test_resolve_intent_command_returns_json(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["resolve-intent", "README.md dosyasını incele"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["kind"] == "CODE_INSPECTION"
    assert payload["referenced_resources"] == ["README.md"]


def test_list_tools(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["list-tools"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "core.echo" in output
    assert "filesystem.read_text" in output
    assert "filesystem.write_text" in output
    assert "workspace.rollback" in output
    assert "process.run_argv" in output


def test_tool_smoke_runs_through_dispatcher(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["tool-smoke", "hello"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["result"]["status"] == "SUCCESS"
    assert payload["result"]["stdout_excerpt"] == "hello"
    assert payload["event"]["decision"] == "EXECUTED"


def test_workspace_smoke_writes_and_rolls_back(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["workspace-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["write_status"] == "SUCCESS"
    assert payload["rollback_status"] == "SUCCESS"
    assert payload["file_exists_after_rollback"] is False
    assert payload["rollback_verified"] is True


def test_process_smoke_uses_shell_false(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["process-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["result"]["status"] == "SUCCESS"
    assert payload["result"]["metadata"]["shell"] is False


def test_audit_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["audit-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["integrity"] is True
    assert payload["event_count"] == 6
    assert payload["secret_absent"] is True


def test_audit_inspect_prints_only_selected_task(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = AppendOnlyAuditLedger(tmp_path)
    selected_task = uuid4()
    other_task = uuid4()
    trace_id = uuid4()
    ledger.append(
        kind=AuditEventKind.OBSERVATION,
        task_id=selected_task,
        trace_id=trace_id,
        subject_id=str(uuid4()),
        payload={"status": "SUCCESS"},
    )
    ledger.append(
        kind=AuditEventKind.OBSERVATION,
        task_id=other_task,
        trace_id=uuid4(),
        subject_id=str(uuid4()),
        payload={"status": "FAILURE"},
    )

    exit_code = main(["audit-inspect", str(tmp_path), str(selected_task)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert len(payload) == 1
    assert payload[0]["task_id"] == str(selected_task)
    assert payload[0]["trace_id"] == str(trace_id)



def test_verify_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["verify-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "VERIFIED_COMPLETE"
    assert payload["audit_integrity"] is True
    assert "VERIFICATION_REPORT" in payload["event_kinds"]
    assert "COMPLETION_DECISION" in payload["event_kinds"]



def test_checkpoint_smoke_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["checkpoint-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["resume_status"] == "READY"
    assert payload["resumed_phase"] == "PLANNED"
    assert payload["journal_mode"] == "wal"
    assert payload["integrity"] is True
    assert "CHECKPOINT_CREATED" in payload["event_kinds"]
    assert "RESUME_DECISION" in payload["event_kinds"]
