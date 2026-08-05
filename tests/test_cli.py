from __future__ import annotations

import json

import pytest

from luna.cli import main


def test_status_command(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["status"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "phase: 2" in output
    assert "status: INTENT_CONTEXT_IMPLEMENTED_UNVERIFIED" in output
    assert "intent_resolver: deterministic_baseline" in output
    assert "context_io: disabled" in output
    assert "runtime_capabilities: disabled" in output


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "Luna 0.1.0"


def test_resolve_intent_command_returns_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["resolve-intent", "README.md dosyasını incele"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["kind"] == "CODE_INSPECTION"
    assert payload["referenced_resources"] == ["README.md"]
