"""Exact-argv process execution with shell parsing disabled and bounded output."""

from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
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

type ProcessStopProbe = Callable[[], bool]

_WINDOWS_JOB_WRAPPER = r"""
import json
import subprocess
import sys

header = sys.stdin.buffer.read(8)
if len(header) != 8:
    raise SystemExit(126)
size = int.from_bytes(header, "big")
payload = sys.stdin.buffer.read(size)
if len(payload) != size:
    raise SystemExit(126)
argv = json.loads(payload.decode("utf-8"))
if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
    raise SystemExit(126)

creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
child = subprocess.Popen(
    argv,
    stdin=subprocess.DEVNULL,
    stdout=None,
    stderr=None,
    shell=False,
    creationflags=creationflags,
)
raise SystemExit(child.wait())
"""


class OwnedProcessTree:
    """Internal process-tree ownership boundary retained beyond root exit."""

    def is_alive(self) -> bool:
        raise NotImplementedError

    def terminate(self, *, graceful_timeout_seconds: float) -> bool:
        """Terminate the tree and report whether hard termination was required."""
        raise NotImplementedError

    def wait_quiescent(self, *, timeout_seconds: float) -> bool:
        deadline = time.perf_counter() + timeout_seconds
        while self.is_alive():
            if time.perf_counter() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def close(self) -> None:
        return None


class _PosixProcessTree(OwnedProcessTree):
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self._pgid = process.pid

    def _linux_non_zombie_member_exists(self) -> bool | None:
        proc = Path("/proc")
        if not proc.is_dir():
            return None
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                raw = (entry / "stat").read_text(encoding="utf-8")
                tail = raw[raw.rfind(")") + 2 :].split()
                state = tail[0]
                process_group = int(tail[2])
            except (OSError, ValueError, IndexError):
                continue
            if process_group == self._pgid and state != "Z":
                return True
        return False

    @staticmethod
    def _signal_process_group(
        process_group_id: int,
        signal_number: int,
    ) -> None:
        killpg = vars(os).get("killpg")
        if not callable(killpg):
            raise RuntimeError(
                "POSIX process-group signaling is unavailable"
            )
        killpg(process_group_id, signal_number)

    def is_alive(self) -> bool:
        self._process.poll()
        linux_alive = self._linux_non_zombie_member_exists()
        if linux_alive is not None:
            return linux_alive
        try:
            self._signal_process_group(
                self._pgid,
                0,
            )
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def terminate(self, *, graceful_timeout_seconds: float) -> bool:
        try:
            self._signal_process_group(
                self._pgid,
                signal.SIGTERM,
            )
        except ProcessLookupError:
            return False

        if self.wait_quiescent(timeout_seconds=graceful_timeout_seconds):
            return False

        try:
            sigkill = vars(signal).get("SIGKILL")
            if not isinstance(sigkill, int):
                raise RuntimeError(
                    "POSIX SIGKILL is unavailable"
                )
            self._signal_process_group(
                self._pgid,
                sigkill,
            )
        except ProcessLookupError:
            return False

        return True


class _WindowsJob(OwnedProcessTree):
    """One Windows Job Object that owns the wrapper and all descendants."""

    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        from ctypes import wintypes

        class _BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class _BasicAccountingInformation(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")

        self._kernel32 = kernel32
        self._handle = handle
        self._accounting_type = _BasicAccountingInformation

        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            self._handle = None
            raise OSError(error, "SetInformationJobObject failed")

        process_handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
        if not kernel32.AssignProcessToJobObject(handle, process_handle):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            self._handle = None
            raise OSError(error, "AssignProcessToJobObject failed")

    def is_alive(self) -> bool:
        if self._handle is None:
            return False
        info = self._accounting_type()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            self._JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            raise OSError(ctypes.get_last_error(), "QueryInformationJobObject failed")
        return bool(info.ActiveProcesses)

    def terminate(self, *, graceful_timeout_seconds: float) -> bool:
        del graceful_timeout_seconds

        if self._handle is None:
            return False

        if not self._kernel32.TerminateJobObject(self._handle, 1):
            raise OSError(ctypes.get_last_error(), "TerminateJobObject failed")

        return True

    def close(self) -> None:
        if self._handle is None:
            return
        handle = self._handle
        self._handle = None
        if not self._kernel32.CloseHandle(handle):
            raise OSError(ctypes.get_last_error(), "CloseHandle(job) failed")


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


def start_owned_process(
    *,
    argv: tuple[str, ...],
    cwd: Path,
    environment: Mapping[str, str],
    stdout: int | BinaryIO | None,
    stderr: int | BinaryIO | None,
) -> tuple[subprocess.Popen[bytes], OwnedProcessTree]:
    """Start one root whose descendants remain owned after direct-root exit."""

    if os.name != "nt":
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=str(cwd),
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                start_new_session=True,
            )
        except OSError as exc:
            raise SafeProcessError(f"process start failed: {exc}") from exc

        return process, _PosixProcessTree(process)

    # Windows cannot recover a process tree from a dead root PID. Launch a tiny
    # trusted gate first, bind that gate to a kill-on-close Job Object, and only
    # then release the validated user argv over stdin. The target and every
    # non-breakaway descendant inherit Job membership.
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", _WINDOWS_JOB_WRAPPER],
            cwd=str(cwd),
            env=dict(environment),
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            shell=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP
            ),
        )
    except OSError as exc:
        raise SafeProcessError(
            f"process ownership gate start failed: {exc}"
        ) from exc

    try:
        tree = _WindowsJob(process)
    except OSError as exc:
        process.kill()
        process.wait()
        raise SafeProcessError(
            f"process tree ownership setup failed: {exc}"
        ) from exc

    assert process.stdin is not None
    payload = json.dumps(list(argv), ensure_ascii=False).encode("utf-8")

    try:
        process.stdin.write(len(payload).to_bytes(8, "big"))
        process.stdin.write(payload)
        process.stdin.flush()
        process.stdin.close()
    except (BrokenPipeError, OSError) as exc:
        try:
            tree.terminate(graceful_timeout_seconds=0.0)
            tree.wait_quiescent(timeout_seconds=5)
        finally:
            tree.close()

        process.wait()
        raise SafeProcessError(
            f"process ownership gate release failed: {exc}"
        ) from exc

    return process, tree


def terminate_owned_process_tree(
    tree: OwnedProcessTree,
    *,
    graceful_timeout_seconds: float = 0.25,
    quiescence_timeout_seconds: float = 5.0,
) -> bool:
    """Terminate every still-owned descendant and prove bounded quiescence."""

    if graceful_timeout_seconds < 0:
        raise ValueError(
            "owned process graceful timeout cannot be negative"
        )
    if quiescence_timeout_seconds < 0:
        raise ValueError(
            "owned process quiescence timeout cannot be negative"
        )

    if not tree.is_alive():
        return False

    hard_termination_used = tree.terminate(
        graceful_timeout_seconds=graceful_timeout_seconds,
    )

    if not tree.wait_quiescent(
        timeout_seconds=quiescence_timeout_seconds
    ):
        raise RuntimeError(
            "owned process tree failed to quiesce after termination"
        )

    return hard_termination_used


def run_bounded_argv(
    *,
    argv: tuple[str, ...],
    working_directory: str,
    timeout_ms: int,
    max_output_chars: int,
    stop_requested: ProcessStopProbe | None = None,
) -> ProcessExecution:
    """Run exact argv with bounded output, whole-tree ownership, and cancellation."""

    validate_safe_argv(argv)
    cwd = Path(working_directory)
    if not cwd.is_dir():
        raise SafeProcessError("working directory does not exist")

    encoded_argv = "\x00".join(argv).encode("utf-8")
    argv_digest = sha256(encoded_argv).hexdigest()
    byte_limit = max_output_chars * 4

    started = time.perf_counter()
    process, tree = start_owned_process(
        argv=argv,
        cwd=cwd,
        environment=_minimal_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

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
    try:
        while tree.is_alive():
            if output_limit.is_set():
                terminate_owned_process_tree(tree)
                break
            if stop_requested is not None and stop_requested():
                terminate_owned_process_tree(tree)
                break
            if time.perf_counter() >= deadline:
                timed_out = True
                terminate_owned_process_tree(tree)
                break
            time.sleep(0.01)

        process.wait()

        for reader in readers:
            reader.join(timeout=1)
        if any(reader.is_alive() for reader in readers):
            raise RuntimeError("process output readers remained live after tree quiescence")
    finally:
        # KILL_ON_JOB_CLOSE gives Windows a final fail-safe if any exceptional
        # path escapes after user code was released.
        tree.close()

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
