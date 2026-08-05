from __future__ import annotations

import json

import pytest

from luna.cli import main


def test_status_command(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["status"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "phase: 4" in output
    assert "tool_dispatcher: deny_by_default" in output
    assert "scripted_test_backend: enabled" in output
    assert "shell: disabled" in output


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
    assert "filesystem.list_directory" in output


def test_tool_smoke_runs_through_dispatcher(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["tool-smoke", "hello"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["result"]["status"] == "SUCCESS"
    assert payload["result"]["stdout_excerpt"] == "hello"
    assert payload["event"]["decision"] == "EXECUTED"
