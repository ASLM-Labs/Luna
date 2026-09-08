"""Strict bounded loader for Agent-Skills-compatible Luna packages."""

from __future__ import annotations

import json
import unicodedata
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from luna.skills.models import SkillPackage, SkillResource, SkillResourceKind

_ALLOWED_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
_SKILL_MD_MAX_BYTES = 256 * 1024
_PACKAGE_MAX_FILES = 256
_RESOURCE_MAX_BYTES = 4 * 1024 * 1024
_PACKAGE_MAX_BYTES = 32 * 1024 * 1024


class SkillPackageError(ValueError):
    """Package syntax, containment, or bound violation."""


def _decode_scalar(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        if len(value) < 2 or value[-1] != value[0]:
            raise SkillPackageError("unterminated quoted skill frontmatter scalar")
        if value[0] == '"':
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError as exc:
                raise SkillPackageError("invalid quoted skill frontmatter scalar") from exc
            if not isinstance(decoded, str):
                raise SkillPackageError("skill frontmatter scalar must decode to text")
            return decoded
        return value[1:-1].replace("''", "'")
    if value.startswith(("[", "{", "&", "*", "!", "|", ">")):
        raise SkillPackageError("unsupported YAML construct in strict skill frontmatter")
    return value


def _split_key_value(line: str) -> tuple[str, str]:
    if ":" not in line:
        raise SkillPackageError("skill frontmatter entries must use key: value syntax")
    key, raw_value = line.split(":", 1)
    key = key.strip()
    if not key:
        raise SkillPackageError("skill frontmatter key must not be blank")
    return key, raw_value


def _parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if not lines or lines[0].strip() != "---":
        raise SkillPackageError("SKILL.md must start with YAML frontmatter")
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as exc:
        raise SkillPackageError("SKILL.md frontmatter is not closed") from exc

    metadata: dict[str, object] = {}
    nested_metadata: dict[str, str] = {}
    in_metadata = False
    for raw_line in lines[1:end]:
        if "\t" in raw_line:
            raise SkillPackageError("tabs are not allowed in strict skill frontmatter")
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw_line.startswith(" "):
            if not in_metadata or not raw_line.startswith("  "):
                raise SkillPackageError("unexpected indentation in strict skill frontmatter")
            key, raw_value = _split_key_value(stripped)
            if key in nested_metadata:
                raise SkillPackageError(f"duplicate skill metadata key: {key}")
            nested_metadata[key] = _decode_scalar(raw_value)
            continue

        in_metadata = False
        key, raw_value = _split_key_value(raw_line)
        if key not in _ALLOWED_FIELDS:
            raise SkillPackageError(f"unexpected skill frontmatter field: {key}")
        if key in metadata:
            raise SkillPackageError(f"duplicate skill frontmatter field: {key}")
        if key == "metadata":
            if raw_value.strip():
                raise SkillPackageError("skill metadata must be a nested string mapping")
            metadata[key] = nested_metadata
            in_metadata = True
            continue
        metadata[key] = _decode_scalar(raw_value)

    if "metadata" in metadata:
        metadata["metadata"] = dict(nested_metadata)
    if "name" not in metadata:
        raise SkillPackageError("missing required skill frontmatter field: name")
    if "description" not in metadata:
        raise SkillPackageError("missing required skill frontmatter field: description")
    body = "\n".join(lines[end + 1 :]).strip()
    return metadata, body


def _resource_kind(relative_path: str) -> SkillResourceKind:
    first = relative_path.split("/", 1)[0].casefold()
    if first == "scripts":
        return SkillResourceKind.SCRIPT
    if first == "references":
        return SkillResourceKind.REFERENCE
    if first == "assets":
        return SkillResourceKind.ASSET
    return SkillResourceKind.OTHER


def _scan_package(root: Path) -> tuple[tuple[SkillResource, ...], str]:
    records: list[tuple[str, int, str]] = []
    resources: list[SkillResource] = []
    seen_paths: set[str] = set()
    total_bytes = 0

    for path in sorted(
        root.rglob("*"),
        key=lambda item: item.relative_to(root).as_posix().casefold(),
    ):
        if path.is_symlink():
            raise SkillPackageError("skill package symlinks are not allowed in v1")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SkillPackageError("skill package contains a non-regular filesystem entry")
        resolved = path.resolve()
        if root not in resolved.parents:
            raise SkillPackageError("skill package entry escaped the package root")
        relative = path.relative_to(root).as_posix()
        path_key = relative.casefold()
        if path_key in seen_paths:
            raise SkillPackageError("skill package paths must be case-insensitively unique")
        seen_paths.add(path_key)
        if len(records) + 1 > _PACKAGE_MAX_FILES:
            raise SkillPackageError("skill package exceeds file-count bound")
        size = path.stat().st_size
        if size > _RESOURCE_MAX_BYTES:
            raise SkillPackageError(f"skill package file exceeds size bound: {relative}")
        total_bytes += size
        if total_bytes > _PACKAGE_MAX_BYTES:
            raise SkillPackageError("skill package exceeds total byte bound")
        digest = sha256(path.read_bytes()).hexdigest()
        records.append((relative, size, digest))
        if relative != "SKILL.md":
            resources.append(
                SkillResource(
                    relative_path=relative,
                    kind=_resource_kind(relative),
                    size_bytes=size,
                    sha256=digest,
                )
            )

    package_hasher = sha256()
    package_hasher.update(b"luna-skill-package-v1\0")
    for relative, size, digest in records:
        package_hasher.update(relative.encode("utf-8"))
        package_hasher.update(b"\0")
        package_hasher.update(str(size).encode("ascii"))
        package_hasher.update(b"\0")
        package_hasher.update(bytes.fromhex(digest))
    return tuple(resources), package_hasher.hexdigest()


def load_skill_package(skill_dir: Path) -> SkillPackage:
    """Load one strict bounded package without executing package resources."""
    supplied_root = Path(skill_dir)
    if supplied_root.is_symlink():
        raise SkillPackageError("skill package root symlinks are not allowed in v1")
    root = supplied_root.resolve()
    if not root.exists():
        raise SkillPackageError(f"skill package path does not exist: {root}")
    if not root.is_dir():
        raise SkillPackageError(f"skill package path is not a directory: {root}")
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        raise SkillPackageError("skill package requires exact SKILL.md")
    if skill_md.is_symlink():
        raise SkillPackageError("SKILL.md may not be a symlink")
    if skill_md.stat().st_size > _SKILL_MD_MAX_BYTES:
        raise SkillPackageError("SKILL.md exceeds 256 KiB bound")
    try:
        text = skill_md.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SkillPackageError("SKILL.md must be valid UTF-8") from exc

    frontmatter, body = _parse_frontmatter(text)
    name = str(frontmatter["name"]).strip()
    description = str(frontmatter["description"]).strip()
    normalized_dir = unicodedata.normalize("NFKC", root.name)
    normalized_name = unicodedata.normalize("NFKC", name)
    if normalized_dir != normalized_name:
        raise SkillPackageError(
            f"skill directory name {root.name!r} must match frontmatter name {name!r}"
        )
    nested = frontmatter.get("metadata", {})
    if not isinstance(nested, dict):
        raise SkillPackageError("skill metadata must be a mapping")
    metadata = tuple(sorted((str(key), str(value)) for key, value in nested.items()))
    raw_hints = str(frontmatter.get("allowed-tools", "")).strip()
    hints = tuple(raw_hints.split()) if raw_hints else ()
    if len(hints) != len(set(hints)):
        raise SkillPackageError("allowed-tools hints must be unique")
    resources, package_digest = _scan_package(root)

    try:
        return SkillPackage(
            name=name,
            description=description,
            body=body,
            license=(
                str(frontmatter["license"]).strip()
                if "license" in frontmatter and str(frontmatter["license"]).strip()
                else None
            ),
            compatibility=(
                str(frontmatter["compatibility"]).strip()
                if "compatibility" in frontmatter
                else None
            ),
            metadata=metadata,
            allowed_tool_hints=hints,
            resources=resources,
            package_digest=package_digest,
        )
    except ValidationError as exc:
        raise SkillPackageError("skill package metadata failed strict validation") from exc
