"""入口拒绝必须持久审计、保守报错，不记录请求正文或凭证。"""

from deeptutor_enterprise.scope import TenantScope
import httpx
import psycopg
import pytest
from test_application import app as app
from test_flows import Socket


async def test_client_tenant_override_and_http_denials_are_audited(app):
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="denials")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
        headers={"Authorization": "Bearer " + token},
    ) as client:
        for headers, url in [
            ({"X-Tenant-Id": "forged"}, "/api/sessions"),
            ({}, "/api/sessions?tenant_id=forged"),
        ]:
            response = await client.get(url, headers=headers)
            assert response.status_code == 403
        assert (await client.get("/api/sessions/unknown")).status_code == 404
    async with enterprise.db.transaction(
        TenantScope(str(enterprise.deployment.tenant_id), "audit")
    ) as c:
        actions = {
            r["action"]
            for r in await (await c.execute("SELECT action FROM enterprise.audit")).fetchall()
        }
    assert {"http.403", "http.404"} <= actions


async def test_pg_error_is_sanitized_for_http_and_ws(app, monkeypatch, caplog):
    from deeptutor_enterprise.stores.postgres.session import PostgresSessionStore

    async def unavailable(*args, **kwargs):
        raise psycopg.OperationalError("dsn password=never-leak-this")

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="safe-error")
    monkeypatch.setattr(PostgresSessionStore, "list_sessions", unavailable)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
        headers={"Authorization": "Bearer " + token},
    ) as client:
        response = await client.get("/api/sessions")
        assert response.status_code == 503 and "never-leak-this" not in response.text
    monkeypatch.setattr(PostgresSessionStore, "get_active_turn", unavailable)
    async with Socket(app, token) as ws:
        await ws.send({"type": "check_active_turn", "session_id": "opaque-id"})
        response = await ws.receive()
        assert response["type"] == "protocol_error"
        assert "never-leak-this" not in str(response)
    assert "never-leak-this" not in caplog.text


async def test_validation_does_not_echo_secrets_or_accept_tenant_fields(app):
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="input-contract")
    async with enterprise.sdk(token):
        from deeptutor.services.session import get_session_store

        session = await get_session_store().create_session()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        response = await client.post(
            "/api/auth/login",
            headers={"Origin": "https://school.example"},
            json={
                "username": "admin",
                "password": "do-not-echo-password",
                "secret": "do-not-echo-secret",
            },
        )
        assert response.status_code == 422
        assert "do-not-echo" not in response.text
        response = await client.patch(
            "/api/sessions/" + session["id"],
            headers={"Authorization": "Bearer " + token},
            json={"title": "changed", "tenant_id": "forged"},
        )
        assert response.status_code == 422
        assert (
            await client.get(
                "/api/sessions/" + session["id"], headers={"Authorization": "Bearer " + token}
            )
        ).json()["title"] == "New conversation"


async def test_non_bearer_authorization_cannot_bypass_cookie_csrf(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        login = await client.post(
            "/api/auth/login",
            headers={"Origin": "https://school.example"},
            json={"username": "admin", "password": "long-password-1"},
        )
        assert login.status_code == 200
        token = client.cookies["dt_token"]
        response = await client.post("/api/auth/logout", headers={"Authorization": "Basic ignored"})
        assert response.status_code == 403
        assert await app.state.enterprise.identity.authenticate(token)
