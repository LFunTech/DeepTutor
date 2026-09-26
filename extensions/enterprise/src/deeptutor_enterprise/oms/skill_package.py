"""云端 Skill 完整 ZIP 的无副作用校验；不负责授权、持久化或执行。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import PurePosixPath
import re
import zipfile

import yaml

_MAX_ZIP_BYTES = 20_000_000
_MAX_TOTAL_BYTES = 20_000_000
_MAX_FILE_BYTES = 1_000_000
_MAX_FILES = 500
_MAX_RATIO = 100
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
_ALLOWED_SUFFIXES = frozenset(
    {
        "",
        ".md",
        ".markdown",
        ".txt",
        ".rst",
        ".py",
        ".js",
        ".mjs",
        ".ts",
        ".sh",
        ".rb",
        ".lua",
        ".r",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".csv",
        ".tsv",
        ".html",
        ".htm",
        ".css",
        ".xml",
        ".sql",
        ".jinja",
        ".j2",
        ".tmpl",
        ".template",
    }
)
_FORBIDDEN_METADATA = frozenset({"owner", "source", "status", "published", "review_status"})


class SkillPackageRejected(ValueError):
    """ZIP 或 SKILL.md 不符合云端安全导入契约。"""


@dataclass(frozen=True, slots=True)
class SkillArchive:
    name: str
    description: str
    body: str
    files: tuple[tuple[str, bytes], ...]
    sha256: str


class _UniqueYamlLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise SkillPackageRejected("frontmatter keys must be unique strings")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _safe_path(raw: str) -> str:
    if not raw or "\\" in raw or "\x00" in raw or any(ord(c) < 32 for c in raw):
        raise SkillPackageRejected("unsafe archive path")
    path = PurePosixPath(raw)
    parts = raw.split("/")
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} or part.startswith(".") for part in parts)
        or ":" in parts[0]
        or parts[0] == "__MACOSX"
    ):
        raise SkillPackageRejected("unsafe archive path")
    return path.as_posix()


def _frontmatter(skill_text: str) -> tuple[str, str, str]:
    match = _FRONTMATTER.match(skill_text)
    if match is None:
        raise SkillPackageRejected("SKILL.md requires YAML frontmatter")
    try:
        metadata = yaml.load(match.group(1), Loader=_UniqueYamlLoader)
    except yaml.YAMLError as error:
        raise SkillPackageRejected("SKILL.md has invalid YAML frontmatter") from error
    if not isinstance(metadata, dict) or _FORBIDDEN_METADATA.intersection(metadata):
        raise SkillPackageRejected("SKILL.md contains invalid or authority-owned metadata")
    name = metadata.get("name")
    description = metadata.get("description")
    body = skill_text[match.end() :].strip()
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise SkillPackageRejected("SKILL.md name is invalid")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise SkillPackageRejected("SKILL.md description is invalid")
    if not body:
        raise SkillPackageRejected("SKILL.md body is empty")
    return name, description.strip(), body


def validate_skill_archive(payload: bytes) -> SkillArchive:
    """解析完整包但不展开到磁盘、不运行脚本、不采信包内 owner/状态。"""

    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_ZIP_BYTES:
        raise SkillPackageRejected("ZIP payload is missing or oversized")
    files: dict[str, bytes] = {}
    total = 0
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > _MAX_FILES * 2:
                raise SkillPackageRejected("ZIP has an invalid file count")
            file_count = 0
            for info in entries:
                path = _safe_path(info.filename[:-1] if info.is_dir() else info.filename)
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise SkillPackageRejected("symbolic links are forbidden")
                if info.is_dir():
                    continue
                file_count += 1
                if file_count > _MAX_FILES:
                    raise SkillPackageRejected("ZIP has an invalid file count")
                if path in files:
                    raise SkillPackageRejected("ZIP contains duplicate file paths")
                if info.flag_bits & 1:
                    raise SkillPackageRejected("encrypted ZIP entries are forbidden")
                if PurePosixPath(path).suffix.lower() not in _ALLOWED_SUFFIXES:
                    raise SkillPackageRejected("ZIP contains a forbidden file type")
                if info.file_size > _MAX_FILE_BYTES:
                    raise SkillPackageRejected("ZIP entry is oversized")
                if info.file_size and (
                    not info.compress_size or info.file_size / info.compress_size > _MAX_RATIO
                ):
                    raise SkillPackageRejected("ZIP compression ratio is unsafe")
                total += info.file_size
                if total > _MAX_TOTAL_BYTES:
                    raise SkillPackageRejected("ZIP expands beyond the total size limit")
                with archive.open(info) as source:
                    content = source.read(_MAX_FILE_BYTES + 1)
                if len(content) != info.file_size or b"\x00" in content:
                    raise SkillPackageRejected("ZIP entry is corrupt or not text")
                content.decode("utf-8")
                files[path] = content
    except (zipfile.BadZipFile, RuntimeError, OSError, UnicodeDecodeError) as error:
        raise SkillPackageRejected("ZIP is corrupt or contains non-UTF-8 content") from error

    skill_paths = [path for path in files if PurePosixPath(path).name == "SKILL.md"]
    if len(skill_paths) != 1:
        raise SkillPackageRejected("ZIP must contain exactly one SKILL.md")
    skill_path = skill_paths[0]
    parts = skill_path.split("/")
    if len(parts) not in (1, 2):
        raise SkillPackageRejected("SKILL.md must be at package root")
    wrapper = parts[0] if len(parts) == 2 else ""
    if wrapper and any(not path.startswith(wrapper + "/") for path in files):
        raise SkillPackageRejected("ZIP has multiple package roots")
    name, description, body = _frontmatter(files[skill_path].decode("utf-8"))
    if wrapper and wrapper != name:
        raise SkillPackageRejected("package directory differs from SKILL.md name")
    normalized = tuple(
        sorted(
            (path[len(wrapper) + 1 :] if wrapper else path, data) for path, data in files.items()
        )
    )
    return SkillArchive(
        name=name,
        description=description,
        body=body,
        files=normalized,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
