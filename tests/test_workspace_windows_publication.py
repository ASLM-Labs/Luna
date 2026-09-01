from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

import luna.workspace.windows_publication as wp

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="Windows native publication regression suite",
)


_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_TOKEN_QUERY = 0x0008
_TOKEN_USER_CLASS = 1

_FILE_WRITE_DATA = 0x00000002
_READ_CONTROL = 0x00020000
_WRITE_DAC = 0x00040000
_SYNCHRONIZE = 0x00100000

_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_FILE_SHARE_DELETE = 0x4
_SHARE_ALL = (
    _FILE_SHARE_READ
    | _FILE_SHARE_WRITE
    | _FILE_SHARE_DELETE
)

_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x80

_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004

_DENY_ACCESS = 3
_NO_INHERITANCE = 0
_NO_MULTIPLE_TRUSTEE = 0
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_USER = 1

_ERROR_ACCESS_DENIED = 5


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", wt.DWORD),
    ]


class _TokenUser(ctypes.Structure):
    _fields_ = [
        ("User", _SidAndAttributes),
    ]


class _TrusteeW(ctypes.Structure):
    pass


_TrusteeW._fields_ = [
    ("pMultipleTrustee", ctypes.POINTER(_TrusteeW)),
    ("MultipleTrusteeOperation", ctypes.c_int),
    ("TrusteeForm", ctypes.c_int),
    ("TrusteeType", ctypes.c_int),
    ("ptstrName", wt.LPWSTR),
]


class _ExplicitAccessW(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", wt.DWORD),
        ("grfAccessMode", ctypes.c_int),
        ("grfInheritance", wt.DWORD),
        ("Trustee", _TrusteeW),
    ]


class _SecurityApis:
    def __init__(self) -> None:
        win_dll = getattr(ctypes, "WinDLL", None)

        if win_dll is None:
            raise RuntimeError(
                "ctypes.WinDLL unavailable"
            )

        kernel32 = win_dll(
            "kernel32",
            use_last_error=True,
        )
        advapi32 = win_dll(
            "advapi32",
            use_last_error=True,
        )

        self.create_file = kernel32.CreateFileW
        self.create_file.argtypes = [
            wt.LPCWSTR,
            wt.DWORD,
            wt.DWORD,
            ctypes.c_void_p,
            wt.DWORD,
            wt.DWORD,
            wt.HANDLE,
        ]
        self.create_file.restype = wt.HANDLE

        self.close_handle = kernel32.CloseHandle
        self.close_handle.argtypes = [
            wt.HANDLE
        ]
        self.close_handle.restype = wt.BOOL

        self.get_current_process = (
            kernel32.GetCurrentProcess
        )
        self.get_current_process.restype = (
            wt.HANDLE
        )

        self.local_free = kernel32.LocalFree
        self.local_free.argtypes = [
            ctypes.c_void_p
        ]
        self.local_free.restype = (
            ctypes.c_void_p
        )

        self.open_process_token = (
            advapi32.OpenProcessToken
        )
        self.open_process_token.argtypes = [
            wt.HANDLE,
            wt.DWORD,
            ctypes.POINTER(wt.HANDLE),
        ]
        self.open_process_token.restype = (
            wt.BOOL
        )

        self.get_token_information = (
            advapi32.GetTokenInformation
        )
        self.get_token_information.argtypes = [
            wt.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wt.DWORD,
            ctypes.POINTER(wt.DWORD),
        ]
        self.get_token_information.restype = (
            wt.BOOL
        )

        self.get_security_info = (
            advapi32.GetSecurityInfo
        )
        self.get_security_info.argtypes = [
            wt.HANDLE,
            ctypes.c_int,
            wt.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.get_security_info.restype = (
            wt.DWORD
        )

        self.set_security_info = (
            advapi32.SetSecurityInfo
        )
        self.set_security_info.argtypes = [
            wt.HANDLE,
            ctypes.c_int,
            wt.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.set_security_info.restype = (
            wt.DWORD
        )

        self.set_entries_in_acl = (
            advapi32.SetEntriesInAclW
        )
        self.set_entries_in_acl.argtypes = [
            wt.ULONG,
            ctypes.POINTER(
                _ExplicitAccessW
            ),
            ctypes.c_void_p,
            ctypes.POINTER(
                ctypes.c_void_p
            ),
        ]
        self.set_entries_in_acl.restype = (
            wt.DWORD
        )


def _close(
    api: _SecurityApis,
    handle: int | None,
) -> None:
    if handle not in (
        None,
        0,
        _INVALID_HANDLE_VALUE,
    ):
        api.close_handle(handle)


def _last_error(name: str) -> OSError:
    return OSError(
        ctypes.get_last_error(),
        name,
    )


def _current_user_sid(
    api: _SecurityApis,
) -> tuple[object, int]:
    token = wt.HANDLE()

    if not api.open_process_token(
        api.get_current_process(),
        _TOKEN_QUERY,
        ctypes.byref(token),
    ):
        raise _last_error(
            "OpenProcessToken"
        )

    try:
        needed = wt.DWORD()

        api.get_token_information(
            token,
            _TOKEN_USER_CLASS,
            None,
            0,
            ctypes.byref(needed),
        )

        backing = (
            ctypes.create_string_buffer(
                needed.value
            )
        )

        if not api.get_token_information(
            token,
            _TOKEN_USER_CLASS,
            backing,
            needed.value,
            ctypes.byref(needed),
        ):
            raise _last_error(
                "GetTokenInformation"
            )

        user = ctypes.cast(
            backing,
            ctypes.POINTER(_TokenUser),
        ).contents

        if user.User.Sid is None:
            raise RuntimeError(
                "current user SID is missing"
            )

        return (
            backing,
            int(user.User.Sid),
        )

    finally:
        _close(
            api,
            token.value,
        )


def _add_deny_write_data(
    path: Path,
) -> None:
    api = _SecurityApis()

    handle = api.create_file(
        str(path),
        _READ_CONTROL | _WRITE_DAC,
        _SHARE_ALL,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )

    if handle == _INVALID_HANDLE_VALUE:
        raise _last_error(
            "CreateFileW(DACL target)"
        )

    old_sd = ctypes.c_void_p()
    old_dacl = ctypes.c_void_p()
    new_dacl = ctypes.c_void_p()

    try:
        result = api.get_security_info(
            handle,
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(old_dacl),
            None,
            ctypes.byref(old_sd),
        )

        if result != 0:
            raise OSError(
                result,
                "GetSecurityInfo",
            )

        sid_backing, sid = (
            _current_user_sid(api)
        )

        explicit = _ExplicitAccessW()
        explicit.grfAccessPermissions = (
            _FILE_WRITE_DATA
        )
        explicit.grfAccessMode = (
            _DENY_ACCESS
        )
        explicit.grfInheritance = (
            _NO_INHERITANCE
        )

        explicit.Trustee.pMultipleTrustee = (
            None
        )
        explicit.Trustee.MultipleTrusteeOperation = (
            _NO_MULTIPLE_TRUSTEE
        )
        explicit.Trustee.TrusteeForm = (
            _TRUSTEE_IS_SID
        )
        explicit.Trustee.TrusteeType = (
            _TRUSTEE_IS_USER
        )
        explicit.Trustee.ptstrName = (
            ctypes.cast(
                ctypes.c_void_p(sid),
                wt.LPWSTR,
            )
        )

        result = api.set_entries_in_acl(
            1,
            ctypes.byref(explicit),
            old_dacl,
            ctypes.byref(new_dacl),
        )

        _ = sid_backing

        if result != 0:
            raise OSError(
                result,
                "SetEntriesInAclW",
            )

        result = api.set_security_info(
            handle,
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            new_dacl,
            None,
        )

        if result != 0:
            raise OSError(
                result,
                "SetSecurityInfo",
            )

    finally:
        if new_dacl.value is not None:
            api.local_free(
                new_dacl
            )

        if old_sd.value is not None:
            api.local_free(
                old_sd
            )

        _close(
            api,
            handle,
        )


def _direct_write_blocked(
    path: Path,
) -> bool:
    api = _SecurityApis()

    ctypes.set_last_error(0)

    handle = api.create_file(
        str(path),
        _FILE_WRITE_DATA
        | _SYNCHRONIZE,
        _SHARE_ALL,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )

    if handle != _INVALID_HANDLE_VALUE:
        _close(
            api,
            handle,
        )
        return False

    error = ctypes.get_last_error()

    if error != _ERROR_ACCESS_DENIED:
        raise OSError(
            error,
            "unexpected direct-write result",
        )

    return True


def _junction(
    link: Path,
    target: Path,
) -> None:
    result = subprocess.run(
        [
            "cmd.exe",
            "/d",
            "/c",
            "mklink",
            "/J",
            str(link),
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "junction creation failed: "
            f"{result.stdout.strip()} "
            f"{result.stderr.strip()}"
        )


def _remove_junction(
    path: Path,
) -> None:
    if (
        hasattr(path, "is_junction")
        and path.is_junction()
    ):
        os.rmdir(path)


def test_existing_replacement_preserves_content_mode_and_dacl(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"
    target.write_bytes(
        b"BEFORE"
    )

    with wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/module.py",
    ) as authority:
        before = (
            authority.observe_target()
        )

        assert before.existed
        assert (
            before.content
            == b"BEFORE"
        )
        assert before.mode == 0o666
        assert (
            before.security_descriptor
            is not None
        )
        assert (
            before.dacl_protected
            is not None
        )

        stage = (
            authority.create_stage(
                source=before,
            )
        )

        try:
            stage.write_bytes(
                b"AFTER"
            )

            result = stage.publish(
                authority.leaf_name,
                replace=True,
            )

            assert (
                result.state
                is wp.PublicationState.PUBLISHED
            )

        finally:
            stage.close()

        after = (
            authority.observe_target()
        )

        assert (
            after.content
            == b"AFTER"
        )
        assert (
            after.mode
            == before.mode
        )
        assert (
            after.dacl
            == before.dacl
        )
        assert (
            after.dacl_protected
            == before.dacl_protected
        )


def test_bounded_target_token_observation_accepts_exact_limit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"
    content = b"LUNA"
    target.write_bytes(content)

    with wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/module.py",
    ) as authority:
        state = authority.observe_target_with_token(
            max_bytes=len(content),
        )

    assert state is not None
    assert state.observation.content == content
    assert state.token.size_bytes == len(content)
    assert (
        state.token.content_sha256
        == sha256(content).hexdigest()
    )


def test_bounded_target_token_observation_rejects_oversize_without_mutation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"
    content = b"LUNA!"
    target.write_bytes(content)

    with wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/module.py",
    ) as authority, pytest.raises(
        wp.WindowsObservationLimitError,
        match="exceeds bounded observation limit",
    ):
        authority.observe_target_with_token(
            max_bytes=len(content) - 1,
        )

    assert target.read_bytes() == content


def test_bounded_target_token_observation_reports_missing_without_claiming_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    with wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/missing.py",
    ) as authority:
        state = authority.observe_target_with_token(
            max_bytes=1,
        )

    assert state is None


def test_new_file_uses_bound_parent_and_inherited_security(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    with wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/new.txt",
    ) as authority:
        before = (
            authority.observe_target()
        )

        assert not before.existed

        stage = (
            authority.create_stage()
        )

        try:
            stage.write_bytes(
                b"NEW"
            )

            result = stage.publish(
                authority.leaf_name,
                replace=False,
            )

            assert (
                result.state
                is wp.PublicationState.PUBLISHED
            )

        finally:
            stage.close()

        after = (
            authority.observe_target()
        )

        assert (
            after.content
            == b"NEW"
        )
        assert (
            after.security_descriptor
            is not None
        )
        assert (
            after.dacl_protected
            is not None
        )


def test_readonly_existing_target_is_refused_before_stage_creation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = (
        source / "readonly.txt"
    )
    target.write_bytes(
        b"KEEP"
    )
    os.chmod(
        target,
        0o444,
    )

    try:
        with wp.BoundPublicationParent.bind(
            str(tmp_path),
            "src/readonly.txt",
        ) as authority:
            before = (
                authority.observe_target()
            )

            assert before.existed
            assert (
                before.mode
                == 0o444
            )

            with pytest.raises(
                wp.WindowsPublicationError,
                match=(
                    "read-only target "
                    "cannot be replaced"
                ),
            ):
                authority.create_stage(
                    source=before,
                )

            assert (
                authority.observe_target().content
                == b"KEEP"
            )

            assert not list(
                source.glob(
                    ".luna-stage-*"
                )
            )

    finally:
        os.chmod(
            target,
            0o666,
        )


def test_restrictive_dacl_and_bound_namespace_survive_prior_drift(
    tmp_path: Path,
) -> None:
    workspace = (
        tmp_path / "workspace"
    )
    source = (
        workspace / "src"
    )
    displaced = (
        workspace / "src-original"
    )
    outside = (
        tmp_path / "outside"
    )

    source.mkdir(
        parents=True
    )
    outside.mkdir()

    target = (
        source / "module.py"
    )
    target.write_bytes(
        b"BEFORE"
    )

    _add_deny_write_data(
        target
    )

    assert _direct_write_blocked(
        target
    )

    authority = (
        wp.BoundPublicationParent.bind(
            str(workspace),
            "src/module.py",
        )
    )

    stage: wp.StagedFile | None = (
        None
    )

    try:
        before = (
            authority.observe_target()
        )

        assert (
            before.content
            == b"BEFORE"
        )
        assert (
            before.security_descriptor
            is not None
        )
        assert (
            before.dacl
            is not None
        )

        source.rename(
            displaced
        )
        _junction(
            source,
            outside,
        )

        outside_target = (
            outside / "module.py"
        )
        outside_target.write_bytes(
            b"OUTSIDE-FOREIGN"
        )

        stage = (
            authority.create_stage(
                source=before,
            )
        )

        stage.write_bytes(
            b"AFTER"
        )

        result = stage.publish(
            authority.leaf_name,
            replace=True,
        )

        assert (
            result.state
            is wp.PublicationState.PUBLISHED
        )

        stage.close()
        stage = None

        after = (
            authority.observe_target()
        )

        assert (
            after.content
            == b"AFTER"
        )
        assert (
            after.dacl
            == before.dacl
        )
        assert (
            after.dacl_protected
            == before.dacl_protected
        )
        assert (
            outside_target.read_bytes()
            == b"OUTSIDE-FOREIGN"
        )
        assert _direct_write_blocked(
            displaced / "module.py"
        )

    finally:
        if stage is not None:
            stage.close()

        authority.close()

        _remove_junction(
            source
        )


def test_no_clobber_collision_preserves_competitor_and_foreign_namespace(
    tmp_path: Path,
) -> None:
    workspace = (
        tmp_path / "workspace"
    )
    source = (
        workspace / "src"
    )
    displaced = (
        workspace / "src-original"
    )
    outside = (
        tmp_path / "outside"
    )

    source.mkdir(
        parents=True
    )
    outside.mkdir()

    authority = (
        wp.BoundPublicationParent.bind(
            str(workspace),
            "src/new.txt",
        )
    )

    stage: wp.StagedFile | None = (
        None
    )

    try:
        assert not (
            authority
            .observe_target()
            .existed
        )

        source.rename(
            displaced
        )
        _junction(
            source,
            outside,
        )

        stage = (
            authority.create_stage()
        )
        stage.write_bytes(
            b"LUNA-CANDIDATE"
        )

        outside_stage = (
            outside / stage.name
        )
        outside_stage.write_bytes(
            b"OUTSIDE-STAGE"
        )

        outside_target = (
            outside / "new.txt"
        )
        outside_target.write_bytes(
            b"OUTSIDE-TARGET"
        )

        competitor = (
            displaced / "new.txt"
        )
        competitor.write_bytes(
            b"BOUND-COMPETITOR"
        )

        result = stage.publish(
            authority.leaf_name,
            replace=False,
        )

        assert (
            result.state
            is wp.PublicationState.COLLISION
        )

        stage_name = stage.name

        stage.discard()
        stage = None

        assert (
            authority
            .observe_target()
            .content
            == b"BOUND-COMPETITOR"
        )
        assert not (
            displaced
            / stage_name
        ).exists()
        assert (
            outside_stage.read_bytes()
            == b"OUTSIDE-STAGE"
        )
        assert (
            outside_target.read_bytes()
            == b"OUTSIDE-TARGET"
        )

    finally:
        if stage is not None:
            stage.close()

        authority.close()

        _remove_junction(
            source
        )


def test_readonly_private_stage_can_be_disposed_by_handle(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path / "src"
    )
    source.mkdir()

    with wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/new.txt",
    ) as authority:
        stage = (
            authority.create_stage()
        )
        stage.write_bytes(
            b"PRIVATE"
        )

        handle = (
            stage._require_handle()
        )

        wp._set_file_mode(
            handle,
            0o444,
        )

        assert (
            wp._file_mode(handle)
            == 0o444
        )

        stage_name = stage.name

        wp._discard(
            handle,
            ignore_readonly=True,
        )

        stage.close()

        assert not (
            source / stage_name
        ).exists()


def test_unknown_publication_state_forbids_stage_discard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (
        tmp_path / "src"
    )
    source.mkdir()

    authority = (
        wp.BoundPublicationParent.bind(
            str(tmp_path),
            "src/new.txt",
        )
    )

    stage = (
        authority.create_stage()
    )

    try:
        stage.write_bytes(
            b"AMBIGUOUS"
        )

        def unknown_publish(
            stage_handle: int,
            parent_handle: int,
            target_name: str,
            *,
            replace: bool,
        ) -> wp.PublicationResult:
            del (
                stage_handle,
                parent_handle,
                target_name,
                replace,
            )

            return wp.PublicationResult(
                wp.PublicationState.UNKNOWN,
                0xC0000001,
            )

        monkeypatch.setattr(
            wp,
            "_publish",
            unknown_publish,
        )

        result = stage.publish(
            authority.leaf_name,
            replace=False,
        )

        assert (
            result.state
            is wp.PublicationState.UNKNOWN
        )

        with pytest.raises(
            wp.WindowsPublicationError,
            match="not safe to discard",
        ):
            stage.discard()

    finally:
        stage.close()
        authority.close()


def test_junction_component_is_rejected_as_reparse_point(
    tmp_path: Path,
) -> None:
    outside = (
        tmp_path / "outside"
    )
    source = (
        tmp_path / "src"
    )

    outside.mkdir()

    _junction(
        source,
        outside,
    )

    try:
        with pytest.raises(
            wp.WindowsPublicationError,
            match="reparse point",
        ):
            (
                wp.BoundPublicationParent
                .bind(
                    str(tmp_path),
                    "src/new.txt",
                )
            )

    finally:
        _remove_junction(
            source
        )


def test_published_existing_rollback_truncates_and_survives_namespace_drift(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src"
    displaced = workspace / "src-original"
    outside = tmp_path / "outside"

    workspace.mkdir()
    source.mkdir()
    outside.mkdir()

    target = source / "module.py"
    original_content = b"OLD"
    candidate_content = (
        b"CANDIDATE-CONTENT-THAT-IS-DELIBERATELY-LONGER-"
        b"THAN-THE-ORIGINAL"
    )
    target.write_bytes(original_content)

    authority = wp.BoundPublicationParent.bind(
        str(workspace),
        "src/module.py",
    )
    stage = None

    try:
        before = authority.observe_target()

        assert before.existed
        assert before.content == original_content
        assert before.mode is not None
        assert before.security_descriptor is not None
        assert before.dacl_protected is not None
        assert len(candidate_content) > len(original_content)

        source.rename(displaced)
        _junction(
            source,
            outside,
        )

        outside_target = outside / "module.py"
        outside_target.write_bytes(
            b"OUTSIDE-FOREIGN"
        )

        stage = authority.create_stage(
            source=before,
        )
        stage.write_bytes(
            candidate_content
        )

        result = stage.publish(
            authority.leaf_name,
            replace=True,
        )

        assert (
            result.state
            is wp.PublicationState.PUBLISHED
        )

        published = (
            stage.observe_published()
        )

        assert (
            published.content
            == candidate_content
        )
        assert (
            published.mode
            == before.mode
        )
        assert (
            published.dacl
            == before.dacl
        )
        assert (
            published.dacl_protected
            == before.dacl_protected
        )

        rolled_back = (
            stage.rollback_published(
                before
            )
        )
        stage = None

        assert rolled_back.existed
        assert (
            rolled_back.content
            == original_content
        )
        assert (
            rolled_back.mode
            == before.mode
        )
        assert (
            rolled_back.dacl
            == before.dacl
        )
        assert (
            rolled_back.dacl_protected
            == before.dacl_protected
        )

        bound_target = (
            displaced / "module.py"
        )

        assert (
            bound_target.read_bytes()
            == original_content
        )
        assert (
            bound_target.stat().st_size
            == len(original_content)
        )
        assert (
            outside_target.read_bytes()
            == b"OUTSIDE-FOREIGN"
        )

    finally:
        if stage is not None:
            stage.close()

        authority.close()
        _remove_junction(
            source
        )


def test_published_create_rollback_survives_namespace_drift(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src"
    displaced = workspace / "src-original"
    outside = tmp_path / "outside"

    workspace.mkdir()
    source.mkdir()
    outside.mkdir()

    authority = wp.BoundPublicationParent.bind(
        str(workspace),
        "src/new.txt",
    )
    stage = None

    try:
        before = authority.observe_target()

        assert not before.existed

        source.rename(displaced)
        _junction(
            source,
            outside,
        )

        outside_target = (
            outside / "new.txt"
        )
        outside_target.write_bytes(
            b"OUTSIDE-FOREIGN"
        )

        stage = authority.create_stage()
        stage.write_bytes(
            b"BOUND-CREATED"
        )

        result = stage.publish(
            authority.leaf_name,
            replace=False,
        )

        assert (
            result.state
            is wp.PublicationState.PUBLISHED
        )
        assert (
            stage.observe_published().content
            == b"BOUND-CREATED"
        )

        rolled_back = (
            stage.rollback_published(
                before
            )
        )
        stage = None

        assert not rolled_back.existed
        assert not (
            displaced / "new.txt"
        ).exists()
        assert (
            outside_target.read_bytes()
            == b"OUTSIDE-FOREIGN"
        )

    finally:
        if stage is not None:
            stage.close()

        authority.close()
        _remove_junction(
            source
        )


def test_collision_cannot_be_treated_as_published_rollback(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    authority = wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/new.txt",
    )
    stage = None

    try:
        before = authority.observe_target()

        assert not before.existed

        stage = authority.create_stage()
        stage.write_bytes(
            b"CANDIDATE"
        )

        competitor = source / "new.txt"
        competitor.write_bytes(
            b"BOUND-COMPETITOR"
        )

        result = stage.publish(
            authority.leaf_name,
            replace=False,
        )

        assert (
            result.state
            is wp.PublicationState.COLLISION
        )

        with pytest.raises(
            wp.WindowsPublicationError,
            match="requires a confirmed PUBLISHED state",
        ):
            stage.rollback_published(
                before
            )

        assert (
            competitor.read_bytes()
            == b"BOUND-COMPETITOR"
        )

        stage.discard()
        stage = None

        assert (
            competitor.read_bytes()
            == b"BOUND-COMPETITOR"
        )

    finally:
        if stage is not None:
            stage.close()

        authority.close()


def test_publish_exception_becomes_unknown_and_forbids_recovery_guess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    authority = wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/new.txt",
    )
    stage = authority.create_stage()

    try:
        before = authority.observe_target()

        assert not before.existed

        stage.write_bytes(
            b"AMBIGUOUS"
        )

        def failing_publish(
            stage_handle: int,
            parent_handle: int,
            target_name: str,
            *,
            replace: bool,
        ) -> wp.PublicationResult:
            del (
                stage_handle,
                parent_handle,
                target_name,
                replace,
            )

            raise wp.WindowsPublicationError(
                "forced publication uncertainty"
            )

        monkeypatch.setattr(
            wp,
            "_publish",
            failing_publish,
        )

        assert stage.publication_state is None

        with pytest.raises(
            wp.WindowsPublicationError,
            match="forced publication uncertainty",
        ):
            stage.publish(
                authority.leaf_name,
                replace=False,
            )

        assert (
            stage.publication_state
            is wp.PublicationState.UNKNOWN
        )

        with pytest.raises(
            wp.WindowsPublicationError,
            match="requires a confirmed PUBLISHED state",
        ):
            stage.rollback_published(
                before
            )

        with pytest.raises(
            wp.WindowsPublicationError,
            match="not safe to discard",
        ):
            stage.discard()

    finally:
        stage.close()
        authority.close()
def test_parent_create_collision_reopens_and_validates_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ctypes

    import luna.workspace.windows_publication as wp

    calls: list[
        tuple[str, int, str]
    ] = []

    missing_status = ctypes.c_int32(
        wp._STATUS_OBJECT_NAME_NOT_FOUND
    ).value

    collision_status = ctypes.c_int32(
        wp._STATUS_OBJECT_NAME_COLLISION
    ).value

    def missing(
        parent: int,
        name: str,
    ) -> tuple[int, int | None]:
        calls.append(
            ("initial-open", parent, name)
        )
        return missing_status, None

    def collide(
        parent: int,
        name: str,
    ) -> tuple[int, int | None]:
        calls.append(
            ("create", parent, name)
        )
        return collision_status, None

    def reopen(
        parent: int,
        name: str,
    ) -> int:
        calls.append(
            ("reopen", parent, name)
        )
        return 7001

    monkeypatch.setattr(
        wp,
        "_open_directory_once",
        missing,
    )

    monkeypatch.setattr(
        wp,
        "_create_directory_once",
        collide,
    )

    monkeypatch.setattr(
        wp,
        "_open_directory",
        reopen,
    )

    result = wp._open_or_create_directory(
        6001,
        "nested",
    )

    assert result == 7001

    assert calls == [
        (
            "initial-open",
            6001,
            "nested",
        ),
        (
            "create",
            6001,
            "nested",
        ),
        (
            "reopen",
            6001,
            "nested",
        ),
    ]
