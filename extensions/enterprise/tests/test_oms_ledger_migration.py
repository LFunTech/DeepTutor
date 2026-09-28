"""OMS 账务表只通过企业版本化迁移进入隔离的合成 PostgreSQL。"""

from __future__ import annotations

import asyncio
from importlib.resources import files
import re
import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
import psycopg
import pytest

from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


async def test_new_oms_migrations_have_no_database_business_routines_or_enum_checks():
    resources = files("deeptutor_enterprise.oms.migrations")
    for name in (
        "0013_global_model_catalog.sql",
        "0014_skill_packages.sql",
        "0015_remove_fact_mutation_function.sql",
        "0016_skill_review_publication_fences.sql",
        "0017_relocate_database_business_rules.sql",
    ):
        sql = resources.joinpath(name).read_text(encoding="utf8")
        assert not re.search(r"\bCREATE\s+(?:FUNCTION|PROCEDURE|TRIGGER)\b", sql, re.I)
        assert not re.search(r"\bCHECK\s*\([^;]*?\bIN\s*\(", sql, re.I | re.S)
        assert not re.search(r"\bCHECK\s*\([^;]*?=\s*ANY\s*\(\s*ARRAY", sql, re.I | re.S)


async def test_oms_ledger_migration_is_versioned_and_repeatable(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    assert {
        "oms/0001_ledger_base",
        "oms/0002_grant_source",
        "oms/0003_grant_command_idempotency",
        "oms/0004_attempt_lifecycle",
        "oms/0005_command_result_summary",
        "oms/0006_append_only_facts",
        "oms/0007_supply_evidence",
        "oms/0008_quota_expiry",
        "oms/0009_entitlement_commands",
        "oms/0010_quota_adjustment",
        "oms/0011_school_binding",
        "oms/0012_school_binding_version_guard",
        "oms/0013_global_model_catalog",
        "oms/0014_skill_packages",
        "oms/0015_remove_fact_mutation_function",
        "oms/0016_skill_review_publication_fences",
        "oms/0017_relocate_database_business_rules",
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
        ("0007_supply_evidence",),
        ("0008_quota_expiry",),
        ("0009_entitlement_commands",),
        ("0010_quota_adjustment",),
        ("0011_school_binding",),
        ("0012_school_binding_version_guard",),
        ("0013_global_model_catalog",),
        ("0014_skill_packages",),
        ("0015_remove_fact_mutation_function",),
        ("0016_skill_review_publication_fences",),
        ("0017_relocate_database_business_rules",),
    ]
    assert {row[0]: tuple(row[1:]) for row in tables} == {
        "schema_history": (False, False),
        "service_definitions": (False, False),
        "supply_lots": (False, False),
        "school_bindings": (False, False),
        "grant_commands": (False, False),
        "tenant_service_entitlements": (True, True),
        "quota_grants": (True, True),
        "grant_commitments": (True, True),
        "usage_attempts": (True, True),
        "attempt_allocations": (True, True),
        "attempt_evidence_events": (True, True),
        "audit_events": (False, False),
        "entitlement_commands": (True, True),
        "model_catalog_config": (False, False),
        "skill_revisions": (True, True),
        "skill_publications": (True, True),
        "skill_grants": (True, True),
        "skill_reviews": (True, True),
    }


@pytest.mark.parametrize(
    "drift",
    [
        "DROP INDEX oms.skill_global_revision_version",
    ],
)
async def test_skill_declarative_guard_drift_blocks_verify(pg_dsn, drift):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(drift)
    with pytest.raises(RuntimeError, match="oms schema drift"):
        await runner.verify()


async def test_oms_schema_drift_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute("ALTER TABLE oms.usage_attempts DISABLE ROW LEVEL SECURITY")

    with pytest.raises(RuntimeError, match="oms schema drift"):
        await runner.verify()


async def test_supply_business_check_reintroduction_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "ALTER TABLE oms.supply_lots ADD CONSTRAINT supply_lots_verified_native "
            "CHECK (supply_basis IS NOT NULL)"
        )
    with pytest.raises(RuntimeError, match="database-owned business rules"):
        await runner.verify()


async def test_quota_expiry_business_check_reintroduction_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "ALTER TABLE oms.quota_grants ADD CONSTRAINT quota_grants_status_check "
            "CHECK (status IS NOT NULL)"
        )
    with pytest.raises(RuntimeError, match="database-owned business rules"):
        await runner.verify()


async def test_quota_adjustment_constraint_drift_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "ALTER TABLE oms.quota_grants DROP CONSTRAINT quota_grants_adjustment_released_valid"
        )
    with pytest.raises(RuntimeError, match="oms schema drift"):
        await runner.verify()


async def test_school_binding_requires_explicit_unique_verified_numeric_target(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    internal_a, internal_b = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        for internal_id in (internal_a, internal_b):
            await connection.execute(
                "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
                "VALUES(%s,'allowed','test-epoch')",
                (internal_id,),
            )
        rows = await (
            await connection.execute("SELECT tenant_id FROM oms.school_bindings")
        ).fetchall()
        assert rows == []
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,42,'verified',now(),'operator','synthetic://binding')",
            (internal_a,),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            await connection.execute(
                "INSERT INTO oms.school_bindings"
                "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
                "VALUES(%s,42,'verified',now(),'operator','synthetic://duplicate')",
                (internal_b,),
            )


async def test_school_binding_constraint_drift_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "ALTER TABLE oms.school_bindings DROP CONSTRAINT school_bindings_eduplus_tenant_id_key"
        )
    with pytest.raises(RuntimeError, match="oms schema drift"):
        await runner.verify()


async def test_school_binding_retarget_requires_runner_transition_version():
    from datetime import datetime, timezone

    school = uuid.uuid4()
    proof_time = datetime.now(timezone.utc)
    before = {school: (101, "verified", 1, proof_time, "synthetic-verifier", "synthetic://a")}
    after = {school: (202, "verified", 1, proof_time, "synthetic-verifier", "synthetic://b")}

    with pytest.raises(RuntimeError, match="school binding transition"):
        MigrationRunner._validate_oms_school_binding_transition(before, after)


async def test_oms_runner_rejects_binding_retarget_without_version_even_without_trigger(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','synthetic')", (school,)
        )
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic','synthetic://original')",
            (school,),
        )

    class InvalidBindingRunner(MigrationRunner):
        def _oms_migrations(self):
            return super()._oms_migrations() + [
                (
                    "0018_invalid_binding_retarget",
                    "UPDATE oms.school_bindings SET eduplus_tenant_id=202,"
                    "source_ref='synthetic://other' WHERE eduplus_tenant_id=101;",
                )
            ]

    with pytest.raises(RuntimeError, match="school binding transition"):
        await InvalidBindingRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT eduplus_tenant_id,version,source_ref FROM oms.school_bindings "
                "WHERE tenant_id=%s", (school,)
            )
        ).fetchone()
    assert row == (101, 1, "synthetic://original")


async def test_oms_runner_rejects_partial_binding_proof_after_enum_checks_retire():
    from datetime import datetime, timezone

    with pytest.raises(RuntimeError, match="school binding transition"):
        MigrationRunner._validate_oms_school_binding_transition(
            {},
            {
                uuid.uuid4(): (
                    101, "pending", 1, datetime.now(timezone.utc), None, "synthetic://partial"
                )
            },
        )


async def test_school_binding_delete_is_rejected_by_runner_transition(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','synthetic')",
            (school,),
        )
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )

    class InvalidDeleteRunner(MigrationRunner):
        def _oms_migrations(self):
            return super()._oms_migrations() + [
                ("0018_invalid_binding_delete", "DELETE FROM oms.school_bindings WHERE eduplus_tenant_id=101")
            ]

    with pytest.raises(RuntimeError, match="school binding transition"):
        await InvalidDeleteRunner(pg_dsn).apply()


async def test_school_binding_version_guard_reintroduction_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "CREATE FUNCTION oms.guard_school_binding_version() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$"
        )
        await connection.execute(
            "CREATE TRIGGER guard_school_binding_version BEFORE UPDATE OR DELETE "
            "ON oms.school_bindings FOR EACH ROW EXECUTE FUNCTION oms.guard_school_binding_version()"
        )
    with pytest.raises(RuntimeError, match="database-owned business rules"):
        await runner.verify()


async def test_oms_attempt_lifecycle_business_check_reintroduction_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "ALTER TABLE oms.usage_attempts ADD CONSTRAINT usage_attempts_status_check "
            "CHECK (status IS NOT NULL)"
        )
    with pytest.raises(RuntimeError, match="database-owned business rules"):
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


async def test_oms_reintroduced_fact_trigger_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "CREATE FUNCTION oms.synthetic_fact_guard() RETURNS trigger "
            "LANGUAGE plpgsql AS 'BEGIN RETURN NEW; END'"
        )
        await connection.execute(
            "CREATE TRIGGER synthetic_fact_guard BEFORE UPDATE ON oms.attempt_evidence_events "
            "FOR EACH ROW EXECUTE FUNCTION oms.synthetic_fact_guard()"
        )
    with pytest.raises(RuntimeError, match="oms schema drift"):
        await runner.verify()


async def test_oms_forward_migration_removes_fact_mutation_function(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        function = await (
            await connection.execute("SELECT to_regprocedure('oms.reject_fact_mutation()')")
        ).fetchone()
        triggers = await (
            await connection.execute(
                "SELECT t.tgname FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=r.relnamespace "
                "WHERE n.nspname='oms' AND r.relname IN "
                "('attempt_evidence_events','audit_events') AND NOT t.tgisinternal"
            )
        ).fetchall()
    assert function == (None,)
    assert triggers == []


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
