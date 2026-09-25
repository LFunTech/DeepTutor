"""核心 PostgreSQL migration runner 的真实数据库契约。"""

import asyncio
import hashlib
from importlib.resources import files
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

pytestmark = pytest.mark.asyncio

SCHEMA_1_VERSION = "0001_identity_sessions"
SCHEMA_2_VERSION = "0002_account_profiles_devices"
SCHEMA_3_VERSION = "0003_device_usage_precision"
SCHEMA_4_VERSION = "0004_notebook_entries_categories"
SCHEMA_5_VERSION = "0005_learning"
SCHEMA_6_VERSION = "0006_reading"
SCHEMA_7_VERSION = "0007_session_resources"
SCHEMA_8_VERSION = "0008_cron"
SCHEMA_9_VERSION = "0009_partner_runtime_status"
SCHEMA_10_VERSION = "0010_matrix_store"
SCHEMA_11_VERSION = "0011_marginnote_store"
SCHEMA_12_VERSION = "0012_offline_import_stage"
SCHEMA_13_VERSION = "0013_courses"
SCHEMA_14_VERSION = "0014_externalized_runtime"
SCHEMA_1_SHA256 = "f6a3825321c2d5aaf7f82842e8eed6df7742a2e6a8c7d6bc89e90c013c8a98b8"
SCHEMA_1_LEGACY_ROLE_GRANT_SHA256 = "06a1a9303d9d45745a31a94ec9a95ce2d864e48ff41be2a6a8d926abdeea7a3f"


def _schema_1_bytes() -> bytes:
    return (
        files("deeptutor.persistence.postgres.migrations")
        .joinpath(f"{SCHEMA_1_VERSION}.sql")
        .read_bytes()
    )


def _single_owner_dsn(pg_dsn: str) -> str:
    info = conninfo_to_dict(pg_dsn)
    role = "owner_" + uuid.uuid4().hex
    with psycopg.connect(pg_dsn) as connection:
        connection.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(sql.Identifier(role))
        )
        connection.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(info["dbname"]), sql.Identifier(role)
            )
        )
    return make_conninfo(**{**info, "user": role})


async def test_core_resource_keeps_schema_1_bytes_and_does_not_connect_on_read(monkeypatch):
    async def unexpected_connect(*args, **kwargs):
        raise AssertionError("读取 core migration 资源时不应连接数据库")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", unexpected_connect)
    assert hashlib.sha256(_schema_1_bytes()).hexdigest() == SCHEMA_1_SHA256
    assert MigrationRunner("host=not-used")._migrations()[0][0] == SCHEMA_1_VERSION


async def test_empty_database_apply_accepts_single_database_owner_without_createrole(pg_dsn):
    """生产迁移若仍要求创建独立运行角色，会阻断单库单用户部署。"""

    owner_dsn = _single_owner_dsn(pg_dsn)

    async with await psycopg.AsyncConnection.connect(owner_dsn) as connection:
        capabilities = await (
            await connection.execute(
                """
                SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls
                FROM pg_roles
                WHERE rolname = current_user
                """
            )
        ).fetchone()
    assert capabilities == (False, False, False, False)

    runner = MigrationRunner(owner_dsn)
    await runner.apply()
    await runner.verify()

    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        role_exists = await (
            await connection.execute("SELECT 1 FROM pg_roles WHERE rolname='dt_enterprise_app'")
        ).fetchone()
    assert role_exists is None


async def test_empty_database_apply_is_repeatable_and_concurrent(pg_dsn):
    runners = [MigrationRunner(pg_dsn), MigrationRunner(pg_dsn)]
    assert await runners[0].plan() == [
        SCHEMA_1_VERSION,
        SCHEMA_2_VERSION,
        SCHEMA_3_VERSION,
        SCHEMA_4_VERSION,
        SCHEMA_5_VERSION,
        SCHEMA_6_VERSION,
        SCHEMA_7_VERSION,
        SCHEMA_8_VERSION,
        SCHEMA_9_VERSION,
        SCHEMA_10_VERSION,
        SCHEMA_11_VERSION,
        SCHEMA_12_VERSION,
        SCHEMA_13_VERSION,
        SCHEMA_14_VERSION,
    ]

    await asyncio.gather(*(runner.apply() for runner in runners))
    await asyncio.gather(*(runner.apply() for runner in runners))

    assert await runners[0].plan() == []
    await runners[0].verify()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        history = await (
            await connection.execute(
                "SELECT version, checksum FROM enterprise.schema_history ORDER BY version"
            )
        ).fetchall()
    assert history[0] == (SCHEMA_1_VERSION, SCHEMA_1_SHA256)
    assert history[1][0] == SCHEMA_2_VERSION
    assert history[2][0] == SCHEMA_3_VERSION
    assert history[3][0] == SCHEMA_4_VERSION
    assert history[4][0] == SCHEMA_5_VERSION
    assert history[5][0] == SCHEMA_6_VERSION
    assert history[6][0] == SCHEMA_7_VERSION
    assert history[7][0] == SCHEMA_8_VERSION
    assert history[8][0] == SCHEMA_9_VERSION
    assert history[9][0] == SCHEMA_10_VERSION
    assert history[10][0] == SCHEMA_11_VERSION
    assert history[11][0] == SCHEMA_12_VERSION
    assert history[12][0] == SCHEMA_13_VERSION
    assert history[13][0] == SCHEMA_14_VERSION
    assert len(history) == 14


async def test_role_grant_only_legacy_schema_1_checksum_remains_verifiable(pg_dsn):
    """已应用库若只因移除独立运行角色授权导致 checksum 不同，不应被误判为结构漂移。"""

    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute("CREATE SCHEMA enterprise")
        await connection.execute(
            """CREATE TABLE enterprise.schema_history (
                   version text PRIMARY KEY,
                   checksum text NOT NULL,
                   applied_at timestamptz NOT NULL DEFAULT now()
               )"""
        )
        await connection.execute(_schema_1_bytes().decode("utf-8"), prepare=False)
        await connection.execute(
            "INSERT INTO enterprise.schema_history(version, checksum) VALUES (%s, %s)",
            (SCHEMA_1_VERSION, SCHEMA_1_LEGACY_ROLE_GRANT_SHA256),
        )

    assert (await MigrationRunner(pg_dsn).plan())[0] == SCHEMA_2_VERSION


async def test_existing_schema_1_history_data_and_all_ids_are_preserved(pg_dsn):
    tenant_id = uuid.UUID("10000000-0000-0000-0000-000000000001")
    auth_session_id = uuid.UUID("20000000-0000-0000-0000-000000000002")
    executor_id = uuid.UUID("30000000-0000-0000-0000-000000000003")
    schema_sql = _schema_1_bytes().decode("utf-8")

    # 模拟旧 enterprise runner 已经应用 schema 1 并产生首切片完整数据。
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute("CREATE SCHEMA enterprise")
        await connection.execute("""CREATE TABLE enterprise.schema_history (
                   version text PRIMARY KEY,
                   checksum text NOT NULL,
                   applied_at timestamptz NOT NULL DEFAULT now()
               )""")
        await connection.execute(schema_sql, prepare=False)
        await connection.execute(
            "INSERT INTO enterprise.schema_history(version, checksum) VALUES (%s, %s)",
            (SCHEMA_1_VERSION, SCHEMA_1_SHA256),
        )
        await connection.execute(
            """INSERT INTO enterprise.tenants(
                   id, external_eligibility, provisioning_status, auth_epoch,
                   bootstrap_completed
               ) VALUES (%s, 'not_required', 'ready', 'epoch-legacy', true)""",
            (tenant_id,),
        )
        await connection.execute(
            """INSERT INTO enterprise.users(tenant_id, id, username, role)
               VALUES (%s, 'user-legacy', 'legacy', 'user')""",
            (tenant_id,),
        )
        await connection.execute(
            """INSERT INTO enterprise.local_credentials(tenant_id, user_id, password_hash)
               VALUES (%s, 'user-legacy', 'hash-legacy')""",
            (tenant_id,),
        )
        await connection.execute(
            """INSERT INTO enterprise.auth_sessions(
                   tenant_id, user_id, id, auth_version, auth_epoch, expires_at
               ) VALUES (%s, 'user-legacy', %s, 1, 'epoch-legacy', now() + interval '1 day')""",
            (tenant_id, auth_session_id),
        )
        await connection.execute(
            """INSERT INTO enterprise.audit(
                   id, tenant_id, actor_id, action, target_id, request_id, result
               ) OVERRIDING SYSTEM VALUE
               VALUES (31, %s, 'user-legacy', 'legacy', 'target-legacy',
                       'request-legacy', 'ok')""",
            (tenant_id,),
        )
        await connection.execute(
            """INSERT INTO enterprise.sessions(tenant_id, owner_id, id, title)
               VALUES (%s, 'user-legacy', 'session-legacy', 'Legacy')""",
            (tenant_id,),
        )
        await connection.execute(
            """INSERT INTO enterprise.messages(
                   tenant_id, owner_id, session_id, id, role, content
               ) OVERRIDING SYSTEM VALUE
               VALUES (%s, 'user-legacy', 'session-legacy', 41, 'user', 'question'),
                      (%s, 'user-legacy', 'session-legacy', 42, 'assistant', 'answer')""",
            (tenant_id, tenant_id),
        )
        await connection.execute(
            """UPDATE enterprise.messages SET parent_message_id=41
               WHERE tenant_id=%s AND id=42""",
            (tenant_id,),
        )
        await connection.execute(
            """UPDATE enterprise.sessions
               SET active_leaf_id=42, summary_up_to_msg_id=42
               WHERE tenant_id=%s AND id='session-legacy'""",
            (tenant_id,),
        )
        await connection.execute(
            """INSERT INTO enterprise.turns(
                   tenant_id, user_id, session_id, id, status, owner_id,
                   assistant_message_id, user_message_id
               ) VALUES (%s, 'user-legacy', 'session-legacy', 'turn-legacy',
                         'completed', 'user-legacy', 42, 41)""",
            (tenant_id,),
        )
        await connection.execute(
            """INSERT INTO enterprise.turn_events(
                   tenant_id, owner_id, session_id, turn_id, seq, event
               ) VALUES (%s, 'user-legacy', 'session-legacy', 'turn-legacy',
                         7, '{"type":"legacy"}')""",
            (tenant_id,),
        )
        await connection.execute(
            """INSERT INTO enterprise.operations(
                   tenant_id, owner_id, operation_id, fingerprint, request,
                   session_id, turn_id
               ) VALUES (%s, 'user-legacy', 'operation-legacy', 'fingerprint-legacy',
                         '{}', 'session-legacy', 'turn-legacy')""",
            (tenant_id,),
        )
        await connection.execute(
            """INSERT INTO enterprise.turn_commands(
                   tenant_id, owner_id, session_id, turn_id, command_id, kind,
                   fingerprint, accepted, state_version
               ) VALUES (%s, 'user-legacy', 'session-legacy', 'turn-legacy',
                         'command-legacy', 'cancel', 'command-fingerprint', false, 1)""",
            (tenant_id,),
        )
        await connection.execute(
            """INSERT INTO enterprise.executor_state(resource, execution_id, status)
               VALUES ('resource-legacy', %s, 'stopped')""",
            (executor_id,),
        )

    runner = MigrationRunner(pg_dsn)
    assert await runner.plan() == [
        SCHEMA_2_VERSION,
        SCHEMA_3_VERSION,
        SCHEMA_4_VERSION,
        SCHEMA_5_VERSION,
        SCHEMA_6_VERSION,
        SCHEMA_7_VERSION,
        SCHEMA_8_VERSION,
        SCHEMA_9_VERSION,
        SCHEMA_10_VERSION,
        SCHEMA_11_VERSION,
        SCHEMA_12_VERSION,
        SCHEMA_13_VERSION,
        SCHEMA_14_VERSION,
    ]
    await runner.apply()
    await runner.verify()

    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        preserved = {
            "tenant": (
                await (await connection.execute("SELECT id FROM enterprise.tenants")).fetchone()
            )[0],
            "user": (
                await (await connection.execute("SELECT id FROM enterprise.users")).fetchone()
            )[0],
            "auth_session": (
                await (
                    await connection.execute("SELECT id FROM enterprise.auth_sessions")
                ).fetchone()
            )[0],
            "audit": (
                await (await connection.execute("SELECT id FROM enterprise.audit")).fetchone()
            )[0],
            "session": (
                await (await connection.execute("SELECT id FROM enterprise.sessions")).fetchone()
            )[0],
            "messages": [
                row[0]
                for row in await (
                    await connection.execute("SELECT id FROM enterprise.messages ORDER BY id")
                ).fetchall()
            ],
            "turn": (
                await (await connection.execute("SELECT id FROM enterprise.turns")).fetchone()
            )[0],
            "event": (
                await (
                    await connection.execute("SELECT seq FROM enterprise.turn_events")
                ).fetchone()
            )[0],
            "operation": (
                await (
                    await connection.execute("SELECT operation_id FROM enterprise.operations")
                ).fetchone()
            )[0],
            "command": (
                await (
                    await connection.execute("SELECT command_id FROM enterprise.turn_commands")
                ).fetchone()
            )[0],
            "executor": (
                await (
                    await connection.execute("SELECT execution_id FROM enterprise.executor_state")
                ).fetchone()
            )[0],
        }
        history = await (
            await connection.execute(
                "SELECT version, checksum FROM enterprise.schema_history ORDER BY version"
            )
        ).fetchall()

    assert preserved == {
        "tenant": tenant_id,
        "user": "user-legacy",
        "auth_session": auth_session_id,
        "audit": 31,
        "session": "session-legacy",
        "messages": [41, 42],
        "turn": "turn-legacy",
        "event": 7,
        "operation": "operation-legacy",
        "command": "command-legacy",
        "executor": executor_id,
    }
    assert history[0] == (SCHEMA_1_VERSION, SCHEMA_1_SHA256)
    assert history[1][0] == SCHEMA_2_VERSION
    assert history[2][0] == SCHEMA_3_VERSION
    assert history[3][0] == SCHEMA_4_VERSION
    assert history[4][0] == SCHEMA_5_VERSION
    assert history[5][0] == SCHEMA_6_VERSION
    assert history[6][0] == SCHEMA_7_VERSION
    assert history[7][0] == SCHEMA_8_VERSION
    assert history[8][0] == SCHEMA_9_VERSION
    assert history[9][0] == SCHEMA_10_VERSION
    assert history[10][0] == SCHEMA_11_VERSION
    assert history[11][0] == SCHEMA_12_VERSION
    assert history[12][0] == SCHEMA_13_VERSION
    assert history[13][0] == SCHEMA_14_VERSION
    assert len(history) == 14


@pytest.mark.parametrize(
    "mutation",
    [
        "ALTER TABLE enterprise.sessions ALTER COLUMN owner_id DROP NOT NULL",
        "DROP POLICY owner_scope ON enterprise.messages",
        "DROP INDEX enterprise.one_active_turn",
    ],
)
async def test_real_catalog_drift_is_rejected(pg_dsn, mutation):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(mutation)

    with pytest.raises(RuntimeError, match="drift"):
        await runner.verify()
    with pytest.raises(RuntimeError, match="drift"):
        await runner.apply()


@pytest.mark.parametrize("already_applied", [False, True])
async def test_failed_migration_rolls_back_schema_data_and_history(pg_dsn, already_applied):
    if already_applied:
        await MigrationRunner(pg_dsn).apply()

    class FailingRunner(MigrationRunner):
        def _migrations(self):
            return super()._migrations() + [
                (
                    "0015_failure",
                    """
                    CREATE TABLE enterprise.uncommitted_probe (id integer PRIMARY KEY);
                    INSERT INTO enterprise.executor_state(resource, execution_id, status)
                    VALUES ('must-rollback',
                            '00000000-0000-0000-0000-000000000001', 'active');
                    SELECT 1/0;
                    """,
                )
            ]

    with pytest.raises(psycopg.errors.DivisionByZero):
        await FailingRunner(pg_dsn).apply()

    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        probe = await (
            await connection.execute("SELECT to_regclass('enterprise.uncommitted_probe')")
        ).fetchone()
        if already_applied:
            assert probe[0] is None
            assert await (
                await connection.execute(
                    "SELECT version FROM enterprise.schema_history ORDER BY version"
                )
            ).fetchall() == [
                (SCHEMA_1_VERSION,),
                (SCHEMA_2_VERSION,),
                (SCHEMA_3_VERSION,),
                (SCHEMA_4_VERSION,),
                (SCHEMA_5_VERSION,),
                (SCHEMA_6_VERSION,),
                (SCHEMA_7_VERSION,),
                (SCHEMA_8_VERSION,),
                (SCHEMA_9_VERSION,),
                (SCHEMA_10_VERSION,),
                (SCHEMA_11_VERSION,),
                (SCHEMA_12_VERSION,),
                (SCHEMA_13_VERSION,),
                (SCHEMA_14_VERSION,),
            ]
            assert (
                await (
                    await connection.execute(
                        "SELECT resource FROM enterprise.executor_state WHERE resource='must-rollback'"
                    )
                ).fetchall()
                == []
            )
        else:
            assert probe[0] is None
            namespace = await (
                await connection.execute("SELECT to_regnamespace('enterprise')")
            ).fetchone()
            assert namespace[0] is None


async def test_enterprise_runner_extends_core_and_keeps_no_root_sql_copy():
    enterprise_runner = pytest.importorskip("deeptutor_enterprise.migrations.runner")
    EnterpriseMigrationRunner = enterprise_runner.MigrationRunner

    assert issubclass(EnterpriseMigrationRunner, MigrationRunner)
    assert [
        item.name
        for item in files("deeptutor_enterprise.migrations").iterdir()
        if item.name.endswith(".sql")
    ] == []
