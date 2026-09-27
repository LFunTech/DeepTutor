"""仅在临时 PG 中验证 OMS 内部授予事务；不作为对外授权 API。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.stores.postgres.connection import Database
import psycopg
import pytest

from deeptutor.persistence.postgres.scope import TenantScope
from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


async def test_adjust_grant_increases_and_decreases_unused_commitment_without_changing_history(
    pg_dsn,
):
    from deeptutor_enterprise.oms.ledger import (
        AdjustRequest,
        GrantRejected,
        GrantRequest,
        OmsGrantLedger,
    )

    tenant_id, lot_ids, now = await _seed(pg_dsn, capacities=(30,))
    scope = TenantScope(str(tenant_id), "platform-operator")
    grant_id = uuid.uuid4()
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-test") as db:
        ledger = OmsGrantLedger(db)
        await ledger.grant(
            scope,
            GrantRequest(
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
                source_ref="campaign://synthetic-adjust",
                actor_subject="platform-operator",
                request_id="grant-adjust",
                idempotency_key="grant-adjust",
                reason="seed",
                expected_entitlement_version=1,
            ),
        )
        increase = AdjustRequest(
            grant_id=grant_id,
            expected_version=1,
            new_quantity=Decimal("25"),
            actor_subject="platform-operator",
            request_id="adjust-up",
            idempotency_key="adjust-up",
            reason="increase",
        )
        first = await ledger.adjust(scope, increase)
        assert first.version == 2
        assert first.previous_quantity == Decimal("20")
        assert first.quantity == Decimal("25")
        assert await ledger.adjust(scope, increase) == first
        from deeptutor_enterprise.oms.ledger import InsufficientSupply

        over_capacity = replace(
            increase,
            expected_version=2,
            new_quantity=Decimal("35"),
            request_id="adjust-over-capacity",
            idempotency_key="adjust-over-capacity",
        )
        with pytest.raises(InsufficientSupply):
            await ledger.adjust(scope, over_capacity)
        with pytest.raises(InsufficientSupply):
            await ledger.adjust(scope, over_capacity)
        with pytest.raises(GrantRejected, match="idempotency"):
            await ledger.adjust(scope, replace(increase, new_quantity=Decimal("26")))
        decrease = replace(
            increase,
            expected_version=2,
            new_quantity=Decimal("15"),
            request_id="adjust-down",
            idempotency_key="adjust-down",
        )
        second = await ledger.adjust(scope, decrease)
        assert second.version == 3
        assert second.previous_quantity == Decimal("25")
        assert second.quantity == Decimal("15")
        with pytest.raises(GrantRejected, match="version"):
            await ledger.adjust(scope, replace(decrease, idempotency_key="stale"))

    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
        lot = await (
            await c.execute(
                "SELECT committed_unspent FROM oms.supply_lots WHERE id=%s", (lot_ids[0],)
            )
        ).fetchone()
        commitment = await (
            await c.execute(
                "SELECT committed_total,unspent,reserved,settled,released "
                "FROM oms.grant_commitments WHERE tenant_id=%s AND grant_id=%s",
                (tenant_id, grant_id),
            )
        ).fetchone()
        grant = await (
            await c.execute(
                "SELECT quantity,version FROM oms.quota_grants WHERE tenant_id=%s AND id=%s",
                (tenant_id, grant_id),
            )
        ).fetchone()
        audit = await (
            await c.execute(
                "SELECT action,safe_summary->>'previous_quantity',safe_summary->>'quantity' "
                "FROM oms.audit_events WHERE object_id=%s ORDER BY created_at,action",
                (str(grant_id),),
            )
        ).fetchall()
    assert lot == (15,)
    assert commitment == (25, 15, 0, 0, 10)
    assert grant == (25, 3)
    assert {row[0] for row in audit} == {"quota.grant", "quota.adjust"}
    assert len(audit) == 4
    from deeptutor_enterprise.oms.ledger import RevokeRequest

    async with Database(single_database_user_dsn(pg_dsn), resource="oms-test") as db:
        revoked = await OmsGrantLedger(db).revoke(
            scope,
            RevokeRequest(
                grant_id=grant_id,
                expected_version=3,
                actor_subject="platform-operator",
                request_id="revoke-after-adjust",
                idempotency_key="revoke-after-adjust",
                reason="finish",
            ),
        )
    assert revoked.version == 4
    assert revoked.released_units == Decimal("15")


async def test_adjust_cannot_release_inflight_attempt_reservation(pg_dsn):
    from deeptutor_enterprise.oms.attempts import AttemptRequest, OmsAttemptLedger
    from deeptutor_enterprise.oms.ledger import (
        AdjustRequest,
        GrantRejected,
        GrantRequest,
        OmsGrantLedger,
    )

    tenant_id, lot_ids, now = await _seed(pg_dsn, capacities=(30,))
    grant_scope = TenantScope(str(tenant_id), "platform-operator")
    learner_scope = TenantScope(str(tenant_id), "learner-1")
    grant_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-test") as db:
        grants = OmsGrantLedger(db)
        attempts = OmsAttemptLedger(db)
        await grants.grant(
            grant_scope,
            GrantRequest(
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
                source_ref="campaign://synthetic-reserve",
                actor_subject="platform-operator",
                request_id="grant-reserve",
                idempotency_key="grant-reserve",
                reason="seed",
                expected_entitlement_version=1,
            ),
        )
        await attempts.reserve(
            learner_scope,
            AttemptRequest(
                operation_id=uuid.uuid4(),
                attempt_id=attempt_id,
                service_id="search",
                unit_code="request",
                provider_id="provider-a",
                provider_account_id="account-a",
                pool_id="pool-a",
                model_id="",
                config_version=1,
                subject_kind="user",
                subject_id="learner-1",
                user_id="learner-1",
                app_id="",
                reserved_units=Decimal("6"),
            ),
        )
        await attempts.mark_dispatched(learner_scope, attempt_id)
        request = AdjustRequest(
            grant_id=grant_id,
            expected_version=1,
            new_quantity=Decimal("5"),
            actor_subject="platform-operator",
            request_id="adjust-too-low",
            idempotency_key="adjust-too-low",
            reason="reduce",
        )
        with pytest.raises(GrantRejected, match="unspent"):
            await grants.adjust(grant_scope, request)
        await grants.adjust(
            grant_scope,
            replace(
                request,
                new_quantity=Decimal("15"),
                request_id="adjust-safe",
                idempotency_key="adjust-safe",
            ),
        )
        await attempts.settle(
            learner_scope,
            attempt_id,
            units=Decimal("6"),
            source="provider_usage",
            evidence_ref="usage://synthetic-adjust",
            provider_request_id="provider-adjust-1",
        )

    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
        lot = await (
            await c.execute(
                "SELECT settled_lifetime,committed_unspent,reserved_inflight "
                "FROM oms.supply_lots WHERE id=%s",
                (lot_ids[0],),
            )
        ).fetchone()
        commitment = await (
            await c.execute(
                "SELECT unspent,reserved,settled,released FROM oms.grant_commitments "
                "WHERE tenant_id=%s AND grant_id=%s",
                (tenant_id, grant_id),
            )
        ).fetchone()
    assert lot == (6, 9, 0)
    assert commitment == (9, 0, 6, 5)


async def _seed(pg_dsn, *, capacities: tuple[int, ...]):
    await MigrationRunner(pg_dsn).apply()
    tenant_id = uuid.uuid4()
    lot_ids = sorted((uuid.uuid4() for _ in capacities), reverse=True)
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
        await c.execute(
            "INSERT INTO oms.tenant_service_entitlements"
            "(tenant_id,service_id,starts_at,expires_at,created_by) "
            "VALUES(%s,'search',%s,%s,'platform-operator')",
            (tenant_id, now - timedelta(days=1), now + timedelta(days=10)),
        )
        for index, (lot_id, capacity) in enumerate(zip(lot_ids, capacities, strict=True)):
            await c.execute(
                "INSERT INTO oms.supply_lots"
                "(id,service_id,provider_id,provider_account_id,pool_id,unit_code,evidence_ref,"
                "hard_ceiling,starts_at,expires_at,supply_basis,verified_at) "
                "VALUES(%s,'search','provider-a','account-a','pool-a','request',%s,%s,%s,%s,"
                "'native_units',now())",
                (
                    lot_id,
                    f"contract://synthetic/{index}",
                    capacity,
                    now - timedelta(days=1),
                    now + timedelta(days=2 + index),
                ),
            )
    return tenant_id, lot_ids, now


async def test_grant_allocates_compatible_lots_and_audits_atomically(pg_dsn):
    from deeptutor_enterprise.oms.ledger import GrantRequest, OmsGrantLedger

    tenant_id, lot_ids, now = await _seed(pg_dsn, capacities=(30, 50))
    scope = TenantScope(str(tenant_id), "platform-operator")
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-test") as db:
        ledger = OmsGrantLedger(db)
        gift_id = uuid.uuid4()
        request = GrantRequest(
            grant_id=gift_id,
            service_id="search",
            unit_code="request",
            acquisition_method="gift",
            quantity=Decimal("60"),
            starts_at=now,
            expires_at=now + timedelta(days=2),
            provider_id="provider-a",
            provider_account_id="account-a",
            pool_id="pool-a",
            source_ref="campaign://synthetic-1",
            actor_subject="platform-operator",
            request_id="req-1",
            idempotency_key="grant-gift-1",
            reason="test gift",
            expected_entitlement_version=1,
        )
        result = await ledger.grant(scope, request)
        assert await ledger.grant(scope, request) == result
        assert result.grant_id == gift_id
        assert result.allocations == ((lot_ids[0], Decimal("30")), (lot_ids[1], Decimal("30")))

    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
        lots = await (
            await c.execute(
                "SELECT id,committed_unspent,settled_lifetime,reserved_inflight "
                "FROM oms.supply_lots ORDER BY expires_at,id"
            )
        ).fetchall()
        assert lots == [(lot_ids[0], 30, 0, 0), (lot_ids[1], 30, 0, 0)]
        commitments = await (
            await c.execute(
                "SELECT lot_id,committed_total,unspent,reserved,settled,released "
                "FROM oms.grant_commitments WHERE tenant_id=%s ORDER BY lot_id",
                (tenant_id,),
            )
        ).fetchall()
        assert {row[0]: tuple(row[1:]) for row in commitments} == {
            lot_ids[0]: (30, 30, 0, 0, 0),
            lot_ids[1]: (30, 30, 0, 0, 0),
        }
        grant = await (
            await c.execute(
                "SELECT acquisition_method,quantity,created_by,source_ref "
                "FROM oms.quota_grants WHERE id=%s",
                (gift_id,),
            )
        ).fetchone()
        assert grant == ("gift", 60, "platform-operator", "campaign://synthetic-1")
        audit = await (
            await c.execute(
                "SELECT action,result,target_tenant_id FROM oms.audit_events WHERE object_id=%s",
                (str(gift_id),),
            )
        ).fetchall()
        assert audit == [("quota.grant", "success", tenant_id)]


async def test_concurrent_grants_cannot_overcommit_same_supply(pg_dsn):
    from deeptutor_enterprise.oms.ledger import GrantRequest, InsufficientSupply, OmsGrantLedger

    tenant_id, lot_ids, now = await _seed(pg_dsn, capacities=(30,))
    scope = TenantScope(str(tenant_id), "platform-operator")

    def request(request_id):
        return GrantRequest(
            grant_id=uuid.uuid4(),
            service_id="search",
            unit_code="request",
            acquisition_method="recharge",
            quantity=Decimal("20"),
            starts_at=now,
            expires_at=now + timedelta(days=1),
            provider_id="provider-a",
            provider_account_id="account-a",
            pool_id="pool-a",
            source_ref="purchase://synthetic-1",
            actor_subject="platform-operator",
            request_id=request_id,
            idempotency_key=request_id,
            reason="test recharge",
            expected_entitlement_version=1,
        )

    async with Database(single_database_user_dsn(pg_dsn), resource="oms-test") as db:
        ledger = OmsGrantLedger(db)
        results = await asyncio.gather(
            ledger.grant(scope, request("req-a")),
            ledger.grant(scope, request("req-b")),
            return_exceptions=True,
        )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, InsufficientSupply) for result in results) == 1

    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
        lot = await (
            await c.execute(
                "SELECT committed_unspent FROM oms.supply_lots WHERE id=%s", (lot_ids[0],)
            )
        ).fetchone()
        grants = await (await c.execute("SELECT id FROM oms.quota_grants")).fetchall()
        commits = await (await c.execute("SELECT grant_id FROM oms.grant_commitments")).fetchall()
        audit = await (
            await c.execute("SELECT result FROM oms.audit_events WHERE action='quota.grant'")
        ).fetchall()
    assert lot == (20,)
    assert len(grants) == len(commits) == 1
    assert sorted(row[0] for row in audit) == ["denied", "success"]


async def test_grant_idempotency_replays_same_result_and_rejects_changed_payload(pg_dsn):
    from deeptutor_enterprise.oms.ledger import GrantRejected, GrantRequest, OmsGrantLedger

    tenant_id, lot_ids, now = await _seed(pg_dsn, capacities=(50,))
    scope = TenantScope(str(tenant_id), "platform-operator")
    request = GrantRequest(
        grant_id=uuid.uuid4(),
        service_id="search",
        unit_code="request",
        acquisition_method="gift",
        quantity=Decimal("20"),
        starts_at=now,
        expires_at=now + timedelta(days=1),
        provider_id="provider-a",
        provider_account_id="account-a",
        pool_id="pool-a",
        source_ref="campaign://synthetic-1",
        actor_subject="platform-operator",
        request_id="req-idempotent",
        idempotency_key="same-operation",
        reason="test gift",
        expected_entitlement_version=1,
    )
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-test") as db:
        ledger = OmsGrantLedger(db)
        first = await ledger.grant(scope, request)
        second = await ledger.grant(scope, request)
        with pytest.raises(GrantRejected, match="idempotency"):
            await ledger.grant(scope, replace(request, quantity=Decimal("25")))
    assert first == second
    assert first.allocations == ((lot_ids[0], Decimal("20")),)

    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
        lot = await (
            await c.execute(
                "SELECT committed_unspent FROM oms.supply_lots WHERE id=%s", (lot_ids[0],)
            )
        ).fetchone()
        audit = await (
            await c.execute(
                "SELECT result FROM oms.audit_events WHERE object_id=%s", (str(request.grant_id),)
            )
        ).fetchall()
    assert lot == (20,)
    assert audit == [("success",)]


async def test_concurrent_same_idempotency_key_creates_one_grant(pg_dsn):
    from deeptutor_enterprise.oms.ledger import GrantRequest, OmsGrantLedger

    tenant_id, lot_ids, now = await _seed(pg_dsn, capacities=(30,))
    scope = TenantScope(str(tenant_id), "platform-operator")
    request = GrantRequest(
        grant_id=uuid.uuid4(),
        service_id="search",
        unit_code="request",
        acquisition_method="recharge",
        quantity=Decimal("20"),
        starts_at=now,
        expires_at=now + timedelta(days=1),
        provider_id="provider-a",
        provider_account_id="account-a",
        pool_id="pool-a",
        source_ref="purchase://synthetic-1",
        actor_subject="platform-operator",
        request_id="req-concurrent-a",
        idempotency_key="concurrent-same-action",
        reason="test recharge",
        expected_entitlement_version=1,
    )
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-test") as db:
        ledger = OmsGrantLedger(db)
        results = await asyncio.gather(
            ledger.grant(scope, request),
            ledger.grant(scope, replace(request, request_id="req-concurrent-b")),
        )
    assert results[0] == results[1]
    assert results[0].allocations == ((lot_ids[0], Decimal("20")),)

    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
        lot = await (
            await c.execute(
                "SELECT committed_unspent FROM oms.supply_lots WHERE id=%s", (lot_ids[0],)
            )
        ).fetchone()
        audit = await (
            await c.execute("SELECT id FROM oms.audit_events WHERE action='quota.grant'")
        ).fetchall()
    assert lot == (20,)
    assert len(audit) == 1
