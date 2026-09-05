from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Thread
from typing import cast
from uuid import uuid4

import pytest

from luna.contracts import TaskContract
from luna.shell import RunArgvTool, SafeProcessError, run_bounded_argv
from luna.tools.lifecycle import ExecutionLifecycleController, ExecutionSettlement
from luna.tools.registry import ToolExecutionContext, ToolExecutionOutput


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            [
                "tasklist",
                "/FI",
                f"PID eq {pid}",
                "/FO",
                "CSV",
                "/NH",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
        return str(pid) in completed.stdout and "No tasks are running" not in completed.stdout
    stat_path = Path(f"/proc/{pid}/stat")
    if stat_path.is_file():
        try:
            raw = stat_path.read_text(encoding="utf-8")
            state = raw[raw.rfind(")") + 2 :].split()[0]
            if state == "Z":
                return False
        except (OSError, IndexError):
            pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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


def test_runner_waits_for_descendant_tree_before_success(tmp_path: Path) -> None:
    marker = tmp_path / "descendant.done"
    child = tmp_path / "child.py"
    parent = tmp_path / "parent.py"
    child.write_text(
        "import pathlib, time\n"
        "time.sleep(0.15)\n"
        f"pathlib.Path({str(marker)!r}).write_text('done', encoding='utf-8')\n",
        encoding="utf-8",
    )
    parent.write_text(
        "import subprocess, sys\n"
        f"subprocess.Popen([sys.executable, {str(child)!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL, shell=False)\n",
        encoding="utf-8",
    )

    started = time.perf_counter()
    result = run_bounded_argv(
        argv=(sys.executable, str(parent)),
        working_directory=str(tmp_path),
        timeout_ms=2000,
        max_output_chars=1000,
    )
    elapsed = time.perf_counter() - started

    assert result.exit_code == 0
    assert not result.timed_out
    assert marker.read_text(encoding="utf-8") == "done"
    assert elapsed >= 0.10


def test_runner_times_out_and_kills_surviving_descendant(tmp_path: Path) -> None:
    pid_file = tmp_path / "descendant.pid"
    child = tmp_path / "child.py"
    parent = tmp_path / "parent.py"
    child.write_text(
        "import time\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    parent.write_text(
        "import pathlib, subprocess, sys\n"
        f"child = subprocess.Popen([sys.executable, {str(child)!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL, shell=False)\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid), encoding='utf-8')\n",
        encoding="utf-8",
    )

    result = run_bounded_argv(
        argv=(sys.executable, str(parent)),
        working_directory=str(tmp_path),
        timeout_ms=1000,
        max_output_chars=1000,
    )

    assert pid_file.exists()
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    assert result.exit_code == 124
    assert result.timed_out
    assert not _pid_alive(child_pid)


def test_process_tool_propagates_lifecycle_stop_to_owned_tree(tmp_path: Path) -> None:
    pid_file = tmp_path / "descendant.pid"
    child = tmp_path / "child.py"
    parent = tmp_path / "parent.py"
    child.write_text(
        "import time\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    parent.write_text(
        "import pathlib, subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, {str(child)!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL, shell=False)\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid), encoding='utf-8')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    cancelled = Event()
    controller = ExecutionLifecycleController.start(
        execution_id=uuid4(),
        timeout_ms=5000,
        cancellation_probe=lambda: "owner cancelled process"
        if cancelled.is_set()
        else None,
    )
    context = ToolExecutionContext(
        task_contract=cast(TaskContract, object()),
        timeout_ms=5000,
        max_output_chars=1000,
        working_directory=str(tmp_path),
        lifecycle=controller.lifecycle,
    )
    outputs: list[ToolExecutionOutput] = []
    errors: list[BaseException] = []

    def execute() -> None:
        try:
            outputs.append(
                RunArgvTool().execute(
                    {"argv": [sys.executable, str(parent)]},
                    context,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    worker = Thread(target=execute)
    worker.start()

    deadline = time.time() + 5
    while not pid_file.exists() and time.time() < deadline:
        time.sleep(0.01)
    assert pid_file.exists()

    child_pid = int(pid_file.read_text(encoding="utf-8"))
    cancelled.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert errors == []
    assert len(outputs) == 1
    assert not _pid_alive(child_pid)
    settlement = controller.settle_handler(failed=outputs[0].exit_code != 0)
    assert settlement is ExecutionSettlement.CANCELLED


def test_runner_rejects_inline_python() -> None:
    with pytest.raises(SafeProcessError, match="inline Python"):
        run_bounded_argv(
            argv=(sys.executable, "-c", "print('no')"),
            working_directory=".",
            timeout_ms=1000,
            max_output_chars=1000,
        )


def test_runner_output_limit_kills_surviving_descendant(tmp_path):
    pid_file = tmp_path / "descendant.pid"
    child = tmp_path / "output_child.py"
    parent = tmp_path / "output_parent.py"

    child.write_text(
        "import os, pathlib, sys, time\n"
        f"pathlib.Path({str(pid_file)!r}).write_text("
        "str(os.getpid()), encoding='utf-8')\n"
        "while True:\n"
        "    sys.stdout.write('X' * 4096)\n"
        "    sys.stdout.flush()\n"
        "    time.sleep(0.002)\n",
        encoding="utf-8",
    )

    parent.write_text(
        "import subprocess, sys\n"
        f"subprocess.Popen([sys.executable, {str(child)!r}], "
        "stdin=subprocess.DEVNULL, "
        "stdout=None, "
        "stderr=None, "
        "shell=False)\n",
        encoding="utf-8",
    )

    result = run_bounded_argv(
        argv=(
            sys.executable,
            str(parent),
        ),
        working_directory=str(tmp_path),
        timeout_ms=5000,
        max_output_chars=64,
    )

    assert pid_file.exists()

    child_pid = int(
        pid_file.read_text(
            encoding="utf-8",
        )
    )

    assert result.exit_code == 125
    assert result.output_limit_exceeded
    assert not result.timed_out
    assert not _pid_alive(child_pid)


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows Job Object contract",
)
def test_windows_job_setup_failure_never_releases_user_argv(
    tmp_path,
    monkeypatch,
):
    import luna.shell.runner as runner_mod

    marker = tmp_path / "user-code-ran.txt"
    target = tmp_path / "target.py"

    target.write_text(
        "import pathlib\n"
        f"pathlib.Path({str(marker)!r}).write_text("
        "'ran', encoding='utf-8')\n",
        encoding="utf-8",
    )

    class _ForcedJobFailure:
        def __init__(self, process):
            del process
            raise OSError(
                5,
                "forced Job setup failure",
            )

    monkeypatch.setattr(
        runner_mod,
        "_WindowsJob",
        _ForcedJobFailure,
    )

    with pytest.raises(
        SafeProcessError,
        match="process tree ownership setup failed",
    ):
        run_bounded_argv(
            argv=(
                sys.executable,
                str(target),
            ),
            working_directory=str(tmp_path),
            timeout_ms=2000,
            max_output_chars=1000,
        )

    assert not marker.exists()


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows Job Object contract",
)
def test_windows_owned_tree_prevents_breakaway_escape(
    tmp_path,
):
    status_file = tmp_path / "breakaway.status"
    pid_file = tmp_path / "breakaway.pid"

    child = tmp_path / "breakaway_child.py"
    parent = tmp_path / "breakaway_parent.py"

    child.write_text(
        "import time\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    parent.write_text(
        "import pathlib, subprocess, sys\n"
        f"status = pathlib.Path({str(status_file)!r})\n"
        f"pid_file = pathlib.Path({str(pid_file)!r})\n"
        "try:\n"
        f"    child = subprocess.Popen("
        f"[sys.executable, {str(child)!r}], "
        "stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL, "
        "shell=False, "
        "creationflags=("
        "subprocess.CREATE_NO_WINDOW | "
        "subprocess.CREATE_BREAKAWAY_FROM_JOB"
        "))\n"
        "except OSError as exc:\n"
        "    status.write_text("
        "f'DENIED:{getattr(exc, \"winerror\", None)}', "
        "encoding='utf-8')\n"
        "else:\n"
        "    pid_file.write_text("
        "str(child.pid), encoding='utf-8')\n"
        "    status.write_text("
        "'CREATED', encoding='utf-8')\n",
        encoding="utf-8",
    )

    result = run_bounded_argv(
        argv=(
            sys.executable,
            str(parent),
        ),
        working_directory=str(tmp_path),
        timeout_ms=3000,
        max_output_chars=1000,
    )

    assert status_file.exists()

    status = status_file.read_text(
        encoding="utf-8",
    )

    if status.startswith("DENIED:"):
        # Safe OS behavior A:
        # Windows refuses the explicit breakaway request.
        assert result.exit_code == 0
        assert not result.timed_out
        assert not result.output_limit_exceeded
        assert not pid_file.exists()
        return

    # Safe OS behavior B:
    # creation succeeds, but the descendant remains inside
    # Luna's owned Job. The runner therefore waits for tree
    # quiescence, times out, terminates the whole tree, and
    # returns only after the descendant is gone.
    assert status == "CREATED"
    assert pid_file.exists()

    child_pid = int(
        pid_file.read_text(
            encoding="utf-8",
        )
    )

    child_alive = _pid_alive(child_pid)

    if child_alive:
        subprocess.run(
            [
                "taskkill",
                "/PID",
                str(child_pid),
                "/T",
                "/F",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

        pytest.fail(
            "breakaway descendant survived runner return"
        )

    assert result.exit_code == 124
    assert result.timed_out
    assert not result.output_limit_exceeded


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows handle/thread ownership contract",
)
def test_repeated_process_execution_does_not_leak_handles_or_threads(
    tmp_path,
):
    import ctypes
    import gc
    import threading

    kernel32 = ctypes.WinDLL(
        "kernel32",
        use_last_error=True,
    )

    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p

    kernel32.GetProcessHandleCount.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]

    kernel32.GetProcessHandleCount.restype = ctypes.c_int

    def handle_count():
        value = ctypes.c_ulong()

        ok = kernel32.GetProcessHandleCount(
            kernel32.GetCurrentProcess(),
            ctypes.byref(value),
        )

        if not ok:
            raise OSError(
                ctypes.get_last_error(),
                "GetProcessHandleCount failed",
            )

        return int(value.value)

    target = tmp_path / "noop.py"

    target.write_text(
        "print('ok')\n",
        encoding="utf-8",
    )

    gc.collect()
    time.sleep(0.10)

    handles_before = handle_count()
    threads_before = len(
        threading.enumerate()
    )

    for _ in range(20):
        result = run_bounded_argv(
            argv=(
                sys.executable,
                str(target),
            ),
            working_directory=str(tmp_path),
            timeout_ms=2000,
            max_output_chars=1000,
        )

        assert result.exit_code == 0
        assert result.stdout.strip() == "ok"
        assert not result.timed_out
        assert not result.output_limit_exceeded

    gc.collect()
    time.sleep(0.25)

    handles_after = handle_count()

    threads_after = len(
        threading.enumerate()
    )

    handle_delta = (
        handles_after
        - handles_before
    )

    thread_delta = (
        threads_after
        - threads_before
    )

    assert handle_delta <= 8
    assert thread_delta <= 0
