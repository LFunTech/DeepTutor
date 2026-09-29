import asyncio
from datetime import datetime, timedelta, timezone
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
import psycopg
import pytest
import pytest_asyncio

from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


def install_oms_verifier(application, subjects_by_token: dict[str, str]):
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            subject = subjects_by_token.get(token)
            if subject is None:
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject=subject,
                client_id="eduplus-platform-admin",
                token_hash="digest-" + subject,
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return subjects_by_token.get(token) == subject and issuer == "https://issuer.example"

    application.state.enterprise.oms_platform_verifier = Verifier()
    application.state.enterprise.oms_account_status = AccountStatus()


def test_enterprise_core_version_falls_back_to_source_tree_version(monkeypatch):
    """源码拷贝型 runtime 没有 distribution metadata 时仍可校验 core 版本。"""

    from importlib.metadata import PackageNotFoundError

    import deeptutor_enterprise.bootstrap as bootstrap

    from deeptutor.__version__ import __version__

    def missing_distribution(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(bootstrap, "version", missing_distribution)

    assert bootstrap._core_version() == __version__


@pytest_asyncio.fixture
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


async def test_oms_me_rejects_tenant_token_and_unconfigured_platform_identity(app):
    enterprise = app.state.enterprise
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        missing = await client.get("/api/v1/oms/me")
        tenant = await client.get(
            "/api/v1/oms/me", headers={"Authorization": "Bearer tenant-token"}
        )
    assert missing.status_code == 401
    assert tenant.status_code == 503
    assert enterprise.oms_platform_verifier is None


async def test_oms_me_uses_verified_platform_identity_and_local_action(app, pg_dsn):
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            if token != "valid-platform-token":
                raise PermissionError("bad platform token")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject="operator",
                client_id="eduplus-platform-admin",
                token_hash="digest",
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        active = True

        async def check(self, token, *, issuer, subject):
            assert token == "valid-platform-token"
            assert (issuer, subject) == ("https://issuer.example", "operator")
            return self.active

    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    status = AccountStatus()
    enterprise.oms_account_status = status
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        no_local_grant = await client.get(
            "/api/v1/oms/me", headers={"Authorization": "Bearer valid-platform-token"}
        )
        assert no_local_grant.status_code == 403
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            principal = uuid.uuid4()
            await c.execute(
                "INSERT INTO management.principals"
                "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
                (principal, "https://issuer.example", "operator"),
            )
            await c.execute(
                "INSERT INTO management.assignments"
                "(id,application,principal_id,role_key,role_version,scope_kind,"
                "valid_from,expires_at,command_id,created_by) "
                "VALUES(%s,'oms',%s,'platform_security_admin',2,'platform',"
                "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
                (uuid.uuid4(), principal, uuid.uuid4()),
            )
        granted = await client.get(
            "/api/v1/oms/me", headers={"Authorization": "Bearer valid-platform-token"}
        )
        assert granted.status_code == 200, granted.text
        assert granted.json()["subject"] == "operator"
        assert granted.json()["application"] == "oms"
        assert "tenant_id" not in granted.json()
        client.cookies.set("dt_oms_token", "valid-platform-token", path="/api/v1/oms")
        client.cookies.set("dt_oms_csrf", "csrf-token", path="/api/v1/oms")
        cookie_granted = await client.get("/api/v1/oms/me")
        assert cookie_granted.status_code == 200, cookie_granted.text
        assert cookie_granted.json()["subject"] == "operator"
        missing_csrf = await client.post(
            "/api/v1/oms/models/draft",
            json={
                "expected_version": 0,
                "reason": "缺 CSRF",
                "models": [
                    {
                        "profile_id": "chat",
                        "model_id": "primary",
                        "model": "example",
                        "base_url": "https://model.example/v1",
                        "secret": "env:DT_TEST_MODEL",
                    }
                ],
            },
            headers={"Origin": "https://school.example"},
        )
        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["detail"] == "Origin or CSRF rejected"
        denied_models = await client.get(
            "/api/v1/oms/models",
            headers={"Authorization": "Bearer valid-platform-token"},
        )
        assert denied_models.status_code == 403
        denied_write = await client.post(
            "/api/v1/oms/models/draft",
            json={
                "expected_version": 0,
                "reason": "无权尝试",
                "models": [
                    {
                        "profile_id": "chat",
                        "model_id": "primary",
                        "model": "example",
                        "base_url": "https://model.example/v1",
                        "secret": "env:DT_TEST_MODEL",
                    }
                ],
            },
            headers={
                "Authorization": "Bearer valid-platform-token",
                "Origin": "https://school.example",
            },
        )
        assert denied_write.status_code == 403
        status.active = False
        disabled = await client.get(
            "/api/v1/oms/me", headers={"Authorization": "Bearer valid-platform-token"}
        )
        assert disabled.status_code == 403
        forged = await client.get(
            "/api/v1/oms/me", headers={"Authorization": "Bearer tenant-token"}
        )
        assert forged.status_code == 401


async def test_oms_first_admin_bootstrap_seeds_local_roles_and_closes_after_first_run(app):
    """首位 OMS 管理员只能来自已认证平台身份，且只在零本地管理员时初始化。"""

    install_oms_verifier(
        app,
        {
            "first-token": "first-operator",
            "second-token": "second-operator",
        },
    )
    command_id = str(uuid.uuid4())
    payload = {"command_id": command_id, "reason": "test-cn 首位 OMS 管理员初始化"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        client.cookies.set("dt_oms_token", "first-token", path="/api/v1/oms")
        client.cookies.set("dt_oms_csrf", "csrf-token", path="/api/v1/oms")

        assert (await client.get("/api/v1/oms/me")).status_code == 403
        missing_csrf = await client.post(
            "/api/v1/oms/bootstrap/first-admin",
            json=payload,
            headers={"Origin": "https://school.example"},
        )
        assert missing_csrf.status_code == 403

        bootstrapped = await client.post(
            "/api/v1/oms/bootstrap/first-admin",
            json=payload,
            headers={"Origin": "https://school.example", "x-csrf-token": "csrf-token"},
        )
        assert bootstrapped.status_code == 200, bootstrapped.text
        body = bootstrapped.json()
        assert body["application"] == "oms"
        assert body["subject_hash"]
        assert body["roles"] == ["platform_config_admin", "platform_security_admin"]
        assert body["replayed"] is False
        assert body["target_policy_version"] >= 3

        me = await client.get("/api/v1/oms/me")
        assert me.status_code == 200, me.text
        assert me.json()["subject"] == "first-operator"
        permissions = await client.get("/api/v1/oms/me/permissions")
        assert permissions.status_code == 200, permissions.text
        actions = set(permissions.json()["platform_actions"])
        assert {
            "ops.oms.access",
            "ops.permissions.manage",
            "ops.providers.manage",
            "ops.skills.read",
            "ops.skills.publish",
        }.issubset(actions)
        assert (await client.get("/api/v1/oms/provider-settings")).status_code == 200
        assert (await client.get("/api/v1/oms/skills")).status_code == 200

        replay = await client.post(
            "/api/v1/oms/bootstrap/first-admin",
            json=payload,
            headers={"Origin": "https://school.example", "x-csrf-token": "csrf-token"},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["replayed"] is True

        client.cookies.set("dt_oms_token", "second-token", path="/api/v1/oms")
        client.cookies.set("dt_oms_csrf", "csrf-token-2", path="/api/v1/oms")
        blocked = await client.post(
            "/api/v1/oms/bootstrap/first-admin",
            json={"command_id": str(uuid.uuid4()), "reason": "second attempt"},
            headers={"Origin": "https://school.example", "x-csrf-token": "csrf-token-2"},
        )
        assert blocked.status_code == 409




async def test_oms_skills_list_requires_skill_read_and_redacts_storage(app, pg_dsn):
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            subjects = {"skill-reader-token": "skill-reader", "access-token": "access-only"}
            subject = subjects.get(token)
            if subject is None:
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject=subject,
                client_id="eduplus-platform-admin",
                token_hash="digest-" + subject,
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return issuer == "https://issuer.example" and token in {"skill-reader-token", "access-token"}

    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    revision_id = uuid.uuid4()
    review_id = uuid.uuid4()
    publication_id = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        reader_id = uuid.uuid4()
        access_id = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) "
            "VALUES(%s,'oms','https://issuer.example','skill-reader','active'),"
            "(%s,'oms','https://issuer.example','access-only','active')",
            (reader_id, access_id),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_security_admin',2,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval'),"
            "(%s,'oms',%s,'platform_security_admin',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), reader_id, uuid.uuid4(), uuid.uuid4(), access_id, uuid.uuid4()),
        )
        await c.execute(
            "INSERT INTO oms.skill_revisions"
            "(id,owner_kind,name,version,source,content_sha256,object_key,content_bytes,"
            "metadata,created_by,created_issuer) "
            "VALUES(%s,'global','lesson-coach',1,'upload',%s,%s,2048,%s::jsonb,"
            "'skill-author','https://issuer.example')",
            (
                revision_id,
                "a" * 64,
                "oms/skills/global/lesson-coach/secret-object.zip",
                json.dumps({"description": "课堂引导 Skill", "tags": ["teaching"], "requires": {"bins": [], "env": [], "sandbox": False}}),
            ),
        )
        await c.execute(
            "INSERT INTO oms.skill_reviews"
            "(id,revision_id,content_sha256,approved,scanner_version,code_file_digests,"
            "code_review_evidence,reviewer_issuer,reviewer_subject,reason,request_id) "
            "VALUES(%s,%s,%s,true,'skill-archive-v1',%s::jsonb,'manual review',"
            "'https://issuer.example','security-reviewer','审查通过','review-1')",
            (review_id, revision_id, "a" * 64, json.dumps({})),
        )
        await c.execute(
            "INSERT INTO oms.skill_publications"
            "(id,owner_kind,name,revision_id,review_id,version,published_by,published_issuer) "
            "VALUES(%s,'global','lesson-coach',%s,%s,1,'publisher','https://issuer.example')",
            (publication_id, revision_id, review_id),
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        allowed = await client.get(
            "/api/v1/oms/skills", headers={"Authorization": "Bearer skill-reader-token"}
        )
        denied = await client.get(
            "/api/v1/oms/skills", headers={"Authorization": "Bearer access-token"}
        )

    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["application"] == "oms"
    assert body["skills"] == [
        {
            "name": "lesson-coach",
            "status": "published",
            "latest_version": 1,
            "published_version": 1,
            "published_revision_id": str(revision_id),
            "sha256": "a" * 64,
            "description": "课堂引导 Skill",
            "tags": ["teaching"],
            "grant_count": 0,
        }
    ]
    assert "secret-object" not in allowed.text
    assert "object_key" not in allowed.text
    assert denied.status_code == 403, denied.text


async def test_oms_permissions_catalog_is_platform_security_admin_only(app, pg_dsn):
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            subjects = {"security-token": "security-admin", "config-token": "config-admin"}
            subject = subjects.get(token)
            if subject is None:
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject=subject,
                client_id="eduplus-platform-admin",
                token_hash="digest-" + subject,
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return token in {"security-token", "config-token"} and issuer == "https://issuer.example"

    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        security_id = uuid.uuid4()
        config_id = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) "
            "VALUES(%s,'oms','https://issuer.example','security-admin','active'),"
            "(%s,'oms','https://issuer.example','config-admin','active')",
            (security_id, config_id),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_security_admin',2,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval'),"
            "(%s,'oms',%s,'platform_config_admin',2,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), security_id, uuid.uuid4(), uuid.uuid4(), config_id, uuid.uuid4()),
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        allowed = await client.get(
            "/api/v1/oms/permissions", headers={"Authorization": "Bearer security-token"}
        )
        denied = await client.get(
            "/api/v1/oms/permissions", headers={"Authorization": "Bearer config-token"}
        )

    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["application"] == "oms"
    assert any(action["action_key"] == "ops.permissions.manage" for action in body["actions"])
    assert {role["role_key"] for role in body["roles"]} >= {
        "platform_security_admin",
        "platform_config_admin",
        "platform_operator",
    }
    assert any(item["subject"] == "security-admin" for item in body["principals"])
    assert any(item["role_key"] == "platform_security_admin" for item in body["assignments"])
    assert all(action["action_key"].startswith("ops.") for action in body["actions"])
    assert "tenant." not in allowed.text
    assert denied.status_code == 403, denied.text


async def test_oms_approval_api_applies_platform_sensitive_role(app, pg_dsn):
    install_oms_verifier(
        app,
        {
            "proposer-token": "security-proposer",
            "reviewer-token": "security-reviewer",
            "config-token": "config-target",
        },
    )
    target_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    approval_expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        proposer_id = uuid.uuid4()
        reviewer_id = uuid.uuid4()
        target_id = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) "
            "VALUES(%s,'oms','https://issuer.example','security-proposer','active'),"
            "(%s,'oms','https://issuer.example','security-reviewer','active'),"
            "(%s,'oms','https://issuer.example','config-target','pending')",
            (proposer_id, reviewer_id, target_id),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_security_admin',2,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval'),"
            "(%s,'oms',%s,'platform_security_admin',2,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), proposer_id, uuid.uuid4(), uuid.uuid4(), reviewer_id, uuid.uuid4()),
        )
        role_actions = await (
            await c.execute(
                "SELECT action_key FROM management.role_actions "
                "WHERE application='oms' AND role_key='platform_config_admin' "
                "AND role_version=2 ORDER BY action_key"
            )
        ).fetchall()
        for row in role_actions:
            await c.execute(
                "INSERT INTO management.delegation_policies"
                "(id,application,principal_id,action_key,scope_kind,school_id,"
                "valid_from,expires_at) "
                "VALUES(%s,'oms',%s,%s,'platform',NULL,now()-interval '1 minute',%s)",
                (uuid.uuid4(), reviewer_id, row[0], target_expires_at),
            )

    headers = {"Authorization": "Bearer proposer-token", "Origin": "https://school.example"}
    reviewer_headers = {"Authorization": "Bearer reviewer-token", "Origin": "https://school.example"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        denied = await client.post(
            "/api/v1/oms/approvals",
            json={
                "operation": "platform_grant",
                "target_principal_id": str(target_id),
                "expected_target_policy_version": 1,
                "expires_at": approval_expires_at.isoformat(),
                "idempotency_key": "oms-platform-grant-1",
                "reason": "缺失显式模板版本确认",
                "external_qualification_ref": "contract://platform/approval/1",
                "external_qualification_version": "v1",
                "target_role_key": "platform_config_admin",
                "target_role_version": 2,
                "target_expires_at": target_expires_at.isoformat(),
            },
            headers=headers,
        )
        created = await client.post(
            "/api/v1/oms/approvals",
            json={
                "operation": "platform_grant",
                "target_principal_id": str(target_id),
                "expected_target_policy_version": 1,
                "expires_at": approval_expires_at.isoformat(),
                "idempotency_key": "oms-platform-grant-2",
                "reason": "授予平台配置管理员",
                "external_qualification_ref": "contract://platform/approval/2",
                "external_qualification_version": "v1",
                "target_role_key": "platform_config_admin",
                "target_role_version": 2,
                "confirmed_role_version": 2,
                "target_expires_at": target_expires_at.isoformat(),
            },
            headers=headers,
        )
        assert denied.status_code == 422, denied.text
        assert created.status_code == 200, created.text
        approval_id = created.json()["approval_id"]
        listed = await client.get(
            "/api/v1/oms/approvals", headers={"Authorization": "Bearer proposer-token"}
        )
        reviewed = await client.post(
            f"/api/v1/oms/approvals/{approval_id}/review",
            json={
                "decision": "approved",
                "expected_target_policy_version": 1,
                "reason": "独立平台安全管理员复核",
            },
            headers=reviewer_headers,
        )
        applied = await client.post(
            f"/api/v1/oms/approvals/{approval_id}/apply",
            json={
                "expected_target_policy_version": 1,
                "command_id": str(uuid.uuid4()),
                "reason": "按已批准审批应用",
            },
            headers=reviewer_headers,
        )
        target_me = await client.get(
            "/api/v1/oms/me", headers={"Authorization": "Bearer config-token"}
        )

    assert listed.status_code == 200, listed.text
    assert any(item["approval_id"] == approval_id for item in listed.json()["approvals"])
    assert "tenant." not in listed.text
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "approved"
    assert applied.status_code == 200, applied.text
    assert applied.json()["role_key"] == "platform_config_admin"
    assert applied.json()["target_policy_version"] == 2
    assert target_me.status_code == 200, target_me.text


async def test_oms_principal_school_scope_grant_and_disable_are_guarded(app, pg_dsn):
    install_oms_verifier(
        app,
        {
            "security-token": "security-admin",
            "auditor-token": "auditor-target",
        },
    )
    school_id = uuid.uuid4()
    hidden_school_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        security_id = uuid.uuid4()
        target_id = uuid.uuid4()
        await c.execute(
            "INSERT INTO enterprise.tenants"
            "(id,external_eligibility,local_enabled,provisioning_status,"
            "recovery_state,auth_epoch,bootstrap_completed) "
            "VALUES(%s,'allowed',true,'ready','normal','epoch',true),"
            "(%s,'allowed',true,'ready','normal','epoch',true)",
            (school_id, hidden_school_id),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,73001,'verified',now(),'synthetic','synthetic://school'),"
            "(%s,73002,'verified',now(),'synthetic','synthetic://hidden')",
            (school_id, hidden_school_id),
        )
        await c.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) "
            "VALUES(%s,'oms','https://issuer.example','security-admin','active'),"
            "(%s,'oms','https://issuer.example','auditor-target','pending')",
            (security_id, target_id),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_security_admin',2,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), security_id, uuid.uuid4()),
        )
        for action_key in ("ops.tenants.read", "ops.oms.access", "ops.audit.read", "ops.usage.read"):
            await c.execute(
                "INSERT INTO management.delegation_policies"
                "(id,application,principal_id,action_key,scope_kind,school_id,"
                "valid_from,expires_at) "
                "VALUES(%s,'oms',%s,%s,'school',%s,now()-interval '1 minute',%s)",
                (uuid.uuid4(), security_id, action_key, school_id, expires_at),
            )

    headers = {"Authorization": "Bearer security-token", "Origin": "https://school.example"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        hidden = await client.post(
            f"/api/v1/oms/principals/{target_id}/roles",
            json={
                "role_key": "platform_auditor",
                "role_version": 1,
                "target_school_id": str(hidden_school_id),
                "expected_target_policy_version": 1,
                "expires_at": expires_at.isoformat(),
                "command_id": str(uuid.uuid4()),
                "reason": "未委托学校负例",
            },
            headers=headers,
        )
        granted = await client.post(
            f"/api/v1/oms/principals/{target_id}/roles",
            json={
                "role_key": "platform_auditor",
                "role_version": 1,
                "target_school_id": str(school_id),
                "expected_target_policy_version": 1,
                "expires_at": expires_at.isoformat(),
                "command_id": str(uuid.uuid4()),
                "reason": "授予学校只读范围",
            },
            headers=headers,
        )
        permissions = await client.get(
            "/api/v1/oms/me/permissions", headers={"Authorization": "Bearer auditor-token"}
        )
        revoked = await client.post(
            f"/api/v1/oms/assignments/{granted.json().get('assignment_id')}/revoke",
            json={
                "target_school_id": str(school_id),
                "expected_assignment_version": 1,
                "expected_target_policy_version": 2,
                "command_id": str(uuid.uuid4()),
                "reason": "撤销学校只读范围",
            },
            headers=headers,
        )
        after_revoke = await client.get(
            "/api/v1/oms/me", headers={"Authorization": "Bearer auditor-token"}
        )
        disabled = await client.post(
            f"/api/v1/oms/principals/{target_id}/disable",
            json={
                "expected_target_policy_version": 3,
                "reason": "停用平台主体",
            },
            headers=headers,
        )
        after_disable = await client.get(
            "/api/v1/oms/me", headers={"Authorization": "Bearer auditor-token"}
        )

    assert hidden.status_code == 403, hidden.text
    assert granted.status_code == 200, granted.text
    assert granted.json()["school_id"] == str(school_id)
    assert permissions.status_code == 200, permissions.text
    assert permissions.json()["school_actions"] == [
        {
            "school_id": str(school_id),
            "actions": ["ops.audit.read", "ops.oms.access", "ops.tenants.read", "ops.usage.read"],
        }
    ]
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["target_policy_version"] == 3
    assert after_revoke.status_code == 403
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["target_policy_version"] == 4
    assert after_disable.status_code == 403


async def test_oms_permissions_summary_allows_school_scoped_operator_without_platform_grant(
    app, pg_dsn
):
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            if token != "school-operator-token":
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject="school-operator",
                client_id="eduplus-platform-admin",
                token_hash="digest",
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return token == "school-operator-token" and subject == "school-operator"

    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    school_id = uuid.uuid4()
    hidden_school_id = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        principal = uuid.uuid4()
        await c.execute(
            "INSERT INTO enterprise.tenants"
            "(id,external_eligibility,local_enabled,provisioning_status,"
            "auth_epoch,bootstrap_completed) "
            "VALUES(%s,'allowed',true,'ready','epoch',true),"
            "(%s,'allowed',true,'ready','epoch',true)",
            (school_id, hidden_school_id),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,72001,'verified',now(),'synthetic','synthetic://school'),"
            "(%s,72002,'verified',now(),'synthetic','synthetic://hidden')",
            (school_id, hidden_school_id),
        )
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal, "https://issuer.example", "school-operator"),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
            "school_binding_version,valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_operator',2,'school',%s,1,"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, school_id, uuid.uuid4()),
        )
    headers = {"Authorization": "Bearer school-operator-token"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        me = await client.get("/api/v1/oms/me", headers=headers)
        permissions = await client.get("/api/v1/oms/me/permissions", headers=headers)
        tenants = await client.get("/api/v1/oms/tenants", headers=headers)
        hidden = await client.get(f"/api/v1/oms/tenants/{hidden_school_id}", headers=headers)
        provider_write = await client.post(
            "/api/v1/oms/models/draft",
            json={
                "expected_version": 0,
                "reason": "越权",
                "models": [
                    {
                        "profile_id": "chat",
                        "model_id": "primary",
                        "model": "example",
                        "base_url": "https://model.example/v1",
                        "secret": "env:DT_TEST_MODEL",
                    }
                ],
            },
            headers={**headers, "Origin": "https://school.example"},
        )

    assert me.status_code == 200, me.text
    assert me.json()["application"] == "oms"
    assert permissions.status_code == 200, permissions.text
    payload = permissions.json()
    assert payload["platform_actions"] == []
    assert payload["school_actions"] == [
        {
            "school_id": str(school_id),
            "actions": [
                "ops.entitlements.manage",
                "ops.entitlements.read",
                "ops.oms.access",
                "ops.quotas.manage",
                "ops.quotas.read",
                "ops.skills.grant",
                "ops.supply.manage",
                "ops.supply.read",
                "ops.tenants.read",
                "ops.usage.read",
            ],
        }
    ]
    assert "ops.providers.manage" not in permissions.text
    assert "tenant." not in permissions.text
    assert tenants.status_code == 200, tenants.text
    assert [item["school_id"] for item in tenants.json()["tenants"]] == [str(school_id)]
    assert hidden.status_code == 403
    assert provider_write.status_code == 403


async def test_oms_model_inventory_requires_provider_read_and_redacts_credentials(app, pg_dsn):
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            if token != "config-token":
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject="config-admin",
                client_id="eduplus-platform-admin",
                token_hash="digest",
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return token == "config-token" and subject == "config-admin"

    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        principal = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal, "https://issuer.example", "config-admin"),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_config_admin',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, uuid.uuid4()),
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        response = await client.get(
            "/api/v1/oms/models", headers={"Authorization": "Bearer config-token"}
        )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "models": [
            {
                "profile_id": "chat",
                "model_id": "primary",
                "model": "some-model",
                "provider": "openai",
                "source": "deployment",
                "managed": False,
                "status": "readiness_unverified",
            }
        ]
    }
    assert "model-secret" not in response.text
    assert "DT_TEST_MODEL" not in response.text
    assert "base_url" not in response.text


async def test_oms_resource_status_maps_platform_categories_without_secrets(app, pg_dsn):
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            if token != "config-token":
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject="config-admin",
                client_id="eduplus-platform-admin",
                token_hash="digest",
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return token == "config-token" and subject == "config-admin"

    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        principal = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal, "https://issuer.example", "config-admin"),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_config_admin',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, uuid.uuid4()),
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        response = await client.get(
            "/api/v1/oms/resources/status", headers={"Authorization": "Bearer config-token"}
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["categories"] == [
        "model_external",
        "agent_capability",
        "tool_integration",
        "knowledge_content",
        "runtime",
    ]
    by_id = {item["id"]: item for item in payload["resources"]}
    assert by_id["model:chat:primary"] == {
        "id": "model:chat:primary",
        "category": "model_external",
        "kind": "chat_model",
        "status": "readiness_unverified",
        "managed": False,
        "display_name": "primary",
        "safe_fields": {
            "profile_id": "chat",
            "model_id": "primary",
            "provider": "openai",
            "task_fallback": "uses_chat_model_when_task_model_missing",
        },
    }
    assert by_id["knowledge:lightrag"]["status"] == "ready"
    assert by_id["knowledge:lightrag"]["safe_fields"] == {
        "workspace_binding": "workspace-main",
        "index_version": "idx-v1",
        "contract_version": "lightrag-api-v1",
        "object_store": "configured",
    }
    assert by_id["tool:web_search"]["status"] == "not_configured"
    assert by_id["model:embedding"]["safe_fields"] == {
        "endpoint_contract": "full_https_url_required",
        "usage_source": "provider_usage_or_reconciliation",
    }
    assert by_id["media:tts"]["status"] == "not_configured"
    assert by_id["media:stt"]["status"] == "not_configured"
    assert by_id["media:image"]["safe_fields"]["native_unit"] == "image"
    assert by_id["media:video"]["safe_fields"]["native_unit"] == "second"
    assert by_id["agent:external"]["safe_fields"]["callable"] is False
    assert by_id["tool:mcp"]["safe_fields"]["requires_tenant_binding"] is True
    assert by_id["runtime:postgres"]["status"] == "ready"
    assert by_id["runtime:object_store"]["status"] == "ready"
    assert "DT_TEST" not in response.text
    assert "objects.example" not in response.text
    assert "lightrag.example" not in response.text
    assert "model.example" not in response.text


async def test_oms_governance_read_api_filters_by_local_school_grants_and_descriptors(
    app, pg_dsn
):
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            if token != "governance-token":
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject="governance-operator",
                client_id="eduplus-platform-admin",
                token_hash="digest",
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return token == "governance-token" and subject == "governance-operator"

    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    school_id = uuid.uuid4()
    hidden_school_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        principal = uuid.uuid4()
        await c.execute(
            "INSERT INTO enterprise.tenants"
            "(id,external_eligibility,local_enabled,provisioning_status,"
            "auth_epoch,bootstrap_completed) "
            "VALUES(%s,'allowed',true,'ready','epoch',true),"
            "(%s,'allowed',true,'ready','epoch',true)",
            (school_id, hidden_school_id),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,71001,'verified',now(),'synthetic','synthetic://school'),"
            "(%s,71002,'verified',now(),'synthetic','synthetic://hidden')",
            (school_id, hidden_school_id),
        )
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal, "https://issuer.example", "governance-operator"),
        )
        await c.execute(
            "INSERT INTO management.role_versions"
            "(application,role_key,version,scope_kind,is_template) "
            "VALUES('oms','school_governance_reader',1,'school',false),"
            "('oms','platform_supply_cost_reader',1,'platform',false)"
        )
        await c.execute(
            "INSERT INTO management.role_actions"
            "(application,role_key,role_version,action_key) VALUES"
            "('oms','school_governance_reader',1,'ops.oms.access'),"
            "('oms','school_governance_reader',1,'ops.tenants.read'),"
            "('oms','school_governance_reader',1,'ops.usage.read'),"
            "('oms','school_governance_reader',1,'ops.jobs.read'),"
            "('oms','school_governance_reader',1,'ops.audit.read'),"
            "('oms','platform_supply_cost_reader',1,'ops.supply.read'),"
            "('oms','platform_supply_cost_reader',1,'ops.cost.read')"
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_security_admin',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval'),"
            "(%s,'oms',%s,'platform_supply_cost_reader',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, uuid.uuid4(), uuid.uuid4(), principal, uuid.uuid4()),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
            "school_binding_version,valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'school_governance_reader',1,'school',%s,1,"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, school_id, uuid.uuid4()),
        )
        await c.execute(
            "INSERT INTO oms.service_definitions"
            "(service_id,unit_code,resource_category,enabled) "
            "VALUES('llm','token','model_external',true)"
        )
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_id),))
        await c.execute(
            "INSERT INTO oms.usage_attempts"
            "(tenant_id,attempt_id,operation_id,service_id,unit_code,provider_id,"
            "provider_account_id,model_id,config_version,subject_kind,subject_id,user_id,"
            "status,reserved_units,settled_units,evidence) "
            "VALUES(%s,%s,%s,'llm','token','provider-a','acct','model-a',1,"
            "'user','learner-1','learner-1','remote_unknown',12,0,%s::jsonb)",
            (school_id, attempt_id, operation_id, json.dumps({"diagnostic": "redacted"})),
        )
        await c.execute(
            "INSERT INTO oms.supply_lots"
            "(id,service_id,provider_id,provider_account_id,pool_id,unit_code,"
            "evidence_ref,hard_ceiling,starts_at,expires_at,supply_basis,verified_at) "
            "VALUES(%s,'llm','provider-a','acct','pool-a','token',"
            "'contract://safe',100,now()-interval '1 day',now()+interval '7 days',"
            "'native_units',now())",
            (uuid.uuid4(),),
        )
        await c.execute("SELECT set_config('app.management_app','oms',true)")
        await c.execute(
            "INSERT INTO management.audit_events"
            "(id,application,school_id,actor_issuer,actor_subject,action_key,"
            "target_kind,target_id,request_id,result,reason,safe_summary) "
            "VALUES(%s,'oms',%s,%s,%s,'ops.tenants.read','school',%s,%s,"
            "'success','synthetic audit',%s::jsonb)",
            (
                uuid.uuid4(),
                school_id,
                "https://issuer.example",
                "governance-operator",
                str(school_id),
                "governance-audit-1",
                json.dumps({"safe": True}),
            ),
        )
    headers = {"Authorization": "Bearer governance-token"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        catalog = await client.get("/api/v1/oms/status/catalog", headers=headers)
        summary = await client.get("/api/v1/oms/summary", headers=headers)
        tenants = await client.get("/api/v1/oms/tenants", headers=headers)
        detail = await client.get(f"/api/v1/oms/tenants/{school_id}", headers=headers)
        hidden = await client.get(f"/api/v1/oms/tenants/{hidden_school_id}", headers=headers)
        usage = await client.get(
            f"/api/v1/oms/schools/{school_id}/usage?service_id=llm&limit=10",
            headers=headers,
        )
        jobs = await client.get(f"/api/v1/oms/schools/{school_id}/jobs", headers=headers)
        supply = await client.get("/api/v1/oms/supply", headers=headers)
        audit = await client.get(
            f"/api/v1/oms/audit?school_id={school_id}&limit=10", headers=headers
        )
        cost = await client.get("/api/v1/oms/cost", headers=headers)

    assert catalog.status_code == 200, catalog.text
    assert any(item["code"] == "reconcile_required" for item in catalog.json()["statuses"])
    assert summary.status_code == 200, summary.text
    assert summary.json()["authorized_school_count"] == 1
    assert tenants.status_code == 200, tenants.text
    assert [item["school_id"] for item in tenants.json()["tenants"]] == [str(school_id)]
    assert detail.status_code == 200, detail.text
    assert detail.json()["external_binding"]["status"]["code"] == "verified"
    assert hidden.status_code == 403
    assert usage.status_code == 200, usage.text
    assert usage.json()["usage"][0]["status"]["code"] == "remote_unknown"
    assert usage.json()["page"] == {"limit": 10, "offset": 0, "count": 1}
    assert usage.json()["details"][0] == {
        "attempt_id": str(attempt_id),
        "operation_id": str(operation_id),
        "service_id": "llm",
        "unit_code": "token",
        "provider_id": "provider-a",
        "model_id": "model-a",
        "subject_kind": "user",
        "subject_id": "learner-1",
        "user_id": "learner-1",
        "app_id": "",
        "status": {
            "code": "remote_unknown",
            "label": "远端结果未知",
            "tone": "warning",
            "description": "远端调用可能已经发生，必须核对后才能释放或结算。",
        },
        "reserved_units": "12",
        "settled_units": "0",
        "started_at": usage.json()["details"][0]["started_at"],
        "updated_at": usage.json()["details"][0]["updated_at"],
    }
    assert "provider_request_id" not in usage.text
    assert "diagnostic" not in usage.text
    assert jobs.status_code == 200, jobs.text
    assert jobs.json()["jobs"][0]["attempt_id"] == str(attempt_id)
    assert "provider_request_id" not in jobs.text
    assert "diagnostic" not in jobs.text
    assert supply.status_code == 200, supply.text
    assert supply.json()["service_definitions"][0]["service_id"] == "llm"
    assert "contract://safe" not in supply.text
    assert audit.status_code == 200, audit.text
    assert audit.json()["management_events"][0]["result"]["code"] == "success"
    assert cost.status_code == 200, cost.text
    assert cost.json()["status"]["code"] == "not_configured"
    assert "DT_TEST" not in (
        catalog.text
        + summary.text
        + tenants.text
        + detail.text
        + usage.text
        + jobs.text
        + supply.text
        + audit.text
        + cost.text
    )


async def test_oms_model_draft_is_versioned_audited_and_never_active_without_publish(
    app, pg_dsn, monkeypatch
):
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    from deeptutor.persistence.postgres.scope import GlobalScope

    class Verifier:
        async def verify(self, token):
            if token != "config-token":
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject="config-admin",
                client_id="eduplus-platform-admin",
                token_hash="digest",
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return token == "config-token" and subject == "config-admin"

    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    original_transaction = enterprise.db.transaction

    def platform_only_transaction(scope):
        if scope.user_id == "@oms-model-draft":
            assert isinstance(scope, GlobalScope), (
                "OMS global model catalog must not borrow tenant scope"
            )
        return original_transaction(scope)

    monkeypatch.setattr(enterprise.db, "transaction", platform_only_transaction)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        principal = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal, "https://issuer.example", "config-admin"),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_config_admin',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, uuid.uuid4()),
        )
    command = {
        "expected_version": 0,
        "reason": "为测试学校准备首个 Agent 模型",
        "models": [
            {
                "profile_id": "chat",
                "model_id": "next",
                "model": "next-model",
                "provider": "openai",
                "base_url": "https://model.example/v1",
                "secret": "env:DT_TEST_MODEL",
                "allowed_roles": ["user"],
            }
        ],
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        response = await client.post(
            "/api/v1/oms/models/draft",
            json=command,
            headers={"Authorization": "Bearer config-token", "Origin": "https://school.example"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"version": 1, "status": "saved"}
        visible = await client.get(
            "/api/v1/oms/models/draft",
            headers={"Authorization": "Bearer config-token"},
        )
        assert visible.status_code == 200, visible.text
        assert visible.json() == {
            "version": 1,
            "status": "saved",
            "models": [
                {
                    "profile_id": "chat",
                    "model_id": "next",
                    "model": "next-model",
                    "provider": "openai",
                    "source": "oms_draft",
                    "managed": True,
                    "status": "not_active",
                }
            ],
        }
        assert "DT_TEST_MODEL" not in visible.text
        assert "base_url" not in visible.text
        stale = await client.post(
            "/api/v1/oms/models/draft",
            json=command,
            headers={"Authorization": "Bearer config-token", "Origin": "https://school.example"},
        )
        assert stale.status_code == 409
        literal = await client.post(
            "/api/v1/oms/models/draft",
            json={
                **command,
                "expected_version": 1,
                "models": [{**command["models"][0], "secret": "plaintext"}],
            },
            headers={"Authorization": "Bearer config-token", "Origin": "https://school.example"},
        )
        assert literal.status_code == 422
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        setting = await (
            await c.execute(
                "SELECT desired,active,status FROM oms.model_catalog_config WHERE id='global'",
            )
        ).fetchone()
        assert setting[0]["models"][0]["model"] == "next-model"
        assert setting[1] == {}
        assert setting[2] == "saved"
        audit = await (
            await c.execute(
                "SELECT action_key,safe_summary FROM management.audit_events "
                "WHERE application='oms' AND actor_subject='config-admin'"
            )
        ).fetchone()
        assert audit[0] == "ops.providers.manage"
        assert "DT_TEST_MODEL" not in json.dumps(audit[1])


async def test_oms_model_test_confirms_target_executors_without_activating(
    app, pg_dsn, monkeypatch
):
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            if token != "config-token":
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject="config-admin",
                client_id="eduplus-platform-admin",
                token_hash="digest",
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return token == "config-token" and subject == "config-admin"

    monkeypatch.setenv("DT_TEST_MODEL", "publish-secret")
    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    enterprise.oms_model_publish_executors = ("backend", "canary")
    seen: list[str] = []

    async def hook(executor, models):
        seen.append(executor)
        assert [model.model_id for model in models] == ["next"]

    enterprise.oms_model_confirmation_hook = hook
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        principal = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal, "https://issuer.example", "config-admin"),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_config_admin',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, uuid.uuid4()),
        )
    command = {
        "expected_version": 0,
        "reason": "测试执行者装载",
        "models": [
            {
                "profile_id": "chat",
                "model_id": "next",
                "model": "next-model",
                "provider": "openai",
                "base_url": "https://model.example/v1",
                "secret": "env:DT_TEST_MODEL",
                "allowed_roles": ["user"],
            }
        ],
    }
    headers = {"Authorization": "Bearer config-token", "Origin": "https://school.example"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        saved = await client.post("/api/v1/oms/models/draft", json=command, headers=headers)
        assert saved.status_code == 200, saved.text
        tested = await client.post(
            "/api/v1/oms/models/test",
            json={"expected_version": 1, "reason": "两实例测试"},
            headers=headers,
        )
        assert tested.status_code == 200, tested.text
        assert tested.json() == {
            "version": 2,
            "status": "tested",
            "confirmed_executors": ["backend", "canary"],
        }
        inventory = await client.get(
            "/api/v1/oms/models", headers={"Authorization": "Bearer config-token"}
        )
        assert inventory.status_code == 200
        assert inventory.json()["models"][0]["source"] == "deployment"
    assert seen == ["backend", "canary"]
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        row = await (
            await c.execute(
                "SELECT version,status,active FROM oms.model_catalog_config WHERE id='global'"
            )
        ).fetchone()
    assert row[0] == 2
    assert row[1] == "tested"
    assert row[2] == {}


async def test_oms_model_publish_confirms_backend_and_becomes_runtime_active(
    app, pg_dsn, monkeypatch
):
    """发布必须由 OMS 权限驱动，并让真实运行时读取 active 而非 draft。"""

    from deeptutor_enterprise.context import identity_context
    from deeptutor_enterprise.model_catalog import load_runtime_model_deployments
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            if token != "config-token":
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject="config-admin",
                client_id="eduplus-platform-admin",
                token_hash="digest",
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return token == "config-token" and subject == "config-admin"

    monkeypatch.setenv("DT_TEST_MODEL", "publish-secret")
    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        principal = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal, "https://issuer.example", "config-admin"),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_config_admin',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, uuid.uuid4()),
        )
    draft = {
        "expected_version": 0,
        "reason": "发布首个 Agent 模型",
        "models": [
            {
                "profile_id": "chat",
                "model_id": "published",
                "model": "published-model",
                "provider": "openai",
                "base_url": "https://model.example/v1",
                "secret": "env:DT_TEST_MODEL",
                "allowed_roles": ["user"],
            }
        ],
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        saved = await client.post(
            "/api/v1/oms/models/draft",
            json=draft,
            headers={"Authorization": "Bearer config-token", "Origin": "https://school.example"},
        )
        assert saved.status_code == 200, saved.text
        published = await client.post(
            "/api/v1/oms/models/publish",
            json={"expected_version": 1, "reason": "确认 backend 执行者已装载"},
            headers={"Authorization": "Bearer config-token", "Origin": "https://school.example"},
        )
        assert published.status_code == 200, published.text
        assert published.json() == {
            "version": 2,
            "active_version": 1,
            "status": "active",
            "confirmed_executors": ["backend"],
        }
        inventory = await client.get(
            "/api/v1/oms/models",
            headers={"Authorization": "Bearer config-token"},
        )
    assert inventory.status_code == 200, inventory.text
    assert inventory.json()["models"] == [
        {
            "profile_id": "chat",
            "model_id": "published",
            "model": "published-model",
            "provider": "openai",
            "source": "oms_active",
            "managed": True,
            "status": "active",
        }
    ]
    assert "publish-secret" not in inventory.text
    assert "DT_TEST_MODEL" not in inventory.text
    token = await enterprise.identity.login("admin", "long-password-1", client="oms-publish")
    identity = await enterprise.identity.authenticate(token)
    with identity_context(identity, token):
        store = enterprise.store_provider.get()
        models = await load_runtime_model_deployments(store, enterprise.deployment.models)
    assert [(model.profile_id, model.model_id, model.model) for model in models] == [
        ("chat", "published", "published-model")
    ]
    school_store = SimpleNamespace(
        db=enterprise.db,
        scope=type(store.scope)(str(uuid.uuid4()), "@school-agent-runtime"),
    )
    school_models = await load_runtime_model_deployments(school_store, enterprise.deployment.models)
    assert [(model.profile_id, model.model_id, model.model) for model in school_models] == [
        ("chat", "published", "published-model")
    ]


async def test_oms_model_publish_failure_keeps_active_and_rollback_discards_bad_draft(
    app, pg_dsn, monkeypatch
):
    """执行者确认失败时必须保留旧 active，并允许 OMS 显式丢弃坏草稿。"""

    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            if token != "config-token":
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject="config-admin",
                client_id="eduplus-platform-admin",
                token_hash="digest",
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return token == "config-token" and subject == "config-admin"

    monkeypatch.setenv("DT_GOOD_MODEL", "publish-secret")
    monkeypatch.delenv("DT_MISSING_MODEL", raising=False)
    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        principal = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal, "https://issuer.example", "config-admin"),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_config_admin',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, uuid.uuid4()),
        )

    def draft(version, *, model_id, model, secret):
        return {
            "expected_version": version,
            "reason": "模型切换",
            "models": [
                {
                    "profile_id": "chat",
                    "model_id": model_id,
                    "model": model,
                    "provider": "openai",
                    "base_url": "https://model.example/v1",
                    "secret": secret,
                    "allowed_roles": ["user"],
                }
            ],
        }

    headers = {"Authorization": "Bearer config-token", "Origin": "https://school.example"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        first = await client.post(
            "/api/v1/oms/models/draft",
            json=draft(0, model_id="stable", model="stable-model", secret="env:DT_GOOD_MODEL"),
            headers=headers,
        )
        assert first.status_code == 200, first.text
        published = await client.post(
            "/api/v1/oms/models/publish",
            json={"expected_version": 1, "reason": "首版确认"},
            headers=headers,
        )
        assert published.status_code == 200, published.text
        bad = await client.post(
            "/api/v1/oms/models/draft",
            json=draft(2, model_id="bad", model="bad-model", secret="env:DT_MISSING_MODEL"),
            headers=headers,
        )
        assert bad.status_code == 200, bad.text
        failed = await client.post(
            "/api/v1/oms/models/publish",
            json={"expected_version": 3, "reason": "确认缺失 Secret 的执行者失败"},
            headers=headers,
        )
        assert failed.status_code == 503, failed.text
        inventory = await client.get(
            "/api/v1/oms/models", headers={"Authorization": "Bearer config-token"}
        )
        assert inventory.status_code == 200, inventory.text
        assert inventory.json()["models"][0]["model_id"] == "stable"
        assert "DT_MISSING_MODEL" not in inventory.text
        rollback = await client.post(
            "/api/v1/oms/models/rollback",
            json={"expected_version": 4, "reason": "丢弃缺失 Secret 的草稿"},
            headers=headers,
        )
        assert rollback.status_code == 200, rollback.text
        assert rollback.json() == {"version": 5, "active_version": 1, "status": "active"}
        draft_view = await client.get(
            "/api/v1/oms/models/draft", headers={"Authorization": "Bearer config-token"}
        )
        assert draft_view.status_code == 200, draft_view.text
        assert draft_view.json()["models"][0]["model_id"] == "stable"

    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        row = await (
            await c.execute(
                "SELECT version,active_version,status,desired,active "
                "FROM oms.model_catalog_config WHERE id='global'"
            )
        ).fetchone()
    assert row[0] == 5
    assert row[1] == 1
    assert row[2] == "active"
    assert row[3]["models"][0]["model_id"] == "stable"
    assert row[4]["models"][0]["model_id"] == "stable"


async def test_oms_provider_settings_are_versioned_redacted_confirmed_and_permissioned(
    app, pg_dsn, monkeypatch
):
    """全服务设置只能由 OMS 配置权限维护，发布前逐执行者确认且不泄露 Secret。"""

    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            if token not in {"config-token", "audit-token"}:
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject="config-admin" if token == "config-token" else "config-auditor",
                client_id="eduplus-platform-admin",
                token_hash="digest",
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return (
                token == "config-token"
                and subject == "config-admin"
                or token == "audit-token"
                and subject == "config-auditor"
            )

    monkeypatch.setenv("DT_PROVIDER_API_KEY", "provider-secret")
    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    enterprise.oms_provider_settings_publish_executors = ("backend", "canary")
    seen: list[str] = []

    async def hook(executor, settings):
        seen.append(executor)
        assert sorted(settings) == ["connections", "models", "search"]

    enterprise.oms_provider_settings_confirmation_hook = hook
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        admin = uuid.uuid4()
        auditor = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES"
            "(%s,'oms',%s,%s,'active'),(%s,'oms',%s,%s,'active')",
            (
                admin,
                "https://issuer.example",
                "config-admin",
                auditor,
                "https://issuer.example",
                "config-auditor",
            ),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_config_admin',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval'),"
            "(%s,'oms',%s,'platform_security_admin',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (
                uuid.uuid4(),
                admin,
                uuid.uuid4(),
                uuid.uuid4(),
                auditor,
                uuid.uuid4(),
            ),
        )
    headers = {"Authorization": "Bearer config-token", "Origin": "https://school.example"}
    settings = {
        "connections": {
            "openai-main": {
                "provider": "openai",
                "base_url": "https://model.example/v1",
                "api_key": "env:DT_PROVIDER_API_KEY",
            }
        },
        "models": [{"profile_id": "chat", "model": "first-agent-model"}],
        "search": {"provider": "serpapi", "api_key": "env:DT_PROVIDER_API_KEY"},
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        dry_run = await client.post(
            "/api/v1/oms/provider-settings/dry-run",
            json={
                "source_kind": "local-json",
                "settings": {
                    **settings,
                    "legacy_personal": {"api_key": "literal-secret"},
                },
            },
            headers={"Authorization": "Bearer config-token", "Origin": "https://school.example"},
        )
        assert dry_run.status_code == 200, dry_run.text
        assert dry_run.json()["recognized_sections"] == ["connections", "models", "search"]
        assert dry_run.json()["unsupported_sections"] == ["legacy_personal"]
        assert "literal-secret" not in dry_run.text
        assert "env:DT_PROVIDER_API_KEY" not in dry_run.text

        visible_empty = await client.get(
            "/api/v1/oms/provider-settings",
            headers={"Authorization": "Bearer config-token"},
        )
        assert visible_empty.status_code == 200, visible_empty.text
        assert visible_empty.json()["version"] == 0

        literal_secret = await client.post(
            "/api/v1/oms/provider-settings/draft",
            json={
                "expected_version": 0,
                "reason": "拒绝明文",
                "settings": {
                    "connections": {
                        "bad": {"provider": "openai", "base_url": "https://model.example/v1", "api_key": "plain"}
                    }
                },
            },
            headers=headers,
        )
        assert literal_secret.status_code == 422

        forbidden = await client.post(
            "/api/v1/oms/provider-settings/draft",
            json={"expected_version": 0, "reason": "审计员无写权限", "settings": settings},
            headers={"Authorization": "Bearer audit-token", "Origin": "https://school.example"},
        )
        assert forbidden.status_code == 403

        saved = await client.post(
            "/api/v1/oms/provider-settings/draft",
            json={"expected_version": 0, "reason": "准备首个 Agent 服务设置", "settings": settings},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json() == {"version": 1, "status": "saved"}
        stale = await client.post(
            "/api/v1/oms/provider-settings/draft",
            json={"expected_version": 0, "reason": "旧版本", "settings": settings},
            headers=headers,
        )
        assert stale.status_code == 409
        tested = await client.post(
            "/api/v1/oms/provider-settings/test",
            json={"expected_version": 1, "reason": "确认双执行者"},
            headers=headers,
        )
        assert tested.status_code == 200, tested.text
        assert tested.json() == {
            "version": 2,
            "status": "tested",
            "confirmed_executors": ["backend", "canary"],
        }
        published = await client.post(
            "/api/v1/oms/provider-settings/publish",
            json={"expected_version": 2, "reason": "发布首个 Agent 服务设置"},
            headers=headers,
        )
        assert published.status_code == 200, published.text
        assert published.json() == {
            "version": 3,
            "status": "active",
            "confirmed_executors": ["backend", "canary"],
            "active_version": 2,
        }
        visible = await client.get(
            "/api/v1/oms/provider-settings",
            headers={"Authorization": "Bearer config-token"},
        )
        assert visible.status_code == 200, visible.text
        payload = visible.json()
        assert payload["version"] == 3
        assert payload["active_version"] == 2
        assert payload["status"] == "active"
        assert payload["settings"]["connections"]["openai-main"]["api_key"] == "<redacted>"
        assert payload["active"]["search"]["api_key"] == "<redacted>"
        assert "DT_PROVIDER_API_KEY" not in visible.text
        assert "provider-secret" not in visible.text
        assert "model.example" in visible.text

        bad_settings = {
            **settings,
            "connections": {
                "openai-main": {
                    "provider": "openai",
                    "base_url": "https://model.example/v1",
                    "api_key": "env:DT_MISSING_PROVIDER_API_KEY",
                }
            },
        }
        bad_draft = await client.post(
            "/api/v1/oms/provider-settings/draft",
            json={
                "expected_version": 3,
                "reason": "保存缺失 Secret 的草稿",
                "settings": bad_settings,
            },
            headers=headers,
        )
        assert bad_draft.status_code == 200, bad_draft.text
        failed_publish = await client.post(
            "/api/v1/oms/provider-settings/publish",
            json={"expected_version": 4, "reason": "执行者应拒绝缺失 Secret"},
            headers=headers,
        )
        assert failed_publish.status_code == 503, failed_publish.text
        after_failed = await client.get(
            "/api/v1/oms/provider-settings",
            headers={"Authorization": "Bearer config-token"},
        )
        assert after_failed.status_code == 200, after_failed.text
        assert after_failed.json()["version"] == 5
        assert after_failed.json()["status"] == "failed"
        assert after_failed.json()["active"]["search"]["api_key"] == "<redacted>"
        assert "DT_MISSING_PROVIDER_API_KEY" not in after_failed.text
        rollback = await client.post(
            "/api/v1/oms/provider-settings/rollback",
            json={"expected_version": 5, "reason": "丢弃缺失 Secret 的草稿"},
            headers=headers,
        )
        assert rollback.status_code == 200, rollback.text
        assert rollback.json() == {"version": 6, "active_version": 2, "status": "active"}

    assert seen == ["backend", "canary", "backend", "canary"]
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        setting = await (
            await c.execute(
                "SELECT version,active_version,status,desired,active "
                "FROM oms.provider_setting_configs WHERE config_key='global'",
            )
        ).fetchone()
        audit = await (
            await c.execute(
                "SELECT action_key,target_kind,safe_summary FROM management.audit_events "
                "WHERE application='oms' AND actor_subject='config-admin' "
                "AND target_kind='provider_settings' ORDER BY created_at DESC LIMIT 1"
            )
        ).fetchone()
    assert setting[0] == 6
    assert setting[1] == 2
    assert setting[2] == "active"
    assert setting[3]["search"]["api_key"] == "env:DT_PROVIDER_API_KEY"
    assert setting[4]["connections"]["openai-main"]["api_key"] == "env:DT_PROVIDER_API_KEY"
    assert audit[0] == "ops.providers.manage"
    assert audit[1] == "provider_settings"
    assert "DT_PROVIDER_API_KEY" not in json.dumps(audit[2])


async def test_oms_school_scoped_operator_cannot_read_platform_provider_settings(
    app, pg_dsn
):
    """只有 school 范围的 OMS grant 不能冒充 platform grant 读取全局 Provider。"""

    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            if token != "school-operator-token":
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject="school-operator",
                client_id="eduplus-platform-admin",
                token_hash="digest",
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return token == "school-operator-token" and subject == "school-operator"

    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        school_id = uuid.uuid4()
        principal_id = uuid.uuid4()
        await c.execute(
            "INSERT INTO enterprise.tenants"
            "(id,external_eligibility,local_enabled,provisioning_status,"
            "recovery_state,auth_epoch,bootstrap_completed) "
            "VALUES(%s,'allowed',true,'ready','normal','epoch',true)",
            (school_id,),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,73003,'verified',now(),'synthetic','synthetic://school-scope')",
            (school_id,),
        )
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal_id, "https://issuer.example", "school-operator"),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
            "school_binding_version,valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_operator',1,'school',%s,1,"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), principal_id, school_id, uuid.uuid4()),
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        provider_settings = await client.get(
            "/api/v1/oms/provider-settings",
            headers={"Authorization": "Bearer school-operator-token"},
        )
        provider_draft = await client.post(
            "/api/v1/oms/provider-settings/draft",
            json={
                "expected_version": 0,
                "reason": "school grant cannot manage platform",
                "settings": {},
            },
            headers={
                "Authorization": "Bearer school-operator-token",
                "Origin": "https://school.example",
            },
        )

    assert provider_settings.status_code == 403, provider_settings.text
    assert provider_settings.json() == {"detail": "Permission denied"}
    assert provider_draft.status_code == 403, provider_draft.text
    assert provider_draft.json() == {"detail": "Permission denied"}


async def test_oms_school_entitlement_and_quota_commands_are_authorized_and_audited(app, pg_dsn):
    """OMS 学校额度写入必须经本产品 school-scope 授权并落到真实总账。"""

    from datetime import datetime, timedelta, timezone

    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            if token != "operator-token":
                raise PermissionError("invalid")
            now = int(time.time())
            return PlatformIdentity(
                issuer="https://issuer.example",
                subject="school-operator",
                client_id="eduplus-platform-admin",
                token_hash="digest",
                issued_at=now,
                expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return token == "operator-token" and subject == "school-operator"

    enterprise = app.state.enterprise
    school_id = enterprise.deployment.tenant_id
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    now = datetime.now(timezone.utc)
    grant_id = uuid.uuid4()
    expired_grant_id = uuid.uuid4()
    lot_id = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET bootstrap_completed=true,local_enabled=true,"
            "provisioning_status='ready',external_eligibility='allowed',"
            "recovery_state='normal' WHERE id=%s",
            (school_id,),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,10001,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school_id,),
        )
        await c.execute(
            "INSERT INTO oms.service_definitions(service_id,unit_code,resource_category,enabled) "
            "VALUES('search','request','tool_integration',true)"
        )
        await c.execute(
            "INSERT INTO oms.supply_lots"
            "(id,service_id,provider_id,provider_account_id,pool_id,unit_code,"
            "evidence_ref,hard_ceiling,starts_at,expires_at,supply_basis,verified_at,created_by) "
            "VALUES(%s,'search','provider-a','account-a','pool-a','request',"
            "'purchase://synthetic',100,now()-interval '1 hour',now()+interval '7 days',"
            "'native_units',now(),'supply-admin')",
            (lot_id,),
        )
        principal = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal, "https://issuer.example", "school-operator"),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
            "school_binding_version,valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_operator',1,'school',%s,1,"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, school_id, uuid.uuid4()),
        )

    headers = {"Authorization": "Bearer operator-token", "Origin": "https://school.example"}
    starts_at = (now - timedelta(minutes=1)).isoformat()
    expires_at = (now + timedelta(days=2)).isoformat()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        entitlement = await client.post(
            f"/api/v1/oms/schools/{school_id}/entitlements/search",
            json={
                "status": "active",
                "starts_at": starts_at,
                "expires_at": expires_at,
                "expected_version": 0,
                "idempotency_key": "entitlement-1",
                "reason": "开通搜索服务",
            },
            headers=headers,
        )
        assert entitlement.status_code == 200, entitlement.text
        assert entitlement.json() == {"service_id": "search", "status": "active", "version": 1}
        stale_entitlement = await client.post(
            f"/api/v1/oms/schools/{school_id}/entitlements/search",
            json={
                "status": "active",
                "starts_at": starts_at,
                "expires_at": expires_at,
                "expected_version": 0,
                "idempotency_key": "entitlement-stale",
                "reason": "旧版本重放",
            },
            headers=headers,
        )
        assert stale_entitlement.status_code == 409
        grant = await client.post(
            f"/api/v1/oms/schools/{school_id}/quota-grants",
            json={
                "grant_id": str(grant_id),
                "service_id": "search",
                "unit_code": "request",
                "acquisition_method": "gift",
                "quantity": "30",
                "starts_at": starts_at,
                "expires_at": expires_at,
                "provider_id": "provider-a",
                "provider_account_id": "account-a",
                "pool_id": "pool-a",
                "source_ref": "campaign://synthetic-secret",
                "expected_entitlement_version": 1,
                "idempotency_key": "grant-1",
                "reason": "赠送首批额度",
            },
            headers=headers,
        )
        assert grant.status_code == 200, grant.text
        assert grant.json()["grant_id"] == str(grant_id)
        assert grant.json()["allocations"] == [{"lot_id": str(lot_id), "quantity": "30"}]
        assert "synthetic-secret" not in grant.text
        adjusted = await client.patch(
            f"/api/v1/oms/schools/{school_id}/quota-grants/{grant_id}",
            json={
                "expected_version": 1,
                "new_quantity": "20",
                "idempotency_key": "adjust-1",
                "reason": "减少未使用额度",
            },
            headers=headers,
        )
        assert adjusted.status_code == 200, adjusted.text
        assert adjusted.json() == {
            "grant_id": str(grant_id),
            "version": 2,
            "previous_quantity": "30",
            "quantity": "20",
        }
        revoked = await client.post(
            f"/api/v1/oms/schools/{school_id}/quota-grants/{grant_id}/revoke",
            json={
                "expected_version": 2,
                "idempotency_key": "revoke-1",
                "reason": "撤销未使用额度",
            },
            headers=headers,
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json() == {
            "grant_id": str(grant_id),
            "version": 3,
            "released_units": "20",
        }
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_id),))
            await c.execute(
                "INSERT INTO oms.quota_grants"
                "(id,tenant_id,service_id,unit_code,acquisition_method,quantity,"
                "starts_at,expires_at,created_by,source_ref) "
                "VALUES(%s,%s,'search','request','recharge',5,"
                "now()-interval '2 days',now()-interval '1 day','school-operator',"
                "'purchase://expired')",
                (expired_grant_id, school_id),
            )
            await c.execute(
                "INSERT INTO oms.grant_commitments"
                "(tenant_id,grant_id,lot_id,committed_total,unspent) "
                "VALUES(%s,%s,%s,5,5)",
                (school_id, expired_grant_id, lot_id),
            )
            await c.execute(
                "UPDATE oms.supply_lots SET committed_unspent=committed_unspent+5 WHERE id=%s",
                (lot_id,),
            )
        expired = await client.post(
            f"/api/v1/oms/schools/{school_id}/quota-grants/{expired_grant_id}/expire",
            json={
                "expected_version": 1,
                "idempotency_key": "expire-1",
                "reason": "到期释放未用额度",
            },
            headers=headers,
        )
        assert expired.status_code == 200, expired.text
        assert expired.json() == {
            "grant_id": str(expired_grant_id),
            "version": 2,
            "released_units": "5",
        }
        summary = await client.get(
            f"/api/v1/oms/schools/{school_id}/quota",
            headers={"Authorization": "Bearer operator-token"},
        )
        assert summary.status_code == 200, summary.text
        assert {row["status"] for row in summary.json()["grants"]} == {"revoked", "expired"}
        assert "synthetic-secret" not in summary.text

    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_id),))
        grant_row = await (
            await c.execute(
                "SELECT status,version,quantity,adjustment_released "
                "FROM oms.quota_grants WHERE tenant_id=%s AND id=%s",
                (school_id, grant_id),
            )
        ).fetchone()
        commitment = await (
            await c.execute(
                "SELECT unspent,released FROM oms.grant_commitments "
                "WHERE tenant_id=%s AND grant_id=%s AND lot_id=%s",
                (school_id, grant_id, lot_id),
            )
        ).fetchone()
        supply = await (
            await c.execute("SELECT committed_unspent FROM oms.supply_lots WHERE id=%s", (lot_id,))
        ).fetchone()
        audit_actions = await (
            await c.execute(
                "SELECT action,result FROM oms.audit_events "
                "WHERE actor_subject='school-operator' ORDER BY created_at,action"
            )
        ).fetchall()
    assert tuple(grant_row) == ("revoked", 3, 30, 10)
    assert tuple(commitment) == (0, 30)
    assert supply[0] == 0
    assert ("service_entitlement.set", "success") in [tuple(row) for row in audit_actions]
    assert ("quota.grant", "success") in [tuple(row) for row in audit_actions]
    assert ("quota.adjust", "success") in [tuple(row) for row in audit_actions]
    assert ("quota.revoke", "success") in [tuple(row) for row in audit_actions]
    assert ("quota.expire", "success") in [tuple(row) for row in audit_actions]


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


async def test_eduplus2_real_webhook_persists_safe_school_projection_before_ack(app, caplog):
    """真实事件 2xx 包含安全学校投影，但不代表资源或管理员已开通。"""

    from deeptutor_enterprise.scope import TenantScope

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    ts = str(int(time.time()))
    event_id = str(uuid.uuid4())
    body = json.dumps(
        {
            "event": "subscription.created",
            "event_id": event_id,
            "timestamp": int(ts),
            "tenant": {"id": 10001, "code": "synthetic-school"},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
            "oauth_client": {
                "client_id": "synthetic-school-client",
                "client_secret": "must-not-persist-this-secret",
            },
            "actor": {"type": "user", "user_id": "synthetic-keycloak-sub"},
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        b"synthetic-webhook-secret",
        ts.encode() + b".subscription.created." + body,
        hashlib.sha256,
    ).hexdigest()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        response = await client.post(
            "/api/v1/eduplus2/webhooks",
            content=body,
            headers={
                "X-EduPlus-Signature": "sha256=" + signature,
                "X-EduPlus-Timestamp": ts,
                "X-EduPlus-Event": "subscription.created",
            },
        )
    assert response.status_code == 204, response.text
    retry_ts = str(int(ts) + 1)
    retry_signature = hmac.new(
        b"synthetic-webhook-secret",
        retry_ts.encode() + b".subscription.created." + body,
        hashlib.sha256,
    ).hexdigest()
    changed = body.replace(b'"status":"active"', b'"status":"suspended"')
    changed_signature = hmac.new(
        b"synthetic-webhook-secret",
        ts.encode() + b".subscription.created." + changed,
        hashlib.sha256,
    ).hexdigest()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        duplicate = await client.post(
            "/api/v1/eduplus2/webhooks",
            content=body,
            headers={
                "X-EduPlus-Signature": "sha256=" + retry_signature,
                "X-EduPlus-Timestamp": retry_ts,
                "X-EduPlus-Event": "subscription.created",
            },
        )
        conflict = await client.post(
            "/api/v1/eduplus2/webhooks",
            content=changed,
            headers={
                "X-EduPlus-Signature": "sha256=" + changed_signature,
                "X-EduPlus-Timestamp": ts,
                "X-EduPlus-Event": "subscription.created",
            },
        )
    assert duplicate.status_code == 204
    assert conflict.status_code == 409
    assert any("lifecycle webhook conflict" in record.message for record in caplog.records)
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-audit")
    async with enterprise.db.transaction(scope) as c:
        event = await (
            await c.execute(
                "SELECT event_type,external_tenant_id,external_app_id,external_subscription_id,"
                "actor_subject,processing_status FROM eduplus2.lifecycle_inbox "
                "WHERE tenant_id=%s AND event_id=%s",
                (enterprise.deployment.tenant_id, event_id),
            )
        ).fetchone()
        tenant = await (
            await c.execute(
                "SELECT external_eligibility FROM enterprise.tenants WHERE id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
        count = await (
            await c.execute(
                "SELECT count(*) AS n FROM eduplus2.lifecycle_inbox "
                "WHERE tenant_id=%s AND event_id=%s",
                (enterprise.deployment.tenant_id, event_id),
            )
        ).fetchone()
        target = await (
            await c.execute(
                "SELECT generation,eligibility,school_id FROM eduplus2.webhook_school_state "
                "WHERE tenant_id=%s "
                "AND external_tenant_id=%s AND external_app_id=%s",
                (enterprise.deployment.tenant_id, 10001, 51),
            )
        ).fetchone()
        school = await (
            await c.execute(
                "SELECT t.external_eligibility,t.provisioning_status,t.local_enabled "
                "FROM enterprise.tenants t JOIN oms.school_bindings b ON b.tenant_id=t.id "
                "WHERE b.eduplus_tenant_id=10001"
            )
        ).fetchone()
    assert event == {
        "event_type": "subscription.created",
        "external_tenant_id": 10001,
        "external_app_id": 51,
        "external_subscription_id": 20001,
        "actor_subject": "synthetic-keycloak-sub",
        "processing_status": "verified",
    }
    assert tenant["external_eligibility"] == "not_required"
    assert count["n"] == 1
    assert target["generation"] == 1
    assert target["eligibility"] == "allowed"
    assert school == {
        "external_eligibility": "allowed",
        "provisioning_status": "pending",
        "local_enabled": False,
    }
    assert "must-not-persist-this-secret" not in json.dumps(event)


async def test_eduplus2_real_webhook_stays_closed_without_receiver_rollout_gate(app):
    """仅配齐签名/应用密钥不能绕过正式接收器发布门禁。"""

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    ts = str(int(time.time()))
    body = json.dumps(
        {
            "event": "subscription.created",
            "event_id": str(uuid.uuid4()),
            "tenant": {"id": 10001},
            "app": {"id": 51},
            "subscription": {"id": 20001, "status": "active"},
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        b"synthetic-webhook-secret",
        ts.encode() + b".subscription.created." + body,
        hashlib.sha256,
    ).hexdigest()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        response = await client.post(
            "/api/v1/eduplus2/webhooks",
            content=body,
            headers={
                "X-EduPlus-Signature": "sha256=" + signature,
                "X-EduPlus-Timestamp": ts,
                "X-EduPlus-Event": "subscription.created",
            },
        )
    assert response.status_code == 503


async def test_eduplus2_real_webhook_does_not_ack_failed_inbox_transaction(app, monkeypatch):
    from deeptutor_enterprise.eduplus2 import webhook_authority

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True

    async def failed_ingest(*args, **kwargs):
        raise RuntimeError("synthetic storage unavailable")

    monkeypatch.setattr(webhook_authority, "ingest_authoritative_webhook", failed_ingest)
    ts = str(int(time.time()))
    body = json.dumps(
        {
            "event": "subscription.created",
            "event_id": "synthetic-failed-inbox-event",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        b"synthetic-webhook-secret",
        ts.encode() + b".subscription.created." + body,
        hashlib.sha256,
    ).hexdigest()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        response = await client.post(
            "/api/v1/eduplus2/webhooks",
            content=body,
            headers={
                "X-EduPlus-Signature": "sha256=" + signature,
                "X-EduPlus-Timestamp": ts,
                "X-EduPlus-Event": "subscription.created",
            },
        )
    assert response.status_code == 503


async def test_eduplus2_webhook_previous_secret_has_bounded_overlap(app):
    """轮换期允许旧密钥验签，到期后立即拒绝。"""

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "new-synthetic-webhook-secret"
    enterprise.eduplus2_webhook_previous_secret = "old-synthetic-webhook-secret"
    enterprise.eduplus2_webhook_previous_until = int(time.time()) + 60
    ts = str(int(time.time()))
    body = json.dumps(
        {"event": "subscription.created", "event_id": "mock_" + str(uuid.uuid4())},
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        b"old-synthetic-webhook-secret",
        ts.encode() + b".subscription.created." + body,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "X-EduPlus-Signature": "sha256=" + signature,
        "X-EduPlus-Timestamp": ts,
        "X-EduPlus-Event": "subscription.created",
        "X-EduPlus-Mock": "true",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        accepted = await client.post("/api/v1/eduplus2/webhooks", content=body, headers=headers)
        enterprise.eduplus2_webhook_previous_until = int(time.time()) - 1
        expired = await client.post("/api/v1/eduplus2/webhooks", content=body, headers=headers)
    assert accepted.status_code == 204
    assert expired.status_code == 401


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
    assert {path for path in paths if path.startswith("/api/settings")} == {"/api/settings/ui"}
    assert {path for path in paths if path.startswith("/api/v1/tms/")} == {
        "/api/v1/tms/approvals",
        "/api/v1/tms/approvals/{approval_id}/apply",
        "/api/v1/tms/approvals/{approval_id}/review",
        "/api/v1/tms/approvals/{approval_id}/withdraw",
        "/api/v1/tms/assignments/{assignment_id}/revoke",
        "/api/v1/tms/authz-audit",
        "/api/v1/tms/directory/users",
        "/api/v1/tms/me/permissions",
        "/api/v1/tms/me/register",
        "/api/v1/tms/members",
        "/api/v1/tms/members/{principal_id}/roles",
        "/api/v1/tms/permissions",
        "/api/v1/tms/quotas",
        "/api/v1/tms/roles/custom",
        "/api/v1/tms/school-bootstrap/activate",
        "/api/v1/tms/school-bootstrap/status",
        "/api/v1/tms/service-access",
        "/api/v1/tms/service-access",
        "/api/v1/tms/service-access/{grant_id}/revoke",
        "/api/v1/tms/skills",
    }
    assert {path for path in paths if path.startswith("/api/v1/oms/")} == {
        "/api/v1/oms/audit",
        "/api/v1/oms/approvals",
        "/api/v1/oms/approvals/{approval_id}/apply",
        "/api/v1/oms/approvals/{approval_id}/review",
        "/api/v1/oms/approvals/{approval_id}/withdraw",
        "/api/v1/oms/assignments/{assignment_id}/revoke",
        "/api/v1/oms/auth/callback",
        "/api/v1/oms/auth/logout",
        "/api/v1/oms/auth/refresh",
        "/api/v1/oms/auth/start",
        "/api/v1/oms/auth/status",
        "/api/v1/oms/bootstrap/first-admin",
        "/api/v1/oms/cost",
        "/api/v1/oms/me",
        "/api/v1/oms/me/permissions",
        "/api/v1/oms/models",
        "/api/v1/oms/models/draft",
        "/api/v1/oms/models/publish",
        "/api/v1/oms/models/rollback",
        "/api/v1/oms/models/test",
        "/api/v1/oms/permissions",
        "/api/v1/oms/principals/{principal_id}/disable",
        "/api/v1/oms/principals/{principal_id}/roles",
        "/api/v1/oms/provider-settings",
        "/api/v1/oms/provider-settings/draft",
        "/api/v1/oms/provider-settings/dry-run",
        "/api/v1/oms/provider-settings/publish",
        "/api/v1/oms/provider-settings/rollback",
        "/api/v1/oms/provider-settings/test",
        "/api/v1/oms/resources/status",
        "/api/v1/oms/schools/{school_id}/entitlements/{service_id}",
        "/api/v1/oms/schools/{school_id}/jobs",
        "/api/v1/oms/schools/{school_id}/quota",
        "/api/v1/oms/schools/{school_id}/quota-grants",
        "/api/v1/oms/schools/{school_id}/quota-grants/{grant_id}",
        "/api/v1/oms/schools/{school_id}/quota-grants/{grant_id}/expire",
        "/api/v1/oms/schools/{school_id}/quota-grants/{grant_id}/revoke",
        "/api/v1/oms/schools/{school_id}/usage",
        "/api/v1/oms/skills",
        "/api/v1/oms/skills/draft",
        "/api/v1/oms/skills/{name}/schools/{school_id}/grant",
        "/api/v1/oms/skills/revisions/{revision_id}/review",
        "/api/v1/oms/skills/revisions/{revision_id}/publish",
        "/api/v1/oms/status/catalog",
        "/api/v1/oms/summary",
        "/api/v1/oms/supply",
        "/api/v1/oms/tenants",
        "/api/v1/oms/tenants/{school_id}",
    }
    for prefix in (
        "/api/skills",
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
    async with enterprise.db.transaction(TenantScope(foreign_tenant, admin_identity.user_id)) as c:
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
    token = await enterprise.identity.login(
        "admin", "long-password-1", client="resource-incomplete"
    )
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
    assert callable(enterprise.providers.skill_service_factory)
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


@pytest.mark.asyncio
async def test_externalized_kb_listing_rejects_unknown_resource_state(app):
    from deeptutor_enterprise.context import identity_context
    from deeptutor_enterprise.knowledge_bases import list_externalized_knowledge_bases
    from deeptutor_enterprise.scope import TenantScope

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="kb-state")
    identity = await enterprise.identity.authenticate(token)
    await seed_externalized_kb(app, owner_id=identity.user_id, kb_id="unknown-state-kb")
    async with enterprise.db.transaction(
        TenantScope(str(enterprise.deployment.tenant_id), identity.user_id)
    ) as connection:
        await connection.execute(
            "ALTER TABLE enterprise.resource_objects DROP CONSTRAINT IF EXISTS resource_objects_state_check"
        )
        await connection.execute(
            "UPDATE enterprise.resource_objects SET state='future-state' "
            "WHERE tenant_id=%s AND owner_id=%s AND resource_id='unknown-state-kb'",
            (enterprise.deployment.tenant_id, identity.user_id),
        )

    with identity_context(identity, token):
        with pytest.raises(ValueError, match="resource state is unknown"):
            await list_externalized_knowledge_bases(enterprise.store_provider.get())


async def test_conversation_test_options_hide_unauthorized_builtin_skills(app):
    """企业学校运行时未获 OMS 授权的 builtin Skill 不得出现在测试页清单。"""

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
    skill_ids = {item["id"] for item in response.json()["skills"]}
    assert "skill-creator" not in skill_ids


async def test_enterprise_voice_stt_is_available_to_authenticated_test_page(app, monkeypatch):
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


async def test_enterprise_turn_environment_loads_multi_model_catalog_from_pg(app, monkeypatch):
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


async def test_model_draft_never_becomes_runtime_active_before_confirmation(app):
    from deeptutor_enterprise.context import identity_context
    from deeptutor_enterprise.model_catalog import load_runtime_model_deployments

    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="draft-gate")
    identity = await enterprise.identity.authenticate(token)
    draft = {
        "models": [
            {
                "profile_id": "chat",
                "model_id": "draft",
                "model": "unconfirmed-model",
                "base_url": "https://model.example/v1",
                "secret": "env:DT_TEST_MODEL",
                "provider": "openai",
                "allowed_roles": ["user"],
            }
        ]
    }
    active = {
        "models": [
            {
                "profile_id": "chat",
                "model_id": "confirmed",
                "model": "confirmed-model",
                "base_url": "https://model.example/v1",
                "secret": "env:DT_TEST_MODEL",
                "provider": "openai",
                "allowed_roles": ["user"],
            }
        ]
    }
    with identity_context(identity, token):
        store = enterprise.store_provider.get()
        async with store.db.transaction(store.scope) as c:
            await c.execute(
                "INSERT INTO enterprise.runtime_settings"
                "(tenant_id,scope_kind,scope_id,key,version,desired,active,status,updated_by)"
                " VALUES(%s,'tenant','','model_catalog',1,%s,'{}'::jsonb,'saved',%s)",
                (store.scope.tenant_id, psycopg.types.json.Jsonb(draft), identity.user_id),
            )
        before = await load_runtime_model_deployments(store, enterprise.deployment.models)
        assert before == enterprise.deployment.models
        async with store.db.transaction(store.scope) as c:
            await c.execute(
                "UPDATE enterprise.runtime_settings SET active=%s,status='saved',version=2 "
                "WHERE tenant_id=%s AND scope_kind='tenant' AND key='model_catalog'",
                (psycopg.types.json.Jsonb(active), store.scope.tenant_id),
            )
        after = await load_runtime_model_deployments(store, enterprise.deployment.models)
    assert [(model.model_id, model.model) for model in after] == [("confirmed", "confirmed-model")]


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
    token = await enterprise.identity.login("admin", "long-password-1", client="resource-policy")
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
    admin_token = await enterprise.identity.login(
        "admin", "long-password-1", client="resource-owner"
    )
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
