"""学习迁移使用同一正式目录：源验证、历史不变、失败回滚与漂移拒绝。"""

import hashlib

import psycopg
import pytest

from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

pytestmark = pytest.mark.asyncio
VERSION = "0005_learning"


async def test_learning_migration_is_registered_and_verified(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    migrations = [m for m in runner._migrations() if m[0] <= VERSION]
    runner._migrations = lambda: migrations
    assert runner._migrations()[-1][0] == VERSION
    await runner.apply()
    await runner.verify()
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute(
            "SELECT version,checksum FROM enterprise.schema_history ORDER BY version"
        ).fetchall() == [
            (v, hashlib.sha256(sql.encode()).hexdigest()) for v, sql in runner._migrations()
        ]
        for table in (
            "mastery_paths",
            "mastery_path_sessions",
            "mastery_interactions",
            "mastery_events",
            "mastery_path_leases",
            "mastery_topic_meta",
            "mastery_topic_sources",
            "mastery_path_operations",
            "mastery_knowledge_points",
        ):
            assert c.execute(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass",
                (f"enterprise.{table}",),
            ).fetchone() == (True, False)


@pytest.mark.parametrize("source", [1, 2, 3, 4])
async def test_learning_upgrade_verifies_source_and_rolls_back_target(pg_dsn, source):
    runner = MigrationRunner(pg_dsn)
    migrations = [m for m in runner._migrations() if m[0] <= VERSION]
    assert migrations[-1][0] == VERSION
    runner._migrations = lambda: migrations[:source]
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        c.execute(
            "INSERT INTO enterprise.executor_state(resource,execution_id,status) VALUES('retained','00000000-0000-0000-0000-000000000001','stopped')"
        )
        c.execute("ALTER TABLE enterprise.sessions DISABLE ROW LEVEL SECURITY")
    runner._migrations = lambda: migrations
    with pytest.raises(RuntimeError, match="RLS"):
        await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT to_regclass('enterprise.mastery_paths')").fetchone() == (None,)
        assert c.execute("SELECT count(*) FROM enterprise.schema_history").fetchone() == (source,)
        c.execute("ALTER TABLE enterprise.sessions ENABLE ROW LEVEL SECURITY")
    original = runner._verify_schema

    async def reject(c, version=None):
        if version is None:
            raise RuntimeError("target verification injected failure")
        await original(c, version)

    runner._verify_schema = reject
    with pytest.raises(RuntimeError, match="target verification"):
        await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT to_regclass('enterprise.mastery_paths')").fetchone() == (None,)
        assert c.execute("SELECT count(*) FROM enterprise.schema_history").fetchone() == (source,)
    runner._verify_schema = original
    await runner.apply()
    await runner.verify()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT resource FROM enterprise.executor_state").fetchall() == [
            ("retained",)
        ]
    runner._migrations = lambda: migrations[:source]
    with pytest.raises(RuntimeError, match="incompatible"):
        await runner.verify()


@pytest.mark.parametrize(
    "mutation",
    [
        "ALTER TABLE enterprise.mastery_paths DISABLE ROW LEVEL SECURITY",
        "DROP POLICY owner_scope ON enterprise.mastery_events",
        "ALTER TABLE enterprise.mastery_path_leases DISABLE TRIGGER ALL",
        "ALTER TABLE enterprise.notebook_entries ALTER COLUMN mastery_path_ref DROP EXPRESSION",
        "ALTER TABLE enterprise.mastery_topic_sources ALTER COLUMN entry_ref DROP EXPRESSION",
        "DROP INDEX enterprise.mastery_one_active_question",
        "DROP INDEX enterprise.mastery_events_cursor",
        "ALTER TABLE enterprise.mastery_path_operations DROP CONSTRAINT mastery_path_operations_version_check",
    ],
)
async def test_learning_catalog_rejects_drift(pg_dsn, mutation):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        c.execute(mutation)
    with pytest.raises(RuntimeError, match="drift"):
        await runner.verify()
    with pytest.raises(RuntimeError, match="drift"):
        await runner.apply()


async def test_schema4_orphan_mastery_notebook_requires_offline_repair(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    migrations = runner._migrations()
    runner._migrations = lambda: migrations[:4]
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        c.execute(
            "INSERT INTO enterprise.tenants(id,auth_epoch,external_eligibility) VALUES('10000000-0000-0000-0000-000000000001','test','not_required')"
        )
        c.execute(
            "INSERT INTO enterprise.users(tenant_id,id,username,role) VALUES('10000000-0000-0000-0000-000000000001','owner','owner','user')"
        )
        c.execute(
            "INSERT INTO enterprise.sessions(tenant_id,owner_id,id,title,created_at,updated_at) VALUES('10000000-0000-0000-0000-000000000001','owner','s','',1,1)"
        )
        c.execute(
            "INSERT INTO enterprise.notebook_entries(tenant_id,owner_id,session_id,question_id,question,source,material_id,created_at,updated_at) VALUES('10000000-0000-0000-0000-000000000001','owner','s','q','q','mastery_path','orphan',1,1)"
        )
    runner._migrations = lambda: migrations
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT to_regclass('enterprise.mastery_paths')").fetchone() == (None,)
        assert c.execute("SELECT count(*) FROM enterprise.schema_history").fetchone() == (4,)
        assert c.execute("SELECT material_id FROM enterprise.notebook_entries").fetchall() == [
            ("orphan",)
        ]
