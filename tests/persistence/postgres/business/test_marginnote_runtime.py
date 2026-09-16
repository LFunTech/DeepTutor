from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from deeptutor.api.routers import marginnote4
from deeptutor.api.routers.auth import require_auth
from deeptutor.capabilities.marginnote4 import MarginNoteCapability
from deeptutor.capabilities.marginnote4.tools import MarginNoteReadTool, MarginNoteSearchTool
from deeptutor.core.context import UnifiedContext
from deeptutor.core.providers import ApplicationProviders, provider_context
from deeptutor.multi_user.context import set_current_user, user_from_token_payload
from deeptutor.persistence.postgres.marginnote import PostgresMarginNoteStore
from deeptutor.persistence.postgres.scope import TenantScope

pytestmark = pytest.mark.asyncio


class _Runtime:
    def __init__(self, database, tenant_id: str) -> None:
        self.sync_db = database
        self.config = SimpleNamespace(tenant_id=tenant_id)

    def marginnote_store_for_current_user(self, kb_id: str) -> PostgresMarginNoteStore:
        from deeptutor.multi_user.context import get_current_user

        user = get_current_user()
        return self.marginnote_store_for_scope(TenantScope(user.scope.tenant_id, user.id), kb_id)

    def marginnote_store_for_scope(self, scope: TenantScope, kb_id: str) -> PostgresMarginNoteStore:
        return PostgresMarginNoteStore(self.sync_db, scope, kb_id=kb_id)


class _Container:
    def __init__(self, runtime: _Runtime) -> None:
        self.postgres_runtime = runtime


def _current_user(actor):
    return user_from_token_payload(actor.identity)


def _install_auth(app: FastAPI, actor) -> None:
    async def _auth_override():
        set_current_user(_current_user(actor))
        return actor.identity

    app.dependency_overrides[require_auth] = _auth_override


async def _client(app: FastAPI):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_marginnote_api_uses_pg_store_without_db_path_and_enforces_cursor_revoke_kb(
    monkeypatch, business_sync_database, business_actors
) -> None:
    owner = business_actors.tenants[0].owners[0]
    runtime = _Runtime(business_sync_database, owner.tenant_id)
    app = FastAPI()
    app.state.postgres_runtime = runtime
    _install_auth(app, owner)
    app.include_router(marginnote4.router, prefix="/api/marginnote4")

    def forbidden_sqlite(*_args, **_kwargs):
        raise AssertionError("MarginNote runtime must not open SQLite or resolve db_path")

    monkeypatch.setattr("deeptutor.capabilities.marginnote4.store.resolve_db_path", forbidden_sqlite)
    monkeypatch.setattr("deeptutor.capabilities.marginnote4.store.MarginNoteStore", forbidden_sqlite)

    async with await _client(app) as client:
        paired = await client.post(
            "/api/marginnote4/pair",
            json={"device_name": "iPad", "device_kind": "ipados"},
            headers={"X-MN4-KB": "biology"},
        )
        assert paired.status_code == 200, paired.text
        credential = paired.json()
        auth = {"Authorization": f"MarginNote {credential['device_id']}:{credential['token']}"}

        first = await client.post(
            "/api/marginnote4/sync",
            json={
                "cursor": "",
                "objects": [
                    {
                        "object_id": "shared-note",
                        "object_type": "note",
                        "title": "Biology payload",
                        "content": "Plants convert light.",
                        "links": ["card1"],
                        "raw": {"source": "api"},
                    }
                ],
                "deleted_ids": [],
            },
            headers={**auth, "X-MN4-KB": "biology"},
        )
        assert first.status_code == 200, first.text
        cursor = first.json()["new_cursor"]
        assert first.json()["stored"] == 1

        stale = await client.post(
            "/api/marginnote4/sync",
            json={
                "cursor": "",
                "objects": [
                    {"object_id": "stale-write", "object_type": "note", "title": "stale"}
                ],
                "deleted_ids": [],
            },
            headers={**auth, "X-MN4-KB": "biology"},
        )
        assert stale.status_code == 409
        assert runtime.marginnote_store_for_scope(owner.scope, "biology").get("stale-write") is None

        updated = await client.post(
            "/api/marginnote4/sync",
            json={
                "cursor": cursor,
                "objects": [
                    {
                        "object_id": "shared-note",
                        "object_type": "note",
                        "title": "Biology payload updated",
                    }
                ],
                "deleted_ids": [],
            },
            headers={**auth, "X-MN4-KB": "biology"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["updated"] == 1

        chemistry = await client.post("/api/marginnote4/pair", json={}, headers={"X-MN4-KB": "chemistry"})
        assert chemistry.status_code == 200, chemistry.text
        chem = chemistry.json()
        chem_auth = {"Authorization": f"MarginNote {chem['device_id']}:{chem['token']}"}
        chem_sync = await client.post(
            "/api/marginnote4/sync",
            json={
                "cursor": "",
                "objects": [
                    {"object_id": "shared-note", "object_type": "note", "title": "Chemistry payload"}
                ],
                "deleted_ids": [],
            },
            headers={**chem_auth, "X-MN4-KB": "chemistry"},
        )
        assert chem_sync.status_code == 200, chem_sync.text
        assert runtime.marginnote_store_for_scope(owner.scope, "biology").get("shared-note").title == (
            "Biology payload updated"
        )
        assert runtime.marginnote_store_for_scope(owner.scope, "chemistry").get("shared-note").title == (
            "Chemistry payload"
        )

        wrong_kb = await client.post(
            "/api/marginnote4/heartbeat",
            headers={**auth, "X-MN4-KB": "chemistry"},
        )
        assert wrong_kb.status_code == 403

        revoked = await client.delete(
            f"/api/marginnote4/devices/{credential['device_id']}",
            headers={"X-MN4-KB": "biology"},
        )
        assert revoked.status_code == 200, revoked.text
        denied = await client.post("/api/marginnote4/heartbeat", headers={**auth, "X-MN4-KB": "biology"})
        assert denied.status_code == 403


async def test_marginnote_capability_and_tools_use_pg_kb_binding_without_db_path(
    monkeypatch, business_sync_database, business_actors
) -> None:
    owner = business_actors.tenants[0].owners[0]
    runtime = _Runtime(business_sync_database, owner.tenant_id)
    store = runtime.marginnote_store_for_scope(owner.scope, "biology")
    device, _token = store.pair_device(device_name="Mac")
    store.ingest(
        __import__("deeptutor.capabilities.marginnote4.models", fromlist=["SyncBatch"]).SyncBatch(
            device_id=device.device_id,
            objects=[
                __import__(
                    "deeptutor.capabilities.marginnote4.models", fromlist=["MarginNoteObject"]
                ).MarginNoteObject(
                    object_id="note1",
                    object_type="note",
                    title="PG capability",
                    content="The capability reads PostgreSQL MarginNote data.",
                    raw={"source": "tool"},
                    device_id=device.device_id,
                )
            ],
        )
    )

    def fake_metadata(ref: str):
        if ref == "biology":
            return {"name": "Biology", "type": "marginnote4", "db_path": "/must/not/use.sqlite3"}
        return {"name": ref, "type": None}

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb_metadata", fake_metadata)
    monkeypatch.setattr(
        "deeptutor.capabilities.marginnote4.store.resolve_db_path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("db_path must not resolve")),
    )

    token = set_current_user(_current_user(owner))
    try:
        cap = MarginNoteCapability()
        ctx = UnifiedContext(user_message="read", knowledge_bases=["biology"])
        kwargs = cap.augment_kwargs("marginnote_read", {"_db_path": "/forged"}, ctx)
        assert kwargs["_mn4_kb_id"] == "biology"
        assert "_db_path" not in kwargs

        with provider_context(ApplicationProviders(container=_Container(runtime))):
            read = await MarginNoteReadTool().execute(object_id="note1", **kwargs)
            assert read.success, read.content
            payload = json.loads(read.content)
            assert payload["raw"] == {"source": "tool"}
            search = await MarginNoteSearchTool().execute(query="PostgreSQL", **kwargs)
            assert search.success, search.content
            assert json.loads(search.content)["results"][0]["object_id"] == "note1"
    finally:
        from deeptutor.multi_user.context import reset_current_user

        reset_current_user(token)
