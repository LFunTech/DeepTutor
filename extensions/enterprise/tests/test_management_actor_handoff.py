"""首位管理员候选只作受控身份交接，不能据此直接授予角色。"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import uuid

from deeptutor_enterprise.eduplus2 import lifecycle
from deeptutor_enterprise.management.authorization import ManagementIdentity
from deeptutor_enterprise.scope import TenantScope
import psycopg
import pytest
from test_application import app as app

pytestmark = pytest.mark.asyncio


class ActiveResolver:
    async def resolve_client(self, client_id, *, expected_tenant_id=None):
        assert (client_id, expected_tenant_id) == ("synthetic-school-client", 10001)
        return {
            "client_id": client_id,
            "external_tenant_id": "10001",
            "external_app_id": "51",
            "status": "active",
            "tenant_status": "active",
            "app_status": "active",
            "subscription_status": "active",
            "version": "synthetic-opaque",
        }


async def _seed_candidate(enterprise):
    enterprise.eduplus2_issuer = "https://synthetic-issuer.example"
    enterprise.eduplus2_resolver = ActiveResolver()
    enterprise.eduplus2_webhook_app_id = 51
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@handoff-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001',"
            "external_eligibility='denied' WHERE id=%s",
            (enterprise.deployment.tenant_id,),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings(tenant_id,eduplus_tenant_id,status,"
            "verified_at,verified_by,source_ref) "
            "VALUES(%s,10001,'verified',now(),'synthetic-review','synthetic-proof')",
            (enterprise.deployment.tenant_id,),
        )
    event = lifecycle.parse_lifecycle_event(
        {
            "event_id": "synthetic-handoff-created",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
            "actor": {"type": "user", "user_id": "synthetic-keycloak-sub"},
        },
        "subscription.created",
        app_id=51,
        digest_key="d" * 48,
    )
    await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    assert await lifecycle.reconcile_lifecycle_target(
        enterprise, external_tenant_id=10001, external_app_id=51
    ) == "allowed"
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="tms",
        issuer="https://synthetic-issuer.example",
        subject="synthetic-keycloak-sub",
        school_id=enterprise.deployment.tenant_id,
        policy_version=1,
        school_binding_version=1,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )


async def test_pending_actor_handoff_requires_trusted_same_school_identity(app):
    from deeptutor_enterprise.management.actor_handoff import find_pending_actor_candidates

    enterprise = app.state.enterprise
    identity = await _seed_candidate(enterprise)
    candidates = await find_pending_actor_candidates(enterprise, identity)
    assert [(item.event_id, item.subscription_id, item.school_id) for item in candidates] == [
        ("synthetic-handoff-created", 20001, enterprise.deployment.tenant_id)
    ]
    for mismatch in (
        replace(identity, issuer="https://wrong-issuer.example"),
        replace(identity, subject="another-subject"),
        replace(identity, school_id=uuid.uuid4()),
        replace(identity, school_binding_version=2),
    ):
        assert await find_pending_actor_candidates(enterprise, mismatch) == ()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@handoff-test")
    async with enterprise.db.transaction(scope) as c:
        principal_count = await (
            await c.execute("SELECT count(*) AS count FROM management.principals")
        ).fetchone()
    assert principal_count["count"] == 0


async def test_pending_actor_handoff_denies_expired_proof_and_receiver_off(app):
    from deeptutor_enterprise.management.actor_handoff import find_pending_actor_candidates

    enterprise = app.state.enterprise
    identity = await _seed_candidate(enterprise)
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@handoff-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE eduplus2.lifecycle_targets SET proof_expires_at=clock_timestamp() "
            "WHERE tenant_id=%s",
            (enterprise.deployment.tenant_id,),
        )
    assert await find_pending_actor_candidates(enterprise, identity) == ()
    enterprise.eduplus2_lifecycle_receiver_enabled = False
    assert await find_pending_actor_candidates(enterprise, identity) == ()


async def test_pending_actor_handoff_denies_untrusted_or_stale_identity(app):
    from deeptutor_enterprise.management.actor_handoff import find_pending_actor_candidates

    enterprise = app.state.enterprise
    identity = await _seed_candidate(enterprise)
    for mismatch in (
        replace(identity, application="oms", school_id=None, school_binding_version=None),
        replace(identity, external_active=False),
        replace(identity, external_checked_at=datetime.now(timezone.utc) - timedelta(minutes=1)),
    ):
        assert await find_pending_actor_candidates(enterprise, mismatch) == ()
    enterprise.eduplus2_issuer = "https://changed-issuer.example"
    assert await find_pending_actor_candidates(enterprise, identity) == ()


@pytest.mark.parametrize("terminal_status", ["consumed", "revoked"])
async def test_pending_actor_handoff_never_revives_terminal_event(app, terminal_status):
    from deeptutor_enterprise.management.actor_handoff import find_pending_actor_candidates

    enterprise = app.state.enterprise
    identity = await _seed_candidate(enterprise)
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@handoff-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE eduplus2.lifecycle_actor_candidates "
            "SET status=%s,resolved_at=clock_timestamp() "
            "WHERE tenant_id=%s AND event_id='synthetic-handoff-created'",
            (terminal_status, enterprise.deployment.tenant_id),
        )
    assert await find_pending_actor_candidates(enterprise, identity) == ()
    assert await lifecycle.reconcile_lifecycle_target(
        enterprise, external_tenant_id=10001, external_app_id=51
    ) == "allowed"
    assert await find_pending_actor_candidates(enterprise, identity) == ()
    with pytest.raises(psycopg.errors.CheckViolation):
        async with enterprise.db.transaction(scope) as c:
            await c.execute(
                "UPDATE eduplus2.lifecycle_actor_candidates "
                "SET status='pending_verification',resolved_at=NULL "
                "WHERE tenant_id=%s AND event_id='synthetic-handoff-created'",
                (enterprise.deployment.tenant_id,),
            )


async def test_pending_actor_handoff_denies_school_binding_reverification(app):
    from deeptutor_enterprise.management.actor_handoff import find_pending_actor_candidates

    enterprise = app.state.enterprise
    identity = await _seed_candidate(enterprise)
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@handoff-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE oms.school_bindings SET status='revoked',verified_at=NULL,"
            "version=version+1 "
            "WHERE tenant_id=%s",
            (identity.school_id,),
        )
    assert await find_pending_actor_candidates(enterprise, identity) == ()
