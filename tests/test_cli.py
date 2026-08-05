from __future__ import annotations
import pytest
from luna.cli import main

def test_status_command(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["status"])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "phase: 0" in output
    assert "status: SCAFFOLD_READY" in output
    assert "runtime_capabilities: disabled" in output

def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "Luna 0.1.0"
