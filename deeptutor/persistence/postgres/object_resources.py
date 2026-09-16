"""Generic PG-authorized ObjectStore resources.

This module is the shared production path for durable non-attachment files
such as reading originals, workspace outputs, generated artifacts, exports and
persistent intermediate manifests. PostgreSQL owns visibility/lifecycle;
ObjectStore keys are never authorization tokens.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.governance import RuntimeGovernanceStore
from deeptutor.runtime.externalized_providers import ObjectBlobRef, ResourceHandle

_SAFE_KIND = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")


def _coerce_kind(value: str) -> str:
    kind = str(value or "").strip()
    if not _SAFE_KIND.fullmatch(kind):
        raise ValueError("invalid resource kind")
    return kind


def _coerce_resource_id(value: str) -> str:
    resource_id = str(value or "").strip()
    if not resource_id or len(resource_id) > 512:
        raise ValueError("invalid resource id")
    return resource_id


def _coerce_filename(value: str) -> str:
    raw = str(value or "").strip()
    if "/" in raw or "\\" in raw:
        raise ValueError("invalid filename")
    name = Path(raw).name.strip()
    if not name or name in {".", ".."} or len(name) > 255:
        raise ValueError("invalid filename")
    return name


class PostgresObjectResourceStore:
    """PG metadata + S3-compatible bytes for durable business resources."""

    def __init__(self, store, object_store, *, bucket: str = "") -> None:
        self.store = store
        self.object_store = object_store
        configured_bucket = getattr(getattr(object_store, "config", None), "bucket", "")
        self.bucket = str(bucket or configured_bucket or "").strip()
        if not self.bucket:
            raise ValueError("object-store bucket is required for PG resources")

    async def _io(self, fn, *args, **kwargs):
        task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        result = task.result()
        if cancelled:
            raise asyncio.CancelledError()
        return result

    async def _authorized(self, c) -> None:
        row = await (
            await c.execute(
                "SELECT id FROM enterprise.users WHERE tenant_id=%s AND id=%s "
                "AND NOT disabled AND deleted_at IS NULL",
                self.store._owner,
            )
        ).fetchone()
        if row is None:
            raise PermissionError("resource owner unavailable")

    def _object_key(self, resource_kind: str, resource_id: str, object_id: UUID) -> str:
        tenant_id, owner_id = self.store._owner
        owner_hash = hashlib.sha256(str(owner_id).encode()).hexdigest()
        resource_hash = hashlib.sha256(resource_id.encode()).hexdigest()
        return f"tenants/{tenant_id}/owners/{owner_hash}/{resource_kind}/{resource_hash}/{object_id}"

    @staticmethod
    def _handle(row) -> ResourceHandle:
        return ResourceHandle(
            tenant_id=str(row["tenant_id"]),
            owner_id=str(row["owner_id"]),
            resource_kind=row["resource_kind"],
            resource_id=row["resource_id"],
            object_id=str(row["id"]),
            version=int(row["version"]),
            state=row["state"],
            size_bytes=int(row["size_bytes"]),
            sha256=row["content_hash"],
            mime_type=row["mime_type"] or "application/octet-stream",
        )

    @staticmethod
    def _blob_ref(row) -> ObjectBlobRef:
        return ObjectBlobRef(
            key=row["object_key"],
            size_bytes=int(row["size_bytes"]),
            sha256=row["content_hash"],
            content_type=row["mime_type"] or "application/octet-stream",
        )

    def proxy_url(self, handle: ResourceHandle, *, filename: str) -> str:
        filename = _coerce_filename(filename)
        return "/files/resources/" + "/".join(
            quote(v, safe="")
            for v in (
                handle.resource_kind,
                handle.resource_id,
                handle.object_id,
                filename,
            )
        )

    async def put(
        self,
        *,
        resource_kind: str,
        resource_id: str,
        filename: str,
        data: bytes,
        mime_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
        retention: str = "default",
    ) -> ResourceHandle:
        if type(data) is not bytes:
            raise ValueError("resource data must be bytes")
        kind = _coerce_kind(resource_kind)
        rid = _coerce_resource_id(resource_id)
        name = _coerce_filename(filename)
        digest = hashlib.sha256(data).hexdigest()
        object_id = uuid4()
        object_key = self._object_key(kind, rid, object_id)
        meta = {**(metadata or {}), "filename": name}
        content_type = str(mime_type or "application/octet-stream")
        try:
            async with self.store.db.transaction(self.store.scope) as c:
                await self._authorized(c)
                await c.execute(
                    "INSERT INTO enterprise.resource_objects"
                    "(tenant_id,owner_id,id,resource_kind,resource_id,bucket,object_key,"
                    "content_hash,size_bytes,mime_type,state,retention,metadata,created_by) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s)",
                    (
                        *self.store._owner,
                        object_id,
                        kind,
                        rid,
                        self.bucket,
                        object_key,
                        digest,
                        len(data),
                        content_type,
                        retention,
                        Jsonb(meta),
                        self.store._owner[1],
                    ),
                )
            ref = await self._io(
                self.object_store.put_bytes,
                object_key,
                data,
                expected_sha256=digest,
                content_type=content_type,
            )
            if ref.key != object_key or ref.size_bytes != len(data) or ref.sha256 != digest:
                raise OSError("object-store verification mismatch")
            async with self.store.db.transaction(self.store.scope) as c:
                await self._authorized(c)
                result = await c.execute(
                    "UPDATE enterprise.resource_objects "
                    "SET state='ready',updated_at=now(),cleanup_error='' "
                    "WHERE tenant_id=%s AND owner_id=%s AND id=%s AND state='pending'",
                    (*self.store._owner, object_id),
                )
                if result.rowcount != 1:
                    raise RuntimeError("resource object candidate was withdrawn")
                row = await (
                    await c.execute(
                        "SELECT * FROM enterprise.resource_objects "
                        "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                        (*self.store._owner, object_id),
                    )
                ).fetchone()
                await RuntimeGovernanceStore(self.store)._audit(
                    c,
                    "object.created",
                    actor_id=self.store._owner[1],
                    scope_kind="resource",
                    scope_id=str(object_id),
                    resource_kind=kind,
                    resource_id=rid,
                    summary={
                        "object_id": str(object_id),
                        "resource_kind": kind,
                        "resource_id": rid,
                        "filename": name,
                        "size_bytes": len(data),
                        "sha256": digest,
                    },
                )
        except BaseException as exc:
            exc.resource_operation_id = str(object_id)
            await self._record_cleanup_request(object_id, error="upload_publish_failed")
            raise
        return self._handle(row)

    async def _record_cleanup_request(self, object_id: UUID, *, error: str = "") -> None:
        try:
            async with self.store.db.transaction(self.store.scope) as c:
                await c.execute(
                    "UPDATE enterprise.resource_objects "
                    "SET state='delete-pending',cleanup_error=%s,updated_at=now() "
                    "WHERE tenant_id=%s AND owner_id=%s AND id=%s AND state<>'deleted'",
                    (str(error or ""), *self.store._owner, object_id),
                )
                await c.execute(
                    "INSERT INTO enterprise.resource_cleanup_jobs"
                    "(tenant_id,owner_id,object_id,state,last_error) "
                    "VALUES(%s,%s,%s,'pending',%s) "
                    "ON CONFLICT(tenant_id,owner_id,object_id) DO UPDATE "
                    "SET state='pending',last_error=EXCLUDED.last_error,updated_at=now()",
                    (*self.store._owner, object_id, str(error or "")),
                )
        except Exception:
            return

    async def list(
        self, *, resource_kind: str, resource_id: str, include_deleted: bool = False
    ) -> list[ResourceHandle]:
        kind = _coerce_kind(resource_kind)
        rid = _coerce_resource_id(resource_id)
        state_clause = "" if include_deleted else "AND state<>'deleted'"
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            rows = await (
                await c.execute(
                    "SELECT * FROM enterprise.resource_objects "
                    "WHERE tenant_id=%s AND owner_id=%s AND resource_kind=%s AND resource_id=%s "
                    f"{state_clause} ORDER BY version,id",
                    (*self.store._owner, kind, rid),
                )
            ).fetchall()
        return [self._handle(row) for row in rows]

    async def _visible_row(self, handle: ResourceHandle):
        kind = _coerce_kind(handle.resource_kind)
        rid = _coerce_resource_id(handle.resource_id)
        object_id = UUID(str(handle.object_id))
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            row = await (
                await c.execute(
                    "SELECT * FROM enterprise.resource_objects "
                    "WHERE tenant_id=%s AND owner_id=%s AND resource_kind=%s "
                    "AND resource_id=%s AND id=%s AND state='ready'",
                    (*self.store._owner, kind, rid, object_id),
                )
            ).fetchone()
        if row is None:
            raise FileNotFoundError("resource object not found")
        return row

    async def read(self, handle: ResourceHandle, *, filename: str = "") -> bytes:
        if filename:
            _coerce_filename(filename)
        row = await self._visible_row(handle)
        data = await self._io(self.object_store.get_bytes, self._blob_ref(row))
        if len(data) != row["size_bytes"] or hashlib.sha256(data).hexdigest() != row["content_hash"]:
            raise OSError("resource object integrity mismatch")
        return data

    async def delete(self, handle: ResourceHandle) -> dict[str, Any]:
        kind = _coerce_kind(handle.resource_kind)
        rid = _coerce_resource_id(handle.resource_id)
        object_id = UUID(str(handle.object_id))
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            result = await c.execute(
                "UPDATE enterprise.resource_objects "
                "SET state='delete-pending',updated_at=now() "
                "WHERE tenant_id=%s AND owner_id=%s AND resource_kind=%s "
                "AND resource_id=%s AND id=%s AND state<>'deleted'",
                (*self.store._owner, kind, rid, object_id),
            )
            if result.rowcount != 1:
                raise FileNotFoundError("resource object not found")
            await c.execute(
                "INSERT INTO enterprise.resource_cleanup_jobs"
                "(tenant_id,owner_id,object_id,state,last_error) VALUES(%s,%s,%s,'pending','') "
                "ON CONFLICT(tenant_id,owner_id,object_id) DO UPDATE "
                "SET state='pending',last_error='',updated_at=now()",
                (*self.store._owner, object_id),
            )
            await RuntimeGovernanceStore(self.store)._audit(
                c,
                "object.delete_requested",
                actor_id=self.store._owner[1],
                scope_kind="resource",
                scope_id=str(object_id),
                resource_kind=kind,
                resource_id=rid,
                summary={
                    "object_id": str(object_id),
                    "resource_kind": kind,
                    "resource_id": rid,
                    "state": "delete-pending",
                },
            )
        return await self.cleanup_pending(resource_kind=kind)

    async def list_cleanup(
        self, *, resource_kind: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        kind = _coerce_kind(resource_kind) if resource_kind else None
        limit = max(1, min(int(limit), 1000))
        kind_clause = "AND r.resource_kind=%s" if kind else ""
        params = (*self.store._owner, *( [kind] if kind else [] ), limit)
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            rows = await (
                await c.execute(
                    "SELECT r.id AS object_id,r.resource_kind,r.resource_id,j.state,j.attempt,"
                    "j.last_error,r.cleanup_error "
                    "FROM enterprise.resource_objects r "
                    "JOIN enterprise.resource_cleanup_jobs j "
                    "ON (j.tenant_id,j.owner_id,j.object_id)=(r.tenant_id,r.owner_id,r.id) "
                    "WHERE r.tenant_id=%s AND r.owner_id=%s "
                    "AND r.state='delete-pending' "
                    f"{kind_clause} "
                    "ORDER BY j.not_before,r.updated_at,r.id LIMIT %s",
                    params,
                )
            ).fetchall()
        return [
            {
                "object_id": str(row["object_id"]),
                "resource_kind": row["resource_kind"],
                "resource_id": row["resource_id"],
                "state": row["state"],
                "attempt": int(row["attempt"]),
                "last_error": row["last_error"] or row["cleanup_error"] or "",
            }
            for row in rows
        ]

    async def cleanup_pending(
        self, *, resource_kind: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        completed = 0
        errors: list[dict[str, str]] = []
        for item in await self.list_cleanup(resource_kind=resource_kind, limit=limit):
            object_id = UUID(item["object_id"])
            try:
                async with self.store.db.transaction(self.store.scope) as c:
                    await self._authorized(c)
                    row = await (
                        await c.execute(
                            "SELECT * FROM enterprise.resource_objects "
                            "WHERE tenant_id=%s AND owner_id=%s AND id=%s "
                            "AND state='delete-pending' FOR UPDATE",
                            (*self.store._owner, object_id),
                        )
                    ).fetchone()
                    if row is None:
                        continue
                    await c.execute(
                        "UPDATE enterprise.resource_cleanup_jobs "
                        "SET state='running',last_error='',updated_at=now() "
                        "WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                        (*self.store._owner, object_id),
                    )
                await self._io(self.object_store.delete, self._blob_ref(row))
                async with self.store.db.transaction(self.store.scope) as c:
                    await c.execute(
                        "UPDATE enterprise.resource_objects "
                        "SET state='deleted',cleanup_error='',deleted_at=now(),updated_at=now() "
                        "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                        (*self.store._owner, object_id),
                    )
                    await c.execute(
                        "UPDATE enterprise.resource_cleanup_jobs "
                        "SET state='done',attempt=attempt+1,last_error='',updated_at=now() "
                        "WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                        (*self.store._owner, object_id),
                    )
                completed += 1
            except Exception as exc:
                error = getattr(exc, "code", "") or type(exc).__name__
                async with self.store.db.transaction(self.store.scope) as c:
                    await c.execute(
                        "UPDATE enterprise.resource_objects "
                        "SET cleanup_error=%s,updated_at=now() "
                        "WHERE tenant_id=%s AND owner_id=%s AND id=%s AND state='delete-pending'",
                        (error, *self.store._owner, object_id),
                    )
                    await c.execute(
                        "INSERT INTO enterprise.resource_cleanup_jobs"
                        "(tenant_id,owner_id,object_id,state,attempt,last_error) "
                        "VALUES(%s,%s,%s,'failed',1,%s) "
                        "ON CONFLICT(tenant_id,owner_id,object_id) DO UPDATE "
                        "SET state='failed',attempt=enterprise.resource_cleanup_jobs.attempt+1,"
                        "last_error=EXCLUDED.last_error,updated_at=now()",
                        (*self.store._owner, object_id, error),
                    )
                errors.append({"object_id": str(object_id), "error": error})
        remaining = await self.list_cleanup(resource_kind=resource_kind, limit=1)
        return {"completed": completed, "pending": len(remaining), "errors": errors}
