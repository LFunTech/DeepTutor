"""仅用临时 PostgreSQL 的合成供给记录验证批次边界。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.stores.postgres.connection import Database
import psycopg
import pytest

from deeptutor.persistence.postgres.scope import GlobalScope, TenantScope
from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


def _supply(*, basis="native_units", ceiling=Decimal("100"), expires_days=3):
    from deeptutor_enterprise.oms.supply import SupplyRequest

    now = datetime.now(timezone.utc)
    return SupplyRequest(
        lot_id=uuid4(),
        service_id="search",
        unit_code="request",
        provider_id="provider-a",
        provider_account_id="account-a",
        pool_id="pool-a",
        basis=basis,
        hard_ceiling=ceiling,
        starts_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=expires_days),
        evidence_ref="contract://synthetic/search-1",
        verified_native=basis == "native_units",
        actor_subject="platform-operator",
        request_id="supply-1",
        reason="synthetic procurement",
    )


async def _setup(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO oms.service_definitions(service_id,unit_code,resource_category,enabled) "
            "VALUES('search','request','tool_integration',true)"
        )


async def test_supply_register_replays_only_identical_lot_and_audits_once(pg_dsn):
    from deeptutor_enterprise.oms.supply import OmsSupplyLedger, SupplyRejected

    await _setup(pg_dsn)
    scope = GlobalScope("platform-operator")
    request = _supply()
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-supply") as db:
        ledger = OmsSupplyLedger(db)
        assert await ledger.register(scope, request) == request.lot_id
        assert await ledger.register(scope, request) == request.lot_id
        with pytest.raises(SupplyRejected, match="conflict"):
            await ledger.register(scope, replace(request, hard_ceiling=Decimal("101")))
        assert await ledger.available(
            scope, "search", "provider-a", "account-a", "pool-a", "request"
        ) == Decimal("100")

    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        row = await (
            await c.execute(
                "SELECT supply_basis,verified_at,hard_ceiling,version FROM oms.supply_lots WHERE id=%s",
                (request.lot_id,),
            )
        ).fetchone()
        audit = await (
            await c.execute(
                "SELECT action,actor_subject,result FROM oms.audit_events WHERE object_id=%s",
                (str(request.lot_id),),
            )
        ).fetchall()
    assert row[0] == "native_units" and row[1] is not None
    assert row[2:] == (Decimal("100"), 1)
    assert audit == [("supply.register", "platform-operator", "success")]


async def test_supply_registration_replay_survives_service_disabling(pg_dsn):
    from deeptutor_enterprise.oms.supply import OmsSupplyLedger, SupplyRejected

    await _setup(pg_dsn)
    scope = GlobalScope("platform-operator")
    request = _supply()
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-supply") as db:
        ledger = OmsSupplyLedger(db)
        await ledger.register(scope, request)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute(
                "UPDATE oms.service_definitions SET enabled=false WHERE service_id='search'"
            )
        assert await ledger.register(scope, request) == request.lot_id
        with pytest.raises(SupplyRejected, match="service is not enabled"):
            await ledger.register(scope, replace(request, lot_id=uuid4()))


async def test_supply_revoke_is_versioned_and_blocks_new_availability(pg_dsn):
    from deeptutor_enterprise.oms.supply import (
        OmsSupplyLedger,
        SupplyRejected,
        SupplyRevokeRequest,
    )

    await _setup(pg_dsn)
    scope = GlobalScope("platform-operator")
    request = _supply()
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-supply") as db:
        ledger = OmsSupplyLedger(db)
        await ledger.register(scope, request)
        revoke = SupplyRevokeRequest(
            lot_id=request.lot_id,
            expected_version=1,
            actor_subject="platform-operator",
            request_id="revoke-1",
            reason="synthetic supplier recall",
        )
        assert await ledger.revoke(scope, revoke) == 2
        with pytest.raises(SupplyRejected, match="version"):
            await ledger.revoke(scope, revoke)
        assert (
            await ledger.available(scope, "search", "provider-a", "account-a", "pool-a", "request")
            == 0
        )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        lot = await (
            await c.execute(
                "SELECT status,version,hard_ceiling FROM oms.supply_lots WHERE id=%s",
                (request.lot_id,),
            )
        ).fetchone()
        audit = await (
            await c.execute(
                "SELECT action,result FROM oms.audit_events WHERE object_id=%s ORDER BY created_at,id",
                (str(request.lot_id),),
            )
        ).fetchall()
    assert lot == ("revoked", 2, Decimal("100"))
    assert sorted(audit) == [("supply.register", "success"), ("supply.revoke", "success")]


async def test_money_credits_paygo_without_native_ceiling_never_become_grantable(pg_dsn):
    from deeptutor_enterprise.oms.attempts import AttemptRequest, OmsAttemptLedger, QuotaUnavailable
    from deeptutor_enterprise.oms.ledger import GrantRequest, InsufficientSupply, OmsGrantLedger
    from deeptutor_enterprise.oms.supply import OmsSupplyLedger, SupplyRejected

    await _setup(pg_dsn)
    scope = GlobalScope("platform-operator")
    tenant_id = uuid4()
    now = datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','synthetic')",
            (tenant_id,),
        )
        await c.execute(
            "INSERT INTO oms.tenant_service_entitlements"
            "(tenant_id,service_id,starts_at,expires_at,created_by) "
            "VALUES(%s,'search',%s,%s,'platform-operator')",
            (tenant_id, now - timedelta(days=1), now + timedelta(days=10)),
        )
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-supply") as db:
        ledger = OmsSupplyLedger(db)
        for basis in ("money", "credits", "paygo"):
            request = _supply(basis=basis, ceiling=None)
            await ledger.register(scope, request)
            with pytest.raises(SupplyRejected, match="native ceiling"):
                await ledger.register(
                    scope,
                    replace(request, lot_id=uuid4(), hard_ceiling=Decimal("100")),
                )
            with pytest.raises(InsufficientSupply):
                await OmsGrantLedger(db).grant(
                    TenantScope(str(tenant_id), "platform-operator"),
                    GrantRequest(
                        grant_id=uuid4(),
                        service_id="search",
                        unit_code="request",
                        acquisition_method="gift",
                        quantity=Decimal("1"),
                        starts_at=now,
                        expires_at=now + timedelta(days=1),
                        provider_id="provider-a",
                        provider_account_id="account-a",
                        pool_id="pool-a",
                        source_ref=f"synthetic://{basis}",
                        actor_subject="platform-operator",
                        request_id=f"grant-{basis}",
                        idempotency_key=f"grant-{basis}",
                        reason="synthetic",
                        expected_entitlement_version=1,
                    ),
                )
        assert (
            await ledger.available(scope, "search", "provider-a", "account-a", "pool-a", "request")
            == 0
        )
        with pytest.raises(QuotaUnavailable):
            await OmsAttemptLedger(db).reserve(
                TenantScope(str(tenant_id), "learner-1"),
                AttemptRequest(
                    operation_id=uuid4(),
                    attempt_id=uuid4(),
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
                    reserved_units=Decimal("1"),
                ),
            )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"verified_native": "yes"}, "verification flag"),
        ({"hard_ceiling": Decimal("1000000000000000000000000")}, "native ceiling"),
        ({"provider_account_id": "bad\x00account"}, "provider_account_id"),
    ],
)
async def test_supply_rejects_invalid_capacity_and_scope_fields(pg_dsn, change, message):
    from deeptutor_enterprise.oms.supply import OmsSupplyLedger, SupplyRejected

    await _setup(pg_dsn)
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-supply") as db:
        with pytest.raises(SupplyRejected, match=message):
            await OmsSupplyLedger(db).register(
                GlobalScope("platform-operator"), replace(_supply(), **change)
            )


async def test_unverified_and_expired_lots_cannot_grant_or_reserve_but_keep_history(pg_dsn):
    from deeptutor_enterprise.oms.attempts import AttemptRequest, OmsAttemptLedger, QuotaUnavailable
    from deeptutor_enterprise.oms.ledger import GrantRequest, InsufficientSupply, OmsGrantLedger
    from deeptutor_enterprise.oms.supply import OmsSupplyLedger

    await _setup(pg_dsn)
    tenant_id = uuid4()
    now = datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','synthetic')",
            (tenant_id,),
        )
        await c.execute(
            "INSERT INTO oms.tenant_service_entitlements"
            "(tenant_id,service_id,starts_at,expires_at,created_by) "
            "VALUES(%s,'search',%s,%s,'platform-operator')",
            (tenant_id, now - timedelta(days=1), now + timedelta(days=10)),
        )
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-supply") as db:
        supply = OmsSupplyLedger(db)
        platform = GlobalScope("platform-operator")
        unverified = replace(_supply(), lot_id=uuid4(), verified_native=False)
        await supply.register(platform, unverified)
        grant = OmsGrantLedger(db)
        grant_scope = TenantScope(str(tenant_id), "platform-operator")
        request = GrantRequest(
            grant_id=uuid4(),
            service_id="search",
            unit_code="request",
            acquisition_method="gift",
            quantity=Decimal("20"),
            starts_at=now,
            expires_at=now + timedelta(days=1),
            provider_id="provider-a",
            provider_account_id="account-a",
            pool_id="pool-a",
            source_ref="campaign://synthetic",
            actor_subject="platform-operator",
            request_id="grant-1",
            idempotency_key="grant-1",
            reason="synthetic",
            expected_entitlement_version=1,
        )
        with pytest.raises(InsufficientSupply):
            await grant.grant(grant_scope, request)
        valid = replace(_supply(), lot_id=uuid4(), expires_at=now + timedelta(days=1))
        await supply.register(platform, valid)
        with pytest.raises(InsufficientSupply):
            await grant.grant(
                grant_scope,
                replace(
                    request,
                    grant_id=uuid4(),
                    idempotency_key="grant-too-long",
                    expires_at=now + timedelta(days=2),
                ),
            )
        awarded = await grant.grant(
            grant_scope, replace(request, grant_id=uuid4(), idempotency_key="grant-2")
        )
        assert awarded.allocations == ((valid.lot_id, Decimal("20")),)
        attempt_ledger = OmsAttemptLedger(db)
        attempt = AttemptRequest(
            operation_id=uuid4(),
            attempt_id=uuid4(),
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
        )
        learner_scope = TenantScope(str(tenant_id), "learner-1")
        await attempt_ledger.reserve(learner_scope, attempt)
        await attempt_ledger.mark_dispatched(learner_scope, attempt.attempt_id)
        await attempt_ledger.mark_remote_unknown(
            learner_scope, attempt.attempt_id, evidence_ref="timeout://synthetic-6"
        )
        # 批次过期不能释放在途未知用量；后到可信回执仍归属原批次。
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute(
                "UPDATE oms.supply_lots SET expires_at=%s WHERE id=%s",
                (now - timedelta(seconds=1), valid.lot_id),
            )
        assert (
            await supply.available(
                platform, "search", "provider-a", "account-a", "pool-a", "request"
            )
            == 0
        )
        with pytest.raises(InsufficientSupply):
            await grant.grant(
                grant_scope,
                replace(request, grant_id=uuid4(), idempotency_key="grant-3"),
            )
        dispatched_attempt_id = attempt.attempt_id
        attempt = replace(attempt, attempt_id=uuid4(), reserved_units=Decimal("1"))
        with pytest.raises(QuotaUnavailable):
            await attempt_ledger.reserve(learner_scope, attempt)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            in_flight = await (
                await c.execute(
                    "SELECT settled_lifetime,committed_unspent,reserved_inflight "
                    "FROM oms.supply_lots WHERE id=%s",
                    (valid.lot_id,),
                )
            ).fetchone()
        assert in_flight == (0, 14, 6)
        await attempt_ledger.settle(
            learner_scope,
            dispatched_attempt_id,
            units=Decimal("5"),
            source="provider_usage",
            evidence_ref="usage://synthetic-5",
            provider_request_id="provider-request-5",
        )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        history = await (
            await c.execute(
                "SELECT settled_lifetime,committed_unspent,reserved_inflight "
                "FROM oms.supply_lots WHERE id=%s",
                (valid.lot_id,),
            )
        ).fetchone()
    assert history == (5, 14, 0)


async def test_concurrent_grants_against_registered_supply_do_not_overcommit(pg_dsn):
    from deeptutor_enterprise.oms.ledger import GrantRequest, InsufficientSupply, OmsGrantLedger
    from deeptutor_enterprise.oms.supply import OmsSupplyLedger

    await _setup(pg_dsn)
    tenant_id = uuid4()
    now = datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','synthetic')",
            (tenant_id,),
        )
        await c.execute(
            "INSERT INTO oms.tenant_service_entitlements"
            "(tenant_id,service_id,starts_at,expires_at,created_by) "
            "VALUES(%s,'search',%s,%s,'platform-operator')",
            (tenant_id, now - timedelta(days=1), now + timedelta(days=10)),
        )
    async with Database(single_database_user_dsn(pg_dsn), resource="oms-supply") as db:
        supply = OmsSupplyLedger(db)
        lot = replace(_supply(), hard_ceiling=Decimal("30"))
        await supply.register(GlobalScope("platform-operator"), lot)
        ledger = OmsGrantLedger(db)
        scope = TenantScope(str(tenant_id), "platform-operator")

        def grant_request():
            return GrantRequest(
                grant_id=uuid4(),
                service_id="search",
                unit_code="request",
                acquisition_method="recharge",
                quantity=Decimal("20"),
                starts_at=now,
                expires_at=now + timedelta(days=1),
                provider_id="provider-a",
                provider_account_id="account-a",
                pool_id="pool-a",
                source_ref="synthetic://purchase",
                actor_subject="platform-operator",
                request_id=str(uuid4()),
                idempotency_key=str(uuid4()),
                reason="synthetic",
                expected_entitlement_version=1,
            )

        results = await asyncio.gather(
            ledger.grant(scope, grant_request()),
            ledger.grant(scope, grant_request()),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, Exception) for item in results) == 1
        assert sum(isinstance(item, InsufficientSupply) for item in results) == 1
        assert await supply.available(
            GlobalScope("platform-operator"),
            "search",
            "provider-a",
            "account-a",
            "pool-a",
            "request",
        ) == Decimal("10")
