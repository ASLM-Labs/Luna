"""Private Windows authority-bound workspace publication primitives."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar
from uuid import uuid4

from luna.tools.paths import normalize_relative_path
from luna.workspace.models import WindowsAfterStateToken


class WindowsPublicationError(RuntimeError):
    """Raised when a Windows publication invariant cannot be satisfied."""


class PublicationState(StrEnum):
    """Mechanically observed state of one native publication attempt."""

    PUBLISHED = "PUBLISHED"
    COLLISION = "COLLISION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PublicationResult:
    """Publication result without guessing about unknown native failures."""

    state: PublicationState
    ntstatus: int

    @property
    def published(self) -> bool | None:
        if self.state is PublicationState.PUBLISHED:
            return True
        if self.state is PublicationState.COLLISION:
            return False
        return None


@dataclass(frozen=True)
class TargetObservation:
    """Regular-file state observed through one bound target handle."""

    existed: bool
    content: bytes | None = None
    mode: int | None = None
    security_descriptor: bytes | None = None
    dacl: bytes | None = None
    dacl_protected: bool | None = None


@dataclass(frozen=True)
class WindowsTargetState:
    """Handle-bound target observation plus durable after-state token."""

    observation: TargetObservation
    token: WindowsAfterStateToken


@dataclass(frozen=True)
class _SecurityState:
    """DACL-bearing state captured from one bound file handle."""

    descriptor: bytes
    dacl: bytes | None
    protected: bool


_HANDLE = ctypes.c_void_p
_ULONG = ctypes.c_uint32
_USHORT = ctypes.c_uint16
_DWORD = ctypes.c_uint32
_ULONGLONG = ctypes.c_uint64
_BYTE = ctypes.c_ubyte
_BOOLEAN = ctypes.c_ubyte


class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("Length", _USHORT),
        ("MaximumLength", _USHORT),
        ("Buffer", ctypes.c_wchar_p),
    ]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("Length", _ULONG),
        ("RootDirectory", _HANDLE),
        ("ObjectName", ctypes.POINTER(_UnicodeString)),
        ("Attributes", _ULONG),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]


class _IosbUnion(ctypes.Union):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("Status", ctypes.c_long),
        ("Pointer", ctypes.c_void_p),
    ]


class _IoStatusBlock(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("u", _IosbUnion), ("Information", ctypes.c_size_t)]


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = [("FileAttributes", _DWORD), ("ReparseTag", _DWORD)]


class _FileStandardInfo(ctypes.Structure):
    _fields_ = [
        ("AllocationSize", ctypes.c_int64),
        ("EndOfFile", ctypes.c_int64),
        ("NumberOfLinks", _DWORD),
        ("DeletePending", _BOOLEAN),
        ("Directory", _BOOLEAN),
    ]


class _FileBasicInfo(ctypes.Structure):
    _fields_ = [
        ("CreationTime", ctypes.c_int64),
        ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64),
        ("ChangeTime", ctypes.c_int64),
        ("FileAttributes", _DWORD),
    ]


class _FileId128(ctypes.Structure):
    _fields_ = [
        ("Identifier", _BYTE * 16),
    ]


class _FileIdInfo(ctypes.Structure):
    _fields_ = [
        ("VolumeSerialNumber", _ULONGLONG),
        ("FileId", _FileId128),
    ]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [
        ("AceCount", _DWORD),
        ("AclBytesInUse", _DWORD),
        ("AclBytesFree", _DWORD),
    ]


class _FileDispositionInformationEx(ctypes.Structure):
    _fields_ = [("Flags", _ULONG)]


class _FileRenameInformation(ctypes.Structure):
    _fields_ = [
        ("ReplaceIfExists", ctypes.c_ubyte),
        ("RootDirectory", _HANDLE),
        ("FileNameLength", _ULONG),
        ("FileName", ctypes.c_wchar * 1),
    ]


_RENAME_NAME_OFFSET = _FileRenameInformation.FileName.offset
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_FILE_READ_DATA = 0x00000001
_FILE_WRITE_DATA = 0x00000002
_FILE_ADD_FILE = 0x00000002
_FILE_TRAVERSE = 0x00000020
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_WRITE_ATTRIBUTES = 0x00000100
_DELETE = 0x00010000
_READ_CONTROL = 0x00020000
_SYNCHRONIZE = 0x00100000

_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_FILE_SHARE_DELETE = 0x4
_SHARE_ALL = _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE

_OPEN_EXISTING = 3
_FILE_BEGIN = 0
_FILE_ATTRIBUTE_READONLY = 0x00000001
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_OPEN_REPARSE_POINT = 0x00200000
_FILE_CREATE = 2
_OBJ_CASE_INSENSITIVE = 0x00000040

_FILE_BASIC_INFO_CLASS = 0
_FILE_STANDARD_INFO_CLASS = 1
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_FILE_ID_INFO_CLASS = 18

_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_ACL_SIZE_INFORMATION_CLASS = 2
_SE_DACL_PROTECTED = 0x1000
_SE_SELF_RELATIVE = 0x8000
_FILE_RENAME_INFORMATION_CLASS = 10
_FILE_DISPOSITION_INFORMATION_EX_CLASS = 64
_FILE_DISPOSITION_DELETE = 0x00000001
_FILE_DISPOSITION_IGNORE_READONLY_ATTRIBUTE = 0x00000010

_STATUS_SUCCESS = 0x00000000
_STATUS_OBJECT_NAME_NOT_FOUND = 0xC0000034
_STATUS_OBJECT_NAME_COLLISION = 0xC0000035


def _u32(value: int) -> int:
    return ctypes.c_uint32(value).value


def _status_text(value: int) -> str:
    return f"0x{_u32(value):08X}"


def _bind(library: Any, name: str, argtypes: list[Any], restype: Any) -> Any:
    function = getattr(library, name)
    function.argtypes = argtypes
    function.restype = restype
    return function


class _WindowsApi:
    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowsPublicationError("Windows publication backend is unavailable")
        win_dll = getattr(ctypes, "WinDLL", None)
        if win_dll is None:
            raise WindowsPublicationError("ctypes.WinDLL is unavailable")

        kernel32 = win_dll("kernel32", use_last_error=True)
        advapi32 = win_dll("advapi32", use_last_error=True)
        ntdll = win_dll("ntdll")
        self.create_file = _bind(
            kernel32,
            "CreateFileW",
            [
                ctypes.c_wchar_p,
                _DWORD,
                _DWORD,
                ctypes.c_void_p,
                _DWORD,
                _DWORD,
                _HANDLE,
            ],
            _HANDLE,
        )
        self.close_handle = _bind(kernel32, "CloseHandle", [_HANDLE], ctypes.c_int)
        self.read_file = _bind(
            kernel32,
            "ReadFile",
            [_HANDLE, ctypes.c_void_p, _DWORD, ctypes.POINTER(_DWORD), ctypes.c_void_p],
            ctypes.c_int,
        )
        self.write_file = _bind(
            kernel32,
            "WriteFile",
            [_HANDLE, ctypes.c_void_p, _DWORD, ctypes.POINTER(_DWORD), ctypes.c_void_p],
            ctypes.c_int,
        )
        self.flush = _bind(kernel32, "FlushFileBuffers", [_HANDLE], ctypes.c_int)
        self.set_file_pointer_ex = _bind(
            kernel32,
            "SetFilePointerEx",
            [
                _HANDLE,
                ctypes.c_longlong,
                ctypes.POINTER(ctypes.c_longlong),
                _DWORD,
            ],
            ctypes.c_int,
        )
        self.set_end_of_file = _bind(
            kernel32,
            "SetEndOfFile",
            [_HANDLE],
            ctypes.c_int,
        )
        self.get_info = _bind(
            kernel32,
            "GetFileInformationByHandleEx",
            [_HANDLE, ctypes.c_int, ctypes.c_void_p, _DWORD],
            ctypes.c_int,
        )
        self.set_info = _bind(
            kernel32,
            "SetFileInformationByHandle",
            [_HANDLE, ctypes.c_int, ctypes.c_void_p, _DWORD],
            ctypes.c_int,
        )
        self.local_free = _bind(
            kernel32,
            "LocalFree",
            [ctypes.c_void_p],
            ctypes.c_void_p,
        )
        self.get_security_info = _bind(
            advapi32,
            "GetSecurityInfo",
            [
                _HANDLE,
                ctypes.c_int,
                _DWORD,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
            ],
            _DWORD,
        )
        self.get_security_descriptor_length = _bind(
            advapi32,
            "GetSecurityDescriptorLength",
            [ctypes.c_void_p],
            _DWORD,
        )
        self.get_security_descriptor_control = _bind(
            advapi32,
            "GetSecurityDescriptorControl",
            [
                ctypes.c_void_p,
                ctypes.POINTER(_USHORT),
                ctypes.POINTER(_DWORD),
            ],
            ctypes.c_int,
        )
        self.get_acl_information = _bind(
            advapi32,
            "GetAclInformation",
            [
                ctypes.c_void_p,
                ctypes.c_void_p,
                _DWORD,
                ctypes.c_int,
            ],
            ctypes.c_int,
        )
        self.nt_open = _bind(
            ntdll,
            "NtOpenFile",
            [
                ctypes.POINTER(_HANDLE),
                _DWORD,
                ctypes.POINTER(_ObjectAttributes),
                ctypes.POINTER(_IoStatusBlock),
                _ULONG,
                _ULONG,
            ],
            ctypes.c_long,
        )
        self.nt_create = _bind(
            ntdll,
            "NtCreateFile",
            [
                ctypes.POINTER(_HANDLE),
                _DWORD,
                ctypes.POINTER(_ObjectAttributes),
                ctypes.POINTER(_IoStatusBlock),
                ctypes.c_void_p,
                _ULONG,
                _ULONG,
                _ULONG,
                _ULONG,
                ctypes.c_void_p,
                _ULONG,
            ],
            ctypes.c_long,
        )
        self.nt_set_info = _bind(
            ntdll,
            "NtSetInformationFile",
            [_HANDLE, ctypes.POINTER(_IoStatusBlock), ctypes.c_void_p, _ULONG, _ULONG],
            ctypes.c_long,
        )


_API: _WindowsApi | None = None


def _api() -> _WindowsApi:
    global _API
    if _API is None:
        _API = _WindowsApi()
    return _API


def _last_error(name: str) -> WindowsPublicationError:
    getter = getattr(ctypes, "get_last_error", None)
    code = 0 if getter is None else int(getter())
    return WindowsPublicationError(f"{name} failed with WinError {code}")


def _close(handle: int | None) -> None:
    if handle not in (None, 0, _INVALID_HANDLE_VALUE):
        _api().close_handle(_HANDLE(handle))


def _object_attributes(
    parent: int,
    name: str,
    *,
    security_descriptor: bytes | None = None,
) -> tuple[object, _UnicodeString, _ObjectAttributes]:
    name_backing = ctypes.create_unicode_buffer(name)
    encoded_length = len(name.encode("utf-16-le"))

    text = _UnicodeString(
        Length=encoded_length,
        MaximumLength=encoded_length + 2,
        Buffer=ctypes.cast(name_backing, ctypes.c_wchar_p),
    )

    security_backing: object | None = None
    security_pointer: ctypes.c_void_p | None = None

    if security_descriptor is not None:
        security_backing = ctypes.create_string_buffer(
            security_descriptor
        )
        security_pointer = ctypes.cast(
            security_backing,
            ctypes.c_void_p,
        )

    attrs = _ObjectAttributes(
        Length=ctypes.sizeof(_ObjectAttributes),
        RootDirectory=_HANDLE(parent),
        ObjectName=ctypes.pointer(text),
        Attributes=_OBJ_CASE_INSENSITIVE,
        SecurityDescriptor=security_pointer,
        SecurityQualityOfService=None,
    )

    return (name_backing, security_backing), text, attrs


def _reject_reparse(handle: int, *, subject: str) -> None:
    info = _FileAttributeTagInfo()
    if not _api().get_info(
        _HANDLE(handle),
        _FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise _last_error("GetFileInformationByHandleEx(FileAttributeTagInfo)")
    if info.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise WindowsPublicationError(
            f"{subject} is a reparse point (tag=0x{info.ReparseTag:08X})"
        )


def _require_directory(handle: int, *, subject: str) -> None:
    info = _FileStandardInfo()
    if not _api().get_info(
        _HANDLE(handle),
        _FILE_STANDARD_INFO_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise _last_error("GetFileInformationByHandleEx(FileStandardInfo)")
    if not info.Directory:
        raise WindowsPublicationError(f"{subject} is not a directory")


def _read_all(handle: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        buffer = ctypes.create_string_buffer(64 * 1024)
        count = _DWORD()
        if not _api().read_file(
            _HANDLE(handle),
            buffer,
            len(buffer),
            ctypes.byref(count),
            None,
        ):
            raise _last_error("ReadFile")
        if count.value == 0:
            return b"".join(chunks)
        chunks.append(buffer.raw[: count.value])


def _write_all(handle: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        piece = content[offset : offset + 64 * 1024]
        buffer = ctypes.create_string_buffer(piece)
        count = _DWORD()
        if not _api().write_file(
            _HANDLE(handle),
            buffer,
            len(piece),
            ctypes.byref(count),
            None,
        ):
            raise _last_error("WriteFile")
        if count.value == 0:
            raise WindowsPublicationError("WriteFile made zero-byte progress")
        offset += count.value
    if not _api().flush(_HANDLE(handle)):
        raise _last_error("FlushFileBuffers")



def _seek_start(handle: int) -> None:
    if not _api().set_file_pointer_ex(
        _HANDLE(handle),
        0,
        None,
        _FILE_BEGIN,
    ):
        raise _last_error("SetFilePointerEx")


def _truncate_here(handle: int) -> None:
    if not _api().set_end_of_file(_HANDLE(handle)):
        raise _last_error("SetEndOfFile")


def _replace_all(handle: int, content: bytes) -> None:
    _seek_start(handle)
    _write_all(handle, content)
    _truncate_here(handle)

    if not _api().flush(_HANDLE(handle)):
        raise _last_error("FlushFileBuffers")


def _observe_handle(handle: int) -> TargetObservation:
    security = _capture_security(handle)

    _seek_start(handle)
    content = _read_all(handle)

    return TargetObservation(
        existed=True,
        content=content,
        mode=_file_mode(handle),
        security_descriptor=security.descriptor,
        dacl=security.dacl,
        dacl_protected=security.protected,
    )


def _capture_security(handle: int) -> _SecurityState:
    dacl_pointer = ctypes.c_void_p()
    descriptor_pointer = ctypes.c_void_p()

    result = int(
        _api().get_security_info(
            _HANDLE(handle),
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(dacl_pointer),
            None,
            ctypes.byref(descriptor_pointer),
        )
    )

    if result != 0:
        raise WindowsPublicationError(
            f"GetSecurityInfo(DACL) failed with WinError {result}"
        )

    if descriptor_pointer.value is None:
        raise WindowsPublicationError(
            "GetSecurityInfo(DACL) returned no security descriptor"
        )

    try:
        control = _USHORT()
        revision = _DWORD()

        if not _api().get_security_descriptor_control(
            descriptor_pointer,
            ctypes.byref(control),
            ctypes.byref(revision),
        ):
            raise _last_error(
                "GetSecurityDescriptorControl"
            )

        if not (control.value & _SE_SELF_RELATIVE):
            raise WindowsPublicationError(
                "GetSecurityInfo returned a non-self-relative "
                "security descriptor"
            )

        descriptor_length = int(
            _api().get_security_descriptor_length(
                descriptor_pointer
            )
        )

        if descriptor_length <= 0:
            raise WindowsPublicationError(
                "security descriptor has invalid length"
            )

        descriptor = ctypes.string_at(
            descriptor_pointer.value,
            descriptor_length,
        )

        dacl: bytes | None = None

        if dacl_pointer.value is not None:
            acl_info = _AclSizeInformation()

            if not _api().get_acl_information(
                dacl_pointer,
                ctypes.byref(acl_info),
                ctypes.sizeof(acl_info),
                _ACL_SIZE_INFORMATION_CLASS,
            ):
                raise _last_error(
                    "GetAclInformation"
                )

            dacl = ctypes.string_at(
                dacl_pointer.value,
                acl_info.AclBytesInUse,
            )

        return _SecurityState(
            descriptor=descriptor,
            dacl=dacl,
            protected=bool(
                control.value & _SE_DACL_PROTECTED
            ),
        )

    finally:
        _api().local_free(
            descriptor_pointer
        )


def _file_basic_info(handle: int) -> _FileBasicInfo:
    info = _FileBasicInfo()

    if not _api().get_info(
        _HANDLE(handle),
        _FILE_BASIC_INFO_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise _last_error(
            "GetFileInformationByHandleEx(FileBasicInfo)"
        )

    return info


def _file_id_info(
    handle: int,
) -> tuple[int, str]:
    info = _FileIdInfo()

    if not _api().get_info(
        _HANDLE(handle),
        _FILE_ID_INFO_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise _last_error(
            "GetFileInformationByHandleEx(FileIdInfo)"
        )

    return (
        int(info.VolumeSerialNumber),
        bytes(info.FileId.Identifier).hex(),
    )


def _mode_from_attributes(
    attributes: int,
) -> int:
    if attributes & _FILE_ATTRIBUTE_READONLY:
        return 0o444

    return 0o666


def _file_mode(handle: int) -> int:
    return _mode_from_attributes(
        int(
            _file_basic_info(
                handle
            ).FileAttributes
        )
    )


def _basic_state_key(
    info: _FileBasicInfo,
) -> tuple[int, int, int, int]:
    return (
        int(info.CreationTime),
        int(info.LastWriteTime),
        int(info.ChangeTime),
        int(info.FileAttributes),
    )


def _observe_handle_with_token(
    handle: int,
) -> WindowsTargetState:
    basic_before = _file_basic_info(
        handle
    )
    identity_before = _file_id_info(
        handle
    )
    security_before = _capture_security(
        handle
    )

    _seek_start(handle)
    content = _read_all(handle)

    basic_after = _file_basic_info(
        handle
    )
    identity_after = _file_id_info(
        handle
    )
    security_after = _capture_security(
        handle
    )

    if identity_after != identity_before:
        raise WindowsPublicationError(
            "target identity changed during bound observation"
        )

    if (
        _basic_state_key(basic_after)
        != _basic_state_key(basic_before)
    ):
        raise WindowsPublicationError(
            "target freshness changed during bound observation"
        )

    if (
        security_after.dacl
        != security_before.dacl
        or security_after.protected
        is not security_before.protected
    ):
        raise WindowsPublicationError(
            "target DACL changed during bound observation"
        )

    mode = _mode_from_attributes(
        int(basic_after.FileAttributes)
    )

    observation = TargetObservation(
        existed=True,
        content=content,
        mode=mode,
        security_descriptor=(
            security_after.descriptor
        ),
        dacl=security_after.dacl,
        dacl_protected=(
            security_after.protected
        ),
    )

    dacl_sha256 = (
        None
        if security_after.dacl is None
        else sha256(
            security_after.dacl
        ).hexdigest()
    )

    token = WindowsAfterStateToken(
        volume_serial_number=(
            identity_after[0]
        ),
        file_id=identity_after[1],
        creation_time=int(
            basic_after.CreationTime
        ),
        last_write_time=int(
            basic_after.LastWriteTime
        ),
        change_time=int(
            basic_after.ChangeTime
        ),
        content_sha256=sha256(
            content
        ).hexdigest(),
        size_bytes=len(content),
        mode=mode,
        dacl_sha256=dacl_sha256,
        dacl_protected=(
            security_after.protected
        ),
    )

    return WindowsTargetState(
        observation=observation,
        token=token,
    )


def _set_file_mode(
    handle: int,
    mode: int,
) -> None:
    current = _file_basic_info(handle)
    attributes = int(current.FileAttributes)

    if mode & 0o222:
        attributes &= ~_FILE_ATTRIBUTE_READONLY

        if attributes == 0:
            attributes = _FILE_ATTRIBUTE_NORMAL

    else:
        attributes &= ~_FILE_ATTRIBUTE_NORMAL
        attributes |= _FILE_ATTRIBUTE_READONLY

    update = _FileBasicInfo(
        CreationTime=0,
        LastAccessTime=0,
        LastWriteTime=0,
        ChangeTime=0,
        FileAttributes=attributes,
    )

    if not _api().set_info(
        _HANDLE(handle),
        _FILE_BASIC_INFO_CLASS,
        ctypes.byref(update),
        ctypes.sizeof(update),
    ):
        raise _last_error(
            "SetFileInformationByHandle(FileBasicInfo)"
        )


def _security_matches(
    observed: _SecurityState,
    *,
    expected_dacl: bytes | None,
    expected_protected: bool,
) -> bool:
    return (
        observed.dacl == expected_dacl
        and observed.protected is expected_protected
    )


def _open_root(path: Path) -> int:
    handle = _api().create_file(
        str(path),
        _FILE_ADD_FILE | _FILE_TRAVERSE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
        _SHARE_ALL,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    value = 0 if not handle else int(handle)
    if value in (0, _INVALID_HANDLE_VALUE):
        raise _last_error("CreateFileW(workspace root)")
    try:
        _reject_reparse(value, subject="workspace root")
        _require_directory(value, subject="workspace root")
        return value
    except Exception:
        _close(value)
        raise


def _validate_directory_handle(
    handle: int,
    *,
    subject: str,
) -> int:
    try:
        _reject_reparse(
            handle,
            subject=subject,
        )
        _require_directory(
            handle,
            subject=subject,
        )
        return handle

    except Exception:
        _close(handle)
        raise


def _open_directory_once(
    parent: int,
    name: str,
) -> tuple[int, int | None]:
    backing, text, attrs = _object_attributes(
        parent,
        name,
    )
    handle = _HANDLE()
    iosb = _IoStatusBlock()

    status = int(
        _api().nt_open(
            ctypes.byref(handle),
            _FILE_ADD_FILE
            | _FILE_TRAVERSE
            | _FILE_READ_ATTRIBUTES
            | _SYNCHRONIZE,
            ctypes.byref(attrs),
            ctypes.byref(iosb),
            _SHARE_ALL,
            _FILE_DIRECTORY_FILE
            | _FILE_SYNCHRONOUS_IO_NONALERT
            | _FILE_OPEN_REPARSE_POINT,
        )
    )

    _ = backing, text

    if (
        status < 0
        or handle.value is None
    ):
        if handle.value is not None:
            _close(
                int(handle.value)
            )

        return status, None

    return (
        status,
        int(handle.value),
    )


def _open_directory(
    parent: int,
    name: str,
) -> int:
    status, handle = (
        _open_directory_once(
            parent,
            name,
        )
    )

    if (
        status < 0
        or handle is None
    ):
        raise WindowsPublicationError(
            f"NtOpenFile(directory {name!r}) "
            f"failed with {_status_text(status)}"
        )

    return _validate_directory_handle(
        handle,
        subject=(
            f"workspace component {name!r}"
        ),
    )


def _create_directory_once(
    parent: int,
    name: str,
) -> tuple[int, int | None]:
    backing, text, attrs = (
        _object_attributes(
            parent,
            name,
        )
    )

    handle = _HANDLE()
    iosb = _IoStatusBlock()

    status = int(
        _api().nt_create(
            ctypes.byref(handle),
            _FILE_ADD_FILE
            | _FILE_TRAVERSE
            | _FILE_READ_ATTRIBUTES
            | _SYNCHRONIZE,
            ctypes.byref(attrs),
            ctypes.byref(iosb),
            None,
            0,
            _SHARE_ALL,
            _FILE_CREATE,
            _FILE_DIRECTORY_FILE
            | _FILE_SYNCHRONOUS_IO_NONALERT
            | _FILE_OPEN_REPARSE_POINT,
            None,
            0,
        )
    )

    _ = backing, text

    if (
        status < 0
        or handle.value is None
    ):
        if handle.value is not None:
            _close(
                int(handle.value)
            )

        return status, None

    return (
        status,
        int(handle.value),
    )


def _open_or_create_directory(
    parent: int,
    name: str,
) -> int:
    open_status, opened = (
        _open_directory_once(
            parent,
            name,
        )
    )

    if (
        open_status >= 0
        and opened is not None
    ):
        return _validate_directory_handle(
            opened,
            subject=(
                f"workspace component {name!r}"
            ),
        )

    if (
        _u32(open_status)
        != _STATUS_OBJECT_NAME_NOT_FOUND
    ):
        raise WindowsPublicationError(
            f"NtOpenFile(directory {name!r}) "
            f"failed with "
            f"{_status_text(open_status)}"
        )

    create_status, created = (
        _create_directory_once(
            parent,
            name,
        )
    )

    if (
        create_status >= 0
        and created is not None
    ):
        return _validate_directory_handle(
            created,
            subject=(
                f"created workspace component "
                f"{name!r}"
            ),
        )

    if (
        _u32(create_status)
        == _STATUS_OBJECT_NAME_COLLISION
    ):
        # Another actor won the absent→present race.
        # Re-open through the already-bound parent and
        # validate the winner instead of trusting its name.
        return _open_directory(
            parent,
            name,
        )

    raise WindowsPublicationError(
        f"NtCreateFile(directory {name!r}) "
        f"failed with "
        f"{_status_text(create_status)}"
    )


def _open_file(parent: int, name: str) -> tuple[int, int | None]:
    backing, text, attrs = _object_attributes(parent, name)
    handle = _HANDLE()
    iosb = _IoStatusBlock()
    status = int(
        _api().nt_open(
            ctypes.byref(handle),
            _FILE_READ_DATA
            | _FILE_READ_ATTRIBUTES
            | _READ_CONTROL
            | _SYNCHRONIZE,
            ctypes.byref(attrs),
            ctypes.byref(iosb),
            _SHARE_ALL,
            _FILE_NON_DIRECTORY_FILE
            | _FILE_SYNCHRONOUS_IO_NONALERT
            | _FILE_OPEN_REPARSE_POINT,
        )
    )
    _ = backing, text
    if status < 0:
        return status, None
    if handle.value is None:
        raise WindowsPublicationError("NtOpenFile(target) returned no handle")
    value = int(handle.value)
    try:
        _reject_reparse(value, subject=f"target {name!r}")
        return status, value
    except Exception:
        _close(value)
        raise


def _open_fenced_file(
    parent: int,
    name: str,
    *,
    writable: bool,
    deletable: bool,
) -> tuple[int, int | None]:
    desired_access = (
        _FILE_READ_DATA
        | _FILE_READ_ATTRIBUTES
        | _READ_CONTROL
        | _SYNCHRONIZE
    )

    if writable:
        desired_access |= _FILE_WRITE_DATA

    if deletable:
        desired_access |= _DELETE

    backing, text, attrs = _object_attributes(
        parent,
        name,
    )
    handle = _HANDLE()
    iosb = _IoStatusBlock()

    status = int(
        _api().nt_open(
            ctypes.byref(handle),
            desired_access,
            ctypes.byref(attrs),
            ctypes.byref(iosb),
            _FILE_SHARE_READ,
            _FILE_NON_DIRECTORY_FILE
            | _FILE_SYNCHRONOUS_IO_NONALERT
            | _FILE_OPEN_REPARSE_POINT,
        )
    )

    _ = backing, text

    if status < 0:
        if handle.value is not None:
            _close(
                int(handle.value)
            )

        return status, None

    if handle.value is None:
        raise WindowsPublicationError(
            "NtOpenFile(fenced target) returned no handle"
        )

    value = int(handle.value)

    try:
        _reject_reparse(
            value,
            subject=f"fenced target {name!r}",
        )

        return status, value

    except Exception:
        _close(value)
        raise


def _create_stage(
    parent: int,
    name: str,
    *,
    security_descriptor: bytes | None = None,
) -> int:
    backing, text, attrs = _object_attributes(
        parent,
        name,
        security_descriptor=security_descriptor,
    )

    handle = _HANDLE()
    iosb = _IoStatusBlock()

    status = int(
        _api().nt_create(
            ctypes.byref(handle),
            _FILE_READ_DATA
            | _FILE_WRITE_DATA
            | _FILE_READ_ATTRIBUTES
            | _FILE_WRITE_ATTRIBUTES
            | _READ_CONTROL
            | _DELETE
            | _SYNCHRONIZE,
            ctypes.byref(attrs),
            ctypes.byref(iosb),
            None,
            _FILE_ATTRIBUTE_NORMAL,
            _FILE_SHARE_DELETE,
            _FILE_CREATE,
            _FILE_NON_DIRECTORY_FILE
            | _FILE_SYNCHRONOUS_IO_NONALERT
            | _FILE_OPEN_REPARSE_POINT,
            None,
            0,
        )
    )

    _ = backing, text

    if status < 0 or handle.value is None:
        raise WindowsPublicationError(
            f"NtCreateFile(stage) failed with {_status_text(status)}"
        )

    value = int(handle.value)

    try:
        _reject_reparse(
            value,
            subject="private stage",
        )
        return value

    except Exception:
        _close(value)
        raise


def _publish(
    stage: int,
    parent: int,
    target_name: str,
    *,
    replace: bool,
) -> PublicationResult:
    encoded = target_name.encode("utf-16-le")
    size = max(
        ctypes.sizeof(_FileRenameInformation),
        _RENAME_NAME_OFFSET + len(encoded),
    )
    raw = ctypes.create_string_buffer(size)
    info = _FileRenameInformation.from_buffer(raw)
    info.ReplaceIfExists = 1 if replace else 0
    info.RootDirectory = _HANDLE(parent)
    info.FileNameLength = len(encoded)
    ctypes.memmove(
        ctypes.addressof(raw) + _RENAME_NAME_OFFSET,
        encoded,
        len(encoded),
    )
    iosb = _IoStatusBlock()
    status = int(
        _api().nt_set_info(
            _HANDLE(stage),
            ctypes.byref(iosb),
            raw,
            size,
            _FILE_RENAME_INFORMATION_CLASS,
        )
    )
    normalized = _u32(status)
    if normalized == _STATUS_SUCCESS:
        return PublicationResult(PublicationState.PUBLISHED, normalized)
    if normalized == _STATUS_OBJECT_NAME_COLLISION:
        return PublicationResult(PublicationState.COLLISION, normalized)
    return PublicationResult(PublicationState.UNKNOWN, normalized)


def _discard(
    stage: int,
    *,
    ignore_readonly: bool = False,
) -> None:
    flags = _FILE_DISPOSITION_DELETE

    if ignore_readonly:
        flags |= (
            _FILE_DISPOSITION_IGNORE_READONLY_ATTRIBUTE
        )

    info = _FileDispositionInformationEx(flags)
    iosb = _IoStatusBlock()
    status = int(
        _api().nt_set_info(
            _HANDLE(stage),
            ctypes.byref(iosb),
            ctypes.byref(info),
            ctypes.sizeof(info),
            _FILE_DISPOSITION_INFORMATION_EX_CLASS,
        )
    )
    if status < 0:
        raise WindowsPublicationError(
            f"NtSetInformationFile(disposition) failed with {_status_text(status)}"
        )


class FencedTarget:
    """Exact expected target held under Windows write/delete exclusion."""

    def __init__(
        self,
        *,
        parent_handle: int,
        name: str,
        handle: int,
        expected_after: WindowsAfterStateToken,
        may_restore: bool,
        may_delete: bool,
    ) -> None:
        self.parent_handle = parent_handle
        self.name = name
        self.expected_after = expected_after
        self._handle: int | None = handle
        self._may_restore = may_restore
        self._may_delete = may_delete

    def _require_handle(self) -> int:
        if self._handle is None:
            raise WindowsPublicationError(
                "fenced target handle is closed"
            )

        return self._handle

    def verify_expected(
        self,
    ) -> WindowsTargetState:
        state = _observe_handle_with_token(
            self._require_handle()
        )

        if state.token != self.expected_after:
            raise WindowsPublicationError(
                "fenced target does not match "
                "committed after-state token"
            )

        return state

    def restore_existing_content(
        self,
        content: bytes,
        *,
        mode: int,
    ) -> WindowsTargetState:
        if not self._may_restore:
            raise WindowsPublicationError(
                "fenced target lacks restore authority"
            )

        if mode != self.expected_after.mode:
            raise WindowsPublicationError(
                "before-state mode does not match "
                "published mode"
            )

        accepted_after = self.verify_expected()

        accepted_after_content = (
            accepted_after.observation.content
        )

        if accepted_after_content is None:
            raise WindowsPublicationError(
                "verified after-state lacks content"
            )

        handle = self._require_handle()

        expected_content_sha256 = sha256(
            content
        ).hexdigest()

        try:
            _replace_all(
                handle,
                content,
            )

            restored = _observe_handle_with_token(
                handle
            )

            if (
                restored.token.volume_serial_number
                != self.expected_after.volume_serial_number
                or restored.token.file_id
                != self.expected_after.file_id
                or restored.token.creation_time
                != self.expected_after.creation_time
                or restored.token.content_sha256
                != expected_content_sha256
                or restored.token.size_bytes
                != len(content)
                or restored.token.mode
                != mode
                or restored.token.dacl_sha256
                != self.expected_after.dacl_sha256
                or restored.token.dacl_protected
                is not self.expected_after.dacl_protected
            ):
                raise WindowsPublicationError(
                    "fenced existing-target restore "
                    "verification failed"
                )

            return restored

        except Exception as exc:
            try:
                current = _observe_handle_with_token(
                    handle
                )
            except Exception:
                current = None

            if (
                current is not None
                and current.token == self.expected_after
            ):
                raise WindowsPublicationError(
                    "fenced existing-target restore "
                    "failed before target state changed"
                ) from exc

            try:
                _replace_all(
                    handle,
                    accepted_after_content,
                )

                recovered = (
                    _observe_handle_with_token(
                        handle
                    )
                )

                if (
                    recovered.observation.content
                    != accepted_after_content
                    or recovered.token.volume_serial_number
                    != self.expected_after.volume_serial_number
                    or recovered.token.file_id
                    != self.expected_after.file_id
                    or recovered.token.creation_time
                    != self.expected_after.creation_time
                    or recovered.token.content_sha256
                    != self.expected_after.content_sha256
                    or recovered.token.size_bytes
                    != self.expected_after.size_bytes
                    or recovered.token.mode
                    != self.expected_after.mode
                    or recovered.token.dacl_sha256
                    != self.expected_after.dacl_sha256
                    or recovered.token.dacl_protected
                    is not self.expected_after.dacl_protected
                ):
                    raise WindowsPublicationError(
                        "accepted after-state recovery "
                        "verification failed"
                    )

            except Exception as recovery_exc:
                raise WindowsPublicationError(
                    "fenced existing-target restore "
                    f"failed: {exc}; accepted after-state "
                    "recovery also failed: "
                    f"{recovery_exc}"
                ) from recovery_exc

            if recovered.token == self.expected_after:
                raise WindowsPublicationError(
                    "fenced existing-target restore "
                    "failed; committed after-state "
                    "was fully recovered"
                ) from exc

            raise WindowsPublicationError(
                "fenced existing-target restore failed; "
                "accepted after-state content was recovered "
                "but the original after-state token is no "
                "longer reusable"
            ) from exc

    def delete_created_target(
        self,
    ) -> TargetObservation:
        if not self._may_delete:
            raise WindowsPublicationError(
                "fenced target lacks delete authority"
            )

        self.verify_expected()

        handle = self._require_handle()

        _discard(
            handle,
            ignore_readonly=True,
        )

        self.close()

        status, observed_handle = _open_file(
            self.parent_handle,
            self.name,
        )

        if (
            _u32(status)
            == _STATUS_OBJECT_NAME_NOT_FOUND
        ):
            return TargetObservation(
                existed=False
            )

        if observed_handle is not None:
            _close(
                observed_handle
            )

        raise WindowsPublicationError(
            "fenced created-target delete could not "
            "verify bound target absence"
        )

    def close(self) -> None:
        if self._handle is not None:
            _close(
                self._handle
            )
            self._handle = None

    def __enter__(
        self,
    ) -> FencedTarget:
        self._require_handle()
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        self.close()


class StagedFile:
    """Same-parent private stage held by an object handle."""

    def __init__(
        self,
        *,
        parent_handle: int,
        name: str,
        handle: int,
        verify_security: bool,
        expected_dacl: bytes | None,
        expected_dacl_protected: bool | None,
        target_mode: int | None,
    ) -> None:
        self.parent_handle = parent_handle
        self.name = name
        self._handle: int | None = handle
        self._publication: PublicationState | None = None
        self._verify_security = verify_security
        self._expected_dacl = expected_dacl
        self._expected_dacl_protected = expected_dacl_protected
        self._target_mode = target_mode
        self._content_written = False
        self._published_name: str | None = None

    def _require_handle(self) -> int:
        if self._handle is None:
            raise WindowsPublicationError(
                "stage handle is closed"
            )

        return self._handle

    @property
    def publication_state(
        self,
    ) -> PublicationState | None:
        """Return the observed publication lifecycle state."""

        return self._publication

    def _require_security_before_content(self) -> None:
        if not self._verify_security:
            return

        if self._expected_dacl_protected is None:
            raise WindowsPublicationError(
                "stage security expectation is incomplete"
            )

        observed = _capture_security(
            self._require_handle()
        )

        if not _security_matches(
            observed,
            expected_dacl=self._expected_dacl,
            expected_protected=(
                self._expected_dacl_protected
            ),
        ):
            raise WindowsPublicationError(
                "private stage DACL changed before "
                "content write"
            )

    def write_bytes(self, content: bytes) -> None:
        if self._publication is not None:
            raise WindowsPublicationError(
                "publication has already been attempted"
            )

        self._require_security_before_content()

        _write_all(
            self._require_handle(),
            content,
        )

        self._content_written = True

    def publish(
        self,
        target_name: str,
        *,
        replace: bool,
    ) -> PublicationResult:
        if self._publication is not None:
            raise WindowsPublicationError(
                "publication has already been attempted"
            )

        if not self._content_written:
            raise WindowsPublicationError(
                "stage content has not been written"
            )

        handle = self._require_handle()

        if self._target_mode is not None:
            _set_file_mode(
                handle,
                self._target_mode,
            )

            if _file_mode(handle) != self._target_mode:
                raise WindowsPublicationError(
                    "private stage mode verification failed"
                )

        self._publication = PublicationState.UNKNOWN

        result = _publish(
            handle,
            self.parent_handle,
            target_name,
            replace=replace,
        )

        self._publication = result.state

        if result.state is PublicationState.PUBLISHED:
            self._published_name = target_name

        return result

    def observe_published(self) -> TargetObservation:
        if self._publication is not PublicationState.PUBLISHED:
            raise WindowsPublicationError(
                "published observation requires a confirmed "
                "PUBLISHED state"
            )

        return _observe_handle(self._require_handle())

    def observe_published_with_token(
        self,
    ) -> WindowsTargetState:
        if (
            self._publication
            is not PublicationState.PUBLISHED
        ):
            raise WindowsPublicationError(
                "published token observation requires "
                "a confirmed PUBLISHED state"
            )

        return _observe_handle_with_token(
            self._require_handle()
        )

    def rollback_published(
        self,
        original: TargetObservation,
    ) -> TargetObservation:
        if self._publication is not PublicationState.PUBLISHED:
            raise WindowsPublicationError(
                "published rollback requires a confirmed "
                "PUBLISHED state"
            )

        handle = self._require_handle()

        if original.existed:
            if (
                original.content is None
                or original.mode is None
                or original.dacl_protected is None
            ):
                raise WindowsPublicationError(
                    "existing rollback observation lacks "
                    "bound content, mode, or DACL evidence"
                )

            _replace_all(handle, original.content)
            _set_file_mode(handle, original.mode)

            observed = _observe_handle(handle)

            if (
                observed.content != original.content
                or observed.mode != original.mode
                or observed.dacl != original.dacl
                or observed.dacl_protected
                is not original.dacl_protected
            ):
                raise WindowsPublicationError(
                    "published existing-target rollback "
                    "verification failed"
                )

            self.close()
            return observed

        if any(
            value is not None
            for value in (
                original.content,
                original.mode,
                original.security_descriptor,
                original.dacl,
                original.dacl_protected,
            )
        ):
            raise WindowsPublicationError(
                "absent rollback observation contains "
                "unexpected target state"
            )

        published_name = self._published_name
        if published_name is None:
            raise WindowsPublicationError(
                "published target name is unavailable "
                "for create rollback verification"
            )

        _discard(handle, ignore_readonly=True)
        self.close()

        status, observed_handle = _open_file(
            self.parent_handle,
            published_name,
        )

        if _u32(status) == _STATUS_OBJECT_NAME_NOT_FOUND:
            return TargetObservation(existed=False)

        if observed_handle is not None:
            _close(observed_handle)

        raise WindowsPublicationError(
            "published create rollback could not verify "
            "bound target absence"
        )

    def discard(self) -> None:
        if self._publication not in (
            None,
            PublicationState.COLLISION,
        ):
            raise WindowsPublicationError(
                "stage publication state is not safe "
                "to discard"
            )

        _discard(
            self._require_handle()
        )

        self.close()

    def close(self) -> None:
        if self._handle is not None:
            _close(self._handle)
            self._handle = None

    def __enter__(self) -> StagedFile:
        self._require_handle()
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        self.close()


class BoundPublicationParent:
    """Handle-bound authority for one target's existing parent namespace."""

    def __init__(
        self,
        *,
        relative_path: str,
        leaf_name: str,
        handles: tuple[int, ...],
    ) -> None:
        self.relative_path = relative_path
        self.leaf_name = leaf_name
        self._handles = list(handles)

    @classmethod
    def bind(
        cls,
        workspace_root: str,
        relative_path: str,
        *,
        create_missing_parents: bool = False,
    ) -> BoundPublicationParent:
        if os.name != "nt":
            raise WindowsPublicationError("Windows publication backend is unavailable")
        normalized = normalize_relative_path(relative_path)
        parts = PurePosixPath(normalized).parts
        handles: list[int] = []
        try:
            root = _open_root(Path(workspace_root).expanduser())
            handles.append(root)
            parent = root
            for component in parts[:-1]:
                if create_missing_parents:
                    parent = (
                        _open_or_create_directory(
                            parent,
                            component,
                        )
                    )
                else:
                    parent = _open_directory(
                        parent,
                        component,
                    )

                handles.append(parent)
            return cls(
                relative_path=normalized,
                leaf_name=parts[-1],
                handles=tuple(handles),
            )
        except Exception:
            for handle in reversed(handles):
                _close(handle)
            raise

    @property
    def parent_handle(self) -> int:
        if not self._handles:
            raise WindowsPublicationError("publication authority is closed")
        return self._handles[-1]

    def observe_target(self) -> TargetObservation:
        status, handle = _open_file(
            self.parent_handle,
            self.leaf_name,
        )

        if (
            _u32(status)
            == _STATUS_OBJECT_NAME_NOT_FOUND
        ):
            return TargetObservation(
                existed=False
            )

        if status < 0 or handle is None:
            raise WindowsPublicationError(
                f"NtOpenFile(target) failed with "
                f"{_status_text(status)}"
            )

        try:
            security = _capture_security(handle)

            return TargetObservation(
                existed=True,
                content=_read_all(handle),
                mode=_file_mode(handle),
                security_descriptor=(
                    security.descriptor
                ),
                dacl=security.dacl,
                dacl_protected=(
                    security.protected
                ),
            )

        finally:
            _close(handle)

    def _fence_expected_target(
        self,
        expected_after: WindowsAfterStateToken,
        *,
        writable: bool,
        deletable: bool,
    ) -> FencedTarget:
        status, handle = _open_fenced_file(
            self.parent_handle,
            self.leaf_name,
            writable=writable,
            deletable=deletable,
        )

        if (
            _u32(status)
            == _STATUS_OBJECT_NAME_NOT_FOUND
        ):
            raise WindowsPublicationError(
                "expected committed target is absent"
            )

        if status < 0 or handle is None:
            raise WindowsPublicationError(
                "NtOpenFile(fenced target) failed with "
                f"{_status_text(status)}"
            )

        target = FencedTarget(
            parent_handle=self.parent_handle,
            name=self.leaf_name,
            handle=handle,
            expected_after=expected_after,
            may_restore=writable,
            may_delete=deletable,
        )

        try:
            target.verify_expected()
            return target

        except Exception:
            target.close()
            raise

    def fence_existing_restore(
        self,
        expected_after: WindowsAfterStateToken,
    ) -> FencedTarget:
        return self._fence_expected_target(
            expected_after,
            writable=True,
            deletable=False,
        )

    def fence_created_delete(
        self,
        expected_after: WindowsAfterStateToken,
    ) -> FencedTarget:
        return self._fence_expected_target(
            expected_after,
            writable=False,
            deletable=True,
        )

    def create_stage(
        self,
        *,
        source: TargetObservation | None = None,
    ) -> StagedFile:
        security_descriptor: bytes | None = None
        verify_security = False
        expected_dacl: bytes | None = None
        expected_dacl_protected: bool | None = None
        target_mode: int | None = None

        if source is not None:
            if not source.existed:
                raise WindowsPublicationError(
                    "existing-source stage requires "
                    "an existing observation"
                )

            if (
                source.security_descriptor is None
                or source.mode is None
                or source.dacl_protected is None
            ):
                raise WindowsPublicationError(
                    "existing-source observation lacks "
                    "bound security or mode evidence"
                )

            # Preserve current Luna Windows behavior:
            # a read-only existing target is rejected rather
            # than silently made writable through replacement.
            if (source.mode & 0o222) == 0:
                raise WindowsPublicationError(
                    "read-only target cannot be replaced"
                )

            security_descriptor = (
                source.security_descriptor
            )
            verify_security = True
            expected_dacl = source.dacl
            expected_dacl_protected = (
                source.dacl_protected
            )
            target_mode = source.mode

        name = f".luna-stage-{uuid4().hex}"

        handle = _create_stage(
            self.parent_handle,
            name,
            security_descriptor=(
                security_descriptor
            ),
        )

        return StagedFile(
            parent_handle=self.parent_handle,
            name=name,
            handle=handle,
            verify_security=verify_security,
            expected_dacl=expected_dacl,
            expected_dacl_protected=(
                expected_dacl_protected
            ),
            target_mode=target_mode,
        )

    def close(self) -> None:
        for handle in reversed(self._handles):
            _close(handle)
        self._handles.clear()

    def __enter__(self) -> BoundPublicationParent:
        _ = self.parent_handle
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
