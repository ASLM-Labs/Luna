from __future__ import annotations

import sys
from pathlib import Path

import pytest

from luna.shell import SafeProcessError, run_bounded_argv


def test_runner_kills_process_at_timeout(tmp_path: Path) -> None:
    script = tmp_path / "sleep_test.py"
    script.write_text("import time\ntime.sleep(1)\n", encoding="utf-8")

    result = run_bounded_argv(
        argv=(sys.executable, str(script)),
        working_directory=str(tmp_path),
        timeout_ms=30,
        max_output_chars=1000,
    )

    assert result.exit_code == 124
    assert result.timed_out
    assert "timeout" in result.stderr


def test_runner_kills_process_at_output_limit(tmp_path: Path) -> None:
    script = tmp_path / "output_test.py"
    script.write_text("print('x' * 100000)\n", encoding="utf-8")

    result = run_bounded_argv(
        argv=(sys.executable, str(script)),
        working_directory=str(tmp_path),
        timeout_ms=5000,
        max_output_chars=20,
    )

    assert result.exit_code == 125
    assert result.output_limit_exceeded
    assert len(result.stdout) <= 80


def test_runner_rejects_inline_python() -> None:
    with pytest.raises(SafeProcessError, match="inline Python"):
        run_bounded_argv(
            argv=(sys.executable, "-c", "print('no')"),
            working_directory=".",
            timeout_ms=1000,
            max_output_chars=1000,
        )
