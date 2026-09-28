"""企业运行时 Skill 服务：学校包优先，OMS global Skill 仅按显式授权可见。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from deeptutor.services.skill.externalized import ExternalizedSkillService
from deeptutor.services.skill.service import (
    _MAX_READ_CHARS,
    BUILTIN_SKILLS_ROOT,
    InvalidSkillNameError,
    SkillDetail,
    SkillFileNotFoundError,
    SkillInfo,
    SkillNotFoundError,
    SkillReadOnlyError,
    SkillSummaryEntry,
)

from ..context import current_token
from .skill_store import _is_packaged_builtin, resolve_authorized_global_skill


def _resolve_scoped_store(value: Any) -> Any | None:
    if value is None:
        return None
    if hasattr(value, "db") and hasattr(value, "scope"):
        return value
    getter = getattr(value, "get", None)
    if callable(getter):
        candidate = getter()
        if hasattr(candidate, "db") and hasattr(candidate, "scope"):
            return candidate
    return value


def _resolve_object_store(value: Any, fallback: Any) -> Any:
    if value is not None:
        if hasattr(value, "put_bytes") and hasattr(value, "get_bytes"):
            return value
        getter = getattr(value, "get", None)
        if callable(getter):
            candidate = getter()
            if hasattr(candidate, "put_bytes") and hasattr(candidate, "get_bytes"):
                return candidate
    if fallback is not None:
        return fallback
    raise RuntimeError("enterprise Skill ObjectStore is unavailable")


def _current_webhook_app_id() -> int | None:
    try:
        claims = jwt.get_unverified_claims(current_token())
    except (PermissionError, JWTError, ValueError, TypeError):
        return None
    eduplus2 = claims.get("eduplus2")
    if not isinstance(eduplus2, dict):
        return None
    value = eduplus2.get("external_app_id")
    if isinstance(value, int) and value > 0:
        return value
    text = str(value or "").strip()
    if text.isascii() and text.isdecimal():
        number = int(text)
        if number > 0:
            return number
    return None


class EnterpriseRuntimeSkillService:
    """学校运行时 Skill 组合视图。

    本校用户/租户 Skill 由 core externalized service 管理；随程序打包的 builtin
    在企业学校运行时默认不可见，后续须走独立打包版本授权目录。OMS global
    Skill 只在学校授权、发布版本与生命周期都通过应用逻辑校验后，作为只读
    admin 层补充。同名学校 Skill 始终优先于 global Skill。
    """

    def __init__(
        self,
        enterprise: Any,
        store: Any,
        object_store: Any,
        *,
        builtin_root: Path | None = BUILTIN_SKILLS_ROOT,
    ) -> None:
        if store is None or not hasattr(store, "db") or not hasattr(store, "scope"):
            raise RuntimeError("enterprise Skill store is unavailable")
        self.enterprise = enterprise
        self.store = store
        self._base = ExternalizedSkillService(store, object_store, builtin_root=None)
        self._policy = self._base._policy

    @property
    def resources(self):  # pragma: no cover - compatibility for existing callers
        return self._base.resources

    @staticmethod
    def _files_from_archive(archive) -> dict[str, str]:
        files: dict[str, str] = {}
        for path, data in archive.files:
            files[str(path)] = bytes(data).decode("utf-8", errors="replace")
        return files

    def _school_id(self) -> UUID:
        return UUID(str(self.store.scope.tenant_id))

    async def _global_names(self) -> list[str]:
        school_id = self._school_id()
        async with self.store.db.transaction(self.store.scope) as c:
            rows = await (
                await c.execute(
                    "SELECT name FROM oms.skill_grants "
                    "WHERE tenant_id=%s AND status='active' AND expires_at>clock_timestamp() "
                    "ORDER BY name",
                    (school_id,),
                )
            ).fetchall()
        return [str(row["name"]) for row in rows]

    async def _resolve_global(self, slug: str):
        return await resolve_authorized_global_skill(
            self.enterprise,
            self._school_id(),
            slug,
            webhook_app_id=_current_webhook_app_id(),
        )

    async def _authorized_global_infos(self, hidden: set[str]) -> list[SkillInfo]:
        infos: list[SkillInfo] = []
        for name in await self._global_names():
            if name in hidden:
                continue
            authorized = await self._resolve_global(name)
            if authorized is None:
                continue
            archive = authorized.archive
            infos.append(
                SkillInfo(
                    name=archive.name,
                    description=archive.description,
                    tags=list(archive.tags),
                    source="admin",
                )
            )
        return infos

    async def list_skills(self) -> list[SkillInfo]:
        visible = await self._base.list_skills()
        hidden = {info.name for info in visible}
        return visible + await self._authorized_global_infos(hidden)

    async def get_detail(self, name: str) -> SkillDetail:
        slug = self._policy._validate_name(name)
        try:
            return await self._base.get_detail(slug)
        except SkillNotFoundError:
            authorized = await self._resolve_global(slug)
            if authorized is None:
                raise SkillNotFoundError(slug) from None
            archive = authorized.archive
            files = self._files_from_archive(archive)
            return SkillDetail(
                name=archive.name,
                description=archive.description,
                content=files["SKILL.md"],
                tags=list(archive.tags),
                source="admin",
            )

    async def read_skill_file(self, name: str, rel_path: str = "SKILL.md") -> str:
        slug = self._policy._validate_name(name)
        path = self._base._validate_package_path(rel_path)
        try:
            return await self._base.read_skill_file(slug, path)
        except SkillNotFoundError:
            authorized = await self._resolve_global(slug)
            if authorized is None:
                raise SkillNotFoundError(slug) from None
            files = self._files_from_archive(authorized.archive)
            if path not in files:
                raise SkillFileNotFoundError(f"File not found in skill: {name}/{path}")
            text = files[path]
            if len(text) > _MAX_READ_CHARS:
                text = text[:_MAX_READ_CHARS] + "\n\n[... truncated ...]"
            return text

    async def list_skill_files(self, name: str) -> list[str]:
        slug = self._policy._validate_name(name)
        try:
            return await self._base.list_skill_files(slug)
        except SkillNotFoundError:
            authorized = await self._resolve_global(slug)
            if authorized is None:
                raise SkillNotFoundError(slug) from None
            return sorted(
                path
                for path, _data in authorized.archive.files
                if not Path(path).name.startswith(".")
            )

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
        names = [
            entry.name for entry in await self.summary_entries() if entry.always and entry.available
        ]
        return await self.load_for_context(names)

    def _reject_builtin_mutation(self, name: str) -> None:
        slug = self._policy._validate_name(name)
        if _is_packaged_builtin(slug):
            raise SkillReadOnlyError(f"Skill is builtin (read-only): {slug}")

    async def create(self, name: str, *args: Any, **kwargs: Any):
        self._reject_builtin_mutation(name)
        return await self._base.create(name, *args, **kwargs)

    async def update(self, name: str, *args: Any, **kwargs: Any):
        self._reject_builtin_mutation(name)
        rename_to = kwargs.get("rename_to")
        if rename_to:
            self._reject_builtin_mutation(str(rename_to))
        return await self._base.update(name, *args, **kwargs)

    async def delete(self, name: str, *args: Any, **kwargs: Any):
        self._reject_builtin_mutation(name)
        return await self._base.delete(name, *args, **kwargs)

    async def install_tree(self, *args: Any, **kwargs: Any):
        return await self._base.install_tree(*args, **kwargs)

    async def list_tags(self):
        return await self._base.list_tags()

    async def create_tag(self, *args: Any, **kwargs: Any):
        return await self._base.create_tag(*args, **kwargs)

    async def rename_tag(self, *args: Any, **kwargs: Any):
        return await self._base.rename_tag(*args, **kwargs)

    async def delete_tag(self, *args: Any, **kwargs: Any):
        return await self._base.delete_tag(*args, **kwargs)


def enterprise_skill_service_factory(
    enterprise: Any,
    *,
    builtin_root: Path | None = BUILTIN_SKILLS_ROOT,
):
    """返回可挂到 ApplicationProviders 的企业 Skill service factory。"""

    def factory() -> EnterpriseRuntimeSkillService:
        from deeptutor.core.providers import get_providers

        providers = get_providers()
        if providers is None:
            raise RuntimeError("enterprise providers are unavailable")
        store = _resolve_scoped_store(providers.store)
        object_store = _resolve_object_store(
            providers.object_store, getattr(enterprise, "object_store", None)
        )
        return EnterpriseRuntimeSkillService(
            enterprise,
            store,
            object_store,
            builtin_root=builtin_root,
        )

    return factory


__all__ = ["EnterpriseRuntimeSkillService", "enterprise_skill_service_factory"]
