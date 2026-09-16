"""TMS/OMS governance API contracts for externalized runtime state."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_admin
from deeptutor.core.providers import get_providers
from deeptutor.persistence.postgres.governance import RuntimeGovernanceStore
from deeptutor.services.auth import TokenPayload

tms_router = APIRouter()
oms_router = APIRouter()


class SaveSettingRequest(BaseModel):
    desired: dict[str, Any] = Field(default_factory=dict)
    scope_kind: Literal["platform", "tenant", "owner"] = "tenant"
    scope_id: str = ""


class ActivateSettingRequest(BaseModel):
    scope_kind: Literal["platform", "tenant", "owner"] = "tenant"
    scope_id: str = ""


class UpsertSecretReferenceRequest(BaseModel):
    provider: str = "env"
    reference: str
    status: Literal["saved", "active", "failed", "draining", "missing"] = "saved"
    scope_kind: Literal["platform", "tenant", "owner"] = "tenant"
    scope_id: str = ""


def _store_from_provider(value):
    if value is None:
        return None
    if hasattr(value, "get") and callable(value.get):
        return value.get()
    return value


def _governance_store(request: Request) -> RuntimeGovernanceStore:
    providers = get_providers()
    provider_store = getattr(providers, "store", None) if providers is not None else None
    store = _store_from_provider(provider_store)
    if store is None:
        container = getattr(request.app.state, "application_container", None)
        container_providers = getattr(container, "providers", None)
        store = _store_from_provider(getattr(container_providers, "store", None))
        if store is None:
            store = _store_from_provider(getattr(container, "store_provider", None))
    if store is None:
        raise HTTPException(503, "PostgreSQL governance store is not configured")
    return RuntimeGovernanceStore(store)


def _actor_id(current: TokenPayload) -> str:
    actor = current.user_id or current.username
    if not actor:
        raise HTTPException(403, "Authenticated actor is required")
    return actor


@tms_router.put("/settings/{key}")
async def save_runtime_setting(
    key: str,
    body: SaveSettingRequest,
    request: Request,
    current: TokenPayload = Depends(require_admin),
) -> dict[str, Any]:
    """Save a tenant-managed runtime setting without persisting Secret plaintext."""

    try:
        return await _governance_store(request).save_setting(
            key=key,
            desired=body.desired,
            actor_id=_actor_id(current),
            scope_kind=body.scope_kind,
            scope_id=body.scope_id,
        )
    except PermissionError as exc:
        raise HTTPException(403, "Governance actor scope mismatch") from exc


@tms_router.post("/settings/{key}/activate")
async def activate_runtime_setting(
    key: str,
    request: Request,
    body: ActivateSettingRequest | None = None,
    current: TokenPayload = Depends(require_admin),
) -> dict[str, Any]:
    """Promote a desired setting version to active for the current scope."""

    payload = body or ActivateSettingRequest()
    try:
        return await _governance_store(request).mark_active(
            key,
            actor_id=_actor_id(current),
            scope_kind=payload.scope_kind,
            scope_id=payload.scope_id,
        )
    except KeyError as exc:
        raise HTTPException(404, "Runtime setting was not found") from exc
    except PermissionError as exc:
        raise HTTPException(403, "Governance actor scope mismatch") from exc


@oms_router.put("/secrets/{name}")
async def upsert_secret_reference(
    name: str,
    body: UpsertSecretReferenceRequest,
    request: Request,
    current: TokenPayload = Depends(require_admin),
) -> dict[str, Any]:
    """Register or rotate a Secret reference; never accepts Secret values."""

    try:
        return await _governance_store(request).upsert_secret_reference(
            name=name,
            provider=body.provider,
            reference=body.reference,
            status=body.status,
            actor_id=_actor_id(current),
            scope_kind=body.scope_kind,
            scope_id=body.scope_id,
        )
    except PermissionError as exc:
        raise HTTPException(403, "Governance actor scope mismatch") from exc


@oms_router.get("/audit")
async def list_audit_events(
    request: Request,
    limit: int = 100,
    _: TokenPayload = Depends(require_admin),
) -> dict[str, Any]:
    """Return redacted tenant-scoped governance audit events."""

    return {"events": await _governance_store(request).list_audit(limit=limit)}


@oms_router.get("/usage")
async def usage_summary(
    request: Request,
    _: TokenPayload = Depends(require_admin),
) -> dict[str, Any]:
    """Return redacted tenant-scoped ObjectStore/cleanup usage metadata."""

    return await _governance_store(request).usage_summary()
