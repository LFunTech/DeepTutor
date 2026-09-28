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
            assert hidden not in summary.text
        assert (
            await client.post("/api/v1/tms/quotas", headers=headers, json={})
        ).status_code == 405
        grants_write = await client.post("/api/v1/tms/quotas/grants", headers=headers, json={})
        assert grants_write.status_code in {401, 404}


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
