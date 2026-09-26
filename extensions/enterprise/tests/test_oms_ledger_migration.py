"""OMS 账务表只通过企业版本化迁移进入隔离的合成 PostgreSQL。"""

from __future__ import annotations

import asyncio
import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
import psycopg
import pytest

from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


async def test_oms_ledger_migration_is_versioned_and_repeatable(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    assert {
        "oms/0001_ledger_base",
        "oms/0002_grant_source",
        "oms/0003_grant_command_idempotency",
        "oms/0004_attempt_lifecycle",
        "oms/0005_command_result_summary",
        "oms/0006_append_only_facts",
    } <= set(await runner.plan())

    await runner.apply()
    await runner.apply()
    await runner.verify()
    assert await runner.plan() == []

    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        history = await (
            await connection.execute("SELECT version FROM oms.schema_history ORDER BY version")
        ).fetchall()
        tables = await (
            await connection.execute(
                """
                SELECT relname,relrowsecurity,relforcerowsecurity
                  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                 WHERE n.nspname='oms' AND c.relkind='r'
                """
            )
        ).fetchall()
    assert history == [
        ("0001_ledger_base",),
        ("0002_grant_source",),
        ("0003_grant_command_idempotency",),
        ("0004_attempt_lifecycle",),
        ("0005_command_result_summary",),
        ("0006_append_only_facts",),
    ]
    assert {row[0]: tuple(row[1:]) for row in tables} == {
        "schema_history": (False, False),
        "service_definitions": (False, False),
        "supply_lots": (False, False),
        "grant_commands": (False, False),
        "tenant_service_entitlements": (True, True),
        "quota_grants": (True, True),
        "grant_commitments": (True, True),
        "usage_attempts": (True, True),
        "attempt_allocations": (True, True),
        "attempt_evidence_events": (True, True),
        "audit_events": (False, False),
    }


async def test_oms_schema_drift_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute("ALTER TABLE oms.usage_attempts DISABLE ROW LEVEL SECURITY")

    with pytest.raises(RuntimeError, match="oms schema drift"):
        await runner.verify()


async def test_oms_attempt_lifecycle_constraint_drift_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "ALTER TABLE oms.usage_attempts DROP CONSTRAINT usage_attempts_status_check"
        )
    with pytest.raises(RuntimeError, match="oms schema drift"):
        await runner.verify()


async def test_oms_command_result_drift_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "ALTER TABLE oms.grant_commands DROP CONSTRAINT grant_commands_result_summary_object"
        )
    with pytest.raises(RuntimeError, match="oms schema drift"):
        await runner.verify()


async def test_oms_append_only_trigger_drift_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "DROP TRIGGER attempt_evidence_append_only ON oms.attempt_evidence_events"
        )
    with pytest.raises(RuntimeError, match="oms schema drift"):
        await runner.verify()


async def test_oms_checksum_and_index_drift_block_apply(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute("DROP INDEX oms.usage_attempts_provider_receipt")
    with pytest.raises(RuntimeError, match="oms schema drift"):
        await runner.apply()

    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "UPDATE oms.schema_history SET checksum='tampered' WHERE version='0001_ledger_base'"
        )
    with pytest.raises(RuntimeError, match="oms schema history drift"):
        await runner.plan()


async def test_oms_tenant_rls_applies_to_runtime_table_owner(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        for tenant_id in (tenant_a, tenant_b):
            await connection.execute(
                "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
                "VALUES(%s,'allowed','test-epoch')",
                (tenant_id,),
            )
        await connection.execute(
            "INSERT INTO oms.service_definitions(service_id,unit_code,resource_category) "
            "VALUES('image','image','model_external')"
        )
        for tenant_id in (tenant_a, tenant_b):
            await connection.execute(
                "INSERT INTO oms.tenant_service_entitlements"
                "(tenant_id,service_id,starts_at,expires_at,created_by) "
                "VALUES(%s,'image',now(),now()+interval '1 day','test')",
                (tenant_id,),
            )

    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant_a),))
        visible = await (
            await connection.execute("SELECT tenant_id FROM oms.tenant_service_entitlements")
        ).fetchall()
        assert visible == [(tenant_a,)]


async def _seed_lot(dsn, *, committed: int, settled: int = 0, reserved: int = 0):
    lot_id = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute(
            "INSERT INTO oms.service_definitions(service_id,unit_code,resource_category) "
            "VALUES('llm','token','model_external')"
        )
        await connection.execute(
            """
            INSERT INTO oms.supply_lots(
              id,service_id,provider_id,pool_id,unit_code,evidence_ref,hard_ceiling,
              settled_lifetime,committed_unspent,reserved_inflight,starts_at,expires_at
            ) VALUES(%s,'llm','provider-a','pool-a','token','contract://test/lot',100,
                     %s,%s,%s,now()-interval '1 hour',now()+interval '1 day')
            """,
            (lot_id, settled, committed, reserved),
        )
    return lot_id


async def test_supply_counter_transfer_does_not_double_count_reservation(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    lot_id = await _seed_lot(pg_dsn, committed=50, settled=20, reserved=10)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:

        async def remaining():
            row = await (
                await connection.execute(
                    "SELECT hard_ceiling-settled_lifetime-committed_unspent-reserved_inflight "
                    "FROM oms.supply_lots WHERE id=%s",
                    (lot_id,),
                )
            ).fetchone()
            return row[0]

        assert await remaining() == 20
        await connection.execute(
            "UPDATE oms.supply_lots SET committed_unspent=35,reserved_inflight=25 WHERE id=%s",
            (lot_id,),
        )
        assert await remaining() == 20
        await connection.execute(
            "UPDATE oms.supply_lots SET settled_lifetime=32,committed_unspent=38,"
            "reserved_inflight=10 WHERE id=%s",
            (lot_id,),
        )
        assert await remaining() == 20
        await connection.execute(
            "UPDATE oms.supply_lots SET starts_at=now()-interval '2 days',"
            "expires_at=now()-interval '1 day' WHERE id=%s",
            (lot_id,),
        )
        historic = await (
            await connection.execute(
                "SELECT settled_lifetime,committed_unspent,reserved_inflight,expires_at<now() "
                "FROM oms.supply_lots WHERE id=%s",
                (lot_id,),
            )
        ).fetchone()
        assert tuple(historic[:3]) == (32, 38, 10)
        assert historic[3] is True


async def test_supply_ceiling_is_safe_under_competing_transactions(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    lot_id = await _seed_lot(pg_dsn, committed=70)

    async def grant_twenty():
        async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
            row = await (
                await connection.execute(
                    """
                    UPDATE oms.supply_lots
                       SET committed_unspent=committed_unspent+20
                     WHERE id=%s AND hard_ceiling IS NOT NULL
                       AND hard_ceiling-settled_lifetime-committed_unspent-reserved_inflight>=20
                    RETURNING committed_unspent
                    """,
                    (lot_id,),
                )
            ).fetchone()
            return row is not None

    results = await asyncio.gather(grant_twenty(), grant_twenty())
    assert sorted(results) == [False, True]
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT committed_unspent FROM oms.supply_lots WHERE id=%s", (lot_id,)
            )
        ).fetchone()
        assert row[0] == 90
        with pytest.raises(psycopg.errors.CheckViolation):
            await connection.execute(
                "UPDATE oms.supply_lots SET committed_unspent=101 WHERE id=%s", (lot_id,)
            )


async def test_operation_allows_distinct_billable_attempts_but_deduplicates_receipts(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    tenant_id, operation_id = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','test-epoch')",
            (tenant_id,),
        )
        await connection.execute(
            "INSERT INTO oms.service_definitions(service_id,unit_code,resource_category) "
            "VALUES('llm','token','model_external')"
        )

    async def insert_attempt(attempt_id, receipt):
        async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
            await connection.execute(
                """
                INSERT INTO oms.usage_attempts(
                  tenant_id,attempt_id,operation_id,service_id,unit_code,provider_id,
                  provider_account_id,config_version,subject_kind,subject_id,
                  provider_request_id,reserved_units
                ) VALUES(%s,%s,%s,'llm','token','provider-a','account-a',1,
                         'user','user-1',%s,10)
                """,
                (tenant_id, attempt_id, operation_id, receipt),
            )

    first, second = uuid.uuid4(), uuid.uuid4()
    await insert_attempt(first, "request-a")
    await insert_attempt(second, "request-b")
    with pytest.raises(psycopg.errors.UniqueViolation):
        await insert_attempt(first, "request-c")
    with pytest.raises(psycopg.errors.UniqueViolation):
        await insert_attempt(uuid.uuid4(), "request-a")

    concurrent_id = uuid.uuid4()
    concurrent = await asyncio.gather(
        insert_attempt(concurrent_id, "request-concurrent"),
        insert_attempt(concurrent_id, "request-concurrent"),
        return_exceptions=True,
    )
    assert sum(result is None for result in concurrent) == 1
    assert sum(isinstance(result, psycopg.errors.UniqueViolation) for result in concurrent) == 1

    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        rows = await (
            await connection.execute(
                "SELECT attempt_id FROM oms.usage_attempts WHERE tenant_id=%s AND operation_id=%s",
                (tenant_id, operation_id),
            )
        ).fetchall()
    assert {row[0] for row in rows} == {first, second, concurrent_id}
