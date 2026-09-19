"""Proxy and API endpoints for PG-authorized ObjectStore resources."""

from __future__ import annotations

import mimetypes
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from deeptutor.api.utils.http_headers import content_disposition
from deeptutor.core.providers import get_providers
from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore
from deeptutor.runtime.externalized_providers import ResourceHandle

router = APIRouter()
api_router = APIRouter()


class UploadIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modality: Literal["file", "image", "audio", "video", "document"] = "file"
    mime_type: str = Field(default="application/octet-stream", min_length=1, max_length=255)
    size_bytes: int = Field(gt=0, le=512 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    purpose: str = Field(default="chat_turn", min_length=1, max_length=128)
    session_id: str = Field(default="", max_length=256)
    filename: str = Field(default="upload.bin", min_length=1, max_length=255)
    expires_seconds: int = Field(default=900, ge=60, le=3600)


class CompleteUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_kind: str = Field(default="turn_input", min_length=1, max_length=64)


def _scoped_store(provider):
    if hasattr(provider, "get") and callable(provider.get):
        return provider.get()
    return provider


def _store() -> PostgresObjectResourceStore:
    providers = get_providers()
    if providers is None or providers.store is None or providers.object_store is None:
        raise HTTPException(status_code=501, detail="ObjectStore resource provider required")
    try:
        scoped = _scoped_store(providers.store)
        return PostgresObjectResourceStore(scoped, providers.object_store)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Resource access denied") from None
    except Exception as exc:
        raise HTTPException(status_code=503, detail="ObjectStore resource provider unavailable") from exc


@api_router.post("/upload-intents")
async def create_upload_intent(payload: UploadIntentRequest):
    try:
        return await _store().create_upload_intent(
            modality=payload.modality,
            mime_type=payload.mime_type,
            size_bytes=payload.size_bytes,
            sha256=payload.sha256,
            purpose=payload.purpose,
            session_id=payload.session_id,
            filename=payload.filename,
            expires_seconds=payload.expires_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Resource access denied") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="ObjectStore resource provider unavailable") from exc


@api_router.post("/upload-intents/{resource_id}/complete")
async def complete_upload_intent(resource_id: str, payload: CompleteUploadRequest | None = None):
    try:
        handle = await _store().complete_upload_intent(
            resource_id=resource_id,
            resource_kind=(payload.resource_kind if payload is not None else "turn_input"),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Resource upload intent not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Resource access denied") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="ObjectStore resource provider unavailable") from exc
    return {
        "resource_id": handle.resource_id,
        "object_id": handle.object_id,
        "resource_kind": handle.resource_kind,
        "state": handle.state,
        "size_bytes": handle.size_bytes,
        "sha256": handle.sha256,
        "mime_type": handle.mime_type,
    }


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
