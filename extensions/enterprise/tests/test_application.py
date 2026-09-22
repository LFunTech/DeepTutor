import asyncio
import hashlib
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
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


async def test_conversation_test_options_are_authenticated_and_non_secret(app):
    """普通测试页选项接口只返回可选能力，不暴露 provider 配置或密钥。"""

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="conversation-test")
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
        serialized = authorized.text.lower()
        assert "secret" not in serialized
        assert "api_secret" not in serialized
        assert "endpoint" not in serialized




async def test_conversation_test_options_disable_kbs_when_rag_policy_is_not_enabled(
    app, monkeypatch
):
    """部署未允许知识库检索时，普通测试页不得展示可选但发送必失败的 KB。"""

    from deeptutor.multi_user import knowledge_access

    monkeypatch.setattr(
        knowledge_access,
        "list_visible_knowledge_bases",
        lambda: [
            {
                "id": "user:kb:test",
                "name": "test",
                "provenance_label": "Created by you",
            }
        ],
    )
    monkeypatch.setattr(
        knowledge_access,
        "resolve_kb",
        lambda resource_id, require_write=False: SimpleNamespace(name="test"),
    )
    monkeypatch.setattr(
        knowledge_access,
        "manager_for_resource",
        lambda resource: SimpleNamespace(get_kb_entry=lambda name: {"status": "ready"}),
    )

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="conversation-test")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
        headers={"Authorization": "Bearer " + token},
    ) as client:
        response = await client.get("/api/v1/enterprise/conversation-test/options")

    assert response.status_code == 200, response.text
    [kb] = response.json()["knowledge_bases"]
    assert kb["id"] == "user:kb:test"
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
