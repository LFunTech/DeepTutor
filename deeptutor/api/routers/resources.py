"""Proxy endpoints for PG-authorized ObjectStore resources."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from deeptutor.api.utils.http_headers import content_disposition
from deeptutor.core.providers import get_providers
from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore
from deeptutor.runtime.externalized_providers import ResourceHandle

router = APIRouter()


def _store() -> PostgresObjectResourceStore:
    providers = get_providers()
    if providers is None or providers.store is None or providers.object_store is None:
        raise HTTPException(status_code=501, detail="ObjectStore resource provider required")
    return PostgresObjectResourceStore(providers.store, providers.object_store)


@router.get("/{resource_kind}/{resource_id}/{object_id}/{filename:path}")
async def get_resource_object(
    resource_kind: str,
    resource_id: str,
    object_id: str,
    filename: str,
):
    handle = ResourceHandle(
        tenant_id="",
        owner_id="",
        resource_kind=resource_kind,
        resource_id=resource_id,
        object_id=object_id,
        version=1,
        state="ready",
        size_bytes=0,
        sha256="",
        mime_type="application/octet-stream",
    )
    try:
        data = await _store().read(handle, filename=filename)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Resource object not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Resource access denied") from None
    return Response(
        content=data,
        media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(filename),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
