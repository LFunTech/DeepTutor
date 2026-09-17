import asyncio
import importlib.util
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.asyncio

EXPECTED_MIGRATIONS = [
    "0001_identity_sessions",
    "0002_account_profiles_devices",
    "0003_device_usage_precision",
    "0004_notebook_entries_categories",
    "0005_learning",
    "0006_reading",
    "0007_session_resources",
    "0008_cron",
    "0009_partner_runtime_status",
    "0010_matrix_store",
    "0011_marginnote_store",
    "0012_offline_import_stage",
    "0013_courses",
    "0014_externalized_runtime",
]
EXPECTED_EXTENSION_MIGRATIONS = [
    "0001_federated_access",
    "0002_profile_permission_snapshots",
    "0003_revocation_state",
    "0004_audit_export_jobs",
]


def module(name):
    assert importlib.util.find_spec("deeptutor_enterprise." + name) is not None, (
        "企业持久化组件尚未实现: " + name
    )
    return __import__("deeptutor_enterprise." + name, fromlist=["*"])


async def migrated(dsn):
    migration = module("migrations.runner")
    runner = migration.MigrationRunner(dsn)
    assert await runner.plan() == EXPECTED_MIGRATIONS + EXPECTED_EXTENSION_MIGRATIONS
    await runner.apply()
    await runner.verify()
    return runner


async def test_migrations_repeat_concurrent_and_runtime_ddl(pg_dsn):
    runner = await migrated(pg_dsn)
    await asyncio.gather(runner.apply(), runner.apply())
    assert await runner.plan() == []
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        role = await (
            await c.execute("SELECT rolname FROM pg_roles WHERE rolname='dt_enterprise_app'")
        ).fetchone()
        assert role
    pool = module("stores.postgres.connection").Database(
        pg_dsn.replace("user=postgres", "user=dt_enterprise_app"), resource="test"
    )
    async with pool:
        scope = module("scope").TenantScope(str(uuid.uuid4()), "u1")
        async with pool.transaction(scope) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await c.execute("CREATE TABLE enterprise.bad (id int)")


async def test_eduplus2_extension_catalog_drift_blocks_verify(pg_dsn):
    runner = await migrated(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("ALTER TABLE eduplus2.audit_export_jobs DISABLE ROW LEVEL SECURITY")
    with pytest.raises(RuntimeError, match="eduplus2 schema drift"):
        await runner.verify()
    with pytest.raises(RuntimeError, match="eduplus2 schema drift"):
        await runner.apply()


async def test_drift_blocks_start(pg_dsn):
    runner = await migrated(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("UPDATE enterprise.schema_history SET checksum='changed'")
    with pytest.raises(RuntimeError, match="drift"):
        await runner.verify()
    with pytest.raises(RuntimeError, match="drift"):
        await runner.apply()


async def test_scope_reuse_cancel_rollback_and_missing_scope(pg_dsn):
    await migrated(pg_dsn)
    mod = module("stores.postgres.connection")
    Scope = module("scope").TenantScope
    async with mod.Database(
        pg_dsn.replace("user=postgres", "user=dt_enterprise_app"), resource="test", max_size=1
    ) as db:
        a, b = Scope(str(uuid.uuid4()), "same-user"), Scope(str(uuid.uuid4()), "same-user")

        async def settings(scope):
            async with db.transaction(scope) as c:
                return await (
                    await c.execute(
                        "SELECT current_setting('app.tenant_id') AS tenant,current_setting('app.user_id') AS owner"
                    )
                ).fetchone()

        assert tuple((await settings(a)).values()) == (a.tenant_id, "same-user")

        async def cancelled():
            async with db.transaction(a) as c:
                await c.execute("SELECT pg_sleep(5)")

        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.1):
                await cancelled()
        assert tuple((await settings(b)).values()) == (b.tenant_id, "same-user")
        with pytest.raises(ValueError, match="scope"):
            async with db.transaction(None):
                pass
        async with db.pool.connection() as c:
            result = await (
                await c.execute("SELECT nullif(current_setting('app.tenant_id',true),'') AS tenant")
            ).fetchone()
            assert result["tenant"] is None
            assert await (await c.execute("SELECT * FROM enterprise.sessions")).fetchall() == []


async def test_runtime_rejects_owner_or_superuser(pg_dsn):
    await migrated(pg_dsn)
    with pytest.raises(RuntimeError, match="restricted"):
        async with module("stores.postgres.connection").Database(pg_dsn, resource="test"):
            pass


@pytest.mark.parametrize(
    "mutation",
    [
        "ALTER TABLE enterprise.tenants DISABLE ROW LEVEL SECURITY",
        "ALTER TABLE enterprise.turns NO FORCE ROW LEVEL SECURITY",
        "DROP POLICY owner_scope ON enterprise.messages",
        "ALTER POLICY tenant_scope ON enterprise.sessions USING (true) WITH CHECK (true)",
        "DROP POLICY owner_scope ON enterprise.sessions; CREATE POLICY owner_scope ON enterprise.sessions USING (owner_id=current_setting('app.user_id')) WITH CHECK (owner_id=current_setting('app.user_id'))",
        "CREATE POLICY extra_bypass ON enterprise.sessions USING (true) WITH CHECK (true)",
        "DO $$ DECLARE n text; BEGIN SELECT conname INTO n FROM pg_constraint WHERE conrelid='enterprise.messages'::regclass AND confrelid='enterprise.sessions'::regclass; EXECUTE format('ALTER TABLE enterprise.messages DROP CONSTRAINT %I',n); END $$",
        "DROP INDEX enterprise.one_active_turn",
        "ALTER TABLE enterprise.turns DROP CONSTRAINT turns_status_check; ALTER TABLE enterprise.turns ADD CONSTRAINT turns_status_check CHECK(status IS NOT NULL)",
        "ALTER TABLE enterprise.sessions ALTER COLUMN owner_id DROP NOT NULL",
        "ALTER TABLE enterprise.turns DISABLE TRIGGER ALL",
        "DROP TABLE enterprise.turn_commands",
        "ALTER POLICY tenant_scope ON enterprise.sessions WITH CHECK (true)",
        "DROP INDEX enterprise.one_active_turn; CREATE INDEX one_active_turn ON enterprise.turns(tenant_id,session_id) WHERE status IN ('queued','running','waiting_input')",
        "ALTER TABLE enterprise.turn_commands DROP CONSTRAINT turn_commands_pkey; ALTER TABLE enterprise.turn_commands ADD PRIMARY KEY(owner_id,turn_id,command_id)",
        "DO $$ DECLARE n text; BEGIN SELECT conname INTO n FROM pg_constraint WHERE conrelid='enterprise.messages'::regclass AND confrelid='enterprise.sessions'::regclass; EXECUTE format('ALTER TABLE enterprise.messages DROP CONSTRAINT %I',n); EXECUTE format('ALTER TABLE enterprise.messages ADD CONSTRAINT %I FOREIGN KEY(tenant_id,owner_id,session_id) REFERENCES enterprise.sessions(tenant_id,owner_id,id) ON DELETE CASCADE NOT VALID',n); END $$",
    ],
)
async def test_real_catalog_drift_blocks_verify_even_when_history_unchanged(pg_dsn, mutation):
    runner = await migrated(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(mutation, prepare=False)
    with pytest.raises(RuntimeError, match="drift"):
        await runner.verify()
    with pytest.raises(RuntimeError, match="drift"):
        await runner.apply()


async def test_verify_catalog_works_without_migration_privileges(pg_dsn):
    await migrated(pg_dsn)
    runner = module("migrations.runner").MigrationRunner(
        pg_dsn.replace("user=postgres", "user=dt_enterprise_app")
    )
    await runner.verify()


@pytest.mark.parametrize(
    "privilege,path",
    [
        ("SUPERUSER", "set"),
        ("BYPASSRLS", "set"),
        ("CREATEROLE", "set"),
        ("CREATEDB", "set"),
        ("table_owner", "inherit"),
        ("schema_owner", "set"),
        ("table_owner", "mixed"),
        ("BYPASSRLS", "admin"),
    ],
)
async def test_runtime_rejects_indirect_privileged_role_paths(pg_dsn, privilege, path):
    await migrated(pg_dsn)
    suffix = uuid.uuid4().hex
    login, middle, target = (name + suffix for name in ("login_", "middle_", "target_"))
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            psycopg.sql.SQL("CREATE ROLE {} LOGIN NOINHERIT").format(psycopg.sql.Identifier(login))
        )
        attribute = (
            privilege
            if privilege in ("SUPERUSER", "BYPASSRLS", "CREATEROLE", "CREATEDB")
            else "NOLOGIN"
        )
        await c.execute(
            psycopg.sql.SQL("CREATE ROLE {} {}").format(
                psycopg.sql.Identifier(target), psycopg.sql.SQL(attribute)
            )
        )
        if privilege == "table_owner":
            await c.execute(
                psycopg.sql.SQL("ALTER TABLE enterprise.sessions OWNER TO {}").format(
                    psycopg.sql.Identifier(target)
                )
            )
        elif privilege == "schema_owner":
            await c.execute(
                psycopg.sql.SQL("ALTER SCHEMA enterprise OWNER TO {}").format(
                    psycopg.sql.Identifier(target)
                )
            )
        if path == "mixed":
            await c.execute(
                psycopg.sql.SQL("CREATE ROLE {} NOINHERIT").format(psycopg.sql.Identifier(middle))
            )
            await c.execute(
                psycopg.sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
                    psycopg.sql.Identifier(middle), psycopg.sql.Identifier(login)
                )
            )
            await c.execute(
                psycopg.sql.SQL("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE").format(
                    psycopg.sql.Identifier(target), psycopg.sql.Identifier(middle)
                )
            )
        else:
            options = {
                "set": "INHERIT FALSE, SET TRUE",
                "inherit": "INHERIT TRUE, SET FALSE",
                "admin": "INHERIT FALSE, SET FALSE, ADMIN TRUE",
            }[path]
            await c.execute(
                psycopg.sql.SQL("GRANT {} TO {} WITH {}").format(
                    psycopg.sql.Identifier(target),
                    psycopg.sql.Identifier(login),
                    psycopg.sql.SQL(options),
                )
            )
    with pytest.raises(RuntimeError, match="restricted"):
        async with module("stores.postgres.connection").Database(
            pg_dsn.replace("user=postgres", f"user={login}"), resource="test"
        ):
            pass


async def test_runtime_allows_nonprivileged_memberships_and_inaccessible_roles(pg_dsn):
    await migrated(pg_dsn)
    suffix = uuid.uuid4().hex
    login, target = "safe_" + suffix, "unavailable_" + suffix
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            psycopg.sql.SQL("CREATE ROLE {} LOGIN NOINHERIT").format(psycopg.sql.Identifier(login))
        )
        await c.execute(
            psycopg.sql.SQL("CREATE ROLE {} BYPASSRLS").format(psycopg.sql.Identifier(target))
        )
        await c.execute(
            psycopg.sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET FALSE, ADMIN FALSE").format(
                psycopg.sql.Identifier(target), psycopg.sql.Identifier(login)
            )
        )
        await c.execute(
            psycopg.sql.SQL("GRANT dt_enterprise_app TO {} WITH INHERIT TRUE, SET TRUE").format(
                psycopg.sql.Identifier(login)
            )
        )
    async with module("stores.postgres.connection").Database(
        pg_dsn.replace("user=postgres", f"user={login}"), resource="test"
    ) as db:
        scope = module("scope").TenantScope(str(uuid.uuid4()), "u1")
        async with db.transaction(scope) as c:
            assert (await (await c.execute("SELECT 42 AS answer")).fetchone())["answer"] == 42


@pytest.mark.parametrize("already_applied", [False, True])
async def test_migration_sql_failure_rolls_back_ddl_data_and_history(pg_dsn, already_applied):
    base = module("migrations.runner").MigrationRunner
    if already_applied:
        await migrated(pg_dsn)

    class FailingArtifactRunner(base):
        def _migrations(self):
            return super()._migrations() + [
                (
                    "0008_failure",
                    """
                CREATE TABLE enterprise.uncommitted_probe (id integer PRIMARY KEY);
                INSERT INTO enterprise.executor_state(resource,execution_id,status)
                    VALUES ('must-rollback','00000000-0000-0000-0000-000000000001','active');
                SELECT 1/0;
            """,
                )
            ]

    with pytest.raises(psycopg.errors.DivisionByZero):
        await FailingArtifactRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        assert (
            await (await c.execute("SELECT to_regclass('enterprise.uncommitted_probe')")).fetchone()
        )[0] is None
        if already_applied:
            assert (
                await (
                    await c.execute(
                        "SELECT resource FROM enterprise.executor_state WHERE resource='must-rollback'"
                    )
                ).fetchall()
                == []
            )
            assert await (
                await c.execute("SELECT version FROM enterprise.schema_history ORDER BY version")
            ).fetchall() == [(version,) for version in EXPECTED_MIGRATIONS]
        else:
            assert (await (await c.execute("SELECT to_regnamespace('enterprise')")).fetchone())[
                0
            ] is None
    await base(pg_dsn).apply()
    await base(pg_dsn).verify()


async def test_forged_success_history_without_real_schema_is_not_verified(pg_dsn):
    import hashlib

    runner = module("migrations.runner").MigrationRunner(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("CREATE SCHEMA enterprise")
        await c.execute(
            "CREATE TABLE enterprise.schema_history(version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for version, artifact in runner._migrations():
            await c.execute(
                "INSERT INTO enterprise.schema_history(version,checksum) VALUES(%s,%s)",
                (version, hashlib.sha256(artifact.encode()).hexdigest()),
            )
    with pytest.raises(RuntimeError, match="drift"):
        await runner.verify()
    with pytest.raises(RuntimeError, match="drift"):
        await runner.apply()


async def test_runtime_rejects_privileged_session_user_hidden_by_startup_role(pg_dsn):
    await migrated(pg_dsn)
    dsn = psycopg.conninfo.make_conninfo(pg_dsn, options="-c role=dt_enterprise_app")
    with pytest.raises(RuntimeError, match="restricted"):
        async with module("stores.postgres.connection").Database(dsn, resource="test"):
            pass
