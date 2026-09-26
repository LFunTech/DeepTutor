import asyncio
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import uuid

from deeptutor_enterprise.configuration import DeploymentConfig
from deeptutor_enterprise.migrations.runner import MigrationRunner
import httpx
import pytest

from tests.fixtures.postgres import single_database_user_dsn


def test_enterprise_core_version_falls_back_to_source_tree_version(monkeypatch):
    """源码拷贝型 runtime 没有 distribution metadata 时仍可校验 core 版本。"""

    from importlib.metadata import PackageNotFoundError

    import deeptutor_enterprise.bootstrap as bootstrap

    from deeptutor.__version__ import __version__

    def missing_distribution(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(bootstrap, "version", missing_distribution)

    assert bootstrap._core_version() == __version__


@pytest.fixture
async def app(pg_dsn, monkeypatch):
    assert importlib.util.find_spec("deeptutor_enterprise.bootstrap"), "企业组合入口尚未实现"
    from deeptutor_enterprise.bootstrap import create_application

    await MigrationRunner(pg_dsn).apply()
    for name, value in {
        "DT_TEST_DB": single_database_user_dsn(pg_dsn),
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


async def seed_externalized_kb(
    application,
    *,
    owner_id="admin",
    kb_id="kb-demo",
    label="示例知识库",
    object_state="ready",
    metadata_status="ready",
):
    from deeptutor_enterprise.knowledge_bases import KNOWLEDGE_BASE_DOCUMENT_KIND
    from deeptutor_enterprise.scope import TenantScope

    enterprise = application.state.enterprise
    digest = hashlib.sha256(f"{kb_id}:doc".encode()).hexdigest()
    metadata = {
        "kb_label": label,
        "description": "用于测试的外部化知识库",
        "status": metadata_status,
        "search_mode": "mix",
    }
    async with enterprise.db.transaction(
        TenantScope(str(enterprise.deployment.tenant_id), owner_id)
    ) as c:
        await c.execute(
            "INSERT INTO enterprise.resource_objects"
            "(tenant_id,owner_id,id,resource_kind,resource_id,bucket,object_key,"
            "content_hash,size_bytes,mime_type,state,retention,metadata,created_by) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'retained',%s::jsonb,%s)",
            (
                str(enterprise.deployment.tenant_id),
                owner_id,
                uuid.uuid4(),
                KNOWLEDGE_BASE_DOCUMENT_KIND,
                kb_id,
                "deeptutor-test",
                f"tests/kb/{kb_id}/{uuid.uuid4()}",
                digest,
                64,
                "text/plain",
                object_state,
                json.dumps(metadata),
                owner_id,
            ),
        )
    return kb_id


async def test_enterprise_health_ready_is_public_for_kubernetes_probe(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready"


async def test_eduplus2_signed_webhook_demo_only_checks_delivery_without_state_change(app):
    """EduPlus2 控制台 mock 投递必须验签；不得当成真实租户事件。"""

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    from deeptutor_enterprise.scope import TenantScope

    scope = TenantScope(str(enterprise.deployment.tenant_id), "@preflight")
    async with enterprise.db.transaction(scope) as c:
        original_tenant = await (
            await c.execute(
                "SELECT external_eligibility FROM enterprise.tenants WHERE id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    ts = str(int(time.time()))
    event = "subscription.suspended"
    body = json.dumps(
        {
            "event": event,
            "event_id": "mock_" + str(uuid.uuid4()),
            "timestamp": int(ts),
            "tenant": {"id": 10001, "code": "synthetic-school"},
            "subscription": {"id": 20001, "status": "suspended"},
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        b"synthetic-webhook-secret",
        ts.encode() + b"." + event.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "X-EduPlus-Signature": "sha256=" + signature,
        "X-EduPlus-Timestamp": ts,
        "X-EduPlus-Event": event,
        "X-EduPlus-Mock": "true",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        accepted = await client.post("/api/v1/eduplus2/webhooks", content=body, headers=headers)
        assert accepted.status_code == 204, accepted.text
        forged = await client.post(
            "/api/v1/eduplus2/webhooks",
            content=body,
            headers={**headers, "X-EduPlus-Signature": "sha256=" + "0" * 64},
        )
        assert forged.status_code == 401
        stale = await client.post(
            "/api/v1/eduplus2/webhooks",
            content=body,
            headers={**headers, "X-EduPlus-Timestamp": str(int(ts) - 301)},
        )
        assert stale.status_code == 401
        changed_event = "subscription.reactivated"
        changed_signature = hmac.new(
            b"synthetic-webhook-secret",
            ts.encode() + b"." + changed_event.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        mismatch = await client.post(
            "/api/v1/eduplus2/webhooks",
            content=body,
            headers={
                **headers,
                "X-EduPlus-Event": changed_event,
                "X-EduPlus-Signature": "sha256=" + changed_signature,
            },
        )
        assert mismatch.status_code == 422
        too_large = await client.post(
            "/api/v1/eduplus2/webhooks",
            content=b"x" * (128 * 1024 + 1),
            headers=headers,
        )
        assert too_large.status_code == 413
        real_body = body.replace(b"mock_", b"real_")
        real_signature = hmac.new(
            b"synthetic-webhook-secret",
            ts.encode() + b"." + event.encode() + b"." + real_body,
            hashlib.sha256,
        ).hexdigest()
        real = await client.post(
            "/api/v1/eduplus2/webhooks",
            content=real_body,
            headers={
                **headers,
                "X-EduPlus-Mock": "false",
                "X-EduPlus-Signature": "sha256=" + real_signature,
            },
        )
        assert real.status_code == 503
        enterprise.eduplus2_webhook_secret = ""
        unavailable = await client.post("/api/v1/eduplus2/webhooks", content=body, headers=headers)
        assert unavailable.status_code == 503

    async with enterprise.db.transaction(scope) as c:
        tenant = await (
            await c.execute(
                "SELECT external_eligibility FROM enterprise.tenants WHERE id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
        event_count = await (
            await c.execute("SELECT count(*) AS event_count FROM eduplus2.revocation_events")
        ).fetchone()
    assert tenant["external_eligibility"] == original_tenant["external_eligibility"]
    assert event_count["event_count"] == 0


async def test_http_auth_csrf_revoke_and_closed_routes(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        ui_bootstrap = await client.get("/api/settings/ui")
        assert ui_bootstrap.status_code == 200, ui_bootstrap.text
        assert set(ui_bootstrap.json()) == {"theme", "language", "response_language"}

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


async def test_enterprise_does_not_mount_legacy_management_writes(app):
    """企业装配不得因复用 core router 而暴露租户管理员配置旁路。"""

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="oms-boundary")
    forbidden = (
        ("PUT", "/api/settings/catalog"),
        ("PUT", "/api/settings/draft"),
        ("POST", "/api/settings/apply"),
        ("PUT", "/api/settings/ui"),
        ("PUT", "/api/settings/mcp/servers/example"),
        ("PUT", "/api/v1/tms/settings/model"),
        ("POST", "/api/v1/tms/settings/model/activate"),
        ("PUT", "/api/v1/oms/secrets/provider"),
        ("POST", "/api/settings/tests/llm/start"),
        ("POST", "/api/settings/providers/openai-codex/oauth/start"),
        ("POST", "/api/skills/create"),
        ("POST", "/api/skills/install"),
        ("PUT", "/api/skills/pdf"),
        ("DELETE", "/api/skills/pdf"),
        ("POST", "/api/partners"),
        ("POST", "/api/v1/oms/releases"),
        ("POST", "/api/v1/oms/providers"),
        ("POST", "/api/v1/oms/tenants/foreign-tenant/grants"),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        for method, path in forbidden:
            response = await client.request(
                method,
                path,
                headers={
                    "Authorization": "Bearer " + token,
                    "Origin": "https://school.example",
                    "X-Scopes": "ops.oms.access ops.providers.manage ops.quotas.manage",
                },
                json={},
            )
            expected = 405 if (method, path) == ("PUT", "/api/settings/ui") else 404
            assert response.status_code == expected, (method, path, response.text)


def test_enterprise_management_route_allowlist_is_narrow(app):
    """新增 core 管理 router 时不能通过企业装配无意暴露。"""

    paths = set(app.openapi()["paths"])
    assert {path for path in paths if path.startswith("/api/settings")} == {
        "/api/settings/ui"
    }
    for prefix in (
        "/api/skills",
        "/api/v1/tms",
        "/api/v1/oms",
        "/api/space/mcp",
        "/api/partners",
        "/api/system",
        "/api/settings/workspace",
        "/api/settings/video-learning",
    ):
        assert not any(path == prefix or path.startswith(prefix + "/") for path in paths)


async def test_m1_fixed_tenant_rejects_b2_escape_attempts(app):
    """B2 未开放时，固定租户 runtime 必须拒绝多租户/治理逃逸尝试。"""

    from deeptutor_enterprise.api.application import SocketAuthentication
    from deeptutor_enterprise.context import identity_context
    from deeptutor_enterprise.runtime import TurnEnvironment
    from deeptutor_enterprise.scope import TenantScope

    from deeptutor.services.session.required_context import ContextResolutionError

    enterprise = app.state.enterprise
    admin_token = await enterprise.identity.login("admin", "long-password-1", client="b2-boundary")
    admin_identity = await enterprise.identity.authenticate(admin_token)
    other_user = await enterprise.identity.create_user(
        admin_token, "b2-private-owner", "long-password-2"
    )
    other_token = await enterprise.identity.login(
        "b2-private-owner", "long-password-2", client="b2-boundary"
    )

    auth = SocketAuthentication(enterprise)
    with identity_context(admin_identity, admin_token):
        for field in ("tenant_id", "tenant", "tenantId"):
            with pytest.raises(ValueError, match="tenant"):
                await auth.validate_start_turn(
                    None,
                    {
                        "content": "固定租户下不得从 body 覆盖 tenant",
                        "attachments": [],
                        "resource_ids": [],
                        field: "forged-tenant",
                    },
                )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
        headers={"Authorization": "Bearer " + admin_token},
    ) as client:
        forged_upload = await client.post(
            "/api/v1/resources/upload-intents",
            json={
                "modality": "image",
                "mime_type": "image/png",
                "size_bytes": 12,
                "sha256": "f" * 64,
                "purpose": "chat_turn",
                "tenant_id": "forged-tenant",
            },
        )
        assert forged_upload.status_code == 422

        for method, path in [
            ("POST", "/api/v1/tms/apps"),
            ("PATCH", "/api/v1/tms/apps/app-1"),
            ("PUT", "/api/v1/tms/clients/client-1"),
        ]:
            response = await client.request(
                method,
                path,
                json={"tenant_id": "forged-tenant", "status": "active"},
            )
            assert response.status_code in (401, 404, 405), (method, path, response.status_code)

    foreign_tenant = str(uuid.uuid4())
    foreign_resource_id = "res_cross_tenant_b2"
    async with enterprise.db.transaction(
        TenantScope(foreign_tenant, admin_identity.user_id)
    ) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants"
            "(id,external_eligibility,local_enabled,provisioning_status,"
            "auth_epoch,bootstrap_completed) "
            "VALUES(%s,'not_required',true,'ready','epoch-foreign',true)",
            (foreign_tenant,),
        )
        await c.execute(
            "INSERT INTO enterprise.users(tenant_id,id,username,role) "
            "VALUES(%s,%s,'foreign-admin','tenant_admin')",
            (foreign_tenant, admin_identity.user_id),
        )
        await c.execute(
            "INSERT INTO enterprise.resource_objects"
            "(tenant_id,owner_id,id,resource_kind,resource_id,bucket,object_key,"
            "content_hash,size_bytes,mime_type,state,retention,metadata,created_by) "
            "VALUES(%s,%s,%s,'turn_input',%s,'deeptutor-test',%s,%s,7,"
            "'image/png','ready','retained',%s::jsonb,%s)",
            (
                foreign_tenant,
                admin_identity.user_id,
                uuid.uuid4(),
                foreign_resource_id,
                f"foreign/{foreign_resource_id}.png",
                "d" * 64,
                json.dumps({"purpose": "chat_turn"}),
                admin_identity.user_id,
            ),
        )

    def object_store_must_not_be_consulted(_key: str):
        raise AssertionError("cross-tenant resource existence must not be probed")

    enterprise.object_store.head_object = object_store_must_not_be_consulted
    with identity_context(admin_identity, admin_token):
        with pytest.raises(ValueError, match="invalid resource reference"):
            await auth.validate_start_turn(
                None,
                {
                    "content": "不能引用其它 tenant 的 resource_id",
                    "attachments": [],
                    "resource_ids": [foreign_resource_id],
                },
            )

    private_kb_id = await seed_externalized_kb(
        app,
        owner_id=other_user["id"],
        kb_id="b2-private-kb",
        label="B2 私有知识库",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
    ) as client:
        options = await client.get(
            "/api/v1/enterprise/conversation-test/options",
            headers={"Authorization": "Bearer " + admin_token},
        )
        assert options.status_code == 200, options.text
        assert private_kb_id not in {item["id"] for item in options.json()["knowledge_bases"]}

        async with enterprise.sdk(other_token):
            from deeptutor.services.session import get_session_store

            private_session = await get_session_store().create_session(title="b2 private")
        session_denied = await client.get(
            "/api/sessions/" + private_session["id"],
            headers={"Authorization": "Bearer " + admin_token},
        )
        assert session_denied.status_code == 404

    with identity_context(admin_identity, admin_token):
        with pytest.raises(ContextResolutionError) as exc:
            await TurnEnvironment(enterprise).prepare_request(
                {
                    "content": "不得访问同租户其它 owner 的私有 KB",
                    "capability": "chat",
                    "knowledge_bases": [private_kb_id],
                    "context_policy": "required",
                    "llm_selection": {"profile_id": "chat", "model_id": "primary"},
                }
            )
    assert exc.value.error_code == "knowledge_base_unavailable"


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


async def test_upload_intent_completion_reports_missing_object_as_incomplete_upload(app):
    """完成 pending intent 前必须真实看到对象；不能把未上传误报为 intent 不存在。"""

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="resource-incomplete")
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
                "sha256": "d" * 64,
                "purpose": "chat_turn",
            },
        )
        assert intent.status_code == 200, intent.text

        def missing_head(_key: str):
            raise FileNotFoundError("object not uploaded")

        enterprise.object_store.head_object = missing_head
        completed = await client.post(
            f"/api/v1/resources/upload-intents/{intent.json()['resource_id']}/complete",
            json={},
        )

    assert completed.status_code == 409
    assert "not uploaded" in completed.text.lower()


async def test_upload_intent_completion_rejects_expired_pending_upload(app):
    """过期 intent 即使对象后续出现也不得被 complete 成 ready。"""

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="resource-expired")
    identity = await enterprise.identity.authenticate(token)
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
                "sha256": "e" * 64,
                "purpose": "chat_turn",
            },
        )
        assert intent.status_code == 200, intent.text
        resource_id = intent.json()["resource_id"]

        from deeptutor_enterprise.context import identity_context

        with identity_context(identity, token):
            store = enterprise.store_provider.get()
            async with store.db.transaction(store.scope) as c:
                await c.execute(
                    "UPDATE enterprise.resource_objects "
                    "SET metadata=jsonb_set(metadata,'{upload_expires_at}','1'::jsonb,true) "
                    "WHERE tenant_id=%s AND owner_id=%s AND resource_id=%s",
                    (*store._owner, resource_id),
                )

        from deeptutor.runtime.externalized_providers import ObjectBlobRef

        def matching_head(key: str):
            return ObjectBlobRef(
                key=key,
                size_bytes=12,
                sha256="e" * 64,
                content_type="image/png",
            )

        enterprise.object_store.head_object = matching_head
        completed = await client.post(f"/api/v1/resources/upload-intents/{resource_id}/complete")

    assert completed.status_code == 409
    assert "expired" in completed.text.lower()


async def test_conversation_test_options_are_authenticated_and_non_secret(app, monkeypatch):
    """普通测试页选项接口只返回可选能力，不暴露 provider 配置或密钥。"""

    from deeptutor.multi_user import knowledge_access

    monkeypatch.setattr(
        knowledge_access,
        "list_visible_knowledge_bases",
        lambda: (_ for _ in ()).throw(AssertionError("must not read local data KBs")),
    )
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="conversation-test")
    identity = await enterprise.identity.authenticate(token)
    await seed_externalized_kb(
        app,
        owner_id=identity.user_id,
        kb_id="external-kb",
        label="外部化知识库",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
    ) as client:
        anonymous = await client.get("/api/v1/enterprise/conversation-test/options")
        assert anonymous.status_code == 401

        authorized = await client.get(
            "/api/v1/enterprise/conversation-test/options",
            headers={"Authorization": "Bearer " + token},
        )
        assert authorized.status_code == 200, authorized.text
        payload = authorized.json()
        assert set(payload) == {"knowledge_bases", "skills", "mcp_tools"}
        assert isinstance(payload["knowledge_bases"], list)
        assert isinstance(payload["skills"], list)
        assert isinstance(payload["mcp_tools"], list)
        assert payload["knowledge_bases"][0]["id"] == "external-kb"
        serialized = authorized.text.lower()
        assert "secret" not in serialized
        assert "api_secret" not in serialized
        assert "endpoint" not in serialized




async def test_conversation_test_options_disable_kbs_when_rag_policy_is_not_enabled(
    app,
):
    """部署未允许知识库检索时，普通测试页不得展示可选但发送必失败的 KB。"""

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="conversation-test")
    identity = await enterprise.identity.authenticate(token)
    await seed_externalized_kb(app, owner_id=identity.user_id, kb_id="user-kb-test", label="test")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
        headers={"Authorization": "Bearer " + token},
    ) as client:
        response = await client.get("/api/v1/enterprise/conversation-test/options")

    assert response.status_code == 200, response.text
    [kb] = response.json()["knowledge_bases"]
    assert kb["id"] == "user-kb-test"
    assert kb["status"] == "unavailable"
    assert kb["disabled"] is True
    assert "知识库检索" in kb["description"]

async def test_conversation_test_options_show_skill_names_as_labels(app):
    """普通测试页的 Skills 选项必须展示可识别的 skill 名称，而不是长说明文案。"""

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="conversation-test")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
    ) as client:
        response = await client.get(
            "/api/v1/enterprise/conversation-test/options",
            headers={"Authorization": "Bearer " + token},
        )
    assert response.status_code == 200, response.text
    skills = response.json()["skills"]
    skill_creator = next(item for item in skills if item["id"] == "skill-creator")
    assert skill_creator["label"] == "skill-creator"
    assert "Design and author DeepTutor skills" in skill_creator["description"]


async def test_enterprise_voice_stt_is_available_to_authenticated_test_page(
    app, monkeypatch
):
    """普通测试页语音输入应能用同一企业 Bearer token 调用服务端转写。"""

    from deeptutor.api.routers import voice as voice_router

    captured = {}

    async def fake_transcribe(audio, *, filename, content_type, language=None):
        captured["bytes"] = len(audio)
        captured["filename"] = filename
        captured["content_type"] = content_type
        captured["language"] = language
        return "语音转写文本"

    monkeypatch.setattr(voice_router, "transcribe_audio", fake_transcribe)

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="conversation-test")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
    ) as client:
        anonymous = await client.post(
            "/api/voice/stt",
            files={"file": ("recording.webm", b"audiobytes", "audio/webm")},
        )
        assert anonymous.status_code == 401

        authorized = await client.post(
            "/api/voice/stt",
            headers={"Authorization": "Bearer " + token},
            files={"file": ("recording.webm", b"audiobytes", "audio/webm")},
            data={"language": "zh-CN"},
        )

    assert authorized.status_code == 200, authorized.text
    assert authorized.json() == {"text": "语音转写文本"}
    assert captured == {
        "bytes": 10,
        "filename": "recording.webm",
        "content_type": "audio/webm",
        "language": "zh-CN",
    }


async def test_local_minio_http_upload_intent_and_ws_resource_policy(app, monkeypatch):
    """本机 MinIO 可用时，验证企业 HTTP API 真实 pre-signed PUT 后可被 WS resource policy 接受。"""

    if os.environ.get("DEEPTUTOR_RUN_LOCAL_MINIO_TESTS") != "1":
        pytest.skip("set DEEPTUTOR_RUN_LOCAL_MINIO_TESTS=1 to run local MinIO integration")

    env_path = Path("/opt/data/minio/config/minio.env")
    if not env_path.exists():
        pytest.skip("local MinIO env file is unavailable")

    local_env: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        local_env[name.strip()] = value.strip().strip('"').strip("'")
    access = local_env.get("MINIO_ROOT_USER", "")
    secret = local_env.get("MINIO_ROOT_PASSWORD", "")
    region = local_env.get("MINIO_REGION_NAME", "us-east-1")
    if not access or not secret:
        pytest.skip("local MinIO credentials are unavailable")

    monkeypatch.setenv("DEEPLT_LOCAL_MINIO_ACCESS", access)
    monkeypatch.setenv("DEEPLT_LOCAL_MINIO_SECRET", secret)

    from dataclasses import replace

    from deeptutor.runtime.externalized_providers import (
        EnvSecretResolver,
        S3CompatibleObjectStore,
        S3ObjectStoreConfig,
        SecretRef,
    )

    object_store = S3CompatibleObjectStore(
        S3ObjectStoreConfig(
            endpoint="http://127.0.0.1:9000",
            region=region,
            bucket="local-debug",
            access_key_ref=SecretRef.parse("env:DEEPLT_LOCAL_MINIO_ACCESS"),
            secret_key_ref=SecretRef.parse("env:DEEPLT_LOCAL_MINIO_SECRET"),
            path_style=True,
            verify_tls=False,
        ),
        secret_resolver=EnvSecretResolver(),
    )
    status = object_store.check_bucket()
    if not status.available:
        pytest.skip(f"local MinIO bucket local-debug unavailable: {status.code}")

    enterprise = app.state.enterprise
    enterprise.object_store = object_store
    enterprise.providers = replace(enterprise.providers, object_store=object_store)

    token = await enterprise.identity.login("admin", "long-password-1", client="local-a2-minio")
    identity = await enterprise.identity.authenticate(token)
    payload = b"local-a2-http-api-minio-resource"
    digest = hashlib.sha256(payload).hexdigest()

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
                "size_bytes": len(payload),
                "sha256": digest,
                "purpose": "chat_turn",
                "filename": "diagram.png",
                "expires_seconds": 300,
            },
        )
        assert intent.status_code == 200, intent.text
        upload = httpx.put(
            intent.json()["upload_url"],
            content=payload,
            headers=intent.json()["headers"],
            timeout=10,
        )
        assert upload.status_code in (200, 204), upload.text

        completed = await client.post(
            f"/api/v1/resources/upload-intents/{intent.json()['resource_id']}/complete",
            json={},
        )
        assert completed.status_code == 200, completed.text
        resource_id = completed.json()["resource_id"]
        object_id = completed.json()["object_id"]
        download = await client.get(
            f"/files/resources/turn_input/{resource_id}/{object_id}/diagram.png"
        )
        assert download.status_code == 200, download.text
        assert download.content == payload
        assert download.headers["cache-control"] == "private, no-store"

    from deeptutor_enterprise.api.application import SocketAuthentication
    from deeptutor_enterprise.context import identity_context

    with identity_context(identity, token):
        await SocketAuthentication(enterprise).validate_start_turn(
            None,
            {
                "content": "请分析附件",
                "attachments": [],
                "resource_ids": [resource_id],
            },
        )


async def test_enterprise_turn_environment_materializes_image_resource_refs_for_llm(app):
    """resource_ids 不能只被 WS policy 校验后丢弃；图片必须进入 LLM attachment 上下文。"""

    import base64

    from deeptutor_enterprise.context import identity_context
    from deeptutor_enterprise.runtime import TurnEnvironment

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore
    from deeptutor.runtime.externalized_providers import ObjectBlobRef
    from deeptutor.services.llm.capabilities import set_catalog_capability_overrides

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="resource-llm")
    identity = await enterprise.identity.authenticate(token)
    image_bytes = b"\x89PNG\r\n\x1a\nresource-image"
    digest = hashlib.sha256(image_bytes).hexdigest()
    blobs: dict[str, tuple[bytes, str, str]] = {}

    def put_bytes(key: str, data: bytes, *, expected_sha256: str, content_type: str):
        blobs[key] = (data, expected_sha256, content_type)
        return ObjectBlobRef(
            key=key,
            size_bytes=len(data),
            sha256=expected_sha256,
            content_type=content_type,
        )

    def head_object(key: str):
        data, expected_sha256, content_type = blobs[key]
        return ObjectBlobRef(
            key=key,
            size_bytes=len(data),
            sha256=expected_sha256,
            content_type=content_type,
        )

    def get_bytes(ref: ObjectBlobRef):
        return blobs[ref.key][0]

    enterprise.object_store.put_bytes = put_bytes
    enterprise.object_store.head_object = head_object
    enterprise.object_store.get_bytes = get_bytes
    set_catalog_capability_overrides([("openai", "some-model", {"vision": True})])
    try:
        with identity_context(identity, token):
            resource_store = PostgresObjectResourceStore(
                enterprise.store_provider.get(), enterprise.object_store
            )
            handle = await resource_store.put(
                resource_kind="turn_input",
                resource_id="res_demo_image",
                filename="diagram.png",
                data=image_bytes,
                mime_type="image/png",
                metadata={"purpose": "chat_turn"},
            )
            prepared = await TurnEnvironment(enterprise).prepare_request(
                {
                    "content": "请分析图片",
                    "capability": "chat",
                    "tools": [],
                    "resource_ids": [handle.resource_id],
                    "llm_selection": {"profile_id": "chat", "model_id": "primary"},
                }
            )
    finally:
        set_catalog_capability_overrides([])

    assert len(prepared.resource_attachments) == 1
    attachment = prepared.resource_attachments[0]
    assert attachment.type == "image"
    assert attachment.mime_type == "image/png"
    assert attachment.filename == "res_demo_image.png"
    assert attachment.base64 == base64.b64encode(image_bytes).decode("ascii")
    assert attachment.url == ""


async def test_enterprise_turn_environment_rejects_non_image_resources_before_llm(app):
    """当前模型输入只支持图片资源，音频/视频必须在后端进入 LLM 前失败关闭。"""

    from deeptutor_enterprise.context import identity_context
    from deeptutor_enterprise.runtime import TurnEnvironment

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore
    from deeptutor.runtime.externalized_providers import ObjectBlobRef

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="resource-audio")
    identity = await enterprise.identity.authenticate(token)
    audio_bytes = b"RIFF....WAVEfmt audio"
    blobs: dict[str, tuple[bytes, str, str]] = {}

    def put_bytes(key: str, data: bytes, *, expected_sha256: str, content_type: str):
        blobs[key] = (data, expected_sha256, content_type)
        return ObjectBlobRef(
            key=key,
            size_bytes=len(data),
            sha256=expected_sha256,
            content_type=content_type,
        )

    def head_object(key: str):
        data, expected_sha256, content_type = blobs[key]
        return ObjectBlobRef(
            key=key,
            size_bytes=len(data),
            sha256=expected_sha256,
            content_type=content_type,
        )

    enterprise.object_store.put_bytes = put_bytes
    enterprise.object_store.head_object = head_object
    with identity_context(identity, token):
        resource_store = PostgresObjectResourceStore(
            enterprise.store_provider.get(), enterprise.object_store
        )
        handle = await resource_store.put(
            resource_kind="turn_input",
            resource_id="res_audio_only",
            filename="question.wav",
            data=audio_bytes,
            mime_type="audio/wav",
            metadata={"purpose": "chat_turn"},
        )
        with pytest.raises(ValueError, match="Only image resources"):
            await TurnEnvironment(enterprise).prepare_request(
                {
                    "content": "请分析音频",
                    "capability": "chat",
                    "tools": [],
                    "resource_ids": [handle.resource_id],
                    "llm_selection": {"profile_id": "chat", "model_id": "primary"},
                }
            )


async def test_enterprise_turn_environment_rejects_image_when_model_lacks_vision_before_llm(
    app,
):
    """图片资源已上传也不能绕过 provider 能力矩阵；不支持 vision 时模型调用前失败。"""

    from deeptutor_enterprise.context import identity_context
    from deeptutor_enterprise.runtime import TurnEnvironment

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore
    from deeptutor.runtime.externalized_providers import ObjectBlobRef
    from deeptutor.services.llm.capabilities import set_catalog_capability_overrides
    from deeptutor.services.session.required_context import ContextResolutionError

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="no-vision")
    identity = await enterprise.identity.authenticate(token)
    image_bytes = b"\x89PNG\r\n\x1a\nresource-image"
    blobs: dict[str, tuple[bytes, str, str]] = {}

    def put_bytes(key: str, data: bytes, *, expected_sha256: str, content_type: str):
        blobs[key] = (data, expected_sha256, content_type)
        return ObjectBlobRef(
            key=key,
            size_bytes=len(data),
            sha256=expected_sha256,
            content_type=content_type,
        )

    def head_object(key: str):
        data, expected_sha256, content_type = blobs[key]
        return ObjectBlobRef(
            key=key,
            size_bytes=len(data),
            sha256=expected_sha256,
            content_type=content_type,
        )

    enterprise.object_store.put_bytes = put_bytes
    enterprise.object_store.head_object = head_object
    enterprise.object_store.get_bytes = lambda ref: blobs[ref.key][0]
    set_catalog_capability_overrides([("openai", "some-model", {"vision": False})])
    try:
        with identity_context(identity, token):
            resource_store = PostgresObjectResourceStore(
                enterprise.store_provider.get(), enterprise.object_store
            )
            handle = await resource_store.put(
                resource_kind="turn_input",
                resource_id="res_image_no_vision",
                filename="diagram.png",
                data=image_bytes,
                mime_type="image/png",
                metadata={"purpose": "chat_turn"},
            )
            with pytest.raises(ContextResolutionError) as exc:
                await TurnEnvironment(enterprise).prepare_request(
                    {
                        "content": "请分析图片",
                        "capability": "chat",
                        "tools": [],
                        "resource_ids": [handle.resource_id],
                        "context_policy": "required",
                        "llm_selection": {"profile_id": "chat", "model_id": "primary"},
                    }
                )
    finally:
        set_catalog_capability_overrides([])

    assert exc.value.error_code == "required_context_unavailable"


async def test_enterprise_turn_environment_required_mcp_fails_closed(app):
    from deeptutor_enterprise.context import identity_context
    from deeptutor_enterprise.runtime import TurnEnvironment

    from deeptutor.services.session.required_context import ContextResolutionError

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="required-context")
    identity = await enterprise.identity.authenticate(token)
    with identity_context(identity, token):
        with pytest.raises(ContextResolutionError) as exc:
            await TurnEnvironment(enterprise).prepare_request(
                {
                    "content": "请调用指定外部工具",
                    "capability": "chat",
                    "mcp_tools": ["missing.tool"],
                    "context_policy": "required",
                    "llm_selection": {"profile_id": "chat", "model_id": "primary"},
                }
            )

    assert exc.value.error_code == "mcp_tool_unavailable"


@pytest.mark.parametrize(
    ("kb_id", "seed_kwargs"),
    [
        ("missing-kb", None),
        ("private-kb", {"owner_id": "__other_user__", "kb_id": "private-kb"}),
        (
            "warming-kb",
            {
                "kb_id": "warming-kb",
                "object_state": "ready",
                "metadata_status": "indexing",
            },
        ),
    ],
)
async def test_enterprise_turn_environment_required_kb_unavailable_cases_fail_closed(
    app,
    kb_id,
    seed_kwargs,
):
    """缺失、私有不可见、未 ready 的 KB 都必须在模型调用前 fail closed。"""

    from deeptutor_enterprise.context import identity_context
    from deeptutor_enterprise.runtime import TurnEnvironment

    from deeptutor.services.session.required_context import ContextResolutionError

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client=f"kb-{kb_id}")
    identity = await enterprise.identity.authenticate(token)
    if seed_kwargs is not None:
        kwargs = dict(seed_kwargs)
        if kwargs.get("owner_id") == "__other_user__":
            other = await enterprise.identity.create_user(
                token, f"owner-{kb_id}", "long-password-1"
            )
            kwargs["owner_id"] = other["id"]
        else:
            kwargs.setdefault("owner_id", identity.user_id)
        await seed_externalized_kb(app, **kwargs)

    with identity_context(identity, token):
        with pytest.raises(ContextResolutionError) as exc:
            await TurnEnvironment(enterprise).prepare_request(
                {
                    "content": "请使用指定知识库",
                    "capability": "chat",
                    "knowledge_bases": [kb_id],
                    "context_policy": "required",
                    "llm_selection": {"profile_id": "chat", "model_id": "primary"},
                }
            )

    assert exc.value.error_code == "knowledge_base_unavailable"


async def test_enterprise_turn_environment_loads_multi_model_catalog_from_pg(
    app, monkeypatch
):
    """模型目录应来自 PG，DB 保存多个 profile 的 secret ref，而不是单本地 key。"""

    from deeptutor_enterprise.context import identity_context
    from deeptutor_enterprise.model_catalog import save_runtime_model_catalog
    from deeptutor_enterprise.runtime import TurnEnvironment

    enterprise = app.state.enterprise
    monkeypatch.setenv("DT_TEST_MODEL_BASIC", "basic-secret")
    monkeypatch.setenv("DT_TEST_MODEL_ADVANCED", "advanced-secret")
    token = await enterprise.identity.login("admin", "long-password-1", client="model-catalog")
    identity = await enterprise.identity.authenticate(token)
    with identity_context(identity, token):
        store = enterprise.store_provider.get()
        async with store.db.transaction(store.scope) as c:
            for name, reference in (
                ("model.basic", "env:DT_TEST_MODEL_BASIC"),
                ("model.advanced", "env:DT_TEST_MODEL_ADVANCED"),
            ):
                await c.execute(
                    "INSERT INTO enterprise.secret_references"
                    "(tenant_id,scope_kind,scope_id,name,provider,reference,version,status,"
                    "redacted_summary,updated_by) "
                    "VALUES(%s,'tenant','',%s,'env',%s,1,'active',%s,%s) "
                    "ON CONFLICT (tenant_id,scope_kind,scope_id,name) DO UPDATE "
                    "SET provider='env',reference=EXCLUDED.reference,status='active',"
                    "redacted_summary=EXCLUDED.redacted_summary,updated_by=EXCLUDED.updated_by,"
                    "version=enterprise.secret_references.version+1,updated_at=now()",
                    (
                        store.scope.tenant_id,
                        name,
                        reference,
                        f"env:{name}:active",
                        identity.user_id,
                    ),
                )
        catalog = {
            "models": [
                {
                    "profile_id": "chat",
                    "model_id": "basic",
                    "model": "qwen3.7-plus",
                    "base_url": "https://model.example/v1",
                    "secret_ref": "model.basic",
                    "provider": "openai",
                    "allowed_roles": ["user", "tenant_admin"],
                },
                {
                    "profile_id": "chat",
                    "model_id": "advanced",
                    "model": "qwen3.8-max",
                    "base_url": "https://model.example/v1",
                    "secret_ref": "model.advanced",
                    "provider": "openai",
                    "allowed_roles": ["user", "tenant_admin"],
                },
            ]
        }
        await save_runtime_model_catalog(store, catalog=catalog, actor_id=identity.user_id)
        prepared = await TurnEnvironment(enterprise).prepare_request(
            {
                "content": "使用高级模型",
                "capability": "chat",
                "tools": [],
                "llm_selection": {"profile_id": "chat", "model_id": "advanced"},
            }
        )

    assert prepared.llm_config.model == "qwen3.8-max"
    assert prepared.llm_config.api_key == "advanced-secret"
    assert "advanced-secret" not in json.dumps(catalog)


async def test_websocket_auth_refresh_updates_copied_turn_execution_context(app, monkeypatch):
    """WS auth_refresh 必须更新 start_turn 后台任务已复制的认证上下文。"""

    from deeptutor_enterprise.api.application import SocketAuthentication
    from deeptutor_enterprise.context import current_token, identity_context

    enterprise = app.state.enterprise
    class FakeEduPlus2:
        async def ensure_token_allowed(self, token):
            return None

        async def record_refresh_audit(self, token, *, request_id="", reason=""):
            return None

    monkeypatch.setattr(
        type(enterprise),
        "eduplus2",
        property(lambda self: FakeEduPlus2()),
    )
    old_token = await enterprise.identity.login("admin", "long-password-1", client="ws-old")
    new_token = await enterprise.identity.login("admin", "long-password-1", client="ws-new")
    assert new_token != old_token
    identity = await enterprise.identity.authenticate(old_token)
    auth = SocketAuthentication(enterprise)
    ws = SimpleNamespace(state=SimpleNamespace())
    release = asyncio.Event()

    async def copied_turn_context_observer():
        before = current_token()
        await release.wait()
        return before, current_token()

    with identity_context(identity, old_token):
        await auth.authenticate(ws)
        observer = asyncio.create_task(copied_turn_context_observer())
        await asyncio.sleep(0)
        await auth.refresh(
            ws,
            {"dt_token": new_token, "command_id": "refresh-copied-context"},
        )
        release.set()
        before, after = await observer

    assert before == old_token
    assert after == new_token


async def test_websocket_auth_refresh_rejects_identity_mismatch(app, monkeypatch):
    """长对话刷新 token 时必须保持同一用户身份，不能切换到另一个账号。"""

    from deeptutor_enterprise.api.application import SocketAuthentication
    from deeptutor_enterprise.context import identity_context

    enterprise = app.state.enterprise

    class FakeEduPlus2:
        async def ensure_token_allowed(self, token):
            return None

        async def record_refresh_audit(self, token, *, request_id="", reason=""):
            return None

    monkeypatch.setattr(
        type(enterprise),
        "eduplus2",
        property(lambda self: FakeEduPlus2()),
    )
    admin_token = await enterprise.identity.login("admin", "long-password-1", client="ws-old")
    await enterprise.identity.create_user(admin_token, "refresh-other", "long-password-2")
    other_token = await enterprise.identity.login(
        "refresh-other", "long-password-2", client="ws-new"
    )
    identity = await enterprise.identity.authenticate(admin_token)
    auth = SocketAuthentication(enterprise)
    ws = SimpleNamespace(state=SimpleNamespace())

    with identity_context(identity, admin_token):
        await auth.authenticate(ws)
        with pytest.raises(PermissionError, match="identity mismatch"):
            await auth.refresh(
                ws,
                {"dt_token": other_token, "command_id": "refresh-cross-user"},
            )


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


async def test_enterprise_production_ws_rejects_cross_owner_resource_refs(app):
    """resource_id 必须属于当前登录用户，不能引用其他用户已上传资源。"""

    from deeptutor_enterprise.api.application import SocketAuthentication
    from deeptutor_enterprise.context import identity_context

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore
    from deeptutor.runtime.externalized_providers import ObjectBlobRef

    enterprise = app.state.enterprise
    admin_token = await enterprise.identity.login("admin", "long-password-1", client="resource-owner")
    await enterprise.identity.create_user(admin_token, "resource-other", "long-password-2")
    other_token = await enterprise.identity.login(
        "resource-other", "long-password-2", client="resource-owner"
    )
    admin_identity = await enterprise.identity.authenticate(admin_token)
    other_identity = await enterprise.identity.authenticate(other_token)
    image_bytes = b"\x89PNG\r\n\x1a\nowner-only"
    blobs: dict[str, tuple[bytes, str, str]] = {}

    def put_bytes(key: str, data: bytes, *, expected_sha256: str, content_type: str):
        blobs[key] = (data, expected_sha256, content_type)
        return ObjectBlobRef(
            key=key,
            size_bytes=len(data),
            sha256=expected_sha256,
            content_type=content_type,
        )

    def head_object(key: str):
        data, expected_sha256, content_type = blobs[key]
        return ObjectBlobRef(
            key=key,
            size_bytes=len(data),
            sha256=expected_sha256,
            content_type=content_type,
        )

    enterprise.object_store.put_bytes = put_bytes
    enterprise.object_store.head_object = head_object
    with identity_context(admin_identity, admin_token):
        resource_store = PostgresObjectResourceStore(
            enterprise.store_provider.get(), enterprise.object_store
        )
        handle = await resource_store.put(
            resource_kind="turn_input",
            resource_id="res_owner_only",
            filename="owner.png",
            data=image_bytes,
            mime_type="image/png",
            metadata={"purpose": "chat_turn"},
        )

    auth = SocketAuthentication(enterprise)
    with identity_context(other_identity, other_token):
        with pytest.raises(ValueError, match="invalid resource reference"):
            await auth.validate_start_turn(
                None,
                {
                    "content": "请分析",
                    "attachments": [],
                    "resource_ids": [handle.resource_id],
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
