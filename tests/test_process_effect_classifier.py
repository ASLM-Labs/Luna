from __future__ import annotations

import pytest

from luna.tools.process_effects import (
    ProcessEffect,
    classify_process_effects,
)


@pytest.mark.parametrize(
    "argv",
    (
        (),
        ("",),
        ("tool", ""),
        ("tool", "bad\x00arg"),
    ),
)
def test_invalid_argv_is_rejected(argv: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        classify_process_effects(argv)


def test_executable_normalization_is_path_and_case_stable() -> None:
    assessment = classify_process_effects(
        (r"C:\Program Files\Git\bin\GIT.EXE", "status"),
    )

    assert assessment.executable == "git"
    assert assessment.effects == (ProcessEffect.READ,)
    assert assessment.rule_id == "git:status"


@pytest.mark.parametrize(
    ("argv", "effects"),
    (
        (("git", "--version"), (ProcessEffect.READ,)),
        (("git", "status"), (ProcessEffect.READ,)),
        (("python", "--version"), (ProcessEffect.READ,)),
        (("where.exe", "git"), (ProcessEffect.READ,)),
        (("git", "init"), (ProcessEffect.WRITE,)),
        (("mkdir", "build"), (ProcessEffect.WRITE,)),
        (("find", ".", "-fprint", "out.txt"), (ProcessEffect.WRITE,)),
        (("curl", "https://example.com"), (ProcessEffect.NETWORK,)),
        (("git", "ls-remote", "origin"), (ProcessEffect.NETWORK,)),
        (("ssh", "host"), (ProcessEffect.NETWORK,)),
        (
            ("curl", "-o", "out.txt", "https://example.com"),
            (ProcessEffect.WRITE, ProcessEffect.NETWORK),
        ),
        (
            ("wget", "https://example.com/file"),
            (ProcessEffect.WRITE, ProcessEffect.NETWORK),
        ),
        (
            ("git", "clone", "https://example.com/repo.git"),
            (ProcessEffect.WRITE, ProcessEffect.NETWORK),
        ),
        (
            ("git", "fetch", "origin"),
            (ProcessEffect.WRITE, ProcessEffect.NETWORK),
        ),
        (
            ("scp", "host:file", "local.txt"),
            (ProcessEffect.WRITE, ProcessEffect.NETWORK),
        ),
        (
            ("unknown-tool.exe", "--anything"),
            (ProcessEffect.WRITE, ProcessEffect.NETWORK),
        ),
        (
            ("python", "script.py"),
            (ProcessEffect.WRITE, ProcessEffect.NETWORK),
        ),
        (
            ("find", ".", "-exec", "tool", "{}", ";"),
            (ProcessEffect.WRITE, ProcessEffect.NETWORK),
        ),
        (("pip", "install", "pkg"), (ProcessEffect.INSTALL,)),
        (
            ("python", "-m", "pip", "install", "pkg"),
            (ProcessEffect.INSTALL,),
        ),
        (("winget", "install", "pkg"), (ProcessEffect.INSTALL,)),
        (("npm", "install", "-g", "pkg"), (ProcessEffect.INSTALL,)),
        (("cargo", "install", "tool"), (ProcessEffect.INSTALL,)),
        (("rm", "-rf", "target"), (ProcessEffect.DESTRUCTIVE,)),
        (("shutdown", "/s"), (ProcessEffect.DESTRUCTIVE,)),
        (("diskpart.exe",), (ProcessEffect.DESTRUCTIVE,)),
        (("git", "clean", "-fd"), (ProcessEffect.DESTRUCTIVE,)),
        (
            ("git", "reset", "--hard", "HEAD"),
            (ProcessEffect.DESTRUCTIVE,),
        ),
        (
            ("git", "push", "--force", "origin", "main"),
            (ProcessEffect.NETWORK, ProcessEffect.DESTRUCTIVE),
        ),
        (("find", ".", "-delete"), (ProcessEffect.DESTRUCTIVE,)),
    ),
)
def test_classifier_effect_matrix(
    argv: tuple[str, ...],
    effects: tuple[ProcessEffect, ...],
) -> None:
    first = classify_process_effects(argv)
    second = classify_process_effects(argv)

    assert first.effects == effects
    assert second == first


def test_shell_launcher_remains_on_opaque_effect_floor() -> None:
    assessment = classify_process_effects(("cmd.exe", "/c", "echo", "blocked"))

    assert assessment.effects == (
        ProcessEffect.WRITE,
        ProcessEffect.NETWORK,
    )
    assert assessment.rule_id == "opaque:unknown"
