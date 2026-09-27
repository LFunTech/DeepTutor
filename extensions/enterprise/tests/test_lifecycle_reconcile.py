"""Webhook 入队后的在线当前态核验；全部使用合成学校。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import uuid

from deeptutor_enterprise.eduplus2 import lifecycle
from deeptutor_enterprise.scope import TenantScope
import psycopg
import pytest
from test_application import app as app

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("event_type", "signed_app_id"),
    [
        ("subscription.unknown", 51),
        ("subscription.created", 0),
    ],
)
async def test_real_event_whitelist_and_signed_app_id_validation(event_type, signed_app_id):
    with pytest.raises(lifecycle.LifecycleInvalid):
        lifecycle.parse_lifecycle_event(
            {
                "event_id": "synthetic-invalid-event",
                "tenant": {"id": 10001},
                "app": {"id": signed_app_id},
                "subscription": {"id": 20001, "status": "active"},
            },
            event_type,
            digest_key="d" * 48,
        )


@pytest.mark.parametrize("actor", [None, {"type": "system"}, {"type": "user"}])
async def test_missing_or_non_user_actor_cannot_form_bootstrap_subject(actor):
    event = lifecycle.parse_lifecycle_event(
        {
            "event_id": "synthetic-no-actor",
            "tenant": {"id": 10001},
            "app": {"id": 51},
            "subscription": {"id": 20001, "status": "active"},
            "actor": actor,
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    assert event.actor_subject == ""


async def test_lifecycle_inbox_owner_cannot_bypass_scope_without_tenant_guc(app):
    enterprise = app.state.enterprise
    event = lifecycle.parse_lifecycle_event(
        {
            "event_id": "synthetic-force-rls-event",
            "tenant": {"id": 10001},
            "app": {"id": 51},
            "subscription": {"id": 20001, "status": "active"},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    dsn = enterprise.postgres.resolve_runtime().reveal()
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        count = await (
            await connection.execute("SELECT count(*) FROM eduplus2.lifecycle_inbox")
        ).fetchone()
    assert count == (0,)


class ActiveResolver:
    async def resolve_client(self, client_id: str, *, expected_tenant_id=None):
        assert client_id == "synthetic-school-client"
        assert expected_tenant_id == 10001
        return {
            "client_id": client_id,
            "external_tenant_id": "10001",
            "external_app_id": "51",
            "status": "active",
            "tenant_status": "active",
            "app_status": "active",
            "subscription_status": "active",
            "version": "opaque-sha256-not-sortable",
        }


async def test_webhook_projection_allows_verified_bound_school_without_resolver(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_resolver = None
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
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
            "event": "subscription.created",
            "event_id": "synthetic-reconcile-event-1",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    from deeptutor_enterprise.eduplus2.webhook_authority import ingest_authoritative_webhook

    assert await ingest_authoritative_webhook(enterprise, event, delivery_timestamp=1) == "allowed"

    async with enterprise.db.transaction(scope) as c:
        projection = await (
            await c.execute(
                "SELECT eligibility,generation,binding_version "
                "FROM eduplus2.webhook_school_state WHERE tenant_id=%s "
                "AND external_tenant_id=10001 AND external_app_id=51",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
        tenant = await (
            await c.execute(
                "SELECT external_eligibility FROM enterprise.tenants WHERE id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert projection == {"eligibility": "allowed", "generation": 1, "binding_version": 1}
    assert tenant["external_eligibility"] == "allowed"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    token = await enterprise.identity.login("admin", "long-password-1", client="synthetic-client")
    assert (await enterprise.identity.authenticate(token)).tenant_id == str(
        enterprise.deployment.tenant_id
    )
    second_app = lifecycle.parse_lifecycle_event(
        {
            "event": "subscription.created",
            "event_id": "synthetic-reconcile-event-2",
            "tenant": {"id": 10001},
            "app": {"id": 52, "client_id": "synthetic-other-client"},
            "subscription": {"id": 20002, "status": "active"},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    assert await ingest_authoritative_webhook(enterprise, second_app, delivery_timestamp=2) == "allowed"
    with pytest.raises(PermissionError, match="school lifecycle unavailable"):
        await enterprise.identity.authenticate(token)


async def test_new_notification_invalidates_existing_school_allowance_before_ack(app):
    enterprise = app.state.enterprise
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001',"
            "external_eligibility='allowed' WHERE id=%s",
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
            "event": "subscription.suspended",
            "event_id": "synthetic-invalidation-event-1",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "suspended"},
        },
        "subscription.suspended",
        digest_key="d" * 48,
    )
    await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    async with enterprise.db.transaction(scope) as c:
        tenant = await (
            await c.execute(
                "SELECT external_eligibility FROM enterprise.tenants WHERE id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert tenant["external_eligibility"] == "denied"


async def test_new_notification_invalidates_client_resolve_cache_before_ack(app):
    enterprise = app.state.enterprise
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "INSERT INTO eduplus2.resolve_cache(tenant_id,client_id,resolved,expires_at) "
            "VALUES(%s,'synthetic-school-client','{}'::jsonb,now()+interval '1 hour')",
            (enterprise.deployment.tenant_id,),
        )
    event = lifecycle.parse_lifecycle_event(
        {
            "event_id": "synthetic-cache-invalidation-event",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "suspended"},
        },
        "subscription.suspended",
        digest_key="d" * 48,
    )
    await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    async with enterprise.db.transaction(scope) as c:
        cached = await (
            await c.execute(
                "SELECT count(*) AS count FROM eduplus2.resolve_cache "
                "WHERE tenant_id=%s AND client_id='synthetic-school-client'",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert cached["count"] == 0


async def test_expired_online_proof_blocks_existing_session_and_new_login(app):
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="synthetic-client")
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001',"
            "external_eligibility='allowed' WHERE id=%s",
            (enterprise.deployment.tenant_id,),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings(tenant_id,eduplus_tenant_id,status,"
            "verified_at,verified_by,source_ref) "
            "VALUES(%s,10001,'verified',now(),'synthetic-review','synthetic-proof')",
            (enterprise.deployment.tenant_id,),
        )
        await c.execute(
            "INSERT INTO eduplus2.lifecycle_targets(tenant_id,external_tenant_id,"
            "external_app_id,eligibility,verified_client_id,proof_checked_at,proof_expires_at,"
            "binding_version) "
            "VALUES(%s,10001,51,'allowed','synthetic-school-client',"
            "now()-interval '2 minutes',now()-interval '1 minute',1)",
            (enterprise.deployment.tenant_id,),
        )
    with pytest.raises(PermissionError):
        await enterprise.identity.authenticate(token)
    with pytest.raises(PermissionError):
        await enterprise.identity.login("admin", "long-password-1", client="synthetic-client-2")


async def test_binding_reverification_cannot_reuse_previous_webhook_projection(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_resolver = None
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
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
            "event_id": "synthetic-reverify-created",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    from deeptutor_enterprise.eduplus2.webhook_authority import ingest_authoritative_webhook

    assert await ingest_authoritative_webhook(enterprise, event, delivery_timestamp=1) == "allowed"
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    await enterprise.identity.login("admin", "long-password-1", client="synthetic-client")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE oms.school_bindings SET status='revoked',verified_at=NULL,"
            "verified_by=NULL,version=version+1 "
            "WHERE tenant_id=%s",
            (enterprise.deployment.tenant_id,),
        )
        await c.execute(
            "UPDATE oms.school_bindings SET status='verified',verified_at=now(),"
            "verified_by='synthetic-rereview',version=version+1 "
            "WHERE tenant_id=%s",
            (enterprise.deployment.tenant_id,),
        )
    with pytest.raises(PermissionError):
        await enterprise.identity.login("admin", "long-password-1", client="synthetic-client-2")


async def test_disabling_receiver_cannot_reenable_expired_external_school(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_lifecycle_receiver_enabled = False
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001',"
            "external_eligibility='allowed' WHERE id=%s",
            (enterprise.deployment.tenant_id,),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings(tenant_id,eduplus_tenant_id,status,"
            "verified_at,verified_by,source_ref) "
            "VALUES(%s,10001,'verified',now(),'synthetic-review','synthetic-proof')",
            (enterprise.deployment.tenant_id,),
        )
        await c.execute(
            "INSERT INTO eduplus2.lifecycle_targets(tenant_id,external_tenant_id,"
            "external_app_id,eligibility,verified_client_id,proof_checked_at,proof_expires_at,"
            "binding_version) "
            "VALUES(%s,10001,51,'allowed','synthetic-school-client',"
            "now()-interval '2 minutes',now()-interval '1 minute',1)",
            (enterprise.deployment.tenant_id,),
        )
    with pytest.raises(PermissionError):
        await enterprise.identity.login("admin", "long-password-1", client="synthetic-client")


async def test_lifecycle_denial_does_not_prevent_receiver_process_from_starting(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_eligibility='denied' WHERE id=%s",
            (enterprise.deployment.tenant_id,),
        )
    await enterprise.close()
    from deeptutor_enterprise.bootstrap import Enterprise

    restarted = Enterprise(enterprise.deployment)
    restarted.eduplus2_lifecycle_receiver_enabled = True
    try:
        await restarted.start()
        assert restarted.container is not None
    finally:
        if restarted.container is not None:
            await restarted.close()


async def test_external_school_process_starts_even_if_receiver_temporarily_off(app):
    enterprise = app.state.enterprise
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001',"
            "external_eligibility='denied' WHERE id=%s",
            (enterprise.deployment.tenant_id,),
        )
    await enterprise.close()
    from deeptutor_enterprise.bootstrap import Enterprise

    restarted = Enterprise(enterprise.deployment)
    restarted.eduplus2_lifecycle_receiver_enabled = False
    try:
        await restarted.start()
        assert restarted.container is not None
    finally:
        if restarted.container is not None:
            await restarted.close()


async def test_online_outage_keeps_school_denied_and_persists_retry(app):
    enterprise = app.state.enterprise

    class OfflineResolver:
        async def resolve_client(self, client_id, *, expected_tenant_id=None):
            raise TimeoutError("synthetic timeout")

    enterprise.eduplus2_resolver = OfflineResolver()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001',"
            "external_eligibility='allowed' WHERE id=%s",
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
            "event": "subscription.expired",
            "event_id": "synthetic-timeout-event-1",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "expired"},
        },
        "subscription.expired",
        digest_key="d" * 48,
    )
    await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    assert (
        await lifecycle.reconcile_lifecycle_target(
            enterprise, external_tenant_id=10001, external_app_id=51
        )
        == "unknown"
    )
    async with enterprise.db.transaction(scope) as c:
        target = await (
            await c.execute(
                "SELECT eligibility,retry_count,last_error_code FROM eduplus2.lifecycle_targets "
                "WHERE tenant_id=%s AND external_tenant_id=10001 AND external_app_id=51",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
        tenant = await (
            await c.execute(
                "SELECT external_eligibility FROM enterprise.tenants WHERE id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert target == {
        "eligibility": "unknown",
        "retry_count": 1,
        "last_error_code": "online_unavailable",
    }
    assert tenant["external_eligibility"] == "denied"


async def test_reconcile_batch_processes_pending_bound_school(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_resolver = ActiveResolver()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
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
            "event": "subscription.created",
            "event_id": "synthetic-batch-event-1",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    process = getattr(lifecycle, "reconcile_due_lifecycle_targets", None)
    assert callable(process), "缺少持久队列定期对账入口"
    assert await process(enterprise) == 1
    async with enterprise.db.transaction(scope) as c:
        tenant = await (
            await c.execute(
                "SELECT external_eligibility FROM enterprise.tenants WHERE id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert tenant["external_eligibility"] == "allowed"


async def test_receiver_restart_retains_atomic_webhook_projection_without_resolver(app):
    enterprise = app.state.enterprise
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
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
            "event": "subscription.created",
            "event_id": "synthetic-restart-event-1",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    from deeptutor_enterprise.eduplus2.webhook_authority import ingest_authoritative_webhook

    assert await ingest_authoritative_webhook(enterprise, event, delivery_timestamp=1) == "allowed"
    await enterprise.close()
    from deeptutor_enterprise.bootstrap import Enterprise

    restarted = Enterprise(enterprise.deployment)
    restarted.eduplus2_lifecycle_receiver_enabled = True
    restarted.eduplus2_resolver = None
    try:
        await restarted.start()
        async with restarted.db.transaction(scope) as c:
            tenant = await (
                await c.execute(
                    "SELECT external_eligibility FROM enterprise.tenants WHERE id=%s",
                    (enterprise.deployment.tenant_id,),
                )
            ).fetchone()
            state = await (
                await c.execute(
                    "SELECT eligibility,generation FROM eduplus2.webhook_school_state "
                    "WHERE tenant_id=%s AND external_tenant_id=10001 AND external_app_id=51",
                    (enterprise.deployment.tenant_id,),
                )
            ).fetchone()
        assert tenant["external_eligibility"] == "allowed"
        assert state == {"eligibility": "allowed", "generation": 1}
    finally:
        await restarted.close()


async def test_periodic_scan_recovers_missed_webhook_for_verified_registration(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_resolver = ActiveResolver()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
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
        await c.execute(
            "INSERT INTO eduplus2.external_client_registrations(tenant_id,id,client_id,"
            "external_tenant_id,external_app_id,internal_tenant_id,registered_by_surface) "
            "VALUES(%s,%s,'synthetic-school-client','10001','51',%s,'test_seed')",
            (enterprise.deployment.tenant_id, uuid.uuid4(), enterprise.deployment.tenant_id),
        )
    assert await lifecycle.reconcile_due_lifecycle_targets(enterprise) == 1
    async with enterprise.db.transaction(scope) as c:
        tenant = await (
            await c.execute(
                "SELECT external_eligibility FROM enterprise.tenants WHERE id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert tenant["external_eligibility"] == "allowed"


async def test_created_actor_handoff_remains_pending_without_current_subscription_proof(
    monkeypatch, app
):
    enterprise = app.state.enterprise
    monkeypatch.setenv("DT_EDUPLUS2_OIDC_ISSUER", "https://synthetic-issuer.example")
    enterprise._configure_eduplus2_from_env()
    enterprise.eduplus2_resolver = ActiveResolver()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001',"
            "external_eligibility='denied',bootstrap_completed=false WHERE id=%s",
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
            "event": "subscription.created",
            "event_id": "synthetic-actor-event-1",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
            "actor": {"type": "user", "user_id": "synthetic-keycloak-sub"},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    assert (
        await lifecycle.reconcile_lifecycle_target(
            enterprise, external_tenant_id=10001, external_app_id=51
        )
        == "allowed"
    )
    async with enterprise.db.transaction(scope) as c:
        candidates = await (
            await c.execute(
                "SELECT school_id,external_subscription_id,actor_issuer,actor_subject,status "
                "FROM eduplus2.lifecycle_actor_candidates WHERE tenant_id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchall()
        principals = await (
            await c.execute("SELECT count(*) AS n FROM management.principals")
        ).fetchone()
    assert candidates == [
        {
            "school_id": enterprise.deployment.tenant_id,
            "external_subscription_id": 20001,
            "actor_issuer": "https://synthetic-issuer.example",
            "actor_subject": "synthetic-keycloak-sub",
            "status": "pending_verification",
        }
    ]
    assert principals["n"] == 0


async def test_late_created_actor_and_system_events_never_activate_admin(monkeypatch, app):
    enterprise = app.state.enterprise
    monkeypatch.setenv("DT_EDUPLUS2_OIDC_ISSUER", "https://synthetic-issuer.example")
    enterprise._configure_eduplus2_from_env()
    enterprise.eduplus2_resolver = ActiveResolver()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001',"
            "external_eligibility='denied',bootstrap_completed=false WHERE id=%s",
            (enterprise.deployment.tenant_id,),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings(tenant_id,eduplus_tenant_id,status,"
            "verified_at,verified_by,source_ref) "
            "VALUES(%s,10001,'verified',now(),'synthetic-review','synthetic-proof')",
            (enterprise.deployment.tenant_id,),
        )
    events = []
    for event_id, subscription_id, actor in (
        ("synthetic-current-created", 20002, {"type": "user", "user_id": "current-subject"}),
        ("synthetic-late-old-created", 20001, {"type": "user", "user_id": "old-subject"}),
        ("synthetic-system-created", 20002, {"type": "system"}),
        ("synthetic-null-created", 20002, None),
    ):
        event = lifecycle.parse_lifecycle_event(
            {
                "event_id": event_id,
                "tenant": {"id": 10001},
                "app": {"id": 51, "client_id": "synthetic-school-client"},
                "subscription": {"id": subscription_id, "status": "active"},
                "actor": actor,
            },
            "subscription.created",
            digest_key="d" * 48,
        )
        events.append(event)
        await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    assert (
        await lifecycle.ingest_lifecycle_event(enterprise, events[1], delivery_timestamp=2)
        == "duplicate"
    )
    assert (
        await lifecycle.reconcile_lifecycle_target(
            enterprise, external_tenant_id=10001, external_app_id=51
        )
        == "allowed"
    )
    async with enterprise.db.transaction(scope) as c:
        candidates = await (
            await c.execute(
                "SELECT external_subscription_id,actor_subject,status "
                "FROM eduplus2.lifecycle_actor_candidates WHERE tenant_id=%s "
                "ORDER BY external_subscription_id,actor_subject",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchall()
        principals = await (
            await c.execute("SELECT count(*) AS n FROM management.principals")
        ).fetchone()
    assert candidates == [
        {
            "external_subscription_id": 20001,
            "actor_subject": "old-subject",
            "status": "pending_verification",
        },
        {
            "external_subscription_id": 20002,
            "actor_subject": "current-subject",
            "status": "pending_verification",
        },
    ]
    assert principals["n"] == 0


async def test_lifecycle_proof_ttl_is_bounded_and_configured(monkeypatch, app):
    enterprise = app.state.enterprise
    monkeypatch.setenv("DT_EDUPLUS2_LIFECYCLE_PROOF_TTL_SECONDS", "7")
    enterprise._configure_eduplus2_from_env()
    assert enterprise.eduplus2_lifecycle_proof_ttl_seconds == 7
    monkeypatch.setenv("DT_EDUPLUS2_LIFECYCLE_PROOF_TTL_SECONDS", "99999")
    enterprise._configure_eduplus2_from_env()
    assert enterprise.eduplus2_lifecycle_proof_ttl_seconds == 60


async def test_lifecycle_reconcile_metrics_aggregate_without_school_identifiers(app):
    enterprise = app.state.enterprise
    baseline = await lifecycle.snapshot_lifecycle_reconcile_metrics(enterprise)
    assert baseline == {
        "allowed": 0,
        "expired_proofs": 0,
        "unknown": 0,
        "denied": 0,
        "pending_binding": 0,
        "pending_reconcile": 0,
        "retry": 0,
        "pending_actor_candidates": 0,
    }
    event = lifecycle.parse_lifecycle_event(
        {
            "event_id": "synthetic-metrics-event",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    pending = await lifecycle.snapshot_lifecycle_reconcile_metrics(enterprise)
    assert pending["unknown"] == 1
    assert pending["pending_binding"] == 1
    assert all(type(value) is int for value in pending.values())
    assert "10001" not in str(pending) and "20001" not in str(pending)


async def test_lifecycle_worker_refreshes_internal_metrics(monkeypatch, app):
    from deeptutor_enterprise.eduplus2 import webhook_authority

    enterprise = app.state.enterprise
    sampled = asyncio.Event()

    async def snapshot(_enterprise):
        assert _enterprise is enterprise
        sampled.set()
        return {"unknown_schools": 3, "legacy_pending_events": 1}

    monkeypatch.setattr(webhook_authority, "snapshot_webhook_authority_metrics", snapshot)
    worker = asyncio.create_task(enterprise._webhook_monitor_loop())
    try:
        await asyncio.wait_for(sampled.wait(), timeout=2)
        await asyncio.sleep(0)
        assert enterprise.webhook_metrics["monitor_failures"] == 0
        assert enterprise.webhook_metrics["unknown_schools"] == 3
        assert enterprise.webhook_metrics["legacy_pending_events"] == 1
    finally:
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker


@pytest.mark.parametrize(
    "missing",
    ["signing_secret", "digest_key", "issuer"],
)
async def test_enabled_lifecycle_receiver_rejects_missing_runtime_contract(
    monkeypatch, app, missing
):
    enterprise = app.state.enterprise
    enterprise.eduplus2_resolver = ActiveResolver()
    values = {
        "DT_EDUPLUS2_LIFECYCLE_RECEIVER_ENABLED": "true",
        "DT_EDUPLUS2_WEBHOOK_SECRET": "synthetic-signing-secret",
        "DT_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY": "d" * 48,
        "DT_EDUPLUS2_OIDC_ISSUER": "https://synthetic-issuer.example",
    }
    missing_key = {
        "signing_secret": "DT_EDUPLUS2_WEBHOOK_SECRET",
        "digest_key": "DT_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY",
        "issuer": "DT_EDUPLUS2_OIDC_ISSUER",
    }.get(missing)
    for key, value in values.items():
        if key != missing_key:
            monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match="lifecycle receiver configuration"):
        enterprise._configure_eduplus2_from_env()


async def test_enabled_lifecycle_receiver_rejects_digest_key_reuse(monkeypatch, app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_resolver = ActiveResolver()
    for key, value in {
        "DT_EDUPLUS2_LIFECYCLE_RECEIVER_ENABLED": "true",
        "DT_EDUPLUS2_WEBHOOK_SECRET": "synthetic-shared-secret" * 3,
        "DT_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY": "synthetic-shared-secret" * 3,
        "DT_EDUPLUS2_OIDC_ISSUER": "https://synthetic-issuer.example",
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match="lifecycle receiver configuration"):
        enterprise._configure_eduplus2_from_env()


async def test_enabled_lifecycle_receiver_accepts_complete_independent_contract(monkeypatch, app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_resolver = ActiveResolver()
    for key, value in {
        "DT_EDUPLUS2_LIFECYCLE_RECEIVER_ENABLED": "true",
        "DT_EDUPLUS2_WEBHOOK_SECRET": "synthetic-signing-secret",
        "DT_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY": "d" * 48,
        "DT_EDUPLUS2_OIDC_ISSUER": "https://synthetic-issuer.example",
    }.items():
        monkeypatch.setenv(key, value)
    enterprise._configure_eduplus2_from_env()
    assert enterprise.eduplus2_lifecycle_receiver_enabled
    assert not hasattr(enterprise, "eduplus2_webhook_app_id")


async def test_lifecycle_receiver_requires_bound_school_and_explicit_secrets(monkeypatch, app):
    enterprise = app.state.enterprise
    monkeypatch.setenv("SYNTHETIC_LIFECYCLE_DIGEST_KEY", "d" * 48)
    monkeypatch.setenv("SYNTHETIC_PREVIOUS_WEBHOOK_KEY", "old-synthetic-secret")
    monkeypatch.setenv(
        "DT_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY_REF", "env:SYNTHETIC_LIFECYCLE_DIGEST_KEY"
    )
    monkeypatch.setenv(
        "DT_EDUPLUS2_WEBHOOK_PREVIOUS_SECRET_REF", "env:SYNTHETIC_PREVIOUS_WEBHOOK_KEY"
    )
    monkeypatch.setenv("DT_EDUPLUS2_WEBHOOK_PREVIOUS_UNTIL", "1234567890")
    enterprise._configure_eduplus2_from_env()
    assert not hasattr(enterprise, "eduplus2_webhook_app_id")
    assert enterprise.eduplus2_webhook_inbox_digest_key == "d" * 48
    assert enterprise.eduplus2_webhook_previous_secret == "old-synthetic-secret"
    assert enterprise.eduplus2_webhook_previous_until == 1234567890
    with pytest.raises(RuntimeError):
        lifecycle.parse_lifecycle_event(
            {
                "event_id": "synthetic-missing-digest",
                "tenant": {"id": 10001},
                "app": {"id": 51},
                "subscription": {"id": 20001, "status": "active"},
            },
            "subscription.created",
            digest_key="",
        )

    enterprise.eduplus2_lifecycle_receiver_enabled = True
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001',"
            "external_eligibility='allowed' WHERE id=%s",
            (enterprise.deployment.tenant_id,),
        )
    with pytest.raises(PermissionError):
        await enterprise.identity.login("admin", "long-password-1", client="synthetic-client")


async def test_inbox_integrity_key_must_not_reuse_webhook_signing_secret(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_webhook_secret = "d" * 48
    enterprise.eduplus2_webhook_inbox_digest_key = "d" * 48
    event = lifecycle.parse_lifecycle_event(
        {
            "event": "subscription.created",
            "event_id": "synthetic-shared-secret-event",
            "tenant": {"id": 10001},
            "app": {"id": 51},
            "subscription": {"id": 20001, "status": "active"},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    with pytest.raises(RuntimeError):
        await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)


async def test_reconcile_serializes_same_school_across_workers(app):
    enterprise = app.state.enterprise
    entered = asyncio.Event()
    release = asyncio.Event()

    class DelayedResolver(ActiveResolver):
        async def resolve_client(self, client_id, *, expected_tenant_id=None):
            entered.set()
            await release.wait()
            return await super().resolve_client(client_id, expected_tenant_id=expected_tenant_id)

    enterprise.eduplus2_resolver = DelayedResolver()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
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
            "event": "subscription.created",
            "event_id": "synthetic-concurrent-event-1",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    first = asyncio.create_task(
        lifecycle.reconcile_lifecycle_target(
            enterprise, external_tenant_id=10001, external_app_id=51
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        second = await asyncio.wait_for(
            lifecycle.reconcile_lifecycle_target(
                enterprise, external_tenant_id=10001, external_app_id=51
            ),
            timeout=1,
        )
        assert second == "busy"
    finally:
        release.set()
    assert await first == "allowed"


async def test_new_event_fences_inflight_online_result(app):
    enterprise = app.state.enterprise
    entered = asyncio.Event()
    release = asyncio.Event()

    class DelayedResolver(ActiveResolver):
        async def resolve_client(self, client_id, *, expected_tenant_id=None):
            entered.set()
            await release.wait()
            return await super().resolve_client(client_id, expected_tenant_id=expected_tenant_id)

    enterprise.eduplus2_resolver = DelayedResolver()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
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

    def event(event_id, event_type, status):
        return lifecycle.parse_lifecycle_event(
            {
                "event": event_type,
                "event_id": event_id,
                "tenant": {"id": 10001},
                "app": {"id": 51, "client_id": "synthetic-school-client"},
                "subscription": {"id": 20001, "status": status},
            },
            event_type,
            digest_key="d" * 48,
        )

    await lifecycle.ingest_lifecycle_event(
        enterprise,
        event("synthetic-race-1", "subscription.created", "active"),
        delivery_timestamp=1,
    )
    first = asyncio.create_task(
        lifecycle.reconcile_lifecycle_target(
            enterprise, external_tenant_id=10001, external_app_id=51
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await lifecycle.ingest_lifecycle_event(
            enterprise,
            event("synthetic-race-2", "subscription.suspended", "suspended"),
            delivery_timestamp=2,
        )
    finally:
        release.set()
    assert await first == "stale"
    async with enterprise.db.transaction(scope) as c:
        target = await (
            await c.execute(
                "SELECT generation,eligibility FROM eduplus2.lifecycle_targets "
                "WHERE tenant_id=%s AND external_tenant_id=10001 AND external_app_id=51",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert target == {"generation": 2, "eligibility": "unknown"}


async def test_seventeen_historical_clients_do_not_permanently_block_current_proof(app):
    enterprise = app.state.enterprise

    class MultiActiveResolver:
        async def resolve_client(self, client_id, *, expected_tenant_id=None):
            return {
                "client_id": client_id,
                "external_tenant_id": "10001",
                "external_app_id": "51",
                "status": "active",
                "tenant_status": "active",
                "app_status": "active",
                "subscription_status": "active",
                "version": "opaque",
            }

    enterprise.eduplus2_resolver = MultiActiveResolver()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
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
    for index in range(17):
        event = lifecycle.parse_lifecycle_event(
            {
                "event": "subscription.renewed",
                "event_id": f"synthetic-many-clients-{index}",
                "tenant": {"id": 10001},
                "app": {"id": 51, "client_id": f"synthetic-client-{index}"},
                "subscription": {"id": 20001, "status": "active"},
            },
            "subscription.renewed",
            digest_key="d" * 48,
        )
        await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    assert (
        await lifecycle.reconcile_lifecycle_target(
            enterprise, external_tenant_id=10001, external_app_id=51
        )
        == "allowed"
    )


async def test_webhook_client_conflicting_with_verified_school_binding_is_rejected(app):
    enterprise = app.state.enterprise
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001' WHERE id=%s",
            (enterprise.deployment.tenant_id,),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings(tenant_id,eduplus_tenant_id,status,"
            "verified_at,verified_by,source_ref) "
            "VALUES(%s,10001,'verified',now(),'synthetic-review','synthetic-proof')",
            (enterprise.deployment.tenant_id,),
        )
        await c.execute(
            "INSERT INTO eduplus2.external_client_registrations(tenant_id,id,client_id,"
            "external_tenant_id,external_app_id,internal_tenant_id,registered_by_surface) "
            "VALUES(%s,%s,'synthetic-school-client','10001','51',%s,'test_seed')",
            (enterprise.deployment.tenant_id, uuid.uuid4(), enterprise.deployment.tenant_id),
        )
    event = lifecycle.parse_lifecycle_event(
        {
            "event": "subscription.created",
            "event_id": "synthetic-conflicting-school-event",
            "tenant": {"id": 10002},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    with pytest.raises(lifecycle.LifecycleConflict):
        await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    async with enterprise.db.transaction(scope) as c:
        count = await (
            await c.execute(
                "SELECT count(*) AS n FROM eduplus2.lifecycle_inbox WHERE tenant_id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert count["n"] == 0


async def test_old_suspension_notification_uses_current_active_resolve(app):
    enterprise = app.state.enterprise
    enterprise.eduplus2_resolver = ActiveResolver()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001',"
            "external_eligibility='denied',local_enabled=false WHERE id=%s",
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
            "event": "subscription.suspended",
            "event_id": "synthetic-late-suspension",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "suspended"},
        },
        "subscription.suspended",
        digest_key="d" * 48,
    )
    await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    assert (
        await lifecycle.reconcile_lifecycle_target(
            enterprise, external_tenant_id=10001, external_app_id=51
        )
        == "allowed"
    )
    async with enterprise.db.transaction(scope) as c:
        tenant = await (
            await c.execute(
                "SELECT external_eligibility,local_enabled FROM enterprise.tenants WHERE id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert tenant == {"external_eligibility": "allowed", "local_enabled": False}


async def test_unavailable_old_client_does_not_override_new_current_client(app):
    enterprise = app.state.enterprise

    class RotatedResolver:
        async def resolve_client(self, client_id, *, expected_tenant_id=None):
            if client_id == "synthetic-old-client":
                raise TimeoutError("synthetic old client unavailable")
            assert client_id == "synthetic-new-client"
            return {
                "client_id": client_id,
                "external_tenant_id": "10001",
                "external_app_id": "51",
                "status": "active",
                "tenant_status": "active",
                "app_status": "active",
                "subscription_status": "active",
                "version": "opaque",
            }

    enterprise.eduplus2_resolver = RotatedResolver()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
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
    for index, client_id in enumerate(("synthetic-old-client", "synthetic-new-client")):
        event = lifecycle.parse_lifecycle_event(
            {
                "event": "subscription.renewed",
                "event_id": f"synthetic-rotated-{index}",
                "tenant": {"id": 10001},
                "app": {"id": 51, "client_id": client_id},
                "subscription": {"id": 20001, "status": "active"},
            },
            "subscription.renewed",
            digest_key="d" * 48,
        )
        await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    assert (
        await lifecycle.reconcile_lifecycle_target(
            enterprise, external_tenant_id=10001, external_app_id=51
        )
        == "allowed"
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("inactive", "denied"), ("contradictory_school", "unknown")],
)
async def test_online_negative_and_contradictory_target_fail_closed(app, mode, expected):
    enterprise = app.state.enterprise

    class Resolver:
        async def resolve_client(self, client_id, *, expected_tenant_id=None):
            if mode == "inactive":
                raise PermissionError("subscription_inactive")
            return {
                "client_id": client_id,
                "external_tenant_id": "10002",
                "external_app_id": "51",
                "status": "active",
                "tenant_status": "active",
                "app_status": "active",
                "subscription_status": "active",
                "version": "opaque",
            }

    enterprise.eduplus2_resolver = Resolver()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
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
            "event": "subscription.renewed",
            "event_id": "synthetic-online-negative",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
        },
        "subscription.renewed",
        digest_key="d" * 48,
    )
    await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    assert (
        await lifecycle.reconcile_lifecycle_target(
            enterprise, external_tenant_id=10001, external_app_id=51
        )
        == expected
    )
    async with enterprise.db.transaction(scope) as c:
        tenant = await (
            await c.execute(
                "SELECT external_eligibility FROM enterprise.tenants WHERE id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert tenant["external_eligibility"] == "denied"


async def test_two_verified_schools_notifications_remain_separate(app):
    enterprise = app.state.enterprise
    school_b = uuid.uuid4()

    class SchoolBResolver:
        async def resolve_client(self, client_id, *, expected_tenant_id=None):
            assert (client_id, expected_tenant_id) == ("synthetic-school-b-client", 10002)
            return {
                "client_id": client_id,
                "external_tenant_id": "10002",
                "external_app_id": "51",
                "status": "active",
                "tenant_status": "active",
                "app_status": "active",
                "subscription_status": "active",
                "version": "opaque",
            }

    enterprise.eduplus2_resolver = SchoolBResolver()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@lifecycle-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET external_tid='10001',"
            "external_eligibility='allowed' WHERE id=%s",
            (enterprise.deployment.tenant_id,),
        )
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_tid,external_eligibility,auth_epoch) "
            "VALUES(%s,'10002','allowed','synthetic')",
            (school_b,),
        )
        for school, external_id in ((enterprise.deployment.tenant_id, 10001), (school_b, 10002)):
            await c.execute(
                "INSERT INTO oms.school_bindings(tenant_id,eduplus_tenant_id,status,"
                "verified_at,verified_by,source_ref) "
                "VALUES(%s,%s,'verified',now(),'synthetic-review','synthetic-proof')",
                (school, external_id),
            )
    event = lifecycle.parse_lifecycle_event(
        {
            "event": "subscription.suspended",
            "event_id": "synthetic-school-b-only",
            "tenant": {"id": 10002},
            "app": {"id": 51, "client_id": "synthetic-school-b-client"},
            "subscription": {"id": 20002, "status": "suspended"},
        },
        "subscription.suspended",
        digest_key="d" * 48,
    )
    await lifecycle.ingest_lifecycle_event(enterprise, event, delivery_timestamp=1)
    async with enterprise.db.transaction(scope) as c:
        rows = await (
            await c.execute(
                "SELECT id,external_eligibility FROM enterprise.tenants "
                "WHERE id IN (%s,%s) ORDER BY id",
                (enterprise.deployment.tenant_id, school_b),
            )
        ).fetchall()
    assert {row["id"]: row["external_eligibility"] for row in rows} == {
        enterprise.deployment.tenant_id: "allowed",
        school_b: "denied",
    }
    assert (
        await lifecycle.reconcile_lifecycle_target(
            enterprise, external_tenant_id=10002, external_app_id=51
        )
        == "allowed"
    )
