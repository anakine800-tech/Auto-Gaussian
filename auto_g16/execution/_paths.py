"""Strict path validation for the frozen execution boundary."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import re
import stat

from ._identity import ExecutionValueError, require_text


_WINDOWS_DRIVE = re.compile(r"^[A-Z]:\\")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def validate_portable_name(value: str, field_name: str) -> str:
    require_text(value, field_name)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise ExecutionValueError(f"{field_name} must be one portable path component")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ExecutionValueError(f"{field_name} must not contain control characters")
    return value


def validate_posix_path(value: str, field_name: str) -> str:
    require_text(value, field_name)
    if not value.startswith("/") or value.startswith("//"):
        raise ExecutionValueError(f"{field_name} must be an absolute canonical POSIX path")
    if value != "/" and value.endswith("/"):
        raise ExecutionValueError(f"{field_name} must not have a trailing separator")
    parts = value.split("/")[1:]
    if any(part in {"", ".", ".."} for part in parts):
        raise ExecutionValueError(f"{field_name} contains a non-canonical component")
    if any(any(ord(character) < 32 or ord(character) == 127 for character in part) for part in parts):
        raise ExecutionValueError(f"{field_name} contains a control character")
    if str(PurePosixPath(value)) != value:
        raise ExecutionValueError(f"{field_name} must already be canonical")
    return value


def validate_windows_path(value: str, field_name: str) -> str:
    require_text(value, field_name)
    if not _WINDOWS_DRIVE.match(value):
        raise ExecutionValueError(
            f"{field_name} must be an uppercase-drive absolute Windows path"
        )
    if value.startswith(("\\\\", "\\?\\", "\\.\\")) or "/" in value:
        raise ExecutionValueError(f"{field_name} uses a forbidden Windows namespace")
    if value.endswith("\\"):
        raise ExecutionValueError(f"{field_name} must not have a trailing separator")
    parts = value[3:].split("\\")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ExecutionValueError(f"{field_name} contains a non-canonical component")
    for part in parts:
        if part.endswith((" ", ".")) or ":" in part:
            raise ExecutionValueError(f"{field_name} contains a forbidden component")
        if any(ord(character) < 32 or ord(character) == 127 for character in part):
            raise ExecutionValueError(f"{field_name} contains a control character")
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise ExecutionValueError(f"{field_name} contains a reserved device name")
    return value


def validate_platform_path(value: str, field_name: str) -> str:
    if value.startswith("/"):
        return validate_posix_path(value, field_name)
    return validate_windows_path(value, field_name)


def require_contained(path: str, root: str, field_name: str) -> None:
    path_parts = PurePosixPath(validate_posix_path(path, field_name)).parts
    root_parts = PurePosixPath(validate_posix_path(root, f"{field_name} root")).parts
    if len(path_parts) <= len(root_parts) or path_parts[: len(root_parts)] != root_parts:
        raise ExecutionValueError(f"{field_name} is not strictly contained under its root")


def require_windows_contained(path: str, root: str, field_name: str) -> None:
    validate_windows_path(path, field_name)
    validate_windows_path(root, f"{field_name} root")
    prefix = root + "\\"
    if not path.startswith(prefix) or path == root:
        raise ExecutionValueError(f"{field_name} is not strictly contained under its root")


def require_local_parent_identity(path: str, root: str) -> tuple[int, int]:
    validate_posix_path(path, "local_attempt_dir")
    validate_posix_path(root, "local approved root")
    candidate = Path(path)
    approved = Path(root)
    if candidate.parent == candidate:
        raise ExecutionValueError("local_attempt_dir has no parent")
    try:
        relative = candidate.relative_to(approved)
    except ValueError as exc:
        raise ExecutionValueError(
            "local_attempt_dir is not contained under the approved root"
        ) from exc
    if not relative.parts:
        raise ExecutionValueError("local_attempt_dir must be below the approved root")
    current = approved
    for part in relative.parts[:-1]:
        current = current / part
    try:
        root_real = approved.resolve(strict=True)
        parent_real = candidate.parent.resolve(strict=True)
    except OSError as exc:
        raise ExecutionValueError("local workspace parent is unavailable") from exc
    if str(root_real) != root or str(parent_real) != str(candidate.parent):
        raise ExecutionValueError("local workspace roots must already be canonical")
    current = Path(root)
    for part in relative.parts[:-1]:
        current = current / part
        value = os.lstat(current)
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode):
            raise ExecutionValueError("local workspace parent chain must be real directories")
    parent = os.lstat(candidate.parent)
    if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
        raise ExecutionValueError("local workspace parent must be a real directory")
    return (parent.st_dev, parent.st_ino)


def verify_local_parent_identity(path: str, expected: tuple[int, int]) -> None:
    parent = os.lstat(Path(path).parent)
    if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
        raise ExecutionValueError("local workspace parent identity is invalid")
    if (parent.st_dev, parent.st_ino) != expected:
        raise ExecutionValueError("local workspace parent identity changed")
