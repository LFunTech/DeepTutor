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
        "DT_TEST_OBJECT_ACCESS": "object-access",
        "DT_TEST_OBJECT_SECRET": "object-secret",
        "DT_TEST_LIGHTRAG_SECRET": "lightrag-secret",
        "DT_TEST_EDUPLUS2_SECRET": "eduplus2-secret",
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
        object_store={
            "provider": "s3-compatible",
            "endpoint": "https://objects.example",
            "bucket": "deeptutor-test",
            "region": "us-east-1",
            "access_key_secret": "env:DT_TEST_OBJECT_ACCESS",
            "secret_key_secret": "env:DT_TEST_OBJECT_SECRET",
        },
        settings_provider={"kind": "postgres"},
        secret_provider={"kind": "env", "name": "test-secrets"},
        lightrag={
            "endpoint": "https://lightrag.example",
            "api_secret": "env:DT_TEST_LIGHTRAG_SECRET",
            "workspace_binding": "workspace-main",
            "index_version": "idx-v1",
            "contract_version": "lightrag-api-v1",
        },
        eduplus2={
            "base_url": "https://eduplus2.example",
            "client_id": "eduplus2-client",
            "client_secret": "env:DT_TEST_EDUPLUS2_SECRET",
        },
        production={"runtime_mode": "production"},
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
            "/tms",
            "/api/v1/tms",
            "/api/v1/tms/tenants",
            "/oms",
            "/api/v1/oms",
            "/api/v1/oms/releases",
            "/api/sessions/x/ask-hint",
        ]:
            response = await client.get(path, headers={"Authorization": "Bearer " + original})
            assert response.status_code in (401, 404, 405)


async def test_m1_does_not_expose_tms_or_oms_surfaces(app):
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="m1-boundary")
    paths = [
        "/tms",
        "/tms/",
        "/api/v1/tms",
        "/api/v1/tms/tenants",
        "/api/v1/tms/apps",
        "/oms",
        "/oms/",
        "/api/v1/oms",
        "/api/v1/oms/releases",
        "/api/v1/oms/releases/foreign-release",
        "/api/v1/oms/evidence",
        "/api/v1/oms/evidence/foreign-release",
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        for path in paths:
            anonymous = await client.get(path)
            authorized = await client.get(path, headers={"Authorization": "Bearer " + token})
            forged_ops = await client.get(
                path,
                headers={
                    "Authorization": "Bearer " + token,
                    "X-Scopes": "ops.release.read ops.evidence.read",
                },
            )
            assert anonymous.status_code in (401, 404, 405), (path, anonymous.status_code)
            assert authorized.status_code in (401, 404, 405), (path, authorized.status_code)
            assert forged_ops.status_code in (401, 404, 405), (path, forged_ops.status_code)


async def test_enterprise_resource_upload_intent_and_ws_resource_ids_contract(app):
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="resource-contract")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
    ) as anonymous:
        denied = await anonymous.post(
            "/api/v1/resources/upload-intents",
            json={
                "modality": "image",
                "mime_type": "image/png",
                "size_bytes": 12,
                "sha256": "a" * 64,
                "purpose": "chat_turn",
            },
        )
        assert denied.status_code == 401

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
        headers={"Authorization": "Bearer " + token},
    ) as client:
        intent = await client.post(
            "/api/v1/resources/upload-intents",
            json={
                "modality": "image",
                "mime_type": "image/png",
                "size_bytes": 12,
                "sha256": "a" * 64,
                "purpose": "chat_turn",
                "session_id": "session-demo",
            },
        )
        assert intent.status_code == 200, intent.text
        payload = intent.json()
        assert payload["resource_id"].startswith("res_")
        assert payload["upload_url"]
        assert "object_key" not in payload
        assert payload["constraints"]["mime_type"] == "image/png"
        assert payload["constraints"]["size_bytes"] == 12
        assert payload["headers"]["content-type"] == "image/png"

        command = {
            "type": "start_turn",
            "protocol_version": "2.0",
            "content": "请分析附件",
            "resource_ids": [payload["resource_id"]],
        }
        from pydantic import TypeAdapter

        from deeptutor.api.contracts.turn_protocol import ClientCommand

        parsed = TypeAdapter(ClientCommand).validate_python(command)
        assert parsed.to_payload()["resource_ids"] == [payload["resource_id"]]

        from deeptutor.runtime.externalized_providers import ObjectBlobRef

        def matching_head(key: str):
            return ObjectBlobRef(
                key=key,
                size_bytes=12,
                sha256="a" * 64,
                content_type="image/png",
            )

        app.state.enterprise.object_store.head_object = matching_head
        completed = await client.post(
            f"/api/v1/resources/upload-intents/{payload['resource_id']}/complete",
            json={},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["state"] == "ready"

        mismatch_intent = await client.post(
            "/api/v1/resources/upload-intents",
            json={
                "modality": "image",
                "mime_type": "image/png",
                "size_bytes": 12,
                "sha256": "b" * 64,
                "purpose": "chat_turn",
            },
        )
        assert mismatch_intent.status_code == 200, mismatch_intent.text
        app.state.enterprise.object_store.head_object = matching_head
        mismatch = await client.post(
            f"/api/v1/resources/upload-intents/{mismatch_intent.json()['resource_id']}/complete",
            json={},
        )
        assert mismatch.status_code == 409
        assert "hash" in mismatch.text.lower()


async def test_enterprise_production_ws_rejects_legacy_payload_and_verifies_resource_refs(app):
    """放宽生产 WS 附件上传或跳过 resource_id 绑定校验时，本测试应失败。"""

    enterprise = app.state.enterprise
    token = await enterprise.identity.login(
        "admin", "long-password-1", client="resource-policy"
    )
    identity = await enterprise.identity.authenticate(token)

    from deeptutor_enterprise.api.application import SocketAuthentication
    from deeptutor_enterprise.context import identity_context

    from deeptutor.runtime.externalized_providers import ObjectBlobRef

    auth = SocketAuthentication(enterprise)
    with identity_context(identity, token):
        with pytest.raises(ValueError, match="resource references"):
            await auth.validate_start_turn(
                None,
                {
                    "content": "请分析",
                    "attachments": [
                        {
                            "type": "file",
                            "filename": "raw.txt",
                            "mime_type": "text/plain",
                            "base64": "cmF3",
                        }
                    ],
                    "resource_ids": [],
                },
            )

        with pytest.raises(ValueError, match="resource reference"):
            await auth.validate_start_turn(
                None,
                {
                    "content": "请分析",
                    "attachments": [],
                    "resource_ids": ["https://objects.example/tenant/raw-key"],
                },
            )

        from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

        store = enterprise.store_provider.get()
        resource_store = PostgresObjectResourceStore(store, enterprise.object_store)
        intent = await resource_store.create_upload_intent(
            modality="image",
            mime_type="image/png",
            size_bytes=7,
            sha256="c" * 64,
            purpose="chat_turn",
            filename="diagram.png",
        )

        def matching_head(key: str):
            return ObjectBlobRef(
                key=key,
                size_bytes=7,
                sha256="c" * 64,
                content_type="image/png",
            )

        enterprise.object_store.head_object = matching_head
        await resource_store.complete_upload_intent(resource_id=intent["resource_id"])
        await auth.validate_start_turn(
            None,
            {
                "content": "请分析",
                "attachments": [],
                "resource_ids": [intent["resource_id"]],
            },
        )


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
