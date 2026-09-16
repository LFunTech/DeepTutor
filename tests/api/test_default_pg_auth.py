# ruff: noqa: F811
# pytest fixture 重导出与注入参数同名。
"""默认原 auth router 的真实 PG 正反例，无主应用生命周期副作用。"""

import uuid

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401
from tests.persistence.postgres.test_accounts import accounts  # noqa: F401


@pytest.fixture
async def client(accounts, tmp_path):
    from deeptutor.api.routers import auth
    from deeptutor.services import auth as auth_service

    assert hasattr(auth_service, "PostgresAuthProvider"), "默认 PG provider 尚未实现"
    from deeptutor.persistence.resources import OwnerResourceProvider
    from deeptutor.services.auth import PostgresAuthProvider

    service, _ = accounts
    app = FastAPI()
    app.state.auth_provider = PostgresAuthProvider(
        service, resources=OwnerResourceProvider(tmp_path / "resources"), cookie_secure=False
    )
    app.include_router(auth.router, prefix="/api/auth")

    @app.get("/private")
    async def private(current=Depends(auth.require_auth)):
        from deeptutor.multi_user.context import get_current_user

        user = get_current_user()
        return {
            "id": user.id,
            "tenant": user.scope.tenant_id,
            "root": user.scope.root,
            "manager": user.is_admin,
        }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_original_auth_envelope_and_no_public_admin(client, accounts):
    r = await client.get("/api/auth/status")
    assert r.json()["enabled"] and not r.json()["authenticated"]
    assert (await client.get("/private")).status_code == 401
    assert (
        await client.post(
            "/api/auth/register", json={"username": "attacker", "password": "long-password-1"}
        )
    ).status_code == 403
    assert (await client.get("/api/auth/is_first_user")).json() == {"is_first_user": False}
    r = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "administrator-123"}
    )
    assert r.status_code == 200
    assert r.json()["ok"] and r.json()["is_admin"] and r.json()["role"] == "tenant_admin"
    cookie = client.cookies.get("dt_token")
    status = (await client.get("/api/auth/status")).json()
    assert status["authenticated"] and status["is_admin"] and status["preset"] == "standard"
    private = (await client.get("/private")).json()
    assert private["root"] is None and private["tenant"] == accounts[0].tenant_id
    assert (await client.post("/api/auth/logout")).json() == {"ok": True}
    assert (
        await client.get("/private", headers={"Authorization": "Bearer " + cookie})
    ).status_code == 401
    assert (await client.post("/api/auth/logout")).status_code == 200


async def test_default_profile_avatar_and_users(client, accounts):
    await client.post(
        "/api/auth/login", json={"username": "admin", "password": "administrator-123"}
    )
    r = await client.post(
        "/api/auth/users",
        json={"username": "learner", "password": "learner-password", "preset": "learner"},
    )
    assert r.status_code == 201, r.text
    uid = r.json()["user_id"]
    assert (
        await client.put("/api/auth/users/learner/learner-profile", json={"age": 10})
    ).status_code == 200
    await client.post(
        "/api/auth/login", json={"username": "learner", "password": "learner-password"}
    )
    assert (await client.get("/api/auth/users")).status_code == 403
    assert (await client.get("/api/auth/profile/learner-profile")).json()["learner_profile"][
        "age"
    ] == 10
    assert (await client.put("/api/auth/profile", json={"avatar": "img:99"})).status_code == 422
    png = b"\x89PNG\r\n\x1a\n" + b"temporary-synthetic-payload"
    r = await client.put(
        "/api/auth/profile/avatar", files={"file": ("wrong.svg", png, "image/svg+xml")}
    )
    assert r.status_code == 200, r.text
    assert r.json()["avatar"] == "img:1"
    r = await client.get("/api/auth/avatar/" + uid)
    assert r.content == png and r.headers["content-type"] == "image/png"
    assert (
        await client.put(
            "/api/auth/profile/avatar", files={"file": ("evil.svg", b"<svg/>", "image/svg+xml")}
        )
    ).status_code == 415
    assert (await client.delete("/api/auth/profile/avatar")).json()["ok"]
    assert (await client.get("/api/auth/avatar/" + uid)).status_code == 404
    assert (await client.get("/api/auth/avatar/" + str(uuid.uuid4()))).status_code == 404


def test_missing_context_never_becomes_local_admin():
    from deeptutor.multi_user.context import get_current_user, user_from_token_payload

    with pytest.raises(PermissionError):
        get_current_user()
    with pytest.raises(PermissionError):
        user_from_token_payload(None)


async def test_callback_without_pending_state_is_safe(client):
    r = await client.get("/api/auth/openai-codex/callback?state=unknown&code=synthetic")
    assert r.status_code in (400, 409)
    assert r.headers["cache-control"] == "no-store"


async def test_surface_policy_from_pg_not_json(client, accounts):
    from deeptutor.api.routers.auth import require_learning_surface

    # 挂入真实依赖，同时禁止调用 JSON policy/identity。
    app = client._transport.app

    @app.get("/forbidden", dependencies=[Depends(require_learning_surface)])
    async def forbidden():
        return {"ok": True}

    service, admin = accounts
    await service.create_user(admin, "learner", "learner-password", preset="learner")
    await client.post(
        "/api/auth/login", json={"username": "learner", "password": "learner-password"}
    )
    assert (await client.get("/forbidden")).status_code == 403


async def test_password_utf8_bytes_and_admin_alias(client):
    await client.post(
        "/api/auth/login", json={"username": "admin", "password": "administrator-123"}
    )
    assert (
        await client.post("/api/auth/users", json={"username": "short", "password": "12345678"})
    ).status_code == 422
    r = await client.post("/api/auth/users", json={"username": "utf8", "password": "中文密码"})
    assert r.status_code == 201
    r = await client.put("/api/auth/users/utf8/role", json={"role": "admin"})
    assert r.json()["role"] == "tenant_admin"


async def test_avatar_uncertain_commit_does_not_delete_referenced_object(
    client, accounts, monkeypatch
):
    import asyncio

    from deeptutor.api.routers.auth import _replace_avatar

    service, token = accounts
    provider = client._transport.app.state.auth_provider
    current = await provider.decode(token)
    obj = provider.resources.write_avatar(current.tenant_id, current.user_id, b"png", "png")
    original = service.set_avatar

    async def committed_then_cancelled(*args, **kwargs):
        await original(*args, **kwargs)
        raise asyncio.CancelledError()

    monkeypatch.setattr(service, "set_avatar", committed_then_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await _replace_avatar(current, "img:1", obj)
    assert provider.resources.read_avatar(current.tenant_id, current.user_id, obj) == b"png"


async def test_current_pg_generation_invalidates_http_socket_adapter_and_sdk_guard(
    client, accounts
):
    from starlette.websockets import WebSocket

    service, admin = accounts
    await service.create_user(admin, "ordinary", "ordinary-password")
    token = await service.login("ordinary", "ordinary-password", client="adapter")
    provider = client._transport.app.state.auth_provider

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        pass

    ws = WebSocket(
        {
            "type": "websocket",
            "path": "/ws",
            "headers": [(b"authorization", ("Bearer " + token).encode())],
            "query_string": b"",
            "app": client._transport.app,
        },
        receive,
        send,
    )
    from deeptutor.multi_user.context import reset_current_user

    context = await provider.authenticate(ws)
    reset_current_user(context)
    actor = await service.authenticate(token)
    await service.revoke_sessions(admin, actor.user_id)
    assert (
        await client.get("/private", headers={"Authorization": "Bearer " + token})
    ).status_code == 401
    with pytest.raises(PermissionError):
        await provider.revalidate(ws)
    # SDK/configured turn guard复用同一authenticate，而非信任缓存actor。
    with pytest.raises(PermissionError):
        await service.authenticate(token)


async def test_auth_errors_never_expose_driver_secret(client, monkeypatch):
    provider = client._transport.app.state.auth_provider

    async def fail(*args, **kwargs):
        raise RuntimeError("postgresql://secret:password@private-host/account")

    monkeypatch.setattr(provider.identity, "login", fail)
    response = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "administrator-123"}
    )
    assert response.status_code == 503
    assert "secret" not in response.text and "private-host" not in response.text


@pytest.mark.parametrize("secure", [False, True])
async def test_cookie_delete_preserves_issue_attributes_623(client, secure):
    client._transport.app.state.auth_provider.cookie_secure = secure
    response = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "administrator-123"}
    )
    issued = response.headers["set-cookie"]
    token = client.cookies.get("dt_token")
    response = await client.post("/api/auth/logout", headers={"Authorization": "Bearer " + token})
    deleted = response.headers["set-cookie"]
    for header in (issued, deleted):
        assert "HttpOnly" in header and "Path=/" in header
        assert ("Secure" in header) == secure
        assert ("SameSite=none" if secure else "SameSite=lax") in header
    assert "Max-Age=0" in deleted
