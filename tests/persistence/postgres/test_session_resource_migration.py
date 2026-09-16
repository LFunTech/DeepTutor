"""资源 schema 从每个已发布源版本升级、源漂移拒绝及目标回滚。"""

import psycopg
import pytest

from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("source", range(1, 7))
async def test_resource_upgrade_from_all_versions(pg_dsn, source):
    runner = MigrationRunner(pg_dsn)
    all_migrations = runner._migrations()
    original = runner._migrations
    runner._migrations = lambda: all_migrations[:source]
    await runner.apply()
    runner._migrations = original
    assert "0007_session_resources" in await runner.plan()
    await runner.apply()
    await runner.verify()
    assert await runner.plan() == []
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        assert (
            await (await c.execute("SELECT to_regclass('enterprise.session_objects')")).fetchone()
        )[0]


@pytest.mark.parametrize("source", range(1, 7))
async def test_resource_source_drift_refused(pg_dsn, source):
    runner = MigrationRunner(pg_dsn)
    all_migrations = runner._migrations()
    runner._migrations = lambda: all_migrations[:source]
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("ALTER TABLE enterprise.sessions DISABLE ROW LEVEL SECURITY")
    runner._migrations = lambda: all_migrations
    with pytest.raises(RuntimeError, match="drift"):
        await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        assert (
            await (await c.execute("SELECT to_regclass('enterprise.session_objects')")).fetchone()
        )[0] is None


@pytest.mark.parametrize("source", range(1, 7))
async def test_resource_target_failure_rolls_back(pg_dsn, source):
    runner = MigrationRunner(pg_dsn)
    all_migrations = runner._migrations()
    runner._migrations = lambda: all_migrations[:source]
    await runner.apply()
    runner._migrations = lambda: all_migrations
    verify = runner._verify_schema

    async def fail_target(c, version=None):
        await verify(c, version)
        if version is None:
            raise ValueError("synthetic target validation failure")

    runner._verify_schema = fail_target
    with pytest.raises(ValueError, match="target"):
        await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        assert (
            await (await c.execute("SELECT count(*) FROM enterprise.schema_history")).fetchone()
        )[0] == source
        assert (
            await (await c.execute("SELECT to_regclass('enterprise.session_objects')")).fetchone()
        )[0] is None


async def test_existing_typed_preferences_gain_foreign_key_without_changing_json(pg_dsn):
    from uuid import uuid4

    from psycopg.types.json import Jsonb

    runner = MigrationRunner(pg_dsn)
    migrations = runner._migrations()
    runner._migrations = lambda: migrations[:6]
    await runner.apply()
    tenant = uuid4()
    prefs = {"reading_workspace_id": "w", "other": {"keep": 42}}
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) VALUES(%s,'not_required','synthetic')",
            (tenant,),
        )
        await c.execute(
            "INSERT INTO enterprise.users(tenant_id,id,username,role) VALUES(%s,'u','u','user')",
            (tenant,),
        )
        await c.execute(
            "INSERT INTO enterprise.sessions(tenant_id,owner_id,id,preferences) VALUES(%s,'u','s',%s)",
            (tenant, Jsonb(prefs)),
        )
        await c.execute(
            "INSERT INTO enterprise.reading_workspaces(tenant_id,owner_id,workspace_id,title,description,version,created_at,updated_at) VALUES(%s,'u','w','w','',1,1,1)",
            (tenant,),
        )
    runner._migrations = lambda: migrations
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        assert (
            await (
                await c.execute(
                    "SELECT preferences FROM enterprise.sessions WHERE tenant_id=%s", (tenant,)
                )
            ).fetchone()
        )[0] == prefs
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await c.execute(
                "DELETE FROM enterprise.reading_workspaces WHERE tenant_id=%s", (tenant,)
            )


async def test_existing_unknown_machine_references_are_persistently_flagged(pg_dsn):
    from uuid import uuid4

    runner = MigrationRunner(pg_dsn)
    migrations = runner._migrations()
    runner._migrations = lambda: migrations[:6]
    await runner.apply()
    tenant = uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) VALUES(%s,'not_required','synthetic')",
            (tenant,),
        )
        await c.execute(
            "INSERT INTO enterprise.users(tenant_id,id,username,role) VALUES(%s,'u','u','user')",
            (tenant,),
        )
        await c.execute(
            "INSERT INTO enterprise.sessions(tenant_id,owner_id,id) VALUES(%s,'u','s')", (tenant,)
        )
        await c.execute(
            "INSERT INTO enterprise.messages(tenant_id,owner_id,session_id,role,content,metadata) VALUES(%s,'u','s','user','synthetic','{\"deep\":{\"course_id\":\"upstream\"}}')",
            (tenant,),
        )
    runner._migrations = lambda: migrations
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        assert (
            await (
                await c.execute(
                    "SELECT unresolved_dependencies FROM enterprise.sessions WHERE tenant_id=%s",
                    (tenant,),
                )
            ).fetchone()
        )[0] is True


@pytest.mark.parametrize(
    "kind,table",
    [
        ("mastery_path_id", "mastery_paths"),
        ("reading_material_id", "reading_materials"),
        ("reading_workspace_id", "reading_workspaces"),
    ],
)
async def test_existing_real_request_snapshot_is_projected_and_protects_target(pg_dsn, kind, table):
    from uuid import uuid4

    from psycopg.types.json import Jsonb

    from tests.persistence.postgres.business.test_session_request_snapshot import snapshot

    runner = MigrationRunner(pg_dsn)
    migrations = runner._migrations()
    runner._migrations = lambda: migrations[:6]
    await runner.apply()
    tenant = uuid4()
    metadata = snapshot(payload={kind: "abcdef12"})
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) VALUES(%s,'not_required','synthetic')",
            (tenant,),
        )
        await c.execute(
            "INSERT INTO enterprise.users(tenant_id,id,username,role) VALUES(%s,'u','u','user')",
            (tenant,),
        )
        await c.execute(
            "INSERT INTO enterprise.sessions(tenant_id,owner_id,id) VALUES(%s,'u','s')", (tenant,)
        )
        if table == "mastery_paths":
            await c.execute(
                "INSERT INTO enterprise.mastery_paths(tenant_id,owner_id,path_id,state,revision,created_at,updated_at) VALUES(%s,'u','abcdef12','{}',1,1,1)",
                (tenant,),
            )
        elif table == "reading_workspaces":
            await c.execute(
                "INSERT INTO enterprise.reading_workspaces(tenant_id,owner_id,workspace_id,title,description,version,created_at,updated_at) VALUES(%s,'u','abcdef12','t','',1,1,1)",
                (tenant,),
            )
        else:
            await c.execute(
                "INSERT INTO enterprise.reading_materials(tenant_id,owner_id,material_id,content_id,filename,title,source_kind,source_url,mime,render_mode,cover_url,duration_seconds,status,progress,error_code,error_detail,last_opened_at,version,created_at,updated_at) VALUES(%s,'u','abcdef12','abcdef12','t','t','file','','application/pdf','pdf','',0,'ready',100,'','',0,1,1,1)",
                (tenant,),
            )
        await c.execute(
            "INSERT INTO enterprise.messages(tenant_id,owner_id,session_id,role,content,metadata) VALUES(%s,'u','s','user','Q',%s)",
            (tenant, Jsonb(metadata)),
        )
    runner._migrations = lambda: migrations
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        row = await (
            await c.execute(
                "SELECT kind,target_id FROM enterprise.session_references WHERE tenant_id=%s AND source_kind='message'",
                (tenant,),
            )
        ).fetchone()
        assert row == (kind, "abcdef12")
        assert (
            await (
                await c.execute(
                    "SELECT metadata FROM enterprise.messages WHERE tenant_id=%s", (tenant,)
                )
            ).fetchone()
        )[0] == metadata
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await c.execute(f"DELETE FROM enterprise.{table} WHERE tenant_id=%s", (tenant,))
