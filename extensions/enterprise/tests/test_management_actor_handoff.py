"""首位管理员候选只作受控身份交接，不能据此直接授予角色。"""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import uuid

from deeptutor_enterprise.eduplus2 import lifecycle, webhook_authority
from deeptutor_enterprise.management.actor_activation import activate_first_school_administrator
from deeptutor_enterprise.management.authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
)
from deeptutor_enterprise.scope import TenantScope
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
    enterprise.eduplus2_resolver = None
    enterprise.eduplus2_lifecycle_receiver_enabled = True
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@handoff-test")
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
            "event_id": "synthetic-handoff-created",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20001, "status": "active"},
            "actor": {"type": "user", "user_id": "synthetic-keycloak-sub"},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    assert (
        await webhook_authority.ingest_authoritative_webhook(
            enterprise, event, delivery_timestamp=1
        )
        == "allowed"
    )
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="tms",
        issuer="https://synthetic-issuer.example",
        subject="synthetic-keycloak-sub",
        school_id=enterprise.deployment.tenant_id,
        policy_version=1,
        school_binding_version=1,
        webhook_app_id=51,
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
        replace(identity, webhook_app_id=52),
    ):
        assert await find_pending_actor_candidates(enterprise, mismatch) == ()
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@handoff-test")
    async with enterprise.db.transaction(scope) as c:
        principal_count = await (
            await c.execute("SELECT count(*) AS count FROM management.principals")
        ).fetchone()
    assert principal_count["count"] == 0


async def test_pending_actor_handoff_denies_suspended_projection_and_receiver_off(app):
    from deeptutor_enterprise.management.actor_handoff import find_pending_actor_candidates

    enterprise = app.state.enterprise
    identity = await _seed_candidate(enterprise)
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@handoff-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE eduplus2.webhook_school_state SET eligibility='denied' WHERE tenant_id=%s",
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
    assert (await find_pending_actor_candidates(enterprise, identity)) == ()
    assert await find_pending_actor_candidates(enterprise, identity) == ()
    with pytest.raises(ManagementAuthorizationDenied):
        await activate_first_school_administrator(
            enterprise,
            identity,
            event_id="synthetic-handoff-created",
            request_id="synthetic-terminal-candidate",
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


@pytest.mark.parametrize("disable_db_bump", [False, True])
async def test_first_admin_activation_concurrent_replay_has_one_assignment(app, disable_db_bump):
    enterprise = app.state.enterprise
    identity = await _seed_candidate(enterprise)
    if disable_db_bump:
        # 最终 schema 已无数据库版本触发器；保留该参数以复用无触发器路径。
        pass
    first, second = await asyncio.gather(
        activate_first_school_administrator(
            enterprise, identity, event_id="synthetic-handoff-created", request_id="race-one"
        ),
        activate_first_school_administrator(
            enterprise, identity, event_id="synthetic-handoff-created", request_id="race-two"
        ),
    )
    assert first.assignment_id == second.assignment_id
    assert {first.replayed, second.replayed} == {False, True}
    assert first.policy_version == second.policy_version == 2
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@handoff-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute("SELECT set_config('app.management_app','tms',true)")
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(identity.school_id),))
        assignments = await (
            await c.execute(
                "SELECT count(*) AS count FROM management.assignments "
                "WHERE application='tms' AND school_id=%s AND role_key='school_admin'",
                (identity.school_id,),
            )
        ).fetchone()
        principal = await (
            await c.execute(
                "SELECT policy_version FROM management.principals WHERE id=%s",
                (first.principal_id,),
            )
        ).fetchone()
    assert assignments["count"] == 1
    assert principal["policy_version"] == 2


async def test_first_admin_activation_denies_wrong_actor_and_suspended_school(app):
    enterprise = app.state.enterprise
    identity = await _seed_candidate(enterprise)
    with pytest.raises(ManagementAuthorizationDenied):
        await activate_first_school_administrator(
            enterprise,
            replace(identity, subject="another-subject"),
            event_id="synthetic-handoff-created",
            request_id="synthetic-wrong-actor",
        )
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@handoff-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE eduplus2.webhook_school_state SET eligibility='denied' WHERE tenant_id=%s",
            (enterprise.deployment.tenant_id,),
        )
    with pytest.raises(ManagementAuthorizationDenied):
        await activate_first_school_administrator(
            enterprise,
            identity,
            event_id="synthetic-handoff-created",
            request_id="synthetic-suspended-school",
        )
    async with enterprise.db.transaction(scope) as c:
        principal_count = await (
            await c.execute("SELECT count(*) AS n FROM management.principals")
        ).fetchone()
        candidate = await (
            await c.execute(
                "SELECT status FROM eduplus2.lifecycle_actor_candidates "
                "WHERE tenant_id=%s AND event_id='synthetic-handoff-created'",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    assert principal_count["n"] == 0
    assert candidate["status"] == "pending_verification"


async def test_pending_actor_handoff_denies_late_event_after_school_bootstrap(app):
    from deeptutor_enterprise.management.actor_handoff import find_pending_actor_candidates

    enterprise = app.state.enterprise
    identity = await _seed_candidate(enterprise)
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@handoff-test")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "UPDATE enterprise.tenants SET bootstrap_completed=true WHERE id=%s",
            (identity.school_id,),
        )
    assert await find_pending_actor_candidates(enterprise, identity) == ()
    late = lifecycle.parse_lifecycle_event(
        {
            "event_id": "synthetic-created-after-bootstrap",
            "tenant": {"id": 10001},
            "app": {"id": 51, "client_id": "synthetic-school-client"},
            "subscription": {"id": 20002, "status": "active"},
            "actor": {"type": "user", "user_id": identity.subject},
        },
        "subscription.created",
        digest_key="d" * 48,
    )
    assert (
        await webhook_authority.ingest_authoritative_webhook(enterprise, late, delivery_timestamp=2)
        == "allowed"
    )
    async with enterprise.db.transaction(scope) as c:
        candidate = await (
            await c.execute(
                "SELECT 1 FROM eduplus2.lifecycle_actor_candidates "
                "WHERE tenant_id=%s AND event_id=%s",
                (enterprise.deployment.tenant_id, late.event_id),
            )
        ).fetchone()
    assert candidate is None
