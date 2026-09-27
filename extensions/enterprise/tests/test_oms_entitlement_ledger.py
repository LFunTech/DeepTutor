"""服务授权的内部 PG 事务；不模拟外部平台权限。"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.stores.postgres.connection import Database
import psycopg
import pytest

from deeptutor.persistence.postgres.scope import TenantScope
from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


async def _seed(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','test-epoch')",
            (tenant_id,),
        )
        await c.execute(
            "INSERT INTO oms.service_definitions(service_id,unit_code,resource_category,enabled) "
            "VALUES('search','request','tool_integration',true)"
        )
    return tenant_id, now


async def test_entitlement_create_update_revoke_are_versioned_and_idempotent(pg_dsn):
    from deeptutor_enterprise.oms.entitlements import (
        EntitlementRejected,
        EntitlementRequest,
        OmsEntitlementLedger,
    )

    tenant_id, now = await _seed(pg_dsn)
    scope = TenantScope(str(tenant_id), "platform-operator")
    create = EntitlementRequest(
        service_id="search",
        status="active",
        starts_at=now,
        expires_at=now + timedelta(days=5),
        expected_version=0,
        actor_subject="platform-operator",
        request_id="create-1",
        idempotency_key="create-1",
        reason="synthetic service approval",
    )
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-test") as db:
        ledger = OmsEntitlementLedger(db)
        first = await ledger.set(scope, create)
        assert (first.status, first.version) == ("active", 1)
        assert await ledger.set(scope, create) == first
        with pytest.raises(EntitlementRejected, match="idempotency"):
            await ledger.set(scope, replace(create, reason="different"))
        with pytest.raises(EntitlementRejected, match="version"):
            await ledger.set(scope, replace(create, idempotency_key="stale"))

        extend = replace(
            create,
            expected_version=1,
            expires_at=now + timedelta(days=6),
            idempotency_key="extend-1",
            request_id="extend-1",
        )
        assert (await ledger.set(scope, extend)).version == 2
        revoke = replace(
            extend,
            status="revoked",
            expected_version=2,
            idempotency_key="revoke-1",
            request_id="revoke-1",
            reason="synthetic revocation",
        )
        assert (await ledger.set(scope, revoke)).version == 3
        assert (await ledger.set(scope, revoke)).version == 3

    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
        state = await (
            await c.execute(
                "SELECT status,version FROM oms.tenant_service_entitlements "
                "WHERE tenant_id=%s AND service_id='search'",
                (tenant_id,),
            )
        ).fetchone()
        audit = await (
            await c.execute(
                "SELECT action,result FROM oms.audit_events "
                "WHERE target_tenant_id=%s AND object_id='search' ORDER BY created_at,id",
                (tenant_id,),
            )
        ).fetchall()
    assert state == ("revoked", 3)
    assert audit == [
        ("service_entitlement.set", "success"),
        ("service_entitlement.set", "success"),
        ("service_entitlement.set", "success"),
    ]


async def test_entitlement_reactivation_rejects_old_active_grant(pg_dsn):
    from deeptutor_enterprise.oms.entitlements import (
        EntitlementRejected,
        EntitlementRequest,
        OmsEntitlementLedger,
    )

    tenant_id, now = await _seed(pg_dsn)
    scope = TenantScope(str(tenant_id), "platform-operator")
    request = EntitlementRequest(
        service_id="search",
        status="active",
        starts_at=now,
        expires_at=now + timedelta(days=5),
        expected_version=0,
        actor_subject="platform-operator",
        request_id="create-1",
        idempotency_key="create-1",
        reason="synthetic approval",
    )
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-test") as db:
        ledger = OmsEntitlementLedger(db)
        await ledger.set(scope, request)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            await c.execute(
                "INSERT INTO oms.quota_grants"
                "(id,tenant_id,service_id,unit_code,acquisition_method,quantity,"
                "starts_at,expires_at,created_by) "
                "VALUES(%s,%s,'search','request','gift',10,%s,%s,'platform-operator')",
                (uuid.uuid4(), tenant_id, now, now + timedelta(days=2)),
            )
        await ledger.set(
            scope,
            replace(
                request,
                status="revoked",
                expected_version=1,
                request_id="revoke-1",
                idempotency_key="revoke-1",
            ),
        )
        with pytest.raises(EntitlementRejected, match="old active grant"):
            await ledger.set(
                scope,
                replace(
                    request,
                    expected_version=2,
                    request_id="reactivate-1",
                    idempotency_key="reactivate-1",
                ),
            )


async def test_entitlement_command_does_not_leak_to_other_tenant_scope(pg_dsn):
    from deeptutor_enterprise.oms.entitlements import EntitlementRequest, OmsEntitlementLedger

    first_tenant, now = await _seed(pg_dsn)
    second_tenant = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','test-epoch')",
            (second_tenant,),
        )
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-test") as db:
        await OmsEntitlementLedger(db).set(
            TenantScope(str(first_tenant), "platform-operator"),
            EntitlementRequest(
                service_id="search",
                status="active",
                starts_at=now,
                expires_at=now + timedelta(days=5),
                expected_version=0,
                actor_subject="platform-operator",
                request_id="command-1",
                idempotency_key="command-1",
                reason="synthetic authorization",
            ),
        )
        async with db.transaction(TenantScope(str(second_tenant), "platform-operator")) as c:
            count = await (
                await c.execute("SELECT count(*) FROM oms.entitlement_commands")
            ).fetchone()
            assert count["count"] == 0
