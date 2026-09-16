"""PG + ObjectStore-backed dynamic personas for production runtimes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore
from deeptutor.services.persona.service import (
    PERSONA_FILE,
    InvalidPersonaNameError,
    PersonaDetail,
    PersonaExistsError,
    PersonaInfo,
    PersonaNotFoundError,
    PersonaService,
)

_RESOURCE_KIND = "dynamic_persona"
_PACKAGE_FILENAME = "package.json"
_PACKAGE_MIME = "application/vnd.deeptutor.persona-package+json"
_PACKAGE_FORMAT = "deeptutor.persona-package.v1"


class ExternalizedPersonaService:
    """Async persona service whose user layer is PG/ObjectStore-backed."""

    def __init__(self, store, object_store):
        self.store = store
        self.resources = PostgresObjectResourceStore(store, object_store)
        self._policy = PersonaService(root=Path("/__deeptutor_persona_policy__"))

    @staticmethod
    def _package_bytes(text: str) -> bytes:
        return json.dumps(
            {"format": _PACKAGE_FORMAT, "files": {PERSONA_FILE: text}},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")

    async def _latest_handles(self, resource_id: str | None = None):
        params: tuple[Any, ...]
        rid_clause = ""
        if resource_id is None:
            params = (*self.store._owner, _RESOURCE_KIND)
        else:
            rid_clause = "AND resource_id=%s "
            params = (*self.store._owner, _RESOURCE_KIND, resource_id)
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

    async def _all_handles(self, slug: str):
        return await self.resources.list(resource_kind=_RESOURCE_KIND, resource_id=slug)

    async def _latest_handle(self, slug: str):
        handles = await self._latest_handles(slug)
        return handles[0] if handles else None

    async def _read_text(self, slug: str) -> str:
        handle = await self._latest_handle(slug)
        if handle is None:
            raise PersonaNotFoundError(slug)
        data = await self.resources.read(handle, filename=_PACKAGE_FILENAME)
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PersonaNotFoundError(slug) from exc
        files = payload.get("files") if isinstance(payload, dict) else None
        text = files.get(PERSONA_FILE) if isinstance(files, dict) else None
        if payload.get("format") != _PACKAGE_FORMAT or not isinstance(text, str):
            raise PersonaNotFoundError(slug)
        return text

    async def _write_text(self, slug: str, text: str, *, cleanup_slug: str | None = None) -> PersonaInfo:
        old_handles = await self._all_handles(cleanup_slug or slug)
        meta, _ = self._policy._parse_frontmatter(text)
        description = str(meta.get("description") or "").strip()
        await self.resources.put(
            resource_kind=_RESOURCE_KIND,
            resource_id=slug,
            filename=_PACKAGE_FILENAME,
            data=self._package_bytes(text),
            mime_type=_PACKAGE_MIME,
            metadata={"name": slug, "description": description},
            retention="default",
        )
        for handle in old_handles:
            await self.resources.delete(handle)
        return PersonaInfo(name=slug, description=description)

    async def list_personas(self) -> list[PersonaInfo]:
        out: list[PersonaInfo] = []
        for handle in await self._latest_handles():
            try:
                text = await self._read_text(handle.resource_id)
            except PersonaNotFoundError:
                continue
            meta, _ = self._policy._parse_frontmatter(text)
            out.append(
                PersonaInfo(
                    name=handle.resource_id,
                    description=str(meta.get("description") or "").strip(),
                )
            )
        return sorted(out, key=lambda item: item.name)

    async def get_detail(self, name: str) -> PersonaDetail:
        slug = self._policy._validate_name(name)
        text = await self._read_text(slug)
        meta, _ = self._policy._parse_frontmatter(text)
        return PersonaDetail(
            name=slug,
            description=str(meta.get("description") or "").strip(),
            content=text,
        )

    async def load_for_context(self, name: str) -> str:
        if not name:
            return ""
        try:
            detail = await self.get_detail(name)
        except (PersonaNotFoundError, InvalidPersonaNameError):
            return ""
        _, body = self._policy._parse_frontmatter(detail.content)
        body = body.strip()
        if not body:
            return ""
        return (
            "## Active Persona\n"
            "Embody the persona below for this entire conversation. It sets your "
            "voice and outranks any tone a mode above prescribes; carry out that "
            "mode's steps in this voice.\n\n"
            f"### Persona: {detail.name}\n\n{body}"
        )

    async def create(self, name: str, description: str, content: str) -> PersonaInfo:
        slug = self._policy._validate_name(name)
        if await self._latest_handle(slug) is not None:
            raise PersonaExistsError(slug)
        text = self._policy._normalize_content(slug, description, content)
        return await self._write_text(slug, text)

    async def update(
        self,
        name: str,
        *,
        description: str | None = None,
        content: str | None = None,
        rename_to: str | None = None,
    ) -> PersonaInfo:
        slug = self._policy._validate_name(name)
        current = await self.get_detail(slug)
        final_slug = slug
        if rename_to and rename_to != slug:
            final_slug = self._policy._validate_name(rename_to)
            if await self._latest_handle(final_slug) is not None:
                raise PersonaExistsError(final_slug)
        new_description = description if description is not None else current.description
        new_body_source = content if content is not None else current.content
        text = self._policy._normalize_content(final_slug, new_description, new_body_source)
        return await self._write_text(final_slug, text, cleanup_slug=slug)

    async def delete(self, name: str) -> None:
        slug = self._policy._validate_name(name)
        handles = await self._all_handles(slug)
        if not handles:
            raise PersonaNotFoundError(slug)
        for handle in handles:
            await self.resources.delete(handle)


__all__ = ["ExternalizedPersonaService"]
