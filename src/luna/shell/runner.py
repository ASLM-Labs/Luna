"""Exact-argv process execution with shell parsing disabled and bounded output."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO


class SafeProcessError(RuntimeError):
    """Raised when an argv request violates the Phase 5 process boundary."""


_BANNED_EXECUTABLES = {
    "bash",
    "bash.exe",
    "cmd",
    "cmd.exe",
    "command.com",
    "cscript",
    "cscript.exe",
    "fish",
    "fish.exe",
    "mshta",
    "mshta.exe",
    "powershell",
    "powershell.exe",
    "powershell_ise.exe",
    "pwsh",
    "pwsh.exe",
    "sh",
    "sh.exe",
    "wscript",
    "wscript.exe",
    "wsl",
    "wsl.exe",
    "zsh",
    "zsh.exe",
}


@dataclass(frozen=True, slots=True)
class ProcessExecution:
    """Bounded raw result consumed by the registered process tool."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    output_limit_exceeded: bool
    argv_digest: str


def _executable_name(value: str) -> str:
    return Path(value).name.casefold()


def validate_safe_argv(argv: tuple[str, ...]) -> None:
    """Reject command interpreters and common inline-code escape hatches."""
    if not argv:
        raise SafeProcessError("argv must contain an executable")
    if any(not value or "\x00" in value for value in argv):
        raise SafeProcessError("argv entries must be non-empty and NUL-free")

    executable = _executable_name(argv[0])
    if executable in _BANNED_EXECUTABLES:
        raise SafeProcessError("shell and script-host executables are not allowed")

    lowered_args = {value.casefold() for value in argv[1:]}
    is_python_launcher = executable in {"py", "py.exe"} or executable.startswith("python")
    if is_python_launcher and ({"-c", "-"} & lowered_args):
        raise SafeProcessError("inline Python execution is not allowed")
    if executable.startswith("node") and ({"-e", "--eval", "-p", "--print"} & lowered_args):
        raise SafeProcessError("inline Node execution is not allowed")
    if executable.startswith(("perl", "ruby")) and "-e" in lowered_args:
        raise SafeProcessError("inline interpreter execution is not allowed")


def _minimal_environment() -> dict[str, str]:
    allowed = {
        "HOME",
        "LANG",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "VIRTUAL_ENV",
        "WINDIR",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment["NO_COLOR"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    return environment


def _read_pipe(
    stream: BinaryIO,
    sink: bytearray,
    *,
    byte_limit: int,
    output_limit: threading.Event,
    lock: threading.Lock,
    total: list[int],
) -> None:
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                return
            with lock:
                remaining = max(0, byte_limit - total[0])
                if remaining:
                    sink.extend(chunk[:remaining])
                total[0] += len(chunk)
                if total[0] > byte_limit:
                    output_limit.set()
                    return
    finally:
        stream.close()


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            killpg = getattr(os, "killpg", None)
            sigkill = getattr(signal, "SIGKILL", None)
            if callable(killpg) and isinstance(sigkill, int):
                killpg(process.pid, sigkill)
            else:
                process.kill()
    except (OSError, subprocess.SubprocessError):
        process.kill()


def run_bounded_argv(
    *,
    argv: tuple[str, ...],
    working_directory: str,
    timeout_ms: int,
    max_output_chars: int,
) -> ProcessExecution:
    """Run exact argv with `shell=False`, no stdin, bounded output, and timeout kill."""
    validate_safe_argv(argv)
    cwd = Path(working_directory)
    if not cwd.is_dir():
        raise SafeProcessError("working directory does not exist")

    encoded_argv = "\x00".join(argv).encode("utf-8")
    argv_digest = sha256(encoded_argv).hexdigest()
    byte_limit = max_output_chars * 4
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP

    started = time.perf_counter()
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            env=_minimal_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    except OSError as exc:
        raise SafeProcessError(f"process start failed: {exc}") from exc

    assert process.stdout is not None
    assert process.stderr is not None
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    output_limit = threading.Event()
    lock = threading.Lock()
    total = [0]
    readers = (
        threading.Thread(
            target=_read_pipe,
            args=(process.stdout, stdout_buffer),
            kwargs={
                "byte_limit": byte_limit,
                "output_limit": output_limit,
                "lock": lock,
                "total": total,
            },
            daemon=True,
        ),
        threading.Thread(
            target=_read_pipe,
            args=(process.stderr, stderr_buffer),
            kwargs={
                "byte_limit": byte_limit,
                "output_limit": output_limit,
                "lock": lock,
                "total": total,
            },
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()

    timed_out = False
    deadline = started + timeout_ms / 1000
    while process.poll() is None:
        if output_limit.is_set():
            _terminate_process_tree(process)
            break
        if time.perf_counter() >= deadline:
            timed_out = True
            _terminate_process_tree(process)
            break
        time.sleep(0.01)
    process.wait()
    for reader in readers:
        reader.join(timeout=1)

    duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    stdout = bytes(stdout_buffer).decode("utf-8", errors="replace")
    stderr = bytes(stderr_buffer).decode("utf-8", errors="replace")
    output_limit_exceeded = output_limit.is_set()
    if timed_out:
        stderr = f"{stderr}\nprocess exceeded timeout budget".strip()
        exit_code = 124
    elif output_limit_exceeded:
        stderr = f"{stderr}\nprocess exceeded output budget".strip()
        exit_code = 125
    else:
        exit_code = int(process.returncode or 0)

    return ProcessExecution(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        timed_out=timed_out,
        output_limit_exceeded=output_limit_exceeded,
        argv_digest=argv_digest,
    )
