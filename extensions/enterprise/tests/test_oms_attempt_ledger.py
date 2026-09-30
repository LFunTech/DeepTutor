"""OMS 内部 attempt 的预留/发出/未知/结算以临时 PG 合成数据验证。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import re
import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.stores.postgres.connection import Database
import psycopg
import pytest

from deeptutor.persistence.postgres.scope import TenantScope
from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


async def _ledger(pg_dsn):
    from deeptutor_enterprise.oms.ledger import GrantRequest, OmsGrantLedger

    await MigrationRunner(pg_dsn).apply()
    tenant_id, lot_id = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','test-epoch')",
            (tenant_id,),
        )
        await c.execute(
            "INSERT INTO oms.service_definitions(service_id,unit_code,resource_category,enabled) "
            "VALUES('llm','token','model_external',true)"
        )
        await c.execute(
            "INSERT INTO oms.tenant_service_entitlements"
            "(tenant_id,service_id,starts_at,expires_at,created_by) "
            "VALUES(%s,'llm',%s,%s,'platform-operator')",
            (tenant_id, now - timedelta(days=1), now + timedelta(days=10)),
        )
        await c.execute(
            "INSERT INTO oms.supply_lots"
            "(id,service_id,provider_id,provider_account_id,pool_id,unit_code,evidence_ref,"
            "hard_ceiling,starts_at,expires_at,supply_basis,verified_at) "
            "VALUES(%s,'llm','provider-a','account-a','pool-a','token',"
            "'contract://synthetic/llm',100,%s,%s,'native_units',now())",
            (lot_id, now - timedelta(days=1), now + timedelta(days=3)),
        )

    db = Database(single_database_user_dsn(pg_dsn), resource="oms-attempt-test")
    await db.__aenter__()
    grant_scope = TenantScope(str(tenant_id), "platform-operator")
    grant_ledger = OmsGrantLedger(db)
    grants = []
    for method, quantity in (("gift", 30), ("recharge", 50)):
        grant_id = uuid.uuid4()
        await grant_ledger.grant(
            grant_scope,
            GrantRequest(
                grant_id=grant_id,
                service_id="llm",
                unit_code="token",
                acquisition_method=method,
                quantity=Decimal(quantity),
                starts_at=now,
                expires_at=now + timedelta(days=2),
                provider_id="provider-a",
                provider_account_id="account-a",
                pool_id="pool-a",
                source_ref=f"synthetic://{method}",
                actor_subject="platform-operator",
                request_id=f"grant-{method}",
                idempotency_key=f"grant-{method}",
                reason="synthetic test",
                expected_entitlement_version=1,
            ),
        )
        grants.append(grant_id)
    return db, tenant_id, lot_id, tuple(grants)


def _request(*, operation_id=None, attempt_id=None, units=45):
    from deeptutor_enterprise.oms.attempts import AttemptRequest

    return AttemptRequest(
        operation_id=operation_id or uuid.uuid4(),
        attempt_id=attempt_id or uuid.uuid4(),
        service_id="llm",
        unit_code="token",
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


async def _balances(pg_dsn, tenant_id, lot_id):
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
        lot = await (
            await c.execute(
                "SELECT settled_lifetime,committed_unspent,reserved_inflight "
                "FROM oms.supply_lots WHERE id=%s",
                (lot_id,),
            )
        ).fetchone()
        grants = await (
            await c.execute(
                "SELECT g.acquisition_method,gc.unspent,gc.reserved,gc.settled,gc.released "
                "FROM oms.grant_commitments gc JOIN oms.quota_grants g ON g.id=gc.grant_id "
                "WHERE gc.tenant_id=%s ORDER BY g.acquisition_method",
                (tenant_id,),
            )
        ).fetchall()
    return lot, {row[0]: tuple(row[1:]) for row in grants}


async def test_quota_exhaustion_does_not_change_webhook_school_eligibility(pg_dsn):
    """服务额度门禁不得冒充 EduPlus2 订阅暂停，也不拦管理入口。"""

    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger, QuotaUnavailable

    db, tenant_id, _, _ = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    try:
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            before = await (
                await c.execute(
                    "SELECT external_eligibility,local_enabled,auth_epoch "
                    "FROM enterprise.tenants WHERE id=%s",
                    (tenant_id,),
                )
            ).fetchone()
        with pytest.raises(QuotaUnavailable):
            await OmsAttemptLedger(db).reserve(scope, _request(units=81))
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            tenant = await (
                await c.execute(
                    "SELECT external_eligibility,local_enabled,auth_epoch "
                    "FROM enterprise.tenants WHERE id=%s",
                    (tenant_id,),
                )
            ).fetchone()
        assert before[0] == "allowed"
        assert tenant == before
    finally:
        await db.__aexit__(None, None, None)


async def test_attempt_gift_first_unknown_keeps_reservation_and_settles_once(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger, SettlementRejected

    db, tenant_id, lot_id, grants = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    request = _request(units=45)
    try:
        ledger = OmsAttemptLedger(db)
        reservation = await ledger.reserve(scope, request)
        assert reservation.allocations == (
            (grants[0], lot_id, Decimal("30")),
            (grants[1], lot_id, Decimal("15")),
        )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 35, 45),
            {"gift": (0, 30, 0, 0), "recharge": (35, 15, 0, 0)},
        )

        await ledger.mark_dispatched(scope, request.attempt_id)
        await ledger.mark_remote_unknown(
            scope, request.attempt_id, evidence_ref="timeout://synthetic-1"
        )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 35, 45),
            {"gift": (0, 30, 0, 0), "recharge": (35, 15, 0, 0)},
        )

        result = await ledger.settle(
            scope,
            request.attempt_id,
            units=Decimal("40"),
            source="provider_usage",
            evidence_ref="usage://synthetic-1",
            provider_request_id="provider-request-1",
        )
        assert result.settled_units == Decimal("40")
        assert (
            await ledger.settle(
                scope,
                request.attempt_id,
                units=Decimal("40"),
                source="provider_usage",
                evidence_ref="usage://synthetic-1",
                provider_request_id="provider-request-1",
            )
            == result
        )
        with pytest.raises(SettlementRejected):
            await ledger.settle(
                scope,
                request.attempt_id,
                units=Decimal("41"),
                source="provider_usage",
                evidence_ref="usage://synthetic-1",
                provider_request_id="provider-request-1",
            )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (40, 40, 0),
            {"gift": (0, 0, 30, 0), "recharge": (40, 0, 10, 0)},
        )
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            events = await (
                await c.execute(
                    "SELECT event_kind FROM oms.attempt_evidence_events "
                    "WHERE tenant_id=%s AND attempt_id=%s ORDER BY created_at,id",
                    (tenant_id, request.attempt_id),
                )
            ).fetchall()
        assert [row[0] for row in events] == [
            "dispatch_intent",
            "remote_unknown",
            "provider_usage",
        ]
    finally:
        await db.__aexit__(None, None, None)


async def test_provider_request_receipt_reconciles_original_attempt_once(pg_dsn):
    """按供应商 request ID 对账时必须回到原 attempt，重复回执不能双扣。"""

    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger, SettlementRejected

    db, tenant_id, lot_id, _ = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    request = _request(units=12)
    try:
        ledger = OmsAttemptLedger(db)
        await ledger.reserve(scope, request)
        await ledger.mark_dispatched(
            scope,
            request.attempt_id,
            evidence_ref="dispatch://request-id-1",
            provider_request_id="provider-request-id-1",
        )
        result = await ledger.settle_provider_receipt(
            scope,
            provider_id="provider-a",
            provider_account_id="account-a",
            provider_request_id="provider-request-id-1",
            units=Decimal("9"),
            evidence_ref="bill://provider-request-id-1",
        )
        assert result.attempt_id == request.attempt_id
        assert result.settled_units == Decimal("9")
        assert (
            await ledger.settle_provider_receipt(
                scope,
                provider_id="provider-a",
                provider_account_id="account-a",
                provider_request_id="provider-request-id-1",
                units=Decimal("9"),
                evidence_ref="bill://provider-request-id-1",
            )
            == result
        )
        with pytest.raises(SettlementRejected, match="provider receipt"):
            await ledger.settle_provider_receipt(
                scope,
                provider_id="provider-a",
                provider_account_id="account-a",
                provider_request_id="provider-missing",
                units=Decimal("1"),
                evidence_ref="bill://provider-missing",
            )
        with pytest.raises(SettlementRejected, match="conflicts"):
            await ledger.mark_dispatched(
                scope,
                request.attempt_id,
                evidence_ref="dispatch://request-id-2",
                provider_request_id="provider-request-id-2",
            )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (9, 71, 0),
            {"gift": (21, 0, 9, 0), "recharge": (50, 0, 0, 0)},
        )
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            attempt = await (
                await c.execute(
                    "SELECT status,provider_request_id,settled_units "
                    "FROM oms.usage_attempts WHERE tenant_id=%s AND attempt_id=%s",
                    (tenant_id, request.attempt_id),
                )
            ).fetchone()
            events = await (
                await c.execute(
                    "SELECT event_kind,provider_request_id FROM oms.attempt_evidence_events "
                    "WHERE tenant_id=%s AND attempt_id=%s ORDER BY created_at,id",
                    (tenant_id, request.attempt_id),
                )
            ).fetchall()
        assert attempt == ("settled", "provider-request-id-1", Decimal("9.000000"))
        assert events == [
            ("dispatch_intent", "provider-request-id-1"),
            ("provider_usage", "provider-request-id-1"),
        ]
    finally:
        await db.__aexit__(None, None, None)


async def test_metered_provider_attempt_runner_settles_or_marks_unknown(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger
    from deeptutor_enterprise.oms.call_context import (
        ProviderAttemptReceipt,
        UsageCallContext,
        run_metered_provider_attempt,
    )

    db, tenant_id, lot_id, _ = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    try:
        ledger = OmsAttemptLedger(db)
        context = UsageCallContext(
            tenant_id=tenant_id,
            operation_id=uuid.uuid4(),
            service_id="llm",
            unit_code="token",
            provider_id="provider-a",
            provider_account_id="account-a",
            pool_id="pool-a",
            model_id="model-a",
            config_version=1,
            subject_kind="user",
            subject_id="learner-1",
            user_id="learner-1",
        )

        async def successful_call(attempt_id):
            assert isinstance(attempt_id, uuid.UUID)
            return ProviderAttemptReceipt(
                result={"content": "ok"},
                units=Decimal("6"),
                evidence_ref="usage://runner-success",
                provider_request_id="provider-runner-success",
            )

        result = await run_metered_provider_attempt(
            ledger,
            scope,
            context,
            reserved_units=Decimal("10"),
            dispatch_evidence_ref="dispatch://runner-success",
            unknown_evidence_ref="timeout://runner-success",
            call=successful_call,
        )
        assert result == {"content": "ok"}

        failing_context = replace(context, operation_id=uuid.uuid4())

        async def failing_call(_attempt_id):
            raise TimeoutError("network timeout after dispatch")

        with pytest.raises(TimeoutError):
            await run_metered_provider_attempt(
                ledger,
                scope,
                failing_context,
                reserved_units=Decimal("5"),
                dispatch_evidence_ref="dispatch://runner-timeout",
                unknown_evidence_ref="timeout://runner-timeout",
                call=failing_call,
            )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (6, 69, 5),
            {"gift": (19, 5, 6, 0), "recharge": (50, 0, 0, 0)},
        )
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            rows = await (
                await c.execute(
                    "SELECT status,provider_request_id,settled_units FROM oms.usage_attempts "
                    "WHERE tenant_id=%s ORDER BY started_at,attempt_id",
                    (tenant_id,),
                )
            ).fetchall()
            events = await (
                await c.execute(
                    "SELECT event_kind,reference,provider_request_id "
                    "FROM oms.attempt_evidence_events WHERE tenant_id=%s "
                    "ORDER BY created_at,id",
                    (tenant_id,),
                )
            ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("settled", "provider-runner-success", Decimal("6.000000")),
            ("remote_unknown", "", Decimal("0.000000")),
        ]
        assert ("provider_usage", "usage://runner-success", "provider-runner-success") in [
            tuple(row) for row in events
        ]
        assert ("remote_unknown", "timeout://runner-timeout", "") in [
            tuple(row) for row in events
        ]
    finally:
        await db.__aexit__(None, None, None)


async def test_confirmed_not_sent_can_release_but_dispatched_cannot(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger, SettlementRejected

    db, tenant_id, lot_id, _ = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    try:
        ledger = OmsAttemptLedger(db)
        first = _request(units=20)
        await ledger.reserve(scope, first)
        await ledger.release_before_dispatch(
            scope, first.attempt_id, evidence_ref="local-validation://synthetic-1"
        )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 80, 0),
            {"gift": (30, 0, 0, 0), "recharge": (50, 0, 0, 0)},
        )
        second = _request(units=20)
        await ledger.reserve(scope, second)
        await ledger.mark_dispatched(scope, second.attempt_id)
        with pytest.raises(SettlementRejected):
            await ledger.release_before_dispatch(
                scope, second.attempt_id, evidence_ref="unverified://synthetic-2"
            )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 60, 20),
            {"gift": (10, 20, 0, 0), "recharge": (50, 0, 0, 0)},
        )
    finally:
        await db.__aexit__(None, None, None)


async def test_overage_requires_reconciliation_without_freeing_reservation(pg_dsn):
    from deeptutor_enterprise.oms.attempts import (
        OmsAttemptLedger,
        SettlementRejected,
        UsageExceedsReservation,
    )

    db, tenant_id, lot_id, _ = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    request = _request(units=15)
    try:
        ledger = OmsAttemptLedger(db)
        await ledger.reserve(scope, request)
        await ledger.mark_dispatched(scope, request.attempt_id)
        with pytest.raises(UsageExceedsReservation):
            await ledger.settle(
                scope,
                request.attempt_id,
                units=Decimal("18"),
                source="provider_usage",
                evidence_ref="usage://overage-1",
                provider_request_id="provider-overage-1",
            )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 65, 15),
            {"gift": (15, 15, 0, 0), "recharge": (50, 0, 0, 0)},
        )
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            row = await (
                await c.execute(
                    "SELECT status,settled_units FROM oms.usage_attempts "
                    "WHERE tenant_id=%s AND attempt_id=%s",
                    (tenant_id, request.attempt_id),
                )
            ).fetchone()
        assert row == ("reconcile_required", 0)
        with pytest.raises(SettlementRejected, match="reconciliation"):
            await ledger.settle(
                scope,
                request.attempt_id,
                units=Decimal("12"),
                source="provider_usage",
                evidence_ref="usage://later-smaller",
                provider_request_id="provider-overage-1",
            )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 65, 15),
            {"gift": (15, 15, 0, 0), "recharge": (50, 0, 0, 0)},
        )
    finally:
        await db.__aexit__(None, None, None)


async def test_competing_reservations_cannot_exceed_effective_quota(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger, QuotaUnavailable

    db, tenant_id, lot_id, _ = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    operation_id = uuid.uuid4()
    try:
        ledger = OmsAttemptLedger(db)
        requests = [_request(operation_id=operation_id, units=45) for _ in range(2)]
        results = await asyncio.wait_for(
            asyncio.gather(
                *(ledger.reserve(scope, request) for request in requests),
                return_exceptions=True,
            ),
            timeout=5,
        )
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert sum(isinstance(result, QuotaUnavailable) for result in results) == 1
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 35, 45),
            {"gift": (0, 30, 0, 0), "recharge": (35, 15, 0, 0)},
        )
    finally:
        await db.__aexit__(None, None, None)


async def test_corrupt_commitment_fails_closed_without_releasing_supply(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger, SettlementRejected

    db, tenant_id, lot_id, grants = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    request = _request(units=15)
    try:
        ledger = OmsAttemptLedger(db)
        await ledger.reserve(scope, request)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            await c.execute(
                "UPDATE oms.grant_commitments SET reserved=0,unspent=30 "
                "WHERE tenant_id=%s AND grant_id=%s AND lot_id=%s",
                (tenant_id, grants[0], lot_id),
            )
        with pytest.raises(SettlementRejected, match="commitment"):
            await ledger.release_before_dispatch(
                scope, request.attempt_id, evidence_ref="not-sent://synthetic"
            )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 65, 15),
            {"gift": (30, 0, 0, 0), "recharge": (50, 0, 0, 0)},
        )
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            row = await (
                await c.execute(
                    "SELECT status FROM oms.usage_attempts WHERE tenant_id=%s AND attempt_id=%s",
                    (tenant_id, request.attempt_id),
                )
            ).fetchone()
        assert row == ("reserved",)
    finally:
        await db.__aexit__(None, None, None)


async def test_release_and_idempotent_replay_use_same_pool_lock_order(pg_dsn, monkeypatch):
    import deeptutor_enterprise.oms.attempts as attempts

    db, tenant_id, lot_id, _ = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    request = _request(units=10)
    try:
        ledger = attempts.OmsAttemptLedger(db)
        await ledger.reserve(scope, request)
        replay_has_pool = asyncio.Event()
        release_waiting_for_pool = asyncio.Event()
        resume_replay = asyncio.Event()
        original_pool_lock = attempts._pool_lock

        async def synchronized_pool_lock(*args):
            task = asyncio.current_task()
            if task is not None and task.get_name() == "release":
                release_waiting_for_pool.set()
            await original_pool_lock(*args)
            if task is not None and task.get_name() == "replay":
                replay_has_pool.set()
                await resume_replay.wait()

        monkeypatch.setattr(attempts, "_pool_lock", synchronized_pool_lock)
        replay = asyncio.create_task(ledger.reserve(scope, request), name="replay")
        await asyncio.wait_for(replay_has_pool.wait(), timeout=3)
        release = asyncio.create_task(
            ledger.release_before_dispatch(
                scope, request.attempt_id, evidence_ref="not-sent://race"
            ),
            name="release",
        )
        await asyncio.wait_for(release_waiting_for_pool.wait(), timeout=3)
        resume_replay.set()
        reservation, _ = await asyncio.wait_for(asyncio.gather(replay, release), timeout=3)
        assert reservation.status == "reserved"
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 80, 0),
            {"gift": (30, 0, 0, 0), "recharge": (50, 0, 0, 0)},
        )
    finally:
        await db.__aexit__(None, None, None)


async def test_one_operation_can_have_two_billable_attempts(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger

    db, tenant_id, lot_id, _ = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    operation_id = uuid.uuid4()
    try:
        ledger = OmsAttemptLedger(db)
        for index in (1, 2):
            request = _request(operation_id=operation_id, units=10)
            await ledger.reserve(scope, request)
            await ledger.mark_dispatched(scope, request.attempt_id)
            await ledger.settle(
                scope,
                request.attempt_id,
                units=Decimal("8"),
                source="provider_usage",
                evidence_ref=f"usage://retry-{index}",
                provider_request_id=f"provider-retry-{index}",
            )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (16, 64, 0),
            {"gift": (14, 0, 16, 0), "recharge": (50, 0, 0, 0)},
        )
    finally:
        await db.__aexit__(None, None, None)


async def test_missing_allocation_cannot_release_reserved_attempt(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger, SettlementRejected

    db, tenant_id, lot_id, _ = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    request = _request(units=10)
    try:
        ledger = OmsAttemptLedger(db)
        await ledger.reserve(scope, request)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            await c.execute(
                "DELETE FROM oms.attempt_allocations WHERE tenant_id=%s AND attempt_id=%s",
                (tenant_id, request.attempt_id),
            )
        with pytest.raises(SettlementRejected, match="allocation"):
            await ledger.release_before_dispatch(
                scope, request.attempt_id, evidence_ref="not-sent://missing-allocation"
            )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 70, 10),
            {"gift": (20, 10, 0, 0), "recharge": (50, 0, 0, 0)},
        )
    finally:
        await db.__aexit__(None, None, None)


async def test_reservation_replay_survives_later_entitlement_revocation(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger

    db, tenant_id, lot_id, _ = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    request = _request(units=10)
    try:
        ledger = OmsAttemptLedger(db)
        original = await ledger.reserve(scope, request)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            await c.execute(
                "UPDATE oms.tenant_service_entitlements SET status='revoked',version=version+1 "
                "WHERE tenant_id=%s AND service_id='llm'",
                (tenant_id,),
            )
        assert await ledger.reserve(scope, request) == original
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 70, 10),
            {"gift": (20, 10, 0, 0), "recharge": (50, 0, 0, 0)},
        )
    finally:
        await db.__aexit__(None, None, None)


async def test_revoke_grant_releases_only_unspent_and_preserves_inflight(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger, QuotaUnavailable
    from deeptutor_enterprise.oms.ledger import GrantRejected, OmsGrantLedger, RevokeRequest

    db, tenant_id, lot_id, grants = await _ledger(pg_dsn)
    learner_scope = TenantScope(str(tenant_id), "learner-1")
    operator_scope = TenantScope(str(tenant_id), "platform-operator")
    request = _request(units=20)
    try:
        attempts = OmsAttemptLedger(db)
        grants_ledger = OmsGrantLedger(db)
        await attempts.reserve(learner_scope, request)
        revoke = RevokeRequest(
            grant_id=grants[0],
            expected_version=1,
            actor_subject="platform-operator",
            request_id="revoke-gift-1",
            idempotency_key="revoke-gift-1",
            reason="synthetic policy correction",
        )
        first = await grants_ledger.revoke(operator_scope, revoke)
        assert first.released_units == Decimal("10")
        assert await grants_ledger.revoke(operator_scope, revoke) == first
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 50, 20),
            {"gift": (0, 20, 0, 10), "recharge": (50, 0, 0, 0)},
        )
        with pytest.raises(QuotaUnavailable):
            await attempts.reserve(learner_scope, _request(units=60))
        await attempts.mark_dispatched(learner_scope, request.attempt_id)
        await attempts.settle(
            learner_scope,
            request.attempt_id,
            units=Decimal("12"),
            source="provider_usage",
            evidence_ref="usage://after-revoke",
            provider_request_id="provider-after-revoke",
        )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (12, 50, 0),
            {"gift": (0, 0, 12, 18), "recharge": (50, 0, 0, 0)},
        )
        assert await grants_ledger.revoke(operator_scope, revoke) == first
        with pytest.raises(GrantRejected, match="version"):
            await grants_ledger.revoke(
                operator_scope, replace(revoke, idempotency_key="new-revoke-command")
            )
        with pytest.raises(GrantRejected, match="idempotency"):
            await grants_ledger.revoke(operator_scope, replace(revoke, reason="different reason"))
    finally:
        await db.__aexit__(None, None, None)


async def test_expire_grant_releases_only_unspent_and_keeps_unknown_attempt(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger
    from deeptutor_enterprise.oms.ledger import (
        ExpireRequest,
        GrantRejected,
        OmsGrantLedger,
    )

    db, tenant_id, lot_id, grants = await _ledger(pg_dsn)
    learner_scope = TenantScope(str(tenant_id), "learner-1")
    worker_scope = TenantScope(str(tenant_id), "oms-expiry-worker")
    request = _request(units=20)
    try:
        attempts = OmsAttemptLedger(db)
        ledger = OmsGrantLedger(db)
        await attempts.reserve(learner_scope, request)
        await attempts.mark_dispatched(learner_scope, request.attempt_id)
        await attempts.mark_remote_unknown(
            learner_scope, request.attempt_id, evidence_ref="timeout://expiry-test"
        )
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            await c.execute(
                "UPDATE oms.quota_grants SET starts_at=now()-interval '2 days',"
                "expires_at=now()-interval '1 second' "
                "WHERE tenant_id=%s AND id=%s",
                (tenant_id, grants[0]),
            )
        expire = ExpireRequest(
            grant_id=grants[0],
            expected_version=1,
            actor_subject="oms-expiry-worker",
            request_id="expiry-1",
            idempotency_key="expiry-1",
            reason="validity elapsed",
        )
        result = await ledger.expire(worker_scope, expire)
        assert result.version == 2
        assert result.released_units == Decimal("10")
        assert await ledger.expire(worker_scope, expire) == result
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 50, 20),
            {"gift": (0, 20, 0, 10), "recharge": (50, 0, 0, 0)},
        )
        await attempts.settle(
            learner_scope,
            request.attempt_id,
            units=Decimal("12"),
            source="provider_usage",
            evidence_ref="usage://after-expiry",
            provider_request_id="provider-after-expiry",
        )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (12, 50, 0),
            {"gift": (0, 0, 12, 18), "recharge": (50, 0, 0, 0)},
        )
        with pytest.raises(GrantRejected, match="version"):
            await ledger.expire(worker_scope, replace(expire, idempotency_key="expiry-2"))
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            state = await (
                await c.execute(
                    "SELECT status,version FROM oms.quota_grants WHERE tenant_id=%s AND id=%s",
                    (tenant_id, grants[0]),
                )
            ).fetchone()
            audit = await (
                await c.execute(
                    "SELECT action,result FROM oms.audit_events WHERE object_id=%s "
                    "AND action='quota.expire'",
                    (str(grants[0]),),
                )
            ).fetchall()
        assert state == ("expired", 2)
        assert audit == [("quota.expire", "success")]
    finally:
        await db.__aexit__(None, None, None)


async def test_grant_cannot_expire_before_its_deadline(pg_dsn):
    from deeptutor_enterprise.oms.ledger import ExpireRequest, GrantRejected, OmsGrantLedger

    db, tenant_id, lot_id, grants = await _ledger(pg_dsn)
    request = ExpireRequest(
        grant_id=grants[0],
        expected_version=1,
        actor_subject="oms-expiry-worker",
        request_id="early-expiry",
        idempotency_key="early-expiry",
        reason="scheduled expiry",
    )
    try:
        with pytest.raises(GrantRejected, match="not expired"):
            await OmsGrantLedger(db).expire(
                TenantScope(str(tenant_id), "oms-expiry-worker"), request
            )
        assert await _balances(pg_dsn, tenant_id, lot_id) == (
            (0, 80, 0),
            {"gift": (30, 0, 0, 0), "recharge": (50, 0, 0, 0)},
        )
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            commands = await (
                await c.execute(
                    "SELECT action FROM oms.grant_commands WHERE grant_id=%s "
                    "AND action='quota.expire'",
                    (grants[0],),
                )
            ).fetchall()
        assert commands == []
    finally:
        await db.__aexit__(None, None, None)


async def test_attempt_evidence_and_audit_facts_are_append_only(pg_dsn):
    from deeptutor_enterprise.oms.attempts import OmsAttemptLedger

    db, tenant_id, _, _ = await _ledger(pg_dsn)
    scope = TenantScope(str(tenant_id), "learner-1")
    request = _request(units=10)
    try:
        ledger = OmsAttemptLedger(db)
        await ledger.reserve(scope, request)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            before = await (
                await c.execute(
                    "SELECT event_kind,reference FROM oms.attempt_evidence_events "
                    "WHERE tenant_id=%s AND attempt_id=%s ORDER BY created_at,id",
                    (tenant_id, request.attempt_id),
                )
            ).fetchall()
        await ledger.mark_dispatched(scope, request.attempt_id)
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_id),))
            after = await (
                await c.execute(
                    "SELECT event_kind,reference FROM oms.attempt_evidence_events "
                    "WHERE tenant_id=%s AND attempt_id=%s ORDER BY created_at,id",
                    (tenant_id, request.attempt_id),
                )
            ).fetchall()
        assert len(after) == len(before) + 1
        assert after[:len(before)] == before
        assert after[-1][0] == "dispatch_intent"
    finally:
        await db.__aexit__(None, None, None)


async def test_oms_application_has_no_fact_mutation_sql():
    source = Path(__file__).parents[1] / "src/deeptutor_enterprise/oms"
    forbidden = re.compile(
        r"\b(?:UPDATE|DELETE\s+FROM)\s+oms\.(?:attempt_evidence_events|audit_events)\b",
        re.IGNORECASE,
    )
    for path in source.rglob("*.py"):
        assert not forbidden.search(path.read_text(encoding="utf8")), path
