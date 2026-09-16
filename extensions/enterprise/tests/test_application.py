import importlib.util
import uuid

from deeptutor_enterprise.configuration import DeploymentConfig
from deeptutor_enterprise.migrations.runner import MigrationRunner
import httpx
import pytest


@pytest.fixture
async def app(pg_dsn, monkeypatch):
    assert importlib.util.find_spec("deeptutor_enterprise.bootstrap"), "企业组合入口尚未实现"
    from deeptutor_enterprise.bootstrap import create_application

    await MigrationRunner(pg_dsn).apply()
    for name, value in {
        "DT_TEST_DB": pg_dsn.replace("user=postgres", "user=dt_enterprise_app"),
        "DT_TEST_SIGN": "s" * 48,
        "DT_TEST_EPOCH": "epoch-1",
        "DT_TEST_BOOT": "b" * 48,
        "DT_TEST_MODEL": "model-secret",
    }.items():
        monkeypatch.setenv(name, value)
    deployment = DeploymentConfig(
        version=1,
        tenant_id=uuid.uuid4(),
        resource="app-test",
        database_secret="env:DT_TEST_DB",
        signing_secret="env:DT_TEST_SIGN",
        auth_epoch_secret="env:DT_TEST_EPOCH",
        bootstrap_secret="env:DT_TEST_BOOT",
        origins=("https://school.example",),
        models=(
            {
                "profile_id": "chat",
                "model_id": "primary",
                "model": "some-model",
                "base_url": "https://model.example/v1",
                "secret": "env:DT_TEST_MODEL",
                "allowed_roles": ("user", "tenant_admin"),
            },
        ),
    )
    application = create_application(deployment)
    async with application.state.enterprise.db:
        await application.state.enterprise.identity.bootstrap(
            "admin", "long-password-1", secret="b" * 48
        )
    application = create_application(deployment)
    async with application.router.lifespan_context(application):
        yield application


async def test_http_auth_csrf_revoke_and_closed_routes(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        assert (await client.get("/api/sessions")).status_code == 401
        assert (await client.get("/api/auth/status")).json()["authenticated"] is False
        denied = await client.post(
            "/api/auth/login",
            headers={"Origin": "https://evil.example"},
            json={"username": "admin", "password": "long-password-1"},
        )
        assert denied.status_code == 403
        login = await client.post(
            "/api/auth/login",
            headers={"Origin": "https://school.example"},
            json={"username": "admin", "password": "long-password-1"},
        )
        assert login.status_code == 200, login.text
        cookie = login.headers.get_list("set-cookie")[0]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
        original = client.cookies["dt_token"]
        assert (await client.get("/api/sessions")).status_code == 200
        assert (await client.post("/api/auth/logout")).status_code == 403
        logout = await client.post(
            "/api/auth/logout",
            headers={"Origin": "https://school.example", "X-CSRF-Token": client.cookies["dt_csrf"]},
        )
        assert logout.status_code == 200, logout.text
        assert "dt_token" not in client.cookies
        assert (
            await client.get("/api/sessions", headers={"Authorization": "Bearer " + original})
        ).status_code == 401
        for path in [
            "/api/settings/models",
            "/api/auth/register",
            "/api/plugins",
            "/api/v1/tms",
            "/api/sessions/x/ask-hint",
        ]:
            response = await client.get(path, headers={"Authorization": "Bearer " + original})
            assert response.status_code in (401, 404, 405)


async def test_sdk_and_http_share_owner_guard(app):
    enterprise = app.state.enterprise
    admin = await enterprise.identity.login("admin", "long-password-1", client="sdk")
    user = await enterprise.identity.create_user(admin, "ordinary", "long-password-2")
    user_token = await enterprise.identity.login("ordinary", "long-password-2", client="sdk")
    async with enterprise.sdk(user_token) as sdk:
        from deeptutor.services.session import get_session_store

        own = await get_session_store().create_session(title="private")
        rows = await sdk.list_sessions()
        assert len(rows) == 1
    async with enterprise.sdk(admin) as sdk:
        assert await sdk.get_session(own["id"]) is None
        with pytest.raises(RuntimeError):
            _ = sdk.notebooks
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        response = await client.get(
            "/api/sessions/" + own["id"], headers={"Authorization": "Bearer " + admin}
        )
        assert response.status_code == 404
        response = await client.get(
            "/api/sessions/" + own["id"], headers={"Authorization": "Bearer " + user_token}
        )
        assert response.status_code == 200 and response.json()["title"] == "private"


async def test_session_routes_have_no_local_cleanup_or_sqlite_bypass(app, monkeypatch):
    from deeptutor.api.routers import sessions

    def forbidden(*a, **kw):
        raise AssertionError("local authority accessed")

    monkeypatch.setattr(sessions, "get_sqlite_session_store", forbidden, raising=False)
    monkeypatch.setattr(sessions, "get_attachment_store", forbidden)
    monkeypatch.setattr(sessions, "LearningStore", forbidden, raising=False)
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="session-test")
    async with enterprise.sdk(token):
        from deeptutor.services.session import get_session_store

        store = get_session_store()
        session = await store.create_session()
        root = await store.add_message(session["id"], "user", "first")
        child = await store.add_message(session["id"], "assistant", "answer")
    auth = {"Authorization": "Bearer " + token}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example", headers=auth
    ) as client:
        prefix = "/api/sessions/" + session["id"]
        response = await client.put(
            prefix + "/branch-selection", json={"selected_branches": {str(root): child}}
        )
        assert response.status_code == 200, response.text
        response = await client.patch(prefix + "/organization", json={"pinned": True})
        assert response.status_code == 200, response.text
        response = await client.patch(prefix + "/organization", json={"course_id": "not-delivered"})
        assert response.status_code == 409, response.text
        response = await client.delete(prefix)
        assert response.status_code == 200, response.text
        assert (await client.get(prefix)).status_code == 404


async def test_sdk_never_falls_back_to_local_after_context_exit(app, monkeypatch):
    from deeptutor.app import facade

    token = await app.state.enterprise.identity.login(
        "admin", "long-password-1", client="sdk-lifetime"
    )
    async with app.state.enterprise.sdk(token) as sdk:
        pass

    def forbidden():
        raise AssertionError("local notebook fallback")

    monkeypatch.setattr(facade, "get_notebook_manager", forbidden)
    with pytest.raises(RuntimeError, match="notebook"):
        sdk.list_notebooks()
