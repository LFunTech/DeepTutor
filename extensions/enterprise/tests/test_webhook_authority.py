"""Webhook-only 学校接入：仅使用隔离合成事件。"""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import time
import uuid

from deeptutor_enterprise.management.actor_activation import activate_first_school_administrator
from deeptutor_enterprise.management.actor_handoff import find_pending_actor_candidates
from deeptutor_enterprise.management.authorization import (
    ManagementIdentity,
    require_management_permission,
)
from deeptutor_enterprise.management.lifecycle_controls import (
    SchoolFreezeConflict,
    inspect_school_lifecycle,
    set_school_lifecycle_freeze,
)
from deeptutor_enterprise.scope import TenantScope
import httpx
from jose import jwt
import psycopg
import pytest
from test_application import app as app

pytestmark = pytest.mark.asyncio


async def _deliver(
    app,
    *,
    event_id,
    event_type,
    status,
    actor=None,
    school_id=10001,
    client_id="synthetic-school-client",
    signing_secret="synthetic-webhook-secret",
    school_code="synthetic-school",
    tenant_type="school",
    app_id=51,
    subscription_id=20001,
):
    body = json.dumps(
        {
            "event": event_type,
            "event_id": event_id,
            "tenant": {"id": school_id, "code": school_code, "tenant_type": tenant_type},
            "app": {"id": app_id, "client_id": client_id},
            "subscription": {"id": subscription_id, "status": status},
            "actor": actor,
        },
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        signing_secret.encode(),
        timestamp.encode() + b"." + event_type.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        return await client.post(
            "/api/v1/eduplus2/webhooks",
            content=body,
            headers={
                "X-EduPlus-Signature": "sha256=" + signature,
                "X-EduPlus-Timestamp": timestamp,
                "X-EduPlus-Event": event_type,
            },
        )


async def test_signed_created_directly_creates_school_without_online_resolve(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_resolver = None
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    event_id = "synthetic-created-" + uuid.uuid4().hex

    response = await _deliver(
        app,
        event_id=event_id,
        event_type="subscription.created",
        status="active",
        actor={"type": "user", "user_id": "synthetic-sub"},
    )
    assert response.status_code == 204, response.text
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-authority-test")
    async with enterprise.db.transaction(scope) as c:
        binding = await (
            await c.execute(
                "SELECT b.tenant_id,b.status,t.external_tid,t.external_eligibility,"
                "t.provisioning_status,t.bootstrap_completed "
                "FROM oms.school_bindings b JOIN enterprise.tenants t ON t.id=b.tenant_id "
                "WHERE b.eduplus_tenant_id=10001"
            )
        ).fetchone()
        candidate = await (
            await c.execute(
                "SELECT school_id,actor_subject FROM eduplus2.lifecycle_actor_candidates "
                "WHERE tenant_id=%s AND event_id=%s",
                (enterprise.deployment.tenant_id, event_id),
            )
        ).fetchone()
        registration = await (
            await c.execute(
                "SELECT tenant_id,client_id,external_tenant_id,external_app_id,"
                "registered_by_surface,status "
                "FROM eduplus2.external_client_registrations "
                "WHERE external_tenant_id='10001' AND external_app_id='51'"
            )
        ).fetchone()
    assert binding is not None
    assert binding["status"] == "verified"
    assert binding["external_tid"] == "10001"
    assert binding["external_eligibility"] == "allowed"
    assert binding["provisioning_status"] == "pending"
    assert binding["bootstrap_completed"] is False
    assert candidate == {"school_id": binding["tenant_id"], "actor_subject": "synthetic-sub"}
    assert registration == {
        "tenant_id": binding["tenant_id"],
        "client_id": "synthetic-school-client",
        "external_tenant_id": "10001",
        "external_app_id": "51",
        "registered_by_surface": "webhook",
        "status": "active",
    }

    now = datetime.now(timezone.utc)
    identity = ManagementIdentity(
        application="tms",
        issuer="https://synthetic-issuer.example",
        subject="synthetic-sub",
        school_id=binding["tenant_id"],
        policy_version=1,
        school_binding_version=1,
        webhook_app_id=51,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )
    candidates = await find_pending_actor_candidates(enterprise, identity)
    assert len(candidates) == 1
    assert candidates[0].event_id == event_id

    duplicate = await _deliver(
        app,
        event_id=event_id,
        event_type="subscription.created",
        status="active",
        actor={"type": "user", "user_id": "synthetic-sub"},
    )
    assert duplicate.status_code == 204
    suspended = await _deliver(
        app,
        event_id="synthetic-suspended-" + uuid.uuid4().hex,
        event_type="subscription.suspended",
        status="suspended",
    )
    assert suspended.status_code == 204
    async with enterprise.db.transaction(scope) as c:
        tenant = await (
            await c.execute(
                "SELECT external_eligibility FROM enterprise.tenants WHERE id=%s",
                (binding["tenant_id"],),
            )
        ).fetchone()
    assert tenant["external_eligibility"] == "denied"
    reactivated = await _deliver(
        app,
        event_id="synthetic-reactivated-" + uuid.uuid4().hex,
        event_type="subscription.reactivated",
        status="active",
    )
    assert reactivated.status_code == 204
    async with enterprise.db.transaction(scope) as c:
        tenant = await (
            await c.execute(
                "SELECT external_eligibility,local_enabled FROM enterprise.tenants WHERE id=%s",
                (binding["tenant_id"],),
            )
        ).fetchone()
        state = await (
            await c.execute(
                "SELECT generation,eligibility,onboarding_event_id,"
                "onboarding_completed_at IS NOT NULL AS database_initialized "
                "FROM eduplus2.webhook_school_state "
                "WHERE tenant_id=%s AND external_tenant_id=10001 AND external_app_id=51",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert tenant == {"external_eligibility": "allowed", "local_enabled": False}
    assert state == {
        "generation": 3,
        "eligibility": "allowed",
        "onboarding_event_id": event_id,
        "database_initialized": True,
    }


async def test_webhook_does_not_accept_unknown_school_binding_version_without_db_check(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    created = await _deliver(
        app,
        event_id="synthetic-binding-version-created",
        event_type="subscription.created",
        status="active",
    )
    assert created.status_code == 204
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@binding-version-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "ALTER TABLE oms.school_bindings DROP CONSTRAINT IF EXISTS school_bindings_version_check"
        )
        await c.execute("UPDATE oms.school_bindings SET version=0 WHERE eduplus_tenant_id=10001")
    denied = await _deliver(
        app,
        event_id="synthetic-binding-version-suspended",
        event_type="subscription.suspended",
        status="suspended",
    )
    assert denied.status_code == 409
    async with enterprise.db.transaction(scope) as c:
        row = await (
            await c.execute(
                "SELECT binding_version,eligibility FROM eduplus2.webhook_school_state "
                "WHERE external_tenant_id=10001"
            )
        ).fetchone()
    assert row == {"binding_version": 1, "eligibility": "allowed"}


async def test_webhook_authority_startup_does_not_require_online_resolver(monkeypatch, app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_resolver = None
    for key, value in {
        "DT_EDUPLUS2_LIFECYCLE_RECEIVER_ENABLED": "true",
        "DT_EDUPLUS2_WEBHOOK_SECRET": "synthetic-signing-secret",
        "DT_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY": "d" * 48,
        "DT_EDUPLUS2_OIDC_ISSUER": "https://synthetic-issuer.example",
    }.items():
        monkeypatch.setenv(key, value)
    enterprise._configure_eduplus2_from_env()
    assert enterprise.eduplus2_lifecycle_receiver_enabled
    assert enterprise.eduplus2_resolver is None


async def test_tms_bootstrap_http_uses_verified_token_and_signed_school_binding(app):
    from deeptutor_enterprise.eduplus2.client import HmacEduPlus2JwtVerifier

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_verifier = HmacEduPlus2JwtVerifier(
        signing_key="synthetic-oidc-signing-key-0123456789", issuer=enterprise.eduplus2_issuer
    )
    event_id = "synthetic-http-bootstrap-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            app_id=52,
            actor={"type": "user", "user_id": "synthetic-tms-sub"},
        )
    ).status_code == 204
    assert (
        await _deliver(
            app,
            event_id="synthetic-other-app-" + uuid.uuid4().hex,
            event_type="subscription.created",
            status="suspended",
            app_id=51,
            client_id="synthetic-other-app-client",
        )
    ).status_code == 204
    async with enterprise.db.transaction(
        TenantScope(str(enterprise.deployment.tenant_id), "@synthetic-eligibility-check")
    ) as connection:
        school = await (
            await connection.execute(
                "SELECT external_eligibility FROM enterprise.tenants WHERE external_tid='10001'"
            )
        ).fetchone()
    assert school == {"external_eligibility": "allowed"}
    issued_at = int(time.time())
    claims = {
        "iss": enterprise.eduplus2_issuer,
        "iat": issued_at,
        "exp": issued_at + 300,
        "tid": "10001",
        "eui": "synthetic-eui",
        "sub": "synthetic-tms-sub",
        "azp": "synthetic-school-client",
    }
    signing_key = "synthetic-oidc-signing-key-0123456789"
    token = jwt.encode(claims, signing_key, algorithm="HS256")
    wrong_client = jwt.encode({**claims, "azp": "other-client"}, signing_key, algorithm="HS256")
    wrong_school = jwt.encode({**claims, "tid": "10002"}, signing_key, algorithm="HS256")
    wrong_actor = jwt.encode(
        {**claims, "sub": "another-school-member"}, signing_key, algorithm="HS256"
    )
    invalid_expiry = jwt.encode({**claims, "exp": 2**100}, signing_key, algorithm="HS256")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        wrong = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={"Authorization": "Bearer " + wrong_client},
        )
        assert wrong.status_code == 403
        assert (
            await client.post(
                "/api/v1/tms/school-bootstrap/activate",
                headers={"Authorization": "Bearer " + wrong_school},
            )
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/tms/school-bootstrap/activate",
                headers={"Authorization": "Bearer " + wrong_actor},
            )
        ).status_code == 409
        assert (
            await client.post(
                "/api/v1/tms/school-bootstrap/activate",
                headers={"Authorization": "Bearer " + token + "invalid"},
            )
        ).status_code == 401
        assert (
            await client.post(
                "/api/v1/tms/school-bootstrap/activate",
                headers={"Authorization": "Bearer " + invalid_expiry},
            )
        ).status_code == 401
        status = await client.get(
            "/api/v1/tms/school-bootstrap/status",
            headers={"Authorization": "Bearer " + token},
        )
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "ready_to_activate"
        activated = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={"Authorization": "Bearer " + token, "X-Request-ID": "synthetic-http"},
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["status"] == "active"
        assert activated.json()["policy_version"] == 2
        active = await client.get(
            "/api/v1/tms/school-bootstrap/status",
            headers={"Authorization": "Bearer " + token},
        )
        assert active.status_code == 200
        assert active.json()["status"] == "active"





async def test_tms_skills_list_uses_current_school_grants_and_redacts_global_storage(app):
    """TMS 只读取当前学校已授权 Skill，不暴露 OMS 存储路径。"""

    from deeptutor_enterprise.eduplus2.client import HmacEduPlus2JwtVerifier

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_verifier = HmacEduPlus2JwtVerifier(
        signing_key="synthetic-oidc-signing-key-0123456789", issuer=enterprise.eduplus2_issuer
    )
    event_id = "synthetic-tms-skills-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-skills-admin"},
        )
    ).status_code == 204
    owner = enterprise.deployment.tenant_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@synthetic-tms-skills")) as c:
        binding = await (
            await c.execute(
                "SELECT tenant_id FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
    assert binding is not None
    school_id = binding["tenant_id"]
    issued_at = int(time.time())
    token = jwt.encode(
        {
            "iss": enterprise.eduplus2_issuer,
            "iat": issued_at,
            "exp": issued_at + 300,
            "tid": "10001",
            "eui": "synthetic-eui",
            "sub": "synthetic-skills-admin",
            "azp": "synthetic-school-client",
        },
        "synthetic-oidc-signing-key-0123456789",
        algorithm="HS256",
    )
    headers = {"Authorization": "Bearer " + token}
    revision_id = uuid.uuid4()
    review_id = uuid.uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        activated = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={**headers, "X-Request-ID": "synthetic-tms-skills"},
        )
        assert activated.status_code == 200, activated.text
    async with enterprise.db.transaction(TenantScope(str(school_id), "@synthetic-tms-skills")) as c:
        await c.execute("SELECT set_config('app.management_app','oms',true)")
        await c.execute(
            "INSERT INTO oms.skill_revisions"
            "(id,owner_kind,name,version,source,content_sha256,object_key,content_bytes,"
            "metadata,created_by,created_issuer) "
            "VALUES(%s,'global','school-tutor',1,'upload',%s,%s,1024,%s::jsonb,"
            "'skill-author','https://issuer.example')",
            (
                revision_id,
                "b" * 64,
                "oms/skills/global/school-tutor/secret-object.zip",
                json.dumps({"description": "学校可用 Skill", "tags": ["agent"]}),
            ),
        )
        await c.execute(
            "INSERT INTO oms.skill_reviews"
            "(id,revision_id,content_sha256,approved,scanner_version,code_file_digests,"
            "reviewer_issuer,reviewer_subject,reason,request_id) "
            "VALUES(%s,%s,%s,true,'skill-archive-v1',%s::jsonb,"
            "'https://issuer.example','security-reviewer','审查通过','review-1')",
            (review_id, revision_id, "b" * 64, json.dumps({})),
        )
        await c.execute(
            "INSERT INTO oms.skill_publications"
            "(id,owner_kind,name,revision_id,review_id,version,published_by,published_issuer) "
            "VALUES(%s,'global','school-tutor',%s,%s,1,'publisher','https://issuer.example')",
            (uuid.uuid4(), revision_id, review_id),
        )
        await c.execute("SELECT set_config('app.management_app','tms',true)")
        await c.execute(
            "INSERT INTO oms.skill_grants"
            "(tenant_id,name,revision_id,publication_version,status,version,expires_at,"
            "granted_by,granted_issuer) "
            "VALUES(%s,'school-tutor',%s,1,'active',1,now()+interval '7 days',"
            "'oms-operator','https://issuer.example')",
            (school_id, revision_id),
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        listed = await client.get("/api/v1/tms/skills", headers=headers)

    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body == {
        "application": "tms",
        "school_id": str(school_id),
        "skills": [
            {
                "name": "school-tutor",
                "revision_id": str(revision_id),
                "publication_version": 1,
                "grant_version": 1,
                "status": "active",
                "sha256": "b" * 64,
                "description": "学校可用 Skill",
                "tags": ["agent"],
            }
        ],
    }
    assert "secret-object" not in listed.text
    assert "object_key" not in listed.text


async def test_tms_permissions_catalog_is_current_school_scoped_and_manage_protected(app):
    """TMS 权限管理 DTO 只读当前学校，且仅 tenant.permissions.manage 可访问。"""

    from deeptutor_enterprise.eduplus2.client import HmacEduPlus2JwtVerifier

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_verifier = HmacEduPlus2JwtVerifier(
        signing_key="synthetic-oidc-signing-key-0123456789", issuer=enterprise.eduplus2_issuer
    )
    event_id = "synthetic-tms-catalog-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-catalog-admin"},
        )
    ).status_code == 204
    owner = enterprise.deployment.tenant_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@synthetic-tms-catalog")) as c:
        binding = await (
            await c.execute(
                "SELECT tenant_id,version FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
    assert binding is not None
    school_id = binding["tenant_id"]
    issued_at = int(time.time())
    base_claims = {
        "iss": enterprise.eduplus2_issuer,
        "iat": issued_at,
        "exp": issued_at + 300,
        "tid": "10001",
        "eui": "synthetic-eui",
        "azp": "synthetic-school-client",
    }
    admin_token = jwt.encode(
        {**base_claims, "sub": "synthetic-catalog-admin"},
        "synthetic-oidc-signing-key-0123456789",
        algorithm="HS256",
    )
    operator_principal_id = uuid.uuid4()
    async with enterprise.db.transaction(TenantScope(str(school_id), "@synthetic-tms-catalog")) as c:
        await c.execute("SELECT set_config('app.management_app','tms',true)")
        await c.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,school_id,status) "
            "VALUES(%s,'tms',%s,'synthetic-catalog-operator',%s,'active')",
            (operator_principal_id, enterprise.eduplus2_issuer, school_id),
        )
        await c.execute(
            "INSERT INTO management.assignments(id,application,principal_id,role_key,"
            "role_version,scope_kind,school_id,school_binding_version,valid_from,expires_at,"
            "command_id,created_by) "
            "VALUES(%s,'tms',%s,'school_operator',1,'school',%s,%s,"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-test')",
            (uuid.uuid4(), operator_principal_id, school_id, binding["version"], uuid.uuid4()),
        )
    operator_token = jwt.encode(
        {**base_claims, "sub": "synthetic-catalog-operator"},
        "synthetic-oidc-signing-key-0123456789",
        algorithm="HS256",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        activated = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={"Authorization": "Bearer " + admin_token, "X-Request-ID": "catalog-admin"},
        )
        assert activated.status_code == 200, activated.text
        allowed = await client.get(
            "/api/v1/tms/permissions",
            headers={"Authorization": "Bearer " + admin_token},
        )
        denied = await client.get(
            "/api/v1/tms/permissions",
            headers={"Authorization": "Bearer " + operator_token},
        )

    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["application"] == "tms"
    assert body["school_id"] == str(school_id)
    assert {role["role_key"] for role in body["roles"]} >= {
        "school_admin",
        "school_operator",
        "school_auditor",
    }
    assert any(item["subject"] == "synthetic-catalog-admin" for item in body["principals"])
    assert any(item["role_key"] == "school_admin" for item in body["assignments"])
    assert all(action["action_key"].startswith("tenant.") for action in body["actions"])
    assert "ops." not in allowed.text
    assert denied.status_code == 403, denied.text


async def test_tms_custom_role_publish_uses_current_school_permissions_and_blocks_ops_actions(app):
    """TMS 自定义角色只能由本校权限管理员发布 tenant.* 低风险动作。"""

    from deeptutor_enterprise.eduplus2.client import HmacEduPlus2JwtVerifier

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_verifier = HmacEduPlus2JwtVerifier(
        signing_key="synthetic-oidc-signing-key-0123456789", issuer=enterprise.eduplus2_issuer
    )
    event_id = "synthetic-tms-custom-role-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-custom-role-admin"},
        )
    ).status_code == 204
    owner = enterprise.deployment.tenant_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@synthetic-tms-custom-role")) as c:
        binding = await (
            await c.execute(
                "SELECT tenant_id FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
    assert binding is not None
    school_id = binding["tenant_id"]
    issued_at = int(time.time())
    token = jwt.encode(
        {
            "iss": enterprise.eduplus2_issuer,
            "iat": issued_at,
            "exp": issued_at + 300,
            "tid": "10001",
            "eui": "synthetic-eui",
            "sub": "synthetic-custom-role-admin",
            "azp": "synthetic-school-client",
        },
        "synthetic-oidc-signing-key-0123456789",
        algorithm="HS256",
    )
    headers = {"Authorization": "Bearer " + token}
    command_id = uuid.uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        activated = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={**headers, "X-Request-ID": "synthetic-custom-role-activation"},
        )
        assert activated.status_code == 200, activated.text
        published = await client.post(
            "/api/v1/tms/roles/custom",
            headers={**headers, "X-Request-ID": "synthetic-custom-role"},
            json={
                "role_key": "custom_lowrisk",
                "action_keys": ["tenant.members.read", "tenant.tms.access"],
                "expected_version": 0,
                "command_id": str(command_id),
                "reason": "发布低风险学校自定义角色",
            },
        )
        replayed = await client.post(
            "/api/v1/tms/roles/custom",
            headers={**headers, "X-Request-ID": "synthetic-custom-role"},
            json={
                "role_key": "custom_lowrisk",
                "action_keys": ["tenant.members.read", "tenant.tms.access"],
                "expected_version": 0,
                "command_id": str(command_id),
                "reason": "发布低风险学校自定义角色",
            },
        )
        cross_app = await client.post(
            "/api/v1/tms/roles/custom",
            headers={**headers, "X-Request-ID": "synthetic-custom-role-cross-app"},
            json={
                "role_key": "custom_cross_app",
                "action_keys": ["ops.oms.access"],
                "expected_version": 0,
                "command_id": str(uuid.uuid4()),
                "reason": "错误地尝试发布 OMS 动作",
            },
        )

    assert published.status_code == 200, published.text
    body = published.json()
    assert body == {
        "application": "tms",
        "school_id": str(school_id),
        "role_key": f"custom_{school_id.hex}_lowrisk",
        "version": 1,
        "scope_kind": "school",
        "action_keys": ["tenant.members.read", "tenant.tms.access"],
        "replayed": False,
    }
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replayed"] is True
    assert cross_app.status_code == 403, cross_app.text
    assert "ops." not in published.text


async def test_tms_assignment_revoke_is_current_school_scoped_and_protects_last_admin(app):
    """TMS 撤权 API 串行当前学校 assignment，且保护最后一名学校管理员。"""

    from deeptutor_enterprise.eduplus2.client import HmacEduPlus2JwtVerifier

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_verifier = HmacEduPlus2JwtVerifier(
        signing_key="synthetic-oidc-signing-key-0123456789", issuer=enterprise.eduplus2_issuer
    )
    event_id = "synthetic-tms-revoke-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-revoke-admin"},
        )
    ).status_code == 204
    issued_at = int(time.time())
    token = jwt.encode(
        {
            "iss": enterprise.eduplus2_issuer,
            "iat": issued_at,
            "exp": issued_at + 300,
            "tid": "10001",
            "eui": "synthetic-eui",
            "sub": "synthetic-revoke-admin",
            "azp": "synthetic-school-client",
        },
        "synthetic-oidc-signing-key-0123456789",
        algorithm="HS256",
    )
    headers = {"Authorization": "Bearer " + token}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        activated = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={**headers, "X-Request-ID": "synthetic-revoke-activation"},
        )
        assert activated.status_code == 200, activated.text

    owner = enterprise.deployment.tenant_id
    operator_principal_id = uuid.uuid4()
    operator_assignment_id = uuid.uuid4()
    async with enterprise.db.transaction(TenantScope(str(owner), "@synthetic-tms-revoke")) as c:
        binding = await (
            await c.execute(
                "SELECT tenant_id,version FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
        assert binding is not None
        school_id = binding["tenant_id"]
    async with enterprise.db.transaction(TenantScope(str(school_id), "@synthetic-tms-revoke")) as c:
        await c.execute("SELECT set_config('app.management_app','tms',true)")
        admin_assignment = await (
            await c.execute(
                "SELECT id,version FROM management.assignments WHERE application='tms' "
                "AND role_key='school_admin' AND school_id=%s",
                (school_id,),
            )
        ).fetchone()
        assert admin_assignment is not None
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,school_id,status) "
            "VALUES(%s,'tms',%s,'synthetic-revoke-operator',%s,'active')",
            (operator_principal_id, enterprise.eduplus2_issuer, school_id),
        )
        await c.execute(
            "INSERT INTO management.assignments(id,application,principal_id,role_key,"
            "role_version,scope_kind,school_id,school_binding_version,valid_from,expires_at,"
            "command_id,created_by) "
            "VALUES(%s,'tms',%s,'school_operator',1,'school',%s,%s,"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-test')",
            (operator_assignment_id, operator_principal_id, school_id, binding["version"], uuid.uuid4()),
        )

    revoke_command_id = uuid.uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        revoked = await client.post(
            f"/api/v1/tms/assignments/{operator_assignment_id}/revoke",
            headers={**headers, "X-Request-ID": "synthetic-revoke-assignment"},
            json={
                "expected_assignment_version": 1,
                "expected_target_policy_version": 1,
                "command_id": str(revoke_command_id),
                "reason": "撤销学校操作员角色",
            },
        )
        replayed = await client.post(
            f"/api/v1/tms/assignments/{operator_assignment_id}/revoke",
            headers={**headers, "X-Request-ID": "synthetic-revoke-assignment"},
            json={
                "expected_assignment_version": 1,
                "expected_target_policy_version": 1,
                "command_id": str(revoke_command_id),
                "reason": "撤销学校操作员角色",
            },
        )
        last_admin = await client.post(
            f"/api/v1/tms/assignments/{admin_assignment['id']}/revoke",
            headers={**headers, "X-Request-ID": "synthetic-revoke-last-admin"},
            json={
                "expected_assignment_version": admin_assignment["version"],
                "expected_target_policy_version": 2,
                "command_id": str(uuid.uuid4()),
                "reason": "不允许撤销最后一名学校管理员",
            },
        )

    assert revoked.status_code == 200, revoked.text
    assert revoked.json() == {
        "application": "tms",
        "school_id": str(school_id),
        "assignment_id": str(operator_assignment_id),
        "assignment_version": 2,
        "target_policy_version": 2,
        "status": "revoked",
        "replayed": False,
    }
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replayed"] is True
    assert last_admin.status_code == 409, last_admin.text


async def test_tms_self_registration_then_admin_grants_low_risk_role(app):
    """学校成员须本人 TMS 登录登记后，管理员才可授予低风险角色。"""

    from deeptutor_enterprise.eduplus2.client import HmacEduPlus2JwtVerifier

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_verifier = HmacEduPlus2JwtVerifier(
        signing_key="synthetic-oidc-signing-key-0123456789", issuer=enterprise.eduplus2_issuer
    )
    event_id = "synthetic-tms-member-grant-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-grant-admin"},
        )
    ).status_code == 204
    issued_at = int(time.time())
    base_claims = {
        "iss": enterprise.eduplus2_issuer,
        "iat": issued_at,
        "exp": issued_at + 300,
        "tid": "10001",
        "eui": "synthetic-eui",
        "azp": "synthetic-school-client",
    }
    signing_key = "synthetic-oidc-signing-key-0123456789"
    admin_token = jwt.encode({**base_claims, "sub": "synthetic-grant-admin"}, signing_key, algorithm="HS256")
    member_token = jwt.encode({**base_claims, "sub": "synthetic-grant-member"}, signing_key, algorithm="HS256")
    admin_headers = {"Authorization": "Bearer " + admin_token}
    member_headers = {"Authorization": "Bearer " + member_token}
    grant_command_id = uuid.uuid4()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        activated = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={**admin_headers, "X-Request-ID": "synthetic-member-grant-activation"},
        )
        assert activated.status_code == 200, activated.text
        initial_summary = await client.get("/api/v1/tms/me/permissions", headers=member_headers)
        registered = await client.post(
            "/api/v1/tms/me/register",
            headers={**member_headers, "X-Request-ID": "synthetic-member-register"},
        )
        assert registered.status_code == 200, registered.text
        body = registered.json()
        async with enterprise.db.transaction(
            TenantScope(str(uuid.UUID(body["school_id"])), "@synthetic-member-row-check")
        ) as c:
            await c.execute("SELECT set_config('app.management_app','tms',true)")
            member_row = await (
                await c.execute(
                    "SELECT subject,status FROM management.principals WHERE id=%s",
                    (uuid.UUID(body["principal_id"]),),
                )
            ).fetchone()
        assert member_row == {"subject": "synthetic-grant-member", "status": "pending"}
        granted = await client.post(
            f"/api/v1/tms/members/{body['principal_id']}/roles",
            headers={**admin_headers, "X-Request-ID": "synthetic-member-grant"},
            json={
                "role_key": "school_auditor",
                "role_version": 1,
                "expected_target_policy_version": 1,
                "expires_at": expires_at,
                "command_id": str(grant_command_id),
                "reason": "授予已本人登录登记成员低风险审计角色",
            },
        )
        replayed = await client.post(
            f"/api/v1/tms/members/{body['principal_id']}/roles",
            headers={**admin_headers, "X-Request-ID": "synthetic-member-grant"},
            json={
                "role_key": "school_auditor",
                "role_version": 1,
                "expected_target_policy_version": 1,
                "expires_at": expires_at,
                "command_id": str(grant_command_id),
                "reason": "授予已本人登录登记成员低风险审计角色",
            },
        )
        elevated = await client.post(
            f"/api/v1/tms/members/{body['principal_id']}/roles",
            headers={**admin_headers, "X-Request-ID": "synthetic-member-grant-admin"},
            json={
                "role_key": "school_admin",
                "role_version": 1,
                "expected_target_policy_version": 2,
                "expires_at": expires_at,
                "command_id": str(uuid.uuid4()),
                "reason": "学校管理员角色必须走独立审批",
            },
        )
        summary = await client.get("/api/v1/tms/me/permissions", headers=member_headers)

    assert initial_summary.status_code == 200, initial_summary.text
    assert initial_summary.json()["actions"] == []
    assert registered.json()["application"] == "tms"
    assert registered.json()["subject"] == "synthetic-grant-member"
    assert registered.json()["status"] == "pending"
    assert registered.json()["policy_version"] == 1
    assert granted.status_code == 200, granted.text
    assert granted.json()["application"] == "tms"
    assert granted.json()["role_key"] == "school_auditor"
    assert granted.json()["target_policy_version"] == 2
    assert granted.json()["status"] == "active"
    assert granted.json()["replayed"] is False
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replayed"] is True
    assert elevated.status_code == 403, elevated.text
    assert summary.status_code == 200, summary.text
    assert summary.json()["actions"] == [
        "tenant.members.read",
        "tenant.quotas.read",
        "tenant.tms.access",
        "tenant.usage.read",
    ]


async def test_tms_authz_audit_is_current_school_scoped_and_permission_guarded(app):
    """TMS 授权记录只暴露当前学校 tenant.* 审计，且须具备权限治理动作。"""

    from deeptutor_enterprise.eduplus2.client import HmacEduPlus2JwtVerifier

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_verifier = HmacEduPlus2JwtVerifier(
        signing_key="synthetic-oidc-signing-key-0123456789", issuer=enterprise.eduplus2_issuer
    )
    event_id = "synthetic-tms-authz-audit-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-authz-audit-admin"},
        )
    ).status_code == 204
    owner = enterprise.deployment.tenant_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@synthetic-authz-audit")) as c:
        binding = await (
            await c.execute(
                "SELECT tenant_id,version FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
    assert binding is not None
    school_id = binding["tenant_id"]
    signing_key = "synthetic-oidc-signing-key-0123456789"
    issued_at = int(time.time())
    base_claims = {
        "iss": enterprise.eduplus2_issuer,
        "iat": issued_at,
        "exp": issued_at + 300,
        "tid": "10001",
        "eui": "synthetic-eui",
        "azp": "synthetic-school-client",
    }
    admin_token = jwt.encode(
        {**base_claims, "sub": "synthetic-authz-audit-admin"},
        signing_key,
        algorithm="HS256",
    )
    auditor_token = jwt.encode(
        {**base_claims, "sub": "synthetic-authz-audit-auditor"},
        signing_key,
        algorithm="HS256",
    )

    async with enterprise.db.transaction(TenantScope(str(school_id), "@synthetic-authz-audit")) as c:
        await c.execute("SELECT set_config('app.management_app','tms',true)")
        auditor_principal_id = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,school_id,status) "
            "VALUES(%s,'tms',%s,'synthetic-authz-audit-auditor',%s,'active')",
            (auditor_principal_id, enterprise.eduplus2_issuer, school_id),
        )
        await c.execute(
            "INSERT INTO management.assignments(id,application,principal_id,role_key,"
            "role_version,scope_kind,school_id,school_binding_version,valid_from,expires_at,"
            "command_id,created_by) "
            "VALUES(%s,'tms',%s,'school_auditor',1,'school',%s,%s,"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-test')",
            (uuid.uuid4(), auditor_principal_id, school_id, binding["version"], uuid.uuid4()),
        )
        await c.execute(
            "INSERT INTO management.audit_events"
            "(id,application,school_id,actor_issuer,actor_subject,action_key,target_kind,"
            "target_id,request_id,result,reason,before_version,after_version,safe_summary) "
            "VALUES(%s,'tms',%s,%s,'synthetic-authz-audit-admin',"
            "'tenant.permissions.manage','assignment','same-school-assignment',"
            "'synthetic-authz-audit','success','same-school audit reason',1,2,%s::jsonb)",
            (
                uuid.uuid4(),
                school_id,
                enterprise.eduplus2_issuer,
                json.dumps({"role_key": "school_auditor"}),
            ),
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        activated = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={
                "Authorization": "Bearer " + admin_token,
                "X-Request-ID": "synthetic-tms-authz-audit-activate",
            },
        )
        assert activated.status_code == 200, activated.text
        allowed = await client.get(
            "/api/v1/tms/authz-audit?limit=20",
            headers={"Authorization": "Bearer " + admin_token},
        )
        denied = await client.get(
            "/api/v1/tms/authz-audit",
            headers={"Authorization": "Bearer " + auditor_token},
        )

    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["application"] == "tms"
    assert body["school_id"] == str(school_id)
    assert any(item["target_id"] == "same-school-assignment" for item in body["events"])
    assert all(item["action_key"].startswith("tenant.") for item in body["events"])
    assert "ops." not in allowed.text
    assert "synthetic-webhook-secret" not in allowed.text
    assert denied.status_code == 403, denied.text


async def test_tms_members_list_is_current_school_read_only_and_member_permission_guarded(app):
    """TMS 成员列表只读本校本产品主体，不能靠外部 token 或跨校字段取数。"""

    from deeptutor_enterprise.eduplus2.client import HmacEduPlus2JwtVerifier

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_verifier = HmacEduPlus2JwtVerifier(
        signing_key="synthetic-oidc-signing-key-0123456789", issuer=enterprise.eduplus2_issuer
    )
    event_id = "synthetic-tms-members-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-members-admin"},
        )
    ).status_code == 204
    owner = enterprise.deployment.tenant_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@synthetic-tms-members")) as c:
        binding = await (
            await c.execute(
                "SELECT tenant_id,version FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
    assert binding is not None
    school_id = binding["tenant_id"]
    signing_key = "synthetic-oidc-signing-key-0123456789"
    issued_at = int(time.time())
    base_claims = {
        "iss": enterprise.eduplus2_issuer,
        "iat": issued_at,
        "exp": issued_at + 300,
        "tid": "10001",
        "eui": "synthetic-eui",
        "azp": "synthetic-school-client",
    }
    admin_headers = {
        "Authorization": "Bearer "
        + jwt.encode(
            {**base_claims, "sub": "synthetic-members-admin"},
            signing_key,
            algorithm="HS256",
        )
    }
    auditor_headers = {
        "Authorization": "Bearer "
        + jwt.encode(
            {**base_claims, "sub": "synthetic-members-auditor"},
            signing_key,
            algorithm="HS256",
        )
    }
    outsider_headers = {
        "Authorization": "Bearer "
        + jwt.encode(
            {**base_claims, "sub": "synthetic-members-outsider"},
            signing_key,
            algorithm="HS256",
        )
    }

    async with enterprise.db.transaction(TenantScope(str(school_id), "@synthetic-tms-members")) as c:
        await c.execute("SELECT set_config('app.management_app','tms',true)")
        auditor_principal_id = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,school_id,status) "
            "VALUES(%s,'tms',%s,'synthetic-members-auditor',%s,'active')",
            (auditor_principal_id, enterprise.eduplus2_issuer, school_id),
        )
        await c.execute(
            "INSERT INTO management.assignments(id,application,principal_id,role_key,"
            "role_version,scope_kind,school_id,school_binding_version,valid_from,expires_at,"
            "command_id,created_by) "
            "VALUES(%s,'tms',%s,'school_auditor',1,'school',%s,%s,"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-test')",
            (uuid.uuid4(), auditor_principal_id, school_id, binding["version"], uuid.uuid4()),
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        activated = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={**admin_headers, "X-Request-ID": "synthetic-tms-members-activate"},
        )
        assert activated.status_code == 200, activated.text
        admin_view = await client.get("/api/v1/tms/members", headers=admin_headers)
        auditor_view = await client.get("/api/v1/tms/members", headers=auditor_headers)
        denied = await client.get("/api/v1/tms/members", headers=outsider_headers)

    assert admin_view.status_code == 200, admin_view.text
    assert auditor_view.status_code == 200, auditor_view.text
    body = admin_view.json()
    assert body["application"] == "tms"
    assert body["school_id"] == str(school_id)
    subjects = {item["subject"] for item in body["members"]}
    assert {"synthetic-members-admin", "synthetic-members-auditor"} <= subjects
    auditor = next(item for item in body["members"] if item["subject"] == "synthetic-members-auditor")
    assert auditor["roles"] == [
        {
            "assignment_id": auditor["roles"][0]["assignment_id"],
            "role_key": "school_auditor",
            "role_version": 1,
            "status": "active",
            "version": 1,
            "expires_at": auditor["roles"][0]["expires_at"],
            "revoked_at": "",
        }
    ]
    assert "ops." not in admin_view.text
    assert "synthetic-webhook-secret" not in admin_view.text
    assert denied.status_code == 403, denied.text


async def test_tms_directory_search_fails_closed_when_external_contract_missing(app):
    """外部学校目录合同未核实时，TMS 返回未启用状态而不是合成用户。"""

    from deeptutor_enterprise.eduplus2.client import HmacEduPlus2JwtVerifier

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_verifier = HmacEduPlus2JwtVerifier(
        signing_key="synthetic-oidc-signing-key-0123456789", issuer=enterprise.eduplus2_issuer
    )
    event_id = "synthetic-tms-directory-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-directory-admin"},
        )
    ).status_code == 204
    issued_at = int(time.time())
    token = jwt.encode(
        {
            "iss": enterprise.eduplus2_issuer,
            "iat": issued_at,
            "exp": issued_at + 300,
            "tid": "10001",
            "eui": "synthetic-eui",
            "sub": "synthetic-directory-admin",
            "azp": "synthetic-school-client",
        },
        "synthetic-oidc-signing-key-0123456789",
        algorithm="HS256",
    )
    member_token = jwt.encode(
        {
            "iss": enterprise.eduplus2_issuer,
            "iat": issued_at,
            "exp": issued_at + 300,
            "tid": "10001",
            "eui": "synthetic-eui",
            "sub": "synthetic-directory-member",
            "azp": "synthetic-school-client",
        },
        "synthetic-oidc-signing-key-0123456789",
        algorithm="HS256",
    )
    headers = {"Authorization": "Bearer " + token}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        activated = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={**headers, "X-Request-ID": "synthetic-tms-directory-activate"},
        )
        assert activated.status_code == 200, activated.text
        directory = await client.get(
            "/api/v1/tms/directory/users?q=teacher",
            headers=headers,
        )
        denied = await client.get(
            "/api/v1/tms/directory/users?q=teacher",
            headers={"Authorization": "Bearer " + member_token},
        )

    assert directory.status_code == 200, directory.text
    assert directory.json() == {
        "application": "tms",
        "school_id": directory.json()["school_id"],
        "status": "not_enabled",
        "reason_code": "external_directory_contract_missing",
        "message": "学校成员目录尚未核实第三方应用授权码用户令牌与策略范围，当前仅支持本人登录登记。",
        "query": "teacher",
        "users": [],
    }
    assert "synthetic-directory-member" not in directory.text
    assert "ops." not in directory.text
    assert denied.status_code == 403, denied.text


async def test_tms_approval_lifecycle_requires_independent_school_admin(app):
    """TMS 高风险审批请求须由同校另一名当前管理员复核，且只写本地审批事实。"""

    from deeptutor_enterprise.eduplus2.client import HmacEduPlus2JwtVerifier

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_verifier = HmacEduPlus2JwtVerifier(
        signing_key="synthetic-oidc-signing-key-0123456789", issuer=enterprise.eduplus2_issuer
    )
    event_id = "synthetic-tms-approval-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-approval-admin"},
        )
    ).status_code == 204
    owner = enterprise.deployment.tenant_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@synthetic-tms-approval")) as c:
        binding = await (
            await c.execute(
                "SELECT tenant_id,version FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
    assert binding is not None
    school_id = binding["tenant_id"]
    signing_key = "synthetic-oidc-signing-key-0123456789"
    issued_at = int(time.time())
    base_claims = {
        "iss": enterprise.eduplus2_issuer,
        "iat": issued_at,
        "exp": issued_at + 300,
        "tid": "10001",
        "eui": "synthetic-eui",
        "azp": "synthetic-school-client",
    }
    admin_headers = {
        "Authorization": "Bearer "
        + jwt.encode(
            {**base_claims, "sub": "synthetic-approval-admin"},
            signing_key,
            algorithm="HS256",
        )
    }
    reviewer_headers = {
        "Authorization": "Bearer "
        + jwt.encode(
            {**base_claims, "sub": "synthetic-approval-reviewer"},
            signing_key,
            algorithm="HS256",
        )
    }
    target_headers = {
        "Authorization": "Bearer "
        + jwt.encode(
            {**base_claims, "sub": "synthetic-approval-target"},
            signing_key,
            algorithm="HS256",
        )
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        activated = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={**admin_headers, "X-Request-ID": "synthetic-tms-approval-activate"},
        )
    assert activated.status_code == 200, activated.text

    async with enterprise.db.transaction(TenantScope(str(school_id), "@synthetic-tms-approval")) as c:
        await c.execute("SELECT set_config('app.management_app','tms',true)")
        reviewer_principal_id = uuid.uuid4()
        target_principal_id = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,school_id,status) "
            "VALUES(%s,'tms',%s,'synthetic-approval-reviewer',%s,'active'),"
            "(%s,'tms',%s,'synthetic-approval-target',%s,'pending')",
            (
                reviewer_principal_id,
                enterprise.eduplus2_issuer,
                school_id,
                target_principal_id,
                enterprise.eduplus2_issuer,
                school_id,
            ),
        )
        await c.execute(
            "INSERT INTO management.assignments(id,application,principal_id,role_key,"
            "role_version,scope_kind,school_id,school_binding_version,valid_from,expires_at,"
            "command_id,created_by) "
            "VALUES(%s,'tms',%s,'school_admin',1,'school',%s,%s,"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-test')",
            (uuid.uuid4(), reviewer_principal_id, school_id, binding["version"], uuid.uuid4()),
        )

    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    create_body = {
        "operation": "school_activation",
        "target_principal_id": str(target_principal_id),
        "expected_target_policy_version": 1,
        "expires_at": expires_at,
        "idempotency_key": "synthetic-school-activation-approval",
        "reason": "学校管理员角色须同校另一名管理员复核",
        "external_qualification_ref": "synthetic://approval/school-admin",
        "external_qualification_version": "v1",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        created = await client.post(
            "/api/v1/tms/approvals",
            headers={**admin_headers, "X-Request-ID": "synthetic-tms-approval-create"},
            json=create_body,
        )
        replayed_create = await client.post(
            "/api/v1/tms/approvals",
            headers={**admin_headers, "X-Request-ID": "synthetic-tms-approval-create"},
            json=create_body,
        )
        assert created.status_code == 200, created.text
        approval_id = created.json()["approval_id"]
        self_review = await client.post(
            f"/api/v1/tms/approvals/{approval_id}/review",
            headers={**admin_headers, "X-Request-ID": "synthetic-tms-approval-self-review"},
            json={
                "decision": "approved",
                "expected_target_policy_version": 1,
                "reason": "本人不能复核自己的审批",
            },
        )
        approved = await client.post(
            f"/api/v1/tms/approvals/{approval_id}/review",
            headers={**reviewer_headers, "X-Request-ID": "synthetic-tms-approval-review"},
            json={
                "decision": "approved",
                "expected_target_policy_version": 1,
                "reason": "同校独立管理员复核",
            },
        )
        command_id = str(uuid.uuid4())
        applied = await client.post(
            f"/api/v1/tms/approvals/{approval_id}/apply",
            headers={**reviewer_headers, "X-Request-ID": "synthetic-tms-approval-apply"},
            json={
                "expected_target_policy_version": 1,
                "command_id": command_id,
                "reason": "审批通过后授予学校管理员",
            },
        )
        replayed_apply = await client.post(
            f"/api/v1/tms/approvals/{approval_id}/apply",
            headers={**reviewer_headers, "X-Request-ID": "synthetic-tms-approval-apply"},
            json={
                "expected_target_policy_version": 1,
                "command_id": command_id,
                "reason": "审批通过后授予学校管理员",
            },
        )
        target_summary = await client.get("/api/v1/tms/me/permissions", headers=target_headers)
        listed = await client.get(
            "/api/v1/tms/approvals?limit=20",
            headers=admin_headers,
        )

    assert replayed_create.status_code == 200, replayed_create.text
    assert replayed_create.json()["replayed"] is True
    assert self_review.status_code == 409, self_review.text
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["replayed"] is False
    assert applied.status_code == 200, applied.text
    assert applied.json()["role_key"] == "school_admin"
    assert applied.json()["target_policy_version"] == 2
    assert applied.json()["replayed"] is False
    assert replayed_apply.status_code == 200, replayed_apply.text
    assert replayed_apply.json()["replayed"] is True
    assert target_summary.status_code == 200, target_summary.text
    assert "tenant.permissions.manage" in target_summary.json()["actions"]
    assert listed.status_code == 200, listed.text
    assert any(item["approval_id"] == approval_id and item["status"] == "approved" for item in listed.json()["approvals"])
    assert "ops." not in listed.text
    assert "synthetic-webhook-secret" not in listed.text


async def test_tms_me_permissions_returns_local_tenant_action_summary(app):
    """TMS 前端只获取本校 tenant.* 权限摘要；真实接口仍逐次 PEP。"""

    from deeptutor_enterprise.eduplus2.client import HmacEduPlus2JwtVerifier

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_verifier = HmacEduPlus2JwtVerifier(
        signing_key="synthetic-oidc-signing-key-0123456789", issuer=enterprise.eduplus2_issuer
    )
    event_id = "synthetic-tms-permissions-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-permissions-admin"},
        )
    ).status_code == 204
    owner = enterprise.deployment.tenant_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@synthetic-tms-permissions")) as c:
        binding = await (
            await c.execute(
                "SELECT tenant_id FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
    assert binding is not None
    school_id = binding["tenant_id"]
    issued_at = int(time.time())
    claims = {
        "iss": enterprise.eduplus2_issuer,
        "iat": issued_at,
        "exp": issued_at + 300,
        "tid": "10001",
        "eui": "synthetic-eui",
        "sub": "synthetic-permissions-admin",
        "azp": "synthetic-school-client",
    }
    token = jwt.encode(claims, "synthetic-oidc-signing-key-0123456789", algorithm="HS256")
    headers = {"Authorization": "Bearer " + token}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        activated = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={**headers, "X-Request-ID": "synthetic-tms-permissions"},
        )
        assert activated.status_code == 200, activated.text
        summary = await client.get("/api/v1/tms/me/permissions", headers=headers)

    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body == {
        "application": "tms",
        "school_id": str(school_id),
        "subject": "synthetic-permissions-admin",
        "policy_version": 2,
        "actions": [
            "tenant.access.manage",
            "tenant.clients.manage",
            "tenant.kb.manage",
            "tenant.members.read",
            "tenant.permissions.manage",
            "tenant.quotas.read",
            "tenant.tms.access",
            "tenant.usage.read",
        ],
    }
    assert all(action.startswith("tenant.") for action in body["actions"])
    assert "ops." not in summary.text


async def test_tms_quota_summary_is_current_school_read_only_and_redacted(app):
    """学校侧只能读取本校配额安全视图，不能看到供给、成本或 Secret 关联字段。"""

    from deeptutor_enterprise.eduplus2.client import HmacEduPlus2JwtVerifier

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_verifier = HmacEduPlus2JwtVerifier(
        signing_key="synthetic-oidc-signing-key-0123456789", issuer=enterprise.eduplus2_issuer
    )
    event_id = "synthetic-tms-quota-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-quota-admin"},
        )
    ).status_code == 204
    issued_at = int(time.time())
    claims = {
        "iss": enterprise.eduplus2_issuer,
        "iat": issued_at,
        "exp": issued_at + 300,
        "tid": "10001",
        "eui": "synthetic-eui",
        "sub": "synthetic-quota-admin",
        "azp": "synthetic-school-client",
    }
    token = jwt.encode(claims, "synthetic-oidc-signing-key-0123456789", algorithm="HS256")
    headers = {"Authorization": "Bearer " + token}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        activated = await client.post(
            "/api/v1/tms/school-bootstrap/activate",
            headers={**headers, "X-Request-ID": "synthetic-quota-activation"},
        )
        assert activated.status_code == 200, activated.text

    now = datetime.now(timezone.utc)
    grant_id = uuid.uuid4()
    async with enterprise.db.transaction(
        TenantScope(str(enterprise.deployment.tenant_id), "@synthetic-quota-school")
    ) as c:
        school_row = await (
            await c.execute(
                "SELECT tenant_id FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
        assert school_row is not None
        school_id = school_row["tenant_id"]
    async with enterprise.db.transaction(TenantScope(str(school_id), "@synthetic-quota-seed")) as c:
        await c.execute(
            "INSERT INTO oms.service_definitions(service_id,unit_code,resource_category,enabled) "
            "VALUES('search','request','tool_integration',true)"
        )
        await c.execute(
            "INSERT INTO oms.tenant_service_entitlements"
            "(tenant_id,service_id,status,starts_at,expires_at,created_by) "
            "VALUES(%s,'search','active',%s,%s,'synthetic-oms')",
            (school_id, now - timedelta(minutes=1), now + timedelta(days=7)),
        )
        await c.execute(
            "INSERT INTO oms.quota_grants"
            "(id,tenant_id,service_id,unit_code,acquisition_method,quantity,"
            "starts_at,expires_at,created_by,source_ref) "
            "VALUES(%s,%s,'search','request','gift',25,%s,%s,'synthetic-oms',"
            "'purchase://provider-secret-source')",
            (grant_id, school_id, now - timedelta(minutes=1), now + timedelta(days=7)),
        )
        await c.execute(
            "INSERT INTO oms.usage_attempts"
            "(tenant_id,attempt_id,operation_id,service_id,unit_code,provider_id,"
            "provider_account_id,model_id,config_version,subject_kind,subject_id,user_id,"
            "status,reserved_units,settled_units,evidence) "
            "VALUES(%s,%s,%s,'search','request','secret-provider','secret-account',"
            "'secret-model',1,'user','synthetic-quota-admin','synthetic-quota-admin',"
            "'settled',3,2,'{\"cost\":\"secret-cost\"}'::jsonb)",
            (school_id, uuid.uuid4(), uuid.uuid4()),
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        summary = await client.get("/api/v1/tms/quotas", headers=headers)
        assert summary.status_code == 200, summary.text
        body = summary.json()
        assert body["school_id"] == str(school_id)
        assert body["entitlements"] == [
            {
                "service_id": "search",
                "status": "active",
                "starts_at": body["entitlements"][0]["starts_at"],
                "expires_at": body["entitlements"][0]["expires_at"],
                "version": 1,
            }
        ]
        assert body["grants"] == [
            {
                "grant_id": str(grant_id),
                "service_id": "search",
                "unit_code": "request",
                "acquisition_method": "gift",
                "quantity": "25",
                "adjustment_released": "0",
                "status": "active",
                "version": 1,
                "starts_at": body["grants"][0]["starts_at"],
                "expires_at": body["grants"][0]["expires_at"],
            }
        ]
        assert body["usage"] == [
            {
                "service_id": "search",
                "unit_code": "request",
                "status": "settled",
                "attempts": 1,
                "reserved_units": "3",
                "settled_units": "2",
            }
        ]
        assert body["usage_page"] == {"limit": 50, "offset": 0, "count": 1}
        assert body["usage_details"][0] == {
            "attempt_id": body["usage_details"][0]["attempt_id"],
            "operation_id": body["usage_details"][0]["operation_id"],
            "service_id": "search",
            "unit_code": "request",
            "subject_kind": "user",
            "subject_id": "synthetic-quota-admin",
            "user_id": "synthetic-quota-admin",
            "app_id": "",
            "status": "settled",
            "reserved_units": "3",
            "settled_units": "2",
            "started_at": body["usage_details"][0]["started_at"],
            "updated_at": body["usage_details"][0]["updated_at"],
        }
        access_id = uuid.uuid4()
        granted = await client.post(
            "/api/v1/tms/service-access",
            headers=headers,
            json={
                "grant_id": str(access_id),
                "service_id": "search",
                "subject_kind": "member",
                "subject_id": "synthetic-quota-admin",
                "starts_at": now.isoformat(),
                "expires_at": (now + timedelta(days=1)).isoformat(),
                "expected_entitlement_version": 1,
                "reason": "学校管理员授予成员搜索服务访问资格",
            },
        )
        assert granted.status_code == 200, granted.text
        assert granted.json() == {
            "grant_id": str(access_id),
            "service_id": "search",
            "subject_kind": "member",
            "subject_id": "synthetic-quota-admin",
            "status": "active",
            "sync_status": "local_ready",
            "version": 1,
        }
        listed = await client.get(
            "/api/v1/tms/service-access?service_id=search&limit=10",
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()["page"] == {"limit": 10, "offset": 0, "count": 1}
        assert listed.json()["service_access_grants"][0]["grant_id"] == str(access_id)
        revoked = await client.post(
            f"/api/v1/tms/service-access/{access_id}/revoke",
            headers=headers,
            json={"expected_version": 1, "reason": "撤销成员搜索服务访问资格"},
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["status"] == "revoked"
        assert revoked.json()["version"] == 2
        for hidden in (
            "source_ref",
            "source_ref_hash",
            "provider_id",
            "provider_account_id",
            "pool_id",
            "provider-secret-source",
            "secret-provider",
            "secret-account",
            "secret-model",
            "secret-cost",
        ):
            assert hidden not in summary.text + listed.text
        assert (
            await client.post("/api/v1/tms/quotas", headers=headers, json={})
        ).status_code == 405
        grants_write = await client.post("/api/v1/tms/quotas/grants", headers=headers, json={})
        assert grants_write.status_code in {401, 404}

    async with enterprise.db.transaction(TenantScope(str(school_id), "@service-access-counts")) as c:
        counts = {}
        for table in ("quota_grants", "usage_attempts", "tenant_service_access_grants"):
            row = await (await c.execute(f"SELECT count(*) AS n FROM oms.{table}")).fetchone()
            counts[table] = row["n"]
    assert counts == {
        "quota_grants": 1,
        "usage_attempts": 1,
        "tenant_service_access_grants": 1,
    }


async def test_authorized_oms_freeze_survives_webhook_reactivation(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    assert (
        await _deliver(
            app,
            event_id="synthetic-freeze-created-" + uuid.uuid4().hex,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-admin"},
        )
    ).status_code == 204
    owner = enterprise.deployment.tenant_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@freeze-test")) as c:
        school = await (
            await c.execute(
                "SELECT tenant_id FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
        school_id = school["tenant_id"]
        await c.execute("SELECT set_config('app.management_app','oms',true)")
        operator_id = uuid.uuid4()
        await c.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) "
            "VALUES(%s,'oms','https://synthetic-issuer.example','synthetic-operator','active')",
            (operator_id,),
        )
        await c.execute(
            "INSERT INTO management.role_versions(application,role_key,version,scope_kind) "
            "VALUES('oms','synthetic_reconciler',1,'school')"
        )
        await c.execute(
            "INSERT INTO management.role_actions(application,role_key,role_version,action_key) "
            "VALUES('oms','synthetic_reconciler',1,'ops.reconciliation.manage')"
        )
        await c.execute(
            "INSERT INTO management.assignments(id,application,principal_id,role_key,"
            "role_version,scope_kind,school_id,school_binding_version,valid_from,"
            "expires_at,command_id,created_by) VALUES(%s,'oms',%s,"
            "'synthetic_reconciler',1,'school',%s,1,now(),"
            "now()+interval '100 years',%s,'synthetic-approval')",
            (uuid.uuid4(), operator_id, school_id, uuid.uuid4()),
        )
        await c.execute(
            "UPDATE management.principals SET policy_version=policy_version+1 WHERE id=%s",
            (operator_id,),
        )
    now = datetime.now(timezone.utc)
    actor = ManagementIdentity(
        application="oms",
        issuer="https://synthetic-issuer.example",
        subject="synthetic-operator",
        school_id=None,
        policy_version=2,
        school_binding_version=None,
        webhook_app_id=51,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )
    first_command = uuid.uuid4()
    frozen = await set_school_lifecycle_freeze(
        enterprise,
        actor,
        school_id=school_id,
        frozen=True,
        expected_version=1,
        command_id=first_command,
        reason="synthetic investigation",
        request_id="synthetic-freeze",
    )
    assert frozen.version == 2 and frozen.frozen and not frozen.replayed
    from deeptutor_enterprise.eduplus2.webhook_authority import snapshot_webhook_authority_metrics

    assert (await snapshot_webhook_authority_metrics(enterprise))["frozen_schools"] == 1
    with pytest.raises(PermissionError):
        await set_school_lifecycle_freeze(
            enterprise,
            replace(actor, subject="unassigned-operator"),
            school_id=school_id,
            frozen=False,
            expected_version=2,
            command_id=uuid.uuid4(),
            reason="unauthorized",
            request_id="synthetic-denied",
        )
    with pytest.raises(SchoolFreezeConflict):
        await set_school_lifecycle_freeze(
            enterprise,
            actor,
            school_id=school_id,
            frozen=False,
            expected_version=1,
            command_id=first_command,
            reason="different command",
            request_id="synthetic-conflict",
        )
    diagnosis = await inspect_school_lifecycle(
        enterprise, actor, school_id=school_id, request_id="synthetic-diagnosis"
    )
    assert diagnosis.frozen is True
    assert diagnosis.eligibility == "allowed"
    assert diagnosis.control_version == 2
    replay = await set_school_lifecycle_freeze(
        enterprise,
        actor,
        school_id=school_id,
        frozen=True,
        expected_version=1,
        command_id=first_command,
        reason="synthetic investigation",
        request_id="synthetic-freeze",
    )
    assert replay.version == 2 and replay.replayed
    assert (
        await _deliver(
            app,
            event_id="synthetic-freeze-reactivated-" + uuid.uuid4().hex,
            event_type="subscription.reactivated",
            status="active",
        )
    ).status_code == 204
    admin = ManagementIdentity(
        application="tms",
        issuer=actor.issuer,
        subject="synthetic-admin",
        school_id=school_id,
        policy_version=1,
        school_binding_version=1,
        webhook_app_id=51,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )
    assert await find_pending_actor_candidates(enterprise, admin) == ()
    assert (
        await _deliver(
            app,
            event_id="synthetic-freeze-suspended-" + uuid.uuid4().hex,
            event_type="subscription.suspended",
            status="suspended",
        )
    ).status_code == 204
    released = await set_school_lifecycle_freeze(
        enterprise,
        actor,
        school_id=school_id,
        frozen=False,
        expected_version=2,
        command_id=uuid.uuid4(),
        reason="synthetic review complete",
        request_id="synthetic-release",
    )
    assert released.version == 3 and not released.frozen
    assert (await snapshot_webhook_authority_metrics(enterprise))["frozen_schools"] == 0
    assert await find_pending_actor_candidates(enterprise, admin) == ()
    assert (
        await _deliver(
            app,
            event_id="synthetic-freeze-final-restore-" + uuid.uuid4().hex,
            event_type="subscription.reactivated",
            status="active",
        )
    ).status_code == 204
    assert len(await find_pending_actor_candidates(enterprise, admin)) == 1


async def test_webhook_metrics_are_aggregate_and_reflect_onboarding_and_freeze(app):
    from deeptutor_enterprise.eduplus2.webhook_authority import (
        snapshot_webhook_authority_metrics,
    )

    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    assert (
        await _deliver(
            app,
            event_id="synthetic-metric-created-" + uuid.uuid4().hex,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-admin"},
        )
    ).status_code == 204
    metrics = await snapshot_webhook_authority_metrics(enterprise)
    assert metrics["accepted_events"] == 1
    assert metrics["allowed_schools"] == 1
    assert metrics["onboarded_schools"] == 1
    assert metrics["frozen_schools"] == 0
    assert metrics["pending_actors"] == 1
    assert "10001" not in str(metrics) and "synthetic-admin" not in str(metrics)


async def test_created_actor_can_activate_first_tms_admin_before_ai_runtime_ready(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    event_id = "synthetic-admin-created-" + uuid.uuid4().hex
    response = await _deliver(
        app,
        event_id=event_id,
        event_type="subscription.created",
        status="active",
        actor={"type": "user", "user_id": "synthetic-first-admin"},
    )
    assert response.status_code == 204
    owner = enterprise.deployment.tenant_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@actor-test")) as c:
        binding = await (
            await c.execute(
                "SELECT tenant_id,version FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
    school_id = binding["tenant_id"]
    now = datetime.now(timezone.utc)
    identity = ManagementIdentity(
        application="tms",
        issuer="https://synthetic-issuer.example",
        subject="synthetic-first-admin",
        school_id=school_id,
        policy_version=1,
        school_binding_version=binding["version"],
        webhook_app_id=51,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )
    result = await activate_first_school_administrator(
        enterprise, identity, event_id=event_id, request_id="synthetic-activation-request"
    )
    assert result.replayed is False
    assert result.policy_version == 2
    replay = await activate_first_school_administrator(
        enterprise, identity, event_id=event_id, request_id="synthetic-activation-replay"
    )
    assert replay.replayed is True
    assert replay.assignment_id == result.assignment_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@actor-test")) as c:
        tenant = await (
            await c.execute(
                "SELECT bootstrap_completed,local_enabled,provisioning_status "
                "FROM enterprise.tenants WHERE id=%s",
                (school_id,),
            )
        ).fetchone()
        candidate = await (
            await c.execute(
                "SELECT status FROM eduplus2.lifecycle_actor_candidates "
                "WHERE tenant_id=%s AND event_id=%s",
                (owner, event_id),
            )
        ).fetchone()
        await c.execute("SELECT set_config('app.management_app','tms',true)")
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_id),))
        principal = await (
            await c.execute(
                "SELECT status,policy_version FROM management.principals WHERE id=%s",
                (result.principal_id,),
            )
        ).fetchone()
        assignments = await (
            await c.execute(
                "SELECT count(*) AS n FROM management.assignments WHERE school_id=%s "
                "AND role_key='school_admin' AND status='active'",
                (school_id,),
            )
        ).fetchone()
    assert tenant == {
        "bootstrap_completed": True,
        "local_enabled": False,
        "provisioning_status": "pending",
    }
    assert candidate == {"status": "consumed"}
    assert principal == {"status": "active", "policy_version": 2}
    assert assignments["n"] == 1
    async with enterprise.db.transaction(TenantScope(str(school_id), "@actor-test")) as c:
        visible_projection = await (
            await c.execute(
                "SELECT eligibility FROM eduplus2.webhook_school_state WHERE school_id=%s",
                (school_id,),
            )
        ).fetchone()
        assert visible_projection == {"eligibility": "allowed"}
        decision = await require_management_permission(
            c,
            ManagementIdentity(
                application="tms",
                issuer=identity.issuer,
                subject=identity.subject,
                school_id=school_id,
                policy_version=result.policy_version,
                school_binding_version=binding["version"],
                webhook_app_id=51,
                external_active=True,
                external_checked_at=datetime.now(timezone.utc),
                external_verified_until=datetime.now(timezone.utc) + timedelta(minutes=1),
            ),
            "tenant.tms.access",
            target_school_id=school_id,
        )
    assert decision.principal_id == result.principal_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@actor-test")) as c:
        await c.execute(
            "UPDATE eduplus2.webhook_school_state SET onboarding_event_id=NULL,"
            "onboarding_completed_at=NULL WHERE tenant_id=%s AND external_app_id=51",
            (owner,),
        )
    async with enterprise.db.transaction(TenantScope(str(school_id), "@actor-test")) as c:
        with pytest.raises(PermissionError):
            await require_management_permission(
                c,
                ManagementIdentity(
                    application="tms",
                    issuer=identity.issuer,
                    subject=identity.subject,
                    school_id=school_id,
                    policy_version=result.policy_version,
                    school_binding_version=binding["version"],
                    webhook_app_id=51,
                    external_active=True,
                    external_checked_at=datetime.now(timezone.utc),
                    external_verified_until=datetime.now(timezone.utc) + timedelta(minutes=1),
                ),
                "tenant.tms.access",
                target_school_id=school_id,
            )
    async with enterprise.db.transaction(TenantScope(str(owner), "@actor-test")) as c:
        await c.execute(
            "UPDATE eduplus2.webhook_school_state SET onboarding_event_id=%s,"
            "onboarding_completed_at=clock_timestamp() "
            "WHERE tenant_id=%s AND external_app_id=51",
            (event_id, owner),
        )
    async with enterprise.db.transaction(TenantScope(str(owner), "@actor-test")) as c:
        await c.execute(
            "UPDATE eduplus2.webhook_school_state SET eligibility='denied' "
            "WHERE tenant_id=%s AND external_app_id=51",
            (owner,),
        )
        await c.execute(
            "INSERT INTO eduplus2.webhook_school_state(tenant_id,external_tenant_id,"
            "external_app_id,school_id,binding_version,eligibility,"
            "external_subscription_id,last_event_id) "
            "VALUES(%s,10001,99,%s,1,'allowed',20001,'synthetic-other-app')",
            (owner, school_id),
        )
    async with enterprise.db.transaction(TenantScope(str(school_id), "@actor-test")) as c:
        with pytest.raises(PermissionError):
            await require_management_permission(
                c,
                ManagementIdentity(
                    application="tms",
                    issuer=identity.issuer,
                    subject=identity.subject,
                    school_id=school_id,
                    policy_version=result.policy_version,
                    school_binding_version=binding["version"],
                    webhook_app_id=51,
                    external_active=True,
                    external_checked_at=datetime.now(timezone.utc),
                    external_verified_until=datetime.now(timezone.utc) + timedelta(minutes=1),
                ),
                "tenant.tms.access",
                target_school_id=school_id,
            )


async def test_signed_client_cannot_bind_to_two_schools(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    first = await _deliver(
        app,
        event_id="synthetic-first-" + uuid.uuid4().hex,
        event_type="subscription.created",
        status="active",
        school_id=10001,
    )
    assert first.status_code == 204
    second = await _deliver(
        app,
        event_id="synthetic-cross-school-" + uuid.uuid4().hex,
        event_type="subscription.created",
        status="active",
        school_id=10002,
    )
    assert second.status_code == 409
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-authority-test")
    async with enterprise.db.transaction(scope) as c:
        count = await (
            await c.execute(
                "SELECT count(*) AS n FROM oms.school_bindings "
                "WHERE eduplus_tenant_id IN (10001,10002)"
            )
        ).fetchone()
    assert count["n"] == 1


async def test_conflicting_projected_school_rolls_back_new_event(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    first = await _deliver(
        app,
        event_id="synthetic-first-" + uuid.uuid4().hex,
        event_type="subscription.created",
        status="active",
    )
    assert first.status_code == 204
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-authority-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE eduplus2.webhook_school_state SET school_id=%s "
            "WHERE tenant_id=%s AND external_tenant_id=10001 AND external_app_id=51",
            (enterprise.deployment.tenant_id, enterprise.deployment.tenant_id),
        )
    event_id = "synthetic-conflict-" + uuid.uuid4().hex
    response = await _deliver(
        app,
        event_id=event_id,
        event_type="subscription.suspended",
        status="suspended",
    )
    assert response.status_code == 409
    async with enterprise.db.transaction(scope) as c:
        inbox = await (
            await c.execute(
                "SELECT 1 FROM eduplus2.lifecycle_inbox WHERE tenant_id=%s AND event_id=%s",
                (enterprise.deployment.tenant_id, event_id),
            )
        ).fetchone()
    assert inbox is None


async def test_webhook_digest_key_cannot_equal_signing_secret(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "s" * 48
    enterprise.eduplus2_webhook_inbox_digest_key = "s" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    response = await _deliver(
        app,
        event_id="synthetic-unsafe-key-" + uuid.uuid4().hex,
        event_type="subscription.created",
        status="active",
        signing_secret="s" * 48,
    )
    assert response.status_code == 503


async def test_distinct_events_use_durable_receipt_order_and_unknown_status_denies(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    prefix = "synthetic-order-" + uuid.uuid4().hex
    for suffix, event_type, status in (
        ("created", "subscription.created", "active"),
        ("stopped", "subscription.suspended", "suspended"),
        ("unknown", "subscription.plan_changed", "future_state"),
        ("late", "subscription.reactivated", "active"),
    ):
        response = await _deliver(
            app,
            event_id=prefix + suffix,
            event_type=event_type,
            status=status,
            subscription_id=20002 if suffix == "late" else 20001,
        )
        assert response.status_code == 204, response.text
        scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-authority-test")
        async with enterprise.db.transaction(scope) as c:
            state = await (
                await c.execute(
                    "SELECT generation,eligibility,external_subscription_id,last_event_id "
                    "FROM eduplus2.webhook_school_state WHERE tenant_id=%s "
                    "AND external_tenant_id=10001 AND external_app_id=51",
                    (enterprise.deployment.tenant_id,),
                )
            ).fetchone()
        assert state["last_event_id"] == prefix + suffix
        assert state["eligibility"] == (
            "allowed"
            if suffix in {"created", "late"}
            else ("unknown" if suffix == "unknown" else "denied")
        )
    assert state["generation"] == 4
    assert state["external_subscription_id"] == 20002


async def test_two_schools_and_code_rotation_keep_stable_bindings(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    prefix = "synthetic-schools-" + uuid.uuid4().hex
    first, second = await asyncio.gather(
        _deliver(
            app,
            event_id=prefix + "one",
            event_type="subscription.created",
            status="active",
            school_id=10001,
            client_id="client-school-one",
        ),
        _deliver(
            app,
            event_id=prefix + "two",
            event_type="subscription.created",
            status="active",
            school_id=10002,
            client_id="client-school-two",
        ),
    )
    assert (first.status_code, second.status_code) == (204, 204)
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-authority-test")
    async with enterprise.db.transaction(scope) as c:
        before = await (
            await c.execute(
                "SELECT eduplus_tenant_id,tenant_id FROM oms.school_bindings "
                "WHERE eduplus_tenant_id IN (10001,10002) ORDER BY eduplus_tenant_id"
            )
        ).fetchall()
    assert len(before) == 2
    assert before[0]["tenant_id"] != before[1]["tenant_id"]
    changed = await _deliver(
        app,
        event_id=prefix + "code-change",
        event_type="subscription.renewed",
        status="active",
        school_id=10001,
        client_id="client-school-one",
        school_code="new-display-code",
    )
    assert changed.status_code == 204
    async with enterprise.db.transaction(scope) as c:
        after = await (
            await c.execute(
                "SELECT eduplus_tenant_id,tenant_id FROM oms.school_bindings "
                "WHERE eduplus_tenant_id IN (10001,10002) ORDER BY eduplus_tenant_id"
            )
        ).fetchall()
        display_code = await (
            await c.execute(
                "SELECT school_code FROM eduplus2.webhook_school_state "
                "WHERE tenant_id=%s AND external_tenant_id=10001 AND external_app_id=51",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert after == before
    assert display_code == {"school_code": "new-display-code"}
    without_code = await _deliver(
        app,
        event_id=prefix + "missing-code",
        event_type="subscription.expiring",
        status="active",
        school_id=10001,
        client_id="client-school-one",
        school_code=None,
    )
    assert without_code.status_code == 204
    async with enterprise.db.transaction(scope) as c:
        retained_code = await (
            await c.execute(
                "SELECT school_code FROM eduplus2.webhook_school_state "
                "WHERE tenant_id=%s AND external_tenant_id=10001 AND external_app_id=51",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert retained_code == {"school_code": "new-display-code"}


async def test_non_school_is_rejected_and_signed_app_id_needs_no_static_config(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    prefix = "synthetic-invalid-" + uuid.uuid4().hex
    wrong_school = await _deliver(
        app,
        event_id=prefix + "group",
        event_type="subscription.created",
        status="active",
        tenant_type="group",
    )
    signed_app = await _deliver(
        app,
        event_id=prefix + "app",
        event_type="subscription.created",
        status="active",
        app_id=52,
    )
    assert wrong_school.status_code == 422
    assert signed_app.status_code == 204
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-authority-test")
    async with enterprise.db.transaction(scope) as c:
        rows = await (
            await c.execute(
                "SELECT count(*) AS n FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
        state = await (
            await c.execute(
                "SELECT external_app_id FROM eduplus2.webhook_school_state "
                "WHERE tenant_id=%s AND external_tenant_id=10001",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert rows["n"] == 1
    assert state["external_app_id"] == 52


async def test_webhook_projection_force_rls_is_owner_scoped(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    response = await _deliver(
        app,
        event_id="synthetic-rls-" + uuid.uuid4().hex,
        event_type="subscription.created",
        status="active",
    )
    assert response.status_code == 204
    dsn = enterprise.postgres.resolve_runtime().reveal()
    async with await psycopg.AsyncConnection.connect(dsn) as c:
        absent = await (
            await c.execute("SELECT count(*) FROM eduplus2.webhook_school_state")
        ).fetchone()
        await c.execute(
            "SELECT set_config('app.tenant_id',%s,true)",
            (str(enterprise.deployment.tenant_id),),
        )
        present = await (
            await c.execute("SELECT count(*) FROM eduplus2.webhook_school_state")
        ).fetchone()
    assert absent == (0,)
    assert present == (1,)


async def test_projection_failure_returns_retryable_503_and_rolls_back_school(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    dsn = enterprise.postgres.resolve_runtime().reveal()
    async with await psycopg.AsyncConnection.connect(dsn) as c:
        await c.execute(
            "CREATE FUNCTION eduplus2.reject_synthetic_projection() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic projection failure'; END $$"
        )
        await c.execute(
            "CREATE TRIGGER reject_synthetic_projection BEFORE INSERT "
            "ON eduplus2.webhook_school_state FOR EACH ROW "
            "EXECUTE FUNCTION eduplus2.reject_synthetic_projection()"
        )
    event_id = "synthetic-rollback-" + uuid.uuid4().hex
    try:
        response = await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
        )
        assert response.status_code == 503
        scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-authority-test")
        async with enterprise.db.transaction(scope) as c:
            inbox = await (
                await c.execute(
                    "SELECT 1 FROM eduplus2.lifecycle_inbox WHERE tenant_id=%s AND event_id=%s",
                    (enterprise.deployment.tenant_id, event_id),
                )
            ).fetchone()
            binding = await (
                await c.execute("SELECT 1 FROM oms.school_bindings WHERE eduplus_tenant_id=10001")
            ).fetchone()
        assert inbox is None
        assert binding is None
    finally:
        async with await psycopg.AsyncConnection.connect(dsn) as c:
            await c.execute(
                "DROP TRIGGER reject_synthetic_projection ON eduplus2.webhook_school_state"
            )
            await c.execute("DROP FUNCTION eduplus2.reject_synthetic_projection()")
    retried = await _deliver(
        app,
        event_id=event_id,
        event_type="subscription.created",
        status="active",
    )
    assert retried.status_code == 204


async def test_unknown_school_non_created_event_is_inbox_only(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    event_id = "synthetic-unknown-school-" + uuid.uuid4().hex
    response = await _deliver(
        app,
        event_id=event_id,
        event_type="subscription.suspended",
        status="suspended",
    )
    assert response.status_code == 204
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-authority-test")
    async with enterprise.db.transaction(scope) as c:
        inbox = await (
            await c.execute(
                "SELECT processing_status,last_error_code,processed_at IS NOT NULL AS processed "
                "FROM eduplus2.lifecycle_inbox "
                "WHERE tenant_id=%s AND event_id=%s",
                (enterprise.deployment.tenant_id, event_id),
            )
        ).fetchone()
        binding = await (
            await c.execute("SELECT 1 FROM oms.school_bindings WHERE eduplus_tenant_id=10001")
        ).fetchone()
    assert inbox == {
        "processing_status": "denied",
        "last_error_code": "school_not_bound",
        "processed": True,
    }
    assert binding is None


async def test_existing_unbound_external_school_cannot_be_duplicated(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-authority-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001' WHERE id=%s",
            (enterprise.deployment.tenant_id,),
        )
    event_id = "synthetic-unbound-" + uuid.uuid4().hex
    response = await _deliver(
        app,
        event_id=event_id,
        event_type="subscription.created",
        status="active",
    )
    assert response.status_code == 409
    async with enterprise.db.transaction(scope) as c:
        tenant_count = await (
            await c.execute(
                "SELECT count(*) AS n FROM enterprise.tenants WHERE external_tid='10001'"
            )
        ).fetchone()
        inbox = await (
            await c.execute(
                "SELECT 1 FROM eduplus2.lifecycle_inbox WHERE tenant_id=%s AND event_id=%s",
                (enterprise.deployment.tenant_id, event_id),
            )
        ).fetchone()
    assert tenant_count["n"] == 1
    assert inbox is None


@pytest.mark.parametrize(
    ("event_type", "status", "expected"),
    [
        ("subscription.suspended", "suspended", "denied"),
        ("subscription.reactivated", "active", "allowed"),
        ("subscription.terminated", "terminated", "denied"),
        ("subscription.expired", "expired", "denied"),
        ("subscription.renewed", "active", "allowed"),
        ("subscription.expiring", "active", "allowed"),
        ("subscription.plan_changed", "active", "allowed"),
    ],
)
async def test_every_subscription_event_projects_documented_status(
    app, event_type, status, expected
):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    prefix = "synthetic-eight-" + uuid.uuid4().hex
    created = await _deliver(
        app,
        event_id=prefix + "created",
        event_type="subscription.created",
        status="active",
    )
    assert created.status_code == 204
    response = await _deliver(
        app,
        event_id=prefix + "event",
        event_type=event_type,
        status=status,
    )
    assert response.status_code == 204, response.text
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-authority-test")
    async with enterprise.db.transaction(scope) as c:
        projection = await (
            await c.execute(
                "SELECT eligibility,generation FROM eduplus2.webhook_school_state "
                "WHERE tenant_id=%s AND external_tenant_id=10001 AND external_app_id=51",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert projection == {"eligibility": expected, "generation": 2}


async def test_reactivation_never_overwrites_local_school_isolation(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    prefix = "synthetic-local-isolation-" + uuid.uuid4().hex
    created = await _deliver(
        app,
        event_id=prefix + "created",
        event_type="subscription.created",
        status="active",
        actor={"type": "user", "user_id": "synthetic-sub"},
    )
    assert created.status_code == 204
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-authority-test")
    async with enterprise.db.transaction(scope) as c:
        school = await (
            await c.execute(
                "SELECT tenant_id FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school["tenant_id"]),))
        await c.execute(
            "UPDATE enterprise.tenants SET provisioning_status='ready',local_enabled=false "
            "WHERE id=%s",
            (school["tenant_id"],),
        )
    resumed = await _deliver(
        app,
        event_id=prefix + "resumed",
        event_type="subscription.reactivated",
        status="active",
    )
    assert resumed.status_code == 204
    async with enterprise.db.transaction(scope) as c:
        state = await (
            await c.execute(
                "SELECT external_eligibility,local_enabled,provisioning_status "
                "FROM enterprise.tenants WHERE id=%s",
                (school["tenant_id"],),
            )
        ).fetchone()
    assert state == {
        "external_eligibility": "allowed",
        "local_enabled": False,
        "provisioning_status": "ready",
    }
    now = datetime.now(timezone.utc)
    identity = ManagementIdentity(
        application="tms",
        issuer="https://synthetic-issuer.example",
        subject="synthetic-sub",
        school_id=school["tenant_id"],
        policy_version=1,
        school_binding_version=1,
        webhook_app_id=51,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )
    # 本地 AI 资源隔离不阻止学校侧进入 TMS 完成引导；它仍拒绝 AI 新业务。
    assert len(await find_pending_actor_candidates(enterprise, identity)) == 1


async def test_signed_webhook_drives_existing_school_login_and_session_gate(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    enterprise.eduplus2_resolver = None
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-authority-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001',external_eligibility='denied' "
            "WHERE id=%s",
            (enterprise.deployment.tenant_id,),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings(tenant_id,eduplus_tenant_id,status,"
            "verified_at,verified_by,source_ref) "
            "VALUES(%s,10001,'verified',clock_timestamp(),'synthetic-test','synthetic-proof')",
            (enterprise.deployment.tenant_id,),
        )
    prefix = "synthetic-login-gate-" + uuid.uuid4().hex
    created = await _deliver(
        app,
        event_id=prefix + "created",
        event_type="subscription.created",
        status="active",
    )
    assert created.status_code == 204
    token = await enterprise.identity.login("admin", "long-password-1", client="synthetic-one")
    assert (await enterprise.identity.authenticate(token)).tenant_id == str(
        enterprise.deployment.tenant_id
    )
    stopped = await _deliver(
        app,
        event_id=prefix + "stopped",
        event_type="subscription.suspended",
        status="suspended",
    )
    assert stopped.status_code == 204
    with pytest.raises(PermissionError):
        await enterprise.identity.authenticate(token)
    with pytest.raises(PermissionError):
        await enterprise.identity.login("admin", "long-password-1", client="synthetic-two")
    resumed = await _deliver(
        app,
        event_id=prefix + "resumed",
        event_type="subscription.reactivated",
        status="active",
    )
    assert resumed.status_code == 204
    assert await enterprise.identity.login("admin", "long-password-1", client="synthetic-three")


async def test_duplicate_webhook_rejects_unknown_inbox_status_without_db_check(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    event_id = "synthetic-inbox-status-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
        )
    ).status_code == 204
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-value-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "ALTER TABLE eduplus2.lifecycle_inbox "
            "DROP CONSTRAINT IF EXISTS lifecycle_inbox_processing_status_check"
        )
        await c.execute(
            "UPDATE eduplus2.lifecycle_inbox SET processing_status='future-status' "
            "WHERE tenant_id=%s AND event_id=%s",
            (enterprise.deployment.tenant_id, event_id),
        )

    duplicate = await _deliver(
        app,
        event_id=event_id,
        event_type="subscription.created",
        status="active",
    )
    assert duplicate.status_code == 503


async def test_actor_handoff_rejects_unknown_status_and_resolution_without_db_checks(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    event_id = "synthetic-actor-status-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=event_id,
            event_type="subscription.created",
            status="active",
            actor={"type": "user", "user_id": "synthetic-actor"},
        )
    ).status_code == 204
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-value-test")
    async with enterprise.db.transaction(scope) as c:
        binding = await (
            await c.execute(
                "SELECT tenant_id,version FROM oms.school_bindings WHERE eduplus_tenant_id=10001"
            )
        ).fetchone()
        school_id = binding["tenant_id"]
        await c.execute(
            "ALTER TABLE eduplus2.lifecycle_actor_candidates "
            "DROP CONSTRAINT IF EXISTS lifecycle_actor_candidate_status_check"
        )
        await c.execute(
            "ALTER TABLE eduplus2.lifecycle_actor_candidates "
            "DROP CONSTRAINT IF EXISTS lifecycle_actor_candidate_resolution_check"
        )
        await c.execute(
            "UPDATE eduplus2.lifecycle_actor_candidates SET status='future-status' "
            "WHERE tenant_id=%s AND event_id=%s",
            (enterprise.deployment.tenant_id, event_id),
        )
    identity = ManagementIdentity(
        application="tms",
        issuer=enterprise.eduplus2_issuer,
        subject="synthetic-actor",
        school_id=school_id,
        policy_version=1,
        school_binding_version=binding["version"],
        webhook_app_id=51,
        external_active=True,
        external_checked_at=datetime.now(timezone.utc),
        external_verified_until=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    with pytest.raises(RuntimeError, match="actor candidate status"):
        await find_pending_actor_candidates(enterprise, identity)

    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE eduplus2.lifecycle_actor_candidates "
            "SET status='consumed', resolved_at=NULL "
            "WHERE tenant_id=%s AND event_id=%s",
            (enterprise.deployment.tenant_id, event_id),
        )
    with pytest.raises(RuntimeError, match="actor candidate resolution"):
        await find_pending_actor_candidates(enterprise, identity)


async def test_webhook_projection_rejects_unknown_existing_eligibility_without_db_check(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "synthetic-webhook-secret"
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    prefix = "synthetic-projection-status-" + uuid.uuid4().hex
    assert (
        await _deliver(
            app,
            event_id=prefix + "created",
            event_type="subscription.created",
            status="active",
        )
    ).status_code == 204
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-value-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "ALTER TABLE eduplus2.webhook_school_state "
            "DROP CONSTRAINT IF EXISTS webhook_school_state_eligibility_check"
        )
        await c.execute(
            "UPDATE eduplus2.webhook_school_state SET eligibility='future-status' "
            "WHERE tenant_id=%s AND external_tenant_id=10001",
            (enterprise.deployment.tenant_id,),
        )
    response = await _deliver(
        app,
        event_id=prefix + "reactivated",
        event_type="subscription.reactivated",
        status="active",
    )
    assert response.status_code == 503
    async with enterprise.db.transaction(scope) as c:
        state = await (
            await c.execute(
                "SELECT eligibility FROM eduplus2.webhook_school_state "
                "WHERE tenant_id=%s AND external_tenant_id=10001",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert state == {"eligibility": "future-status"}


async def test_lifecycle_target_metrics_reject_unknown_eligibility_and_bad_proof_without_db_checks(
    app,
):
    from deeptutor_enterprise.eduplus2.lifecycle import snapshot_lifecycle_reconcile_metrics

    enterprise = app.state.enterprise
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@webhook-value-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "ALTER TABLE eduplus2.lifecycle_targets "
            "DROP CONSTRAINT IF EXISTS lifecycle_targets_eligibility_check"
        )
        await c.execute(
            "ALTER TABLE eduplus2.lifecycle_targets "
            "DROP CONSTRAINT IF EXISTS lifecycle_targets_check3"
        )
        await c.execute(
            "ALTER TABLE eduplus2.lifecycle_targets "
            "DROP CONSTRAINT IF EXISTS lifecycle_allowed_requires_binding_version"
        )
        await c.execute(
            "INSERT INTO eduplus2.lifecycle_targets("
            "tenant_id,external_tenant_id,external_app_id,generation,eligibility"
            ") VALUES(%s,10001,51,1,'future-status')",
            (enterprise.deployment.tenant_id,),
        )

    with pytest.raises(RuntimeError, match="lifecycle target eligibility"):
        await snapshot_lifecycle_reconcile_metrics(enterprise)

    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE eduplus2.lifecycle_targets SET eligibility='allowed',"
            "verified_client_id='', proof_checked_at=NULL, proof_expires_at=NULL,"
            "binding_version=0 WHERE tenant_id=%s AND external_tenant_id=10001",
            (enterprise.deployment.tenant_id,),
        )
    with pytest.raises(RuntimeError, match="lifecycle target proof"):
        await snapshot_lifecycle_reconcile_metrics(enterprise)
