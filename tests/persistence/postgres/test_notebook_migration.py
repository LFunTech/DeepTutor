"""题库版本演进必须先校验源，且生成引用、索引不能静默漂移。"""

import hashlib

import psycopg
import pytest

from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("source", [1, 2, 3])
async def test_upgrade_keeps_source_data_and_contiguous_history(pg_dsn, source):
    runner = MigrationRunner(pg_dsn)
    migrations = runner._migrations()
    assert len(migrations) >= 4
    assert migrations[3][0] == "0004_notebook_entries_categories"
    runner._migrations = lambda: migrations[:source]
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        c.execute(
            "INSERT INTO enterprise.executor_state(resource,execution_id,status) VALUES('retained','00000000-0000-0000-0000-000000000001','stopped')"
        )
    runner._migrations = lambda: migrations
    await runner.apply()
    await runner.verify()
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT resource FROM enterprise.executor_state").fetchall() == [
            ("retained",)
        ]
        assert c.execute(
            "SELECT version,checksum FROM enterprise.schema_history ORDER BY version"
        ).fetchall() == [(v, hashlib.sha256(s.encode()).hexdigest()) for v, s in migrations]
    # 旧 build 不可通过 verify 后访问新结构。
    runner._migrations = lambda: migrations[:source]
    with pytest.raises(RuntimeError, match="incompatible"):
        await runner.verify()


@pytest.mark.parametrize("source", [1, 2, 3])
async def test_source_drift_and_target_failure_do_not_apply_notebook_ddl(pg_dsn, source):
    runner = MigrationRunner(pg_dsn)
    migrations = runner._migrations()
    assert len(migrations) >= 4
    assert migrations[3][0] == "0004_notebook_entries_categories"
    runner._migrations = lambda: migrations[:source]
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        c.execute("ALTER TABLE enterprise.sessions DISABLE ROW LEVEL SECURITY")
    runner._migrations = lambda: migrations
    with pytest.raises(RuntimeError, match="RLS"):
        await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT to_regclass('enterprise.notebook_entries')").fetchone() == (None,)
        assert c.execute("SELECT count(*) FROM enterprise.schema_history").fetchone() == (source,)
        c.execute("ALTER TABLE enterprise.sessions ENABLE ROW LEVEL SECURITY")
    original = runner._verify_schema

    async def reject(c, version=None):
        if version is None:
            raise RuntimeError("target verification injected failure")
        return await original(c, version)

    runner._verify_schema = reject
    with pytest.raises(RuntimeError, match="target verification"):
        await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT to_regclass('enterprise.notebook_entries')").fetchone() == (None,)
        assert c.execute("SELECT to_regclass('enterprise.notebook_categories')").fetchone() == (
            None,
        )
        assert c.execute("SELECT count(*) FROM enterprise.schema_history").fetchone() == (source,)


@pytest.mark.parametrize(
    "mutation",
    [
        "ALTER TABLE enterprise.notebook_entries NO FORCE ROW LEVEL SECURITY",
        "DROP POLICY owner_scope ON enterprise.notebook_categories",
        "ALTER TABLE enterprise.notebook_entry_categories DISABLE TRIGGER ALL",
        "ALTER TABLE enterprise.notebook_entries ALTER COLUMN execution_turn_id DROP EXPRESSION",
        "ALTER TABLE enterprise.notebook_entries ALTER COLUMN followup_session_ref DROP EXPRESSION",
        "ALTER TABLE enterprise.notebook_categories ALTER COLUMN name_key DROP EXPRESSION",
        'ALTER TABLE enterprise.notebook_categories ALTER COLUMN name_key TYPE text COLLATE "POSIX"',
        "DROP INDEX enterprise.notebook_entries_recent",
        "DROP INDEX enterprise.notebook_entry_categories_category",
        "ALTER TABLE enterprise.notebook_entries ALTER COLUMN version DROP DEFAULT",
        "ALTER TABLE enterprise.notebook_entries ALTER COLUMN source SET DEFAULT 'book'",
        "ALTER TABLE enterprise.notebook_entries ALTER COLUMN turn_id DROP DEFAULT",
    ],
)
async def test_notebook_catalog_drift_is_not_a_new_baseline(pg_dsn, mutation):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert (
            c.execute("SELECT to_regclass('enterprise.notebook_entries')").fetchone()[0] is not None
        )
        c.execute(mutation)
    with pytest.raises(RuntimeError, match="drift"):
        await runner.verify()
    with pytest.raises(RuntimeError, match="drift"):
        await runner.apply()
