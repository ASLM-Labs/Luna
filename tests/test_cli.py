from __future__ import annotations

import json

import pytest

from luna.cli import main


def test_status_command(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["status"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "phase: 5" in output
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
