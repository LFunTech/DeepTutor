"""OMS 枚举/条件 CHECK 退役后的程序值域防线。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.stores.postgres.connection import Database
import psycopg
import pytest

from deeptutor.persistence.postgres.scope import GlobalScope, TenantScope
from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


async def _drop(c, table: str, constraint: str) -> None:
    await c.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")


async def _seed_oms(pg_dsn, *, service_category: str = "tool_integration"):
    await MigrationRunner(pg_dsn).apply()
    tenant_id = uuid.uuid4()
    lot_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','test-epoch')",
            (tenant_id,),
        )
        await c.execute(
            "INSERT INTO oms.service_definitions(service_id,unit_code,resource_category,enabled) "
            "VALUES('search','request',%s,true)",
            (service_category,),
        )
        await c.execute(
            "INSERT INTO oms.tenant_service_entitlements"
            "(tenant_id,service_id,starts_at,expires_at,created_by) "
            "VALUES(%s,'search',%s,%s,'platform-operator')",
            (tenant_id, now - timedelta(days=1), now + timedelta(days=10)),
        )
        await c.execute(
            "INSERT INTO oms.supply_lots"
            "(id,service_id,provider_id,provider_account_id,pool_id,unit_code,evidence_ref,"
            "hard_ceiling,starts_at,expires_at,supply_basis,verified_at,created_by) "
            "VALUES(%s,'search','provider-a','account-a','pool-a','request',"
            "'contract://synthetic/search',100,%s,%s,'native_units',now(),'platform-operator')",
            (lot_id, now - timedelta(days=1), now + timedelta(days=3)),
        )
    return tenant_id, lot_id, now


def _supply_request(lot_id: uuid.UUID | None = None):
    from deeptutor_enterprise.oms.supply import SupplyRequest

    now = datetime.now(timezone.utc)
    return SupplyRequest(
        lot_id=lot_id or uuid.uuid4(),
        service_id="search",
        unit_code="request",
        provider_id="provider-a",
        provider_account_id="account-a",
        pool_id="pool-a",
        basis="native_units",
        hard_ceiling=Decimal("100"),
        starts_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=3),
        evidence_ref="contract://synthetic/new-search",
        verified_native=True,
        actor_subject="platform-operator",
        request_id="supply-new",
        reason="synthetic procurement",
    )


def _grant_request(grant_id: uuid.UUID, now: datetime, *, key: str = "grant-1"):
    from deeptutor_enterprise.oms.ledger import GrantRequest

    return GrantRequest(
        grant_id=grant_id,
        service_id="search",
        unit_code="request",
        acquisition_method="gift",
        quantity=Decimal("20"),
        starts_at=now,
        expires_at=now + timedelta(days=1),
        provider_id="provider-a",
        provider_account_id="account-a",
        pool_id="pool-a",
        source_ref=f"campaign://synthetic/{key}",
        actor_subject="platform-operator",
        request_id=key,
        idempotency_key=key,
        reason="synthetic grant",
        expected_entitlement_version=1,
    )


def _attempt_request(attempt_id: uuid.UUID | None = None, *, units: str = "6"):
    from deeptutor_enterprise.oms.attempts import AttemptRequest

    return AttemptRequest(
        operation_id=uuid.uuid4(),
        attempt_id=attempt_id or uuid.uuid4(),
        service_id="search",
        unit_code="request",
        provider_id="provider-a",
        provider_account_id="account-a",
        pool_id="pool-a",
        model_id="model-a",
        config_version=1,
        subject_kind="user",
        subject_id="learner-1",
        user_id="learner-1",
        app_id="",
        reserved_units=Decimal(units),
    )


async def test_service_definition_unknown_resource_category_is_rejected_without_db_check(pg_dsn):
    from deeptutor_enterprise.oms.supply import OmsSupplyLedger, SupplyRejected

    await _seed_oms(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await _drop(c, "oms.service_definitions", "service_definitions_resource_category_check")
        await c.execute(
            "UPDATE oms.service_definitions SET resource_category='future-category' "
            "WHERE service_id='search'"
        )
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-value") as db:
        with pytest.raises(SupplyRejected, match="service resource category"):
            await OmsSupplyLedger(db).register(GlobalScope("platform-operator"), _supply_request())


async def test_supply_replay_and_revoke_reject_unknown_status_and_invalid_native_proof(pg_dsn):
    from deeptutor_enterprise.oms.supply import (
        OmsSupplyLedger,
        SupplyRejected,
        SupplyRevokeRequest,
    )

    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO oms.service_definitions(service_id,unit_code,resource_category,enabled) "
            "VALUES('search','request','tool_integration',true)"
        )
    scope = GlobalScope("platform-operator")
    request = _supply_request()
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-value") as db:
        ledger = OmsSupplyLedger(db)
        await ledger.register(scope, request)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await _drop(c, "oms.supply_lots", "supply_lots_status_check")
            await c.execute("UPDATE oms.supply_lots SET status='future-status' WHERE id=%s", (request.lot_id,))
        with pytest.raises(SupplyRejected, match="supply lot status"):
            await ledger.register(scope, request)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await _drop(c, "oms.supply_lots", "supply_lots_verified_native")
            await c.execute(
                "UPDATE oms.supply_lots SET status='active',hard_ceiling=NULL," 
                "supply_basis='native_units',verified_at=now() WHERE id=%s",
                (request.lot_id,),
            )
        with pytest.raises(SupplyRejected, match="supply lot native proof"):
            await ledger.revoke(
                scope,
                SupplyRevokeRequest(
                    lot_id=request.lot_id,
                    expected_version=1,
                    actor_subject="platform-operator",
                    request_id="revoke-invalid-proof",
                    reason="synthetic",
                ),
            )


async def test_entitlement_rejects_unknown_existing_status_without_db_check(pg_dsn):
    from deeptutor_enterprise.oms.entitlements import (
        EntitlementRejected,
        EntitlementRequest,
        OmsEntitlementLedger,
    )

    tenant_id, _, now = await _seed_oms(pg_dsn)
    scope = TenantScope(str(tenant_id), "platform-operator")
    request = EntitlementRequest(
        service_id="search",
        status="active",
        starts_at=now,
        expires_at=now + timedelta(days=4),
        expected_version=1,
        actor_subject="platform-operator",
        request_id="entitlement-extend",
        idempotency_key="entitlement-extend",
        reason="synthetic",
    )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
        await _drop(c, "oms.tenant_service_entitlements", "tenant_service_entitlements_status_check")
        await c.execute(
            "UPDATE oms.tenant_service_entitlements SET status='future-status' "
            "WHERE tenant_id=%s AND service_id='search'",
            (tenant_id,),
        )
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-value") as db:
        with pytest.raises(EntitlementRejected, match="entitlement status"):
            await OmsEntitlementLedger(db).set(scope, request)


async def test_grant_replay_and_close_reject_unknown_command_and_grant_values(pg_dsn):
    from deeptutor_enterprise.oms.ledger import GrantRejected, OmsGrantLedger, RevokeRequest

    tenant_id, _, now = await _seed_oms(pg_dsn)
    scope = TenantScope(str(tenant_id), "platform-operator")
    grant_id = uuid.uuid4()
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-value") as db:
        ledger = OmsGrantLedger(db)
        request = _grant_request(grant_id, now)
        await ledger.grant(scope, request)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            await _drop(c, "oms.grant_commands", "grant_commands_result_check")
            await c.execute(
                "UPDATE oms.grant_commands SET result='future-result' "
                "WHERE actor_subject='platform-operator' AND idempotency_key='grant-1'"
            )
        with pytest.raises(GrantRejected, match="grant command result"):
            await ledger.grant(scope, request)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            await c.execute(
                "UPDATE oms.grant_commands SET result='success' "
                "WHERE actor_subject='platform-operator' AND idempotency_key='grant-1'"
            )
            await _drop(c, "oms.quota_grants", "quota_grants_status_check")
            await c.execute(
                "UPDATE oms.quota_grants SET status='future-status' WHERE tenant_id=%s AND id=%s",
                (tenant_id, grant_id),
            )
        with pytest.raises(GrantRejected, match="quota grant status"):
            await ledger.revoke(
                scope,
                RevokeRequest(
                    grant_id=grant_id,
                    expected_version=1,
                    actor_subject="platform-operator",
                    request_id="revoke-unknown-status",
                    idempotency_key="revoke-unknown-status",
                    reason="synthetic",
                ),
            )


async def test_attempts_reject_unknown_usage_and_evidence_values_without_db_checks(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger, SettlementRejected
    from deeptutor_enterprise.oms.ledger import OmsGrantLedger

    tenant_id, _, now = await _seed_oms(pg_dsn)
    grant_scope = TenantScope(str(tenant_id), "platform-operator")
    learner_scope = TenantScope(str(tenant_id), "learner-1")
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-value") as db:
        await OmsGrantLedger(db).grant(grant_scope, _grant_request(uuid.uuid4(), now))
        ledger = OmsAttemptLedger(db)
        request = _attempt_request()
        await ledger.reserve(learner_scope, request)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            await _drop(c, "oms.usage_attempts", "usage_attempts_status_check")
            await c.execute(
                "UPDATE oms.usage_attempts SET status='future-status' "
                "WHERE tenant_id=%s AND attempt_id=%s",
                (tenant_id, request.attempt_id),
            )
        with pytest.raises(SettlementRejected, match="usage attempt status"):
            await ledger.mark_dispatched(learner_scope, request.attempt_id)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            await _drop(c, "oms.usage_attempts", "usage_attempts_subject_kind_check")
            await c.execute(
                "UPDATE oms.usage_attempts SET status='reserved',subject_kind='future-kind' "
                "WHERE tenant_id=%s AND attempt_id=%s",
                (tenant_id, request.attempt_id),
            )
        with pytest.raises(SettlementRejected, match="usage attempt subject kind"):
            await ledger.mark_dispatched(learner_scope, request.attempt_id)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            await c.execute(
                "UPDATE oms.usage_attempts SET subject_kind='user' "
                "WHERE tenant_id=%s AND attempt_id=%s",
                (tenant_id, request.attempt_id),
            )
        await ledger.mark_dispatched(learner_scope, request.attempt_id)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            await _drop(c, "oms.attempt_evidence_events", "attempt_evidence_events_event_kind_check")
            await c.execute(
                "INSERT INTO oms.attempt_evidence_events"
                "(tenant_id,attempt_id,id,event_kind,reference,observed_units,provider_request_id) "
                "VALUES(%s,%s,%s,'future-kind','synthetic://bad',NULL,'')",
                (tenant_id, request.attempt_id, uuid.uuid4()),
            )
        with pytest.raises(SettlementRejected, match="attempt evidence event kind"):
            await ledger.settle(
                learner_scope,
                request.attempt_id,
                units=Decimal("5"),
                source="provider_usage",
                evidence_ref="usage://synthetic",
                provider_request_id="provider-1",
            )


async def test_attempt_reserve_rejects_unknown_active_grant_acquisition_method(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger, QuotaUnavailable
    from deeptutor_enterprise.oms.ledger import OmsGrantLedger

    tenant_id, _, now = await _seed_oms(pg_dsn)
    grant_id = uuid.uuid4()
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-value") as db:
        await OmsGrantLedger(db).grant(
            TenantScope(str(tenant_id), "platform-operator"), _grant_request(grant_id, now)
        )
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            await _drop(c, "oms.quota_grants", "quota_grants_acquisition_method_check")
            await c.execute(
                "UPDATE oms.quota_grants SET acquisition_method='future-method' "
                "WHERE tenant_id=%s AND id=%s",
                (tenant_id, grant_id),
            )
        with pytest.raises(QuotaUnavailable, match="quota grant acquisition method"):
            await OmsAttemptLedger(db).reserve(
                TenantScope(str(tenant_id), "learner-1"), _attempt_request()
            )


async def test_management_target_school_rejects_unknown_binding_status_and_bad_proof(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        ManagementIdentity,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    school_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_tid,external_eligibility,local_enabled,"
            "provisioning_status,auth_epoch,bootstrap_completed,recovery_state) "
            "VALUES(%s,'10001','allowed',true,'ready','test-epoch',true,'normal')",
            (school_id,),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings(tenant_id,eduplus_tenant_id,status,version,"
            "verified_at,verified_by,source_ref) VALUES(%s,10001,'verified',1,now(),"
            "'platform-operator','webhook://synthetic')",
            (school_id,),
        )
        await _drop(c, "oms.school_bindings", "school_bindings_status_check")
        await _drop(c, "oms.school_bindings", "school_bindings_check")
        await c.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status,policy_version) "
            "VALUES(%s,'oms','issuer','operator','active',1)",
            (principal_id,),
        )
        await c.execute(
            "UPDATE oms.school_bindings SET status='future-status' WHERE tenant_id=%s",
            (school_id,),
        )
        identity = ManagementIdentity(
            application="oms",
            issuer="issuer",
            subject="operator",
            school_id=None,
            policy_version=1,
            school_binding_version=None,
            external_active=True,
            external_checked_at=now,
            external_verified_until=now + timedelta(seconds=30),
        )
        with pytest.raises(ManagementAuthorizationDenied, match="binding fact"):
            await require_management_permission(
                c, identity, "ops.permissions.manage", target_school_id=school_id
            )
        await c.execute(
            "UPDATE oms.school_bindings SET status='verified',verified_at=NULL,verified_by=NULL "
            "WHERE tenant_id=%s",
            (school_id,),
        )
        with pytest.raises(ManagementAuthorizationDenied, match="binding fact"):
            await require_management_permission(
                c, identity, "ops.permissions.manage", target_school_id=school_id
            )
