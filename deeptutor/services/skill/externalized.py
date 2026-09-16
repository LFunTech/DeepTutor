"""PG + ObjectStore-backed dynamic skill packages for production runtimes.

User-authored and hub-imported skills are persisted as package JSON objects in
S3-compatible ObjectStore with PostgreSQL ``resource_objects`` metadata as the
visibility and ownership authority.  Builtin skills remain read-only package
files shipped in the application image.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore
from deeptutor.services.skill.service import (
    _IMPORT_ALLOWED_SUFFIXES,
    _IMPORT_MAX_FILE_BYTES,
    _IMPORT_MAX_FILES,
    _IMPORT_MAX_TOTAL_BYTES,
    _MAX_READ_CHARS,
    _TAGS_FILE,
    BUILTIN_SKILLS_ROOT,
    InvalidSkillNameError,
    InvalidSkillPathError,
    SkillDetail,
    SkillExistsError,
    SkillFileNotFoundError,
    SkillImportError,
    SkillInfo,
    SkillInstallResult,
    SkillNotFoundError,
    SkillReadOnlyError,
    SkillService,
    SkillSummaryEntry,
    TagExistsError,
    TagNotFoundError,
)

_RESOURCE_KIND = "dynamic_skill"
_VOCAB_KIND = "dynamic_skill_vocab"
_PACKAGE_FILENAME = "package.json"
_PACKAGE_MIME = "application/vnd.deeptutor.skill-package+json"
_PACKAGE_FORMAT = "deeptutor.skill-package.v1"


class ExternalizedSkillService:
    """Async skill service whose user layer is PG/ObjectStore-backed."""

    def __init__(self, store, object_store, *, builtin_root: Path | None = BUILTIN_SKILLS_ROOT):
        self.store = store
        self.resources = PostgresObjectResourceStore(store, object_store)
        self._builtin = SkillService(root=Path("/__deeptutor_no_user_skills__"), builtin_root=builtin_root)
        self._policy = SkillService(root=Path("/__deeptutor_skill_policy__"), builtin_root=None)
        self._origin_cache: dict[str, dict[str, Any]] = {}

    # ── PG/ObjectStore package helpers ──────────────────────────────────

    @staticmethod
    def _validate_package_path(rel_path: str) -> str:
        candidate = (rel_path or "SKILL.md").strip() or "SKILL.md"
        rel = Path(candidate)
        if rel.is_absolute() or ".." in rel.parts:
            raise InvalidSkillPathError(f"Illegal skill file path: {rel_path}")
        if not rel.parts or any(not part or part in {".", ".."} for part in rel.parts):
            raise InvalidSkillPathError(f"Illegal skill file path: {rel_path}")
        return rel.as_posix()

    @staticmethod
    def _package_bytes(files: dict[str, str], *, origin: dict[str, Any] | None = None) -> bytes:
        payload = {
            "format": _PACKAGE_FORMAT,
            "files": {key: files[key] for key in sorted(files)},
            "hub_origin": dict(origin or {}),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")

    async def _latest_handles(self, kind: str, resource_id: str | None = None):
        params: tuple[Any, ...]
        rid_clause = ""
        if resource_id is None:
            params = (*self.store._owner, kind)
        else:
            rid_clause = "AND resource_id=%s "
            params = (*self.store._owner, kind, resource_id)
        async with self.store.db.transaction(self.store.scope) as c:
            await self.resources._authorized(c)
            rows = await (
                await c.execute(
                    "SELECT DISTINCT ON (resource_id) * FROM enterprise.resource_objects "
                    "WHERE tenant_id=%s AND owner_id=%s AND resource_kind=%s "
                    f"{rid_clause}AND state='ready' AND deleted_at IS NULL "
                    "ORDER BY resource_id, created_at DESC, id DESC",
                    params,
                )
            ).fetchall()
        return [self.resources._handle(row) for row in rows]

    async def _all_handles(self, kind: str, resource_id: str):
        return await self.resources.list(resource_kind=kind, resource_id=resource_id)

    async def _latest_handle(self, slug: str):
        handles = await self._latest_handles(_RESOURCE_KIND, slug)
        return handles[0] if handles else None

    async def _read_package(self, slug: str) -> dict[str, Any]:
        handle = await self._latest_handle(slug)
        if handle is None:
            raise SkillNotFoundError(slug)
        data = await self.resources.read(handle, filename=_PACKAGE_FILENAME)
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SkillImportError("Stored skill package is corrupt.") from exc
        if not isinstance(payload, dict) or payload.get("format") != _PACKAGE_FORMAT:
            raise SkillImportError("Stored skill package has an unsupported format.")
        files = payload.get("files")
        if not isinstance(files, dict) or not isinstance(files.get("SKILL.md"), str):
            raise SkillImportError("Stored skill package is missing SKILL.md.")
        return payload

    async def _write_package(
        self,
        slug: str,
        files: dict[str, str],
        *,
        origin: dict[str, Any] | None = None,
        cleanup_resource_ids: tuple[str, ...] = (),
    ) -> SkillInfo:
        text = files["SKILL.md"]
        meta, _ = self._policy._parse_frontmatter(text)
        description = str(meta.get("description") or "").strip()
        tags = self._policy._tags_from_meta(meta)
        old_handles = []
        for rid in cleanup_resource_ids:
            old_handles.extend(await self._all_handles(_RESOURCE_KIND, rid))
        await self.resources.put(
            resource_kind=_RESOURCE_KIND,
            resource_id=slug,
            filename=_PACKAGE_FILENAME,
            data=self._package_bytes(files, origin=origin),
            mime_type=_PACKAGE_MIME,
            metadata={"name": slug, "description": description, "tags": tags},
            retention="default",
        )
        for handle in old_handles:
            with contextlib_suppress_all():
                await self.resources.delete(handle)
        if origin is not None:
            self._origin_cache[slug] = dict(origin)
        await self._merge_tags_into_vocab(tags)
        return SkillInfo(name=slug, description=description, tags=tags)

    async def _user_infos(self) -> list[SkillInfo]:
        infos: list[SkillInfo] = []
        for handle in await self._latest_handles(_RESOURCE_KIND):
            try:
                payload = json.loads((await self.resources.read(handle, filename=_PACKAGE_FILENAME)).decode("utf-8"))
            except Exception:
                continue
            files = payload.get("files") if isinstance(payload, dict) else None
            text = files.get("SKILL.md") if isinstance(files, dict) else None
            if not isinstance(text, str):
                continue
            meta, _ = self._policy._parse_frontmatter(text)
            infos.append(
                SkillInfo(
                    name=handle.resource_id,
                    description=str(meta.get("description") or "").strip(),
                    tags=self._policy._tags_from_meta(meta),
                    source="user",
                )
            )
        return sorted(infos, key=lambda item: item.name)

    # ── read API ────────────────────────────────────────────────────────

    async def list_skills(self) -> list[SkillInfo]:
        out = await self._user_infos()
        seen = {info.name for info in out}
        for info in self._builtin.list_skills():
            if info.name not in seen:
                out.append(info)
        return out

    async def get_detail(self, name: str) -> SkillDetail:
        slug = self._policy._validate_name(name)
        try:
            payload = await self._read_package(slug)
        except SkillNotFoundError:
            return self._builtin.get_detail(slug)
        text = payload["files"]["SKILL.md"]
        meta, _ = self._policy._parse_frontmatter(text)
        return SkillDetail(
            name=slug,
            description=str(meta.get("description") or "").strip(),
            content=text,
            tags=self._policy._tags_from_meta(meta),
            source="user",
        )

    async def read_skill_file(self, name: str, rel_path: str = "SKILL.md") -> str:
        slug = self._policy._validate_name(name)
        path = self._validate_package_path(rel_path)
        try:
            payload = await self._read_package(slug)
            files = payload["files"]
            if path not in files:
                raise SkillFileNotFoundError(f"File not found in skill: {name}/{path}")
            text = str(files[path])
        except SkillNotFoundError:
            return self._builtin.read_skill_file(slug, path)
        if len(text) > _MAX_READ_CHARS:
            text = text[:_MAX_READ_CHARS] + "\n\n[... truncated ...]"
        return text

    async def list_skill_files(self, name: str) -> list[str]:
        slug = self._policy._validate_name(name)
        try:
            payload = await self._read_package(slug)
        except SkillNotFoundError:
            return self._builtin.list_skill_files(slug)
        return sorted(path for path in payload["files"] if not Path(path).name.startswith("."))

    async def summary_entries(self) -> list[SkillSummaryEntry]:
        entries: list[SkillSummaryEntry] = []
        for info in await self.list_skills():
            detail = await self.get_detail(info.name)
            meta, _ = self._policy._parse_frontmatter(detail.content)
            available, missing = self._policy._availability(meta)
            entries.append(
                SkillSummaryEntry(
                    name=info.name,
                    description=info.description,
                    available=available,
                    missing=missing,
                    always=bool(meta.get("always")),
                )
            )
        return entries

    async def load_for_context(self, names: list[str]) -> str:
        if not names:
            return ""
        parts: list[str] = []
        for name in names:
            try:
                detail = await self.get_detail(name)
            except (SkillNotFoundError, InvalidSkillNameError):
                continue
            _, body = self._policy._parse_frontmatter(detail.content)
            body = body.strip()
            if body:
                parts.append(f"### Skill: {detail.name}\n\n{body}")
        if not parts:
            return ""
        return (
            "## Active Skills\n"
            "Follow the playbooks below. They override generic defaults.\n\n"
            + "\n\n---\n\n".join(parts)
        )

    async def load_always_for_context(self) -> str:
        names = [e.name for e in await self.summary_entries() if e.always and e.available]
        return await self.load_for_context(names)

    # ── write API ───────────────────────────────────────────────────────

    async def create(
        self, name: str, description: str, content: str, tags: list[str] | None = None
    ) -> SkillInfo:
        slug = self._policy._validate_name(name)
        if await self._latest_handle(slug) is not None:
            raise SkillExistsError(slug)
        clean_tags = self._policy._validate_tag_list(tags)
        body = self._policy._normalize_content(slug, description, content, tags=clean_tags)
        return await self._write_package(slug, {"SKILL.md": body})

    async def update(
        self,
        name: str,
        *,
        description: str | None = None,
        content: str | None = None,
        rename_to: str | None = None,
        tags: list[str] | None = None,
    ) -> SkillInfo:
        slug = self._policy._validate_name(name)
        try:
            payload = await self._read_package(slug)
        except SkillNotFoundError:
            try:
                self._builtin.get_detail(slug)
            except SkillNotFoundError:
                raise
            raise SkillReadOnlyError(f"Skill is builtin (read-only): {slug}") from None
        files = {str(k): str(v) for k, v in payload["files"].items()}
        text = content if content is not None else files["SKILL.md"]
        if description is not None:
            text = self._policy._rewrite_frontmatter(text, description=description.strip())
        if tags is not None:
            text = self._policy._rewrite_frontmatter(text, tags=self._policy._validate_tag_list(tags))
        final_slug = slug
        cleanup = (slug,)
        if rename_to and rename_to != slug:
            final_slug = self._policy._validate_name(rename_to)
            if await self._latest_handle(final_slug) is not None:
                raise SkillExistsError(final_slug)
            text = self._policy._rewrite_frontmatter(text, name=final_slug)
        files["SKILL.md"] = text
        return await self._write_package(
            final_slug,
            files,
            origin=payload.get("hub_origin") if isinstance(payload.get("hub_origin"), dict) else None,
            cleanup_resource_ids=cleanup,
        )

    async def delete(self, name: str) -> None:
        slug = self._policy._validate_name(name)
        handles = await self._all_handles(_RESOURCE_KIND, slug)
        if not handles:
            try:
                self._builtin.get_detail(slug)
            except SkillNotFoundError:
                raise SkillNotFoundError(slug) from None
            raise SkillReadOnlyError(f"Skill is builtin (read-only): {slug}")
        for handle in handles:
            await self.resources.delete(handle)

    async def install_tree(
        self,
        source_dir: str | Path,
        *,
        rename_to: str | None = None,
        fallback_description: str | None = None,
        origin: dict[str, Any] | None = None,
        force: bool = False,
        extra_tags: list[str] | None = None,
    ) -> SkillInstallResult:
        source = Path(source_dir).resolve()
        skill_md = source / "SKILL.md"
        if not skill_md.is_file():
            raise SkillImportError("Package has no SKILL.md at its root.")
        if skill_md.stat().st_size > _IMPORT_MAX_FILE_BYTES:
            raise SkillImportError("SKILL.md exceeds the import size limit.")
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        meta, body = self._policy._parse_frontmatter(text)
        slug = self._policy._validate_name(
            self._policy._slugify(str(rename_to or meta.get("name") or source.name))
        )
        description = str(meta.get("description") or "").strip() or (fallback_description or "").strip()
        if not description:
            raise SkillImportError("SKILL.md has no description and no fallback was provided.")
        tags = self._policy._validate_tag_list(
            (meta.get("tags") if isinstance(meta.get("tags"), list) else []) + list(extra_tags or [])
        )
        if await self._latest_handle(slug) is not None and not force:
            raise SkillExistsError(slug)
        header = yaml.safe_dump(
            self._policy._compose_imported_frontmatter(meta, slug=slug, description=description, tags=tags),
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        files = {"SKILL.md": f"---\n{header}\n---\n\n{body.lstrip()}".rstrip() + "\n"}
        skipped = self._collect_support_files(source, files)
        cleanup = (slug,) if force else ()
        info = await self._write_package(slug, files, origin=origin, cleanup_resource_ids=cleanup)
        return SkillInstallResult(info=info, skipped=skipped)

    def _collect_support_files(self, source: Path, files: dict[str, str]) -> list[tuple[str, str]]:
        skipped: list[tuple[str, str]] = []
        count = 0
        total = 0
        for path in sorted(source.rglob("*")):
            rel = path.relative_to(source)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if path.is_symlink():
                raise SkillImportError(f"Symbolic links are not allowed: {rel}")
            if path.is_dir() or rel.as_posix() == "SKILL.md":
                continue
            if path.suffix.lower() not in _IMPORT_ALLOWED_SUFFIXES:
                skipped.append((rel.as_posix(), "file type not allowed"))
                continue
            size = path.stat().st_size
            if size > _IMPORT_MAX_FILE_BYTES:
                skipped.append((rel.as_posix(), "file exceeds size limit"))
                continue
            count += 1
            total += size
            if count > _IMPORT_MAX_FILES:
                raise SkillImportError("Package has too many files.")
            if total > _IMPORT_MAX_TOTAL_BYTES:
                raise SkillImportError("Package exceeds the total size limit.")
            rel_path = self._validate_package_path(rel.as_posix())
            files[rel_path] = path.read_text(encoding="utf-8", errors="replace")
        return skipped

    # ── hub provenance and tags ─────────────────────────────────────────

    def hub_origin(self, name: str) -> dict[str, Any] | None:
        try:
            slug = self._policy._validate_name(name)
        except InvalidSkillNameError:
            return None
        cached = self._origin_cache.get(slug)
        return dict(cached) if cached else None

    async def get_hub_origin(self, name: str) -> dict[str, Any] | None:
        try:
            payload = await self._read_package(self._policy._validate_name(name))
        except (SkillNotFoundError, InvalidSkillNameError):
            return None
        origin = payload.get("hub_origin")
        return dict(origin) if isinstance(origin, dict) and origin else None

    async def _read_vocab(self) -> list[str]:
        handles = await self._latest_handles(_VOCAB_KIND, _TAGS_FILE)
        if not handles:
            return []
        try:
            data = json.loads((await self.resources.read(handles[0], filename=_PACKAGE_FILENAME)).decode("utf-8"))
        except Exception:
            return []
        raw = data.get("tags") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return []
        return self._policy._dedupe_tags(
            [self._policy._normalize_tag(item) for item in raw if str(item).strip()]
        )

    async def _write_vocab(self, tags: list[str]) -> None:
        old_handles = await self._all_handles(_VOCAB_KIND, _TAGS_FILE)
        data = json.dumps({"tags": self._policy._dedupe_tags(tags)}, ensure_ascii=False).encode("utf-8")
        await self.resources.put(
            resource_kind=_VOCAB_KIND,
            resource_id=_TAGS_FILE,
            filename=_PACKAGE_FILENAME,
            data=data,
            mime_type="application/json",
            metadata={"tags": self._policy._dedupe_tags(tags)},
        )
        for handle in old_handles:
            with contextlib_suppress_all():
                await self.resources.delete(handle)

    async def list_tags(self) -> list[str]:
        vocab = await self._read_vocab()
        found: list[str] = []
        for info in await self._user_infos():
            for tag in info.tags:
                if tag not in found:
                    found.append(tag)
        union = self._policy._dedupe_tags(list(("style", "tool")) + vocab + found)
        if union != vocab:
            await self._write_vocab(union)
        return union

    async def _merge_tags_into_vocab(self, tags: list[str]) -> None:
        if not tags:
            await self.list_tags()
            return
        current = await self.list_tags()
        merged = self._policy._dedupe_tags(current + tags)
        if merged != current:
            await self._write_vocab(merged)

    async def create_tag(self, name: str) -> str:
        tag = self._policy._normalize_tag(name)
        vocab = await self.list_tags()
        if tag in vocab:
            raise TagExistsError(tag)
        await self._write_vocab(vocab + [tag])
        return tag

    async def rename_tag(self, old: str, new: str) -> str:
        old_tag = self._policy._normalize_tag(old)
        new_tag = self._policy._normalize_tag(new)
        vocab = await self.list_tags()
        if old_tag not in vocab:
            raise TagNotFoundError(old_tag)
        if new_tag != old_tag and new_tag in vocab:
            raise TagExistsError(new_tag)
        if new_tag == old_tag:
            return old_tag
        for info in await self._user_infos():
            if old_tag not in info.tags:
                continue
            updated = []
            for tag in info.tags:
                if tag == old_tag:
                    if new_tag not in updated:
                        updated.append(new_tag)
                elif tag not in updated:
                    updated.append(tag)
            await self.update(info.name, tags=updated)
        await self._write_vocab([new_tag if tag == old_tag else tag for tag in vocab])
        return new_tag

    async def delete_tag(self, name: str) -> None:
        tag = self._policy._normalize_tag(name)
        vocab = await self.list_tags()
        if tag not in vocab:
            raise TagNotFoundError(tag)
        for info in await self._user_infos():
            if tag in info.tags:
                await self.update(info.name, tags=[item for item in info.tags if item != tag])
        await self._write_vocab([item for item in vocab if item != tag])


class contextlib_suppress_all:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return True


__all__ = ["ExternalizedSkillService"]
