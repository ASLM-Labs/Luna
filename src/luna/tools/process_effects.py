"""Deterministic argv-derived process effect classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProcessEffect(StrEnum):
    """Conservative effects inferred from one exact argv."""

    READ = "READ"
    WRITE = "WRITE"
    NETWORK = "NETWORK"
    INSTALL = "INSTALL"
    DESTRUCTIVE = "DESTRUCTIVE"


_EFFECT_ORDER = {
    ProcessEffect.READ: 0,
    ProcessEffect.WRITE: 1,
    ProcessEffect.NETWORK: 2,
    ProcessEffect.INSTALL: 3,
    ProcessEffect.DESTRUCTIVE: 4,
}

_DESTRUCTIVE_BASES = {
    "bcdedit",
    "dd",
    "diskpart",
    "fdisk",
    "format",
    "halt",
    "mkfs",
    "parted",
    "poweroff",
    "reg",
    "regedit",
    "reboot",
    "rmdir",
    "rm",
    "runas",
    "sc",
    "sfdisk",
    "shutdown",
    "shred",
    "takeown",
    "unlink",
    "vssadmin",
    "wipefs",
}

_NETWORK_ONLY_BASES = {
    "curl",
    "nc",
    "ncat",
    "netcat",
    "socat",
    "ssh",
    "telnet",
}

_NETWORK_WRITE_BASES = {
    "ftp",
    "rsync",
    "scp",
    "sftp",
    "tftp",
    "wget",
}

_READ_ONLY_BASES = {
    "basename",
    "cat",
    "cut",
    "date",
    "diff",
    "dirname",
    "echo",
    "file",
    "grep",
    "head",
    "ls",
    "pwd",
    "readlink",
    "realpath",
    "sort",
    "stat",
    "systeminfo",
    "tail",
    "tasklist",
    "tr",
    "uniq",
    "wc",
    "where",
    "which",
    "whoami",
}

_WRITE_BASES = {
    "attrib",
    "chmod",
    "chown",
    "cp",
    "icacls",
    "ln",
    "mkdir",
    "mv",
    "tee",
    "touch",
}

_GIT_READ_VERBS = {
    "blame",
    "cat-file",
    "check-attr",
    "check-ignore",
    "count-objects",
    "describe",
    "diff",
    "fsck",
    "grep",
    "help",
    "log",
    "ls-files",
    "ls-tree",
    "name-rev",
    "reflog",
    "rev-list",
    "rev-parse",
    "shortlog",
    "show",
    "status",
    "var",
    "verify-commit",
    "version",
    "whatchanged",
}

_GIT_LOCAL_WRITE_VERBS = {
    "add",
    "checkout",
    "cherry-pick",
    "commit",
    "init",
    "merge",
    "rebase",
    "restore",
    "revert",
    "switch",
}

_GIT_NETWORK_WRITE_VERBS = {
    "clone",
    "fetch",
    "pull",
    "push",
}

_FIND_WRITE_FLAGS = {
    "-fls",
    "-fprintf",
    "-fprint",
    "-fprint0",
}

_FIND_EXEC_FLAGS = {
    "-exec",
    "-execdir",
    "-ok",
    "-okdir",
}

_SYSTEM_INSTALL_BASES = {
    "apt",
    "apt-get",
    "brew",
    "choco",
    "dnf",
    "flatpak",
    "scoop",
    "snap",
    "winget",
    "yum",
    "zypper",
}

_PIP_BASES = {"pip", "pip3", "pipx", "gem"}
_NODE_PACKAGE_BASES = {"npm", "pnpm"}
_INTERPRETER_BASES = {"perl", "ruby"}


@dataclass(frozen=True, slots=True)
class ProcessEffectAssessment:
    """Canonical effect result for one exact argv."""

    executable: str
    effects: tuple[ProcessEffect, ...]
    rule_id: str

    def __post_init__(self) -> None:
        if not self.executable:
            raise ValueError("process effect executable must not be blank")
        if not self.rule_id:
            raise ValueError("process effect rule_id must not be blank")
        if not self.effects:
            raise ValueError("process effect assessment requires at least one effect")
        if len(self.effects) != len(set(self.effects)):
            raise ValueError("process effects must be unique")
        canonical = tuple(sorted(self.effects, key=_EFFECT_ORDER.__getitem__))
        if self.effects != canonical:
            raise ValueError("process effects must be in canonical order")
        if ProcessEffect.READ in self.effects and len(self.effects) != 1:
            raise ValueError("READ must be exclusive")


def _basename(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].casefold()


def _normalized_executable(value: str) -> str:
    name = _basename(value)
    for suffix in (".exe", ".com"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _assessment(
    executable: str,
    rule_id: str,
    *effects: ProcessEffect,
) -> ProcessEffectAssessment:
    unique = set(effects)
    if not unique:
        unique.add(ProcessEffect.READ)
    if len(unique) > 1:
        unique.discard(ProcessEffect.READ)
    canonical = tuple(sorted(unique, key=_EFFECT_ORDER.__getitem__))
    return ProcessEffectAssessment(
        executable=executable,
        effects=canonical,
        rule_id=rule_id,
    )


def _has_any(args: tuple[str, ...], values: set[str]) -> bool:
    return any(value in values for value in args)


def _is_python_launcher(executable: str) -> bool:
    return (
        executable == "py"
        or executable == "python"
        or executable == "pythonw"
        or executable.startswith("python")
        or executable.startswith("pythonw")
    )


def _is_version_probe(executable: str, raw_args: tuple[str, ...]) -> bool:
    if len(raw_args) != 1:
        return False
    arg = raw_args[0]
    if _is_python_launcher(executable):
        return arg in {"--version", "-V", "-VV"}
    if executable in {"node", "nodejs", "ruby", "perl"}:
        return arg in {"--version", "-v"}
    if executable in _PIP_BASES:
        return arg in {"--version", "-V"}
    return False


def _is_install_command(executable: str, args: tuple[str, ...]) -> bool:
    has = set(args).__contains__
    first = args[0] if args else None

    if executable in {"apt", "apt-get", "dnf", "yum", "zypper"}:
        return has("install")
    if executable == "apk":
        return has("add")
    if executable in _SYSTEM_INSTALL_BASES:
        return has("install")
    if executable in _PIP_BASES:
        return first == "install"
    if executable in {"cargo", "go"}:
        return first == "install"
    if executable in _NODE_PACKAGE_BASES:
        return (
            first in {"add", "i", "install"}
            and ("-g" in args or "--global" in args)
        )
    if executable == "yarn":
        return first == "global"
    return False


def _classify_git(
    executable: str,
    raw_args: tuple[str, ...],
    args: tuple[str, ...],
) -> ProcessEffectAssessment:
    if raw_args == ("--version",):
        return _assessment(executable, "git:version", ProcessEffect.READ)
    if not args:
        return _assessment(
            executable,
            "git:opaque",
            ProcessEffect.WRITE,
            ProcessEffect.NETWORK,
        )

    verb = args[0]
    remaining = args[1:]

    if verb == "clean":
        return _assessment(
            executable,
            "git:clean",
            ProcessEffect.DESTRUCTIVE,
        )
    if verb == "reset" and "--hard" in remaining:
        return _assessment(
            executable,
            "git:reset-hard",
            ProcessEffect.DESTRUCTIVE,
        )
    if verb == "checkout" and _has_any(remaining, {"-f", "--force"}):
        return _assessment(
            executable,
            "git:checkout-force",
            ProcessEffect.DESTRUCTIVE,
        )
    if verb == "push" and any(
        value == "-f"
        or value == "--force"
        or value.startswith("--force-with-lease")
        for value in remaining
    ):
        return _assessment(
            executable,
            "git:push-force",
            ProcessEffect.NETWORK,
            ProcessEffect.DESTRUCTIVE,
        )
    if verb == "branch" and _has_any(remaining, {"-d", "--delete"}):
        return _assessment(
            executable,
            "git:branch-delete",
            ProcessEffect.DESTRUCTIVE,
        )
    if verb == "tag" and _has_any(remaining, {"-d", "--delete"}):
        return _assessment(
            executable,
            "git:tag-delete",
            ProcessEffect.DESTRUCTIVE,
        )

    if verb == "ls-remote":
        return _assessment(
            executable,
            "git:ls-remote",
            ProcessEffect.NETWORK,
        )
    if verb in _GIT_NETWORK_WRITE_VERBS:
        return _assessment(
            executable,
            f"git:{verb}",
            ProcessEffect.WRITE,
            ProcessEffect.NETWORK,
        )
    if verb in _GIT_READ_VERBS:
        return _assessment(executable, f"git:{verb}", ProcessEffect.READ)
    if verb in _GIT_LOCAL_WRITE_VERBS:
        return _assessment(executable, f"git:{verb}", ProcessEffect.WRITE)

    return _assessment(
        executable,
        "git:opaque",
        ProcessEffect.WRITE,
        ProcessEffect.NETWORK,
    )


def _classify_find(
    executable: str,
    args: tuple[str, ...],
) -> ProcessEffectAssessment:
    stripped = tuple(value.strip("'\"") for value in args)

    if "-delete" in stripped:
        return _assessment(
            executable,
            "find:delete",
            ProcessEffect.DESTRUCTIVE,
        )
    if _has_any(stripped, _FIND_WRITE_FLAGS):
        return _assessment(executable, "find:file-output", ProcessEffect.WRITE)
    if _has_any(stripped, _FIND_EXEC_FLAGS):
        return _assessment(
            executable,
            "find:nested-execution",
            ProcessEffect.WRITE,
            ProcessEffect.NETWORK,
        )
    return _assessment(executable, "find:read", ProcessEffect.READ)


def classify_process_effects(
    argv: tuple[str, ...],
) -> ProcessEffectAssessment:
    """Return the conservative deterministic effect floor for exact argv."""
    if not argv or len(argv) > 128:
        raise ValueError("process argv must contain between 1 and 128 entries")
    if any(not value or "\x00" in value for value in argv):
        raise ValueError("process argv entries must be non-empty and NUL-free")

    executable = _normalized_executable(argv[0])
    raw_args = argv[1:]
    args = tuple(value.casefold() for value in raw_args)

    if executable in _DESTRUCTIVE_BASES:
        return _assessment(
            executable,
            "destructive:base",
            ProcessEffect.DESTRUCTIVE,
        )

    if executable == "git":
        return _classify_git(executable, raw_args, args)

    if executable == "find":
        return _classify_find(executable, args)

    if (
        _is_python_launcher(executable)
        and len(args) >= 3
        and args[0] == "-m"
        and args[1] in _PIP_BASES
        and args[2] == "install"
    ):
        return _assessment(
            executable,
            "install:python-pip",
            ProcessEffect.INSTALL,
        )

    if _is_install_command(executable, args):
        return _assessment(
            executable,
            "install:package-manager",
            ProcessEffect.INSTALL,
        )

    if executable == "curl":
        writes_file = any(
            value in {"-o", "--output", "-O", "--remote-name", "--remote-name-all"}
            or value.startswith("--output=")
            or value.startswith("--output-dir=")
            for value in raw_args
        )
        if writes_file:
            return _assessment(
                executable,
                "network:curl-output",
                ProcessEffect.WRITE,
                ProcessEffect.NETWORK,
            )
        return _assessment(executable, "network:curl", ProcessEffect.NETWORK)

    if executable in _NETWORK_WRITE_BASES:
        return _assessment(
            executable,
            "network:transfer",
            ProcessEffect.WRITE,
            ProcessEffect.NETWORK,
        )
    if executable in _NETWORK_ONLY_BASES:
        return _assessment(
            executable,
            "network:direct",
            ProcessEffect.NETWORK,
        )

    if _is_version_probe(executable, raw_args):
        return _assessment(executable, "version-probe", ProcessEffect.READ)

    if (
        _is_python_launcher(executable)
        or executable in {"node", "nodejs", *_INTERPRETER_BASES}
    ):
        return _assessment(
            executable,
            "opaque:interpreter",
            ProcessEffect.WRITE,
            ProcessEffect.NETWORK,
        )

    if executable in _PIP_BASES or executable in {
        "cargo",
        "go",
        "npm",
        "pnpm",
        "yarn",
        *_SYSTEM_INSTALL_BASES,
    }:
        return _assessment(
            executable,
            "opaque:package-manager",
            ProcessEffect.WRITE,
            ProcessEffect.NETWORK,
        )

    if executable in _READ_ONLY_BASES:
        return _assessment(executable, "known:read", ProcessEffect.READ)

    if executable in _WRITE_BASES:
        return _assessment(executable, "known:write", ProcessEffect.WRITE)

    return _assessment(
        executable,
        "opaque:unknown",
        ProcessEffect.WRITE,
        ProcessEffect.NETWORK,
    )
