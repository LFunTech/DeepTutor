"""0006 固定结构、旧版本升级及漂移拒绝。"""

import hashlib

import psycopg
import pytest

from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

pytestmark = pytest.mark.asyncio


async def test_reading_schema_registered(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    assert runner._migrations()[5][0] == "0006_reading"
    await runner.apply()
    await runner.verify()
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute(
            "SELECT version,checksum FROM enterprise.schema_history ORDER BY version"
        ).fetchall() == [
            (v, hashlib.sha256(s.encode()).hexdigest()) for v, s in runner._migrations()
        ]


@pytest.mark.parametrize("source", [1, 2, 3, 4, 5])
async def test_all_source_versions_verified_before_reading_target_and_failure_rolls_back(
    pg_dsn, source
):
    runner = MigrationRunner(pg_dsn)
    migrations = runner._migrations()
    runner._migrations = lambda: migrations[:source]
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        c.execute(
            "INSERT INTO enterprise.executor_state(resource,execution_id,status) VALUES('preserved','00000000-0000-0000-0000-000000000001','stopped')"
        )
        c.execute("ALTER TABLE enterprise.sessions DISABLE ROW LEVEL SECURITY")
    runner._migrations = lambda: migrations
    with pytest.raises(RuntimeError, match="RLS"):
        await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT to_regclass('enterprise.reading_materials')").fetchone() == (None,)
        assert c.execute("SELECT count(*) FROM enterprise.schema_history").fetchone() == (source,)
        c.execute("ALTER TABLE enterprise.sessions ENABLE ROW LEVEL SECURITY")
    original = runner._verify_schema

    async def fail(c, version=None):
        if version is None:
            raise RuntimeError("reading target injected failure")
        await original(c, version)

    runner._verify_schema = fail
    with pytest.raises(RuntimeError, match="target injected"):
        await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT to_regclass('enterprise.reading_materials')").fetchone() == (None,)
        assert c.execute("SELECT count(*) FROM enterprise.schema_history").fetchone() == (source,)
    runner._verify_schema = original
    await runner.apply()
    await runner.verify()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT resource FROM enterprise.executor_state").fetchall() == [
            ("preserved",)
        ]
    runner._migrations = lambda: migrations[:source]
    with pytest.raises(RuntimeError, match="incompatible"):
        await runner.verify()


@pytest.mark.parametrize(
    "mutation",
    [
        "ALTER TABLE enterprise.reading_materials DISABLE ROW LEVEL SECURITY",
        "DROP POLICY owner_scope ON enterprise.reading_workspaces",
        "ALTER TABLE enterprise.reading_workspace_sessions DISABLE TRIGGER ALL",
        "ALTER TABLE enterprise.notebook_entries ALTER COLUMN reading_material_ref DROP EXPRESSION",
        "DROP INDEX enterprise.reading_materials_content",
        "DROP INDEX enterprise.reading_links_target",
        "ALTER TABLE enterprise.reading_workspace_materials DROP CONSTRAINT reading_workspace_materials_tab_order_check",
        "ALTER TABLE enterprise.reading_materials ALTER COLUMN version SET DEFAULT 9",
    ],
)
async def test_reading_catalog_drift_is_rejected(pg_dsn, mutation):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        c.execute(mutation)
    with pytest.raises(RuntimeError, match="drift"):
        await runner.verify()
    with pytest.raises(RuntimeError, match="drift"):
        await runner.apply()


async def test_previous_sql_and_learning_catalog_are_immutable():
    from importlib.resources import files

    resources = files("deeptutor.persistence.postgres.migrations")
    assert (
        hashlib.sha256(resources.joinpath("0005_learning.sql").read_bytes()).hexdigest()
        == "2823fc004f4a05ab6d04861c2a2b477e27bce36705792155b56a1efab9564a3c"
    )
    assert (
        hashlib.sha256(resources.joinpath("learning_catalog.json").read_bytes()).hexdigest()
        == "bcce92ffd5dbf82a9a2c7b9ffac1bf1390bde81d2e3e20fb3af737fa1ac79427"
    )


@pytest.mark.parametrize("source", [4, 5])
async def test_unpublished_intermediate_free_text_provenance_fails_closed_without_data_loss(
    pg_dsn, source
):
    """合成的未发布 v4/v5 中间数据，不冒充已发布 schema1 升级缺陷。"""
    runner = MigrationRunner(pg_dsn)
    migrations = runner._migrations()
    runner._migrations = lambda: migrations[:source]
    await runner.apply()
    tenant = "10000000-0000-0000-0000-000000000001"
    # 只构造迁移制品的旧表数据，不用伪造 TenantScope 测 Store 授权。
    with psycopg.connect(pg_dsn) as c:
        c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) VALUES(%s,'not_required','synthetic')",
            (tenant,),
        )
        c.execute(
            "INSERT INTO enterprise.users(tenant_id,id,username,role) VALUES(%s,'u','u','user')",
            (tenant,),
        )
        c.execute(
            "INSERT INTO enterprise.sessions(tenant_id,owner_id,id) VALUES(%s,'u','s')", (tenant,)
        )
        c.execute(
            "INSERT INTO enterprise.notebook_entries(tenant_id,owner_id,session_id,turn_id,question_id,question,source,material_id,created_at,updated_at) VALUES(%s,'u','s','','q','preserved','immersive_reading','original-material',1,1)",
            (tenant,),
        )
        before = c.execute("SELECT * FROM enterprise.notebook_entries").fetchall()
    runner._migrations = lambda: migrations
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT * FROM enterprise.notebook_entries").fetchall() == before
        assert c.execute("SELECT count(*) FROM enterprise.schema_history").fetchone() == (source,)
        assert c.execute("SELECT to_regclass('enterprise.reading_materials')").fetchone() == (None,)
