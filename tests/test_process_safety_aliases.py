from __future__ import annotations

import pytest

from luna.shell import SafeProcessError, validate_safe_argv


@pytest.mark.parametrize(
    "executable",
    (
        "bash.exe",
        "command.com",
        "fish.exe",
        "powershell_ise.exe",
        "pwsh.exe",
        "sh.exe",
        "zsh.exe",
    ),
)
def test_shell_aliases_are_rejected(executable: str) -> None:
    with pytest.raises(SafeProcessError, match="shell"):
        validate_safe_argv((executable, "--version"))


@pytest.mark.parametrize("launcher", ("py", "py.exe", "python", "python.exe"))
def test_python_launchers_reject_inline_code(launcher: str) -> None:
    with pytest.raises(SafeProcessError, match="inline Python"):
        validate_safe_argv((launcher, "-c", "print('blocked')"))
