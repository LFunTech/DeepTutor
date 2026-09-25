"""全业务 PG adapter 共用的隔离 fixture。

这里只装配已经存在的产品 migration、受限 ``Database``、身份服务和
``PostgresSessionStore``。尚未实现的领域 adapter 必须由各自任务追加 factory，
不得在这里用 SQLite、内存库或测试 stub 冒充。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import uuid
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest
import pytest_asyncio

from deeptutor.persistence.postgres.connection import Database, SyncDatabase
from deeptutor.persistence.postgres.identity.service import Identity, IdentityService
from deeptutor.persistence.postgres.migrations.runner import MigrationRunner
from deeptutor.persistence.postgres.scope import TenantScope
from deeptutor.persistence.postgres.session import PostgresSessionStore

SCHEMA_1 = "0001_identity_sessions"
_SIGNING_KEY = "task-1.2-signing-key-is-synthetic-and-long-enough"
_BOOTSTRAP_SECRET = "task-1.2-bootstrap-secret-is-synthetic-and-long-enough"


def _single_owner_dsn(dsn: str) -> tuple[str, str]:
    info = conninfo_to_dict(dsn)
    role = "owner_" + uuid.uuid4().hex
    with psycopg.connect(dsn) as connection:
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
    return make_conninfo(**{**info, "user": role}), role


@dataclass(frozen=True, slots=True)
class MigratedPostgres:
    admin_dsn: str
    runtime_dsn: str
    runtime_role: str
    schema_versions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TestActor:
    tenant_id: str
    user_id: str
    username: str
    role: str
    token: str
    identity: Identity
    scope: TenantScope


@dataclass(frozen=True, slots=True)
class TenantActors:
    tenant_id: str
    identity_service: IdentityService
    admin: TestActor
    owners: tuple[TestActor, TestActor]


@dataclass(frozen=True, slots=True)
class BusinessActors:
    tenants: tuple[TenantActors, TenantActors]


@pytest_asyncio.fixture
async def migrated_pg(pg_dsn) -> MigratedPostgres:
    """对每测试独立数据库运行真实产品 migration，并验证 catalog。"""

    owner_dsn, runtime_role = _single_owner_dsn(pg_dsn)
    runner = MigrationRunner(owner_dsn)
    pending = await runner.plan()
    assert pending and pending[0] == SCHEMA_1
    await runner.apply()
    await runner.verify()
    assert await runner.plan() == []
    async with await psycopg.AsyncConnection.connect(owner_dsn) as connection:
        versions = tuple(
            row[0]
            for row in await (
                await connection.execute(
                    "SELECT version FROM enterprise.schema_history ORDER BY version"
                )
            ).fetchall()
        )
    return MigratedPostgres(
        admin_dsn=owner_dsn,
        runtime_dsn=owner_dsn,
        runtime_role=runtime_role,
        schema_versions=versions,
    )


@pytest_asyncio.fixture
async def business_database(migrated_pg: MigratedPostgres):
    """共享一个有界、低权的产品数据库池，并在 teardown 等待完整关闭。"""

    async with Database(
        migrated_pg.runtime_dsn,
        resource="task-1.2-business-contract",
        max_size=4,
        max_waiting=8,
    ) as database:
        yield database


@pytest_asyncio.fixture
async def business_sync_database(migrated_pg: MigratedPostgres):
    """同步领域 Store 通过该有界 worker 使用同一受限运行角色。"""

    async with SyncDatabase(
        migrated_pg.runtime_dsn,
        resource="task-1.2-business-sync-contract",
        max_size=4,
        max_waiting=8,
    ) as database:
        yield database


async def _authenticated_actor(
    service: IdentityService,
    record: dict,
    password: str,
    *,
    client: str,
) -> TestActor:
    token = await service.login(record["username"], password, client=client)
    identity = await service.authenticate(token)
    return TestActor(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        username=identity.username,
        role=identity.role,
        token=token,
        identity=identity,
        scope=TenantScope(identity.tenant_id, identity.user_id),
    )


@pytest_asyncio.fixture
async def business_actors(business_database: Database) -> BusinessActors:
    """每测试建立两个 tenant；每个 tenant 有一名 admin 和两名普通 owner。"""

    tenants = []
    for index in (1, 2):
        tenant_id = str(UUID(f"10000000-0000-0000-0000-00000000000{index}"))
        service = IdentityService(
            business_database,
            tenant_id=tenant_id,
            signing_key=_SIGNING_KEY,
            auth_epoch="task-1.2-epoch",
            bootstrap_secret=_BOOTSTRAP_SECRET,
        )
        admin_password = f"admin-password-{index:02d}"
        admin_record = await service.bootstrap(
            f"admin-{index}", admin_password, secret=_BOOTSTRAP_SECRET
        )
        admin = await _authenticated_actor(
            service, admin_record, admin_password, client=f"tenant-{index}-admin"
        )

        owners = []
        for owner_index in (1, 2):
            password = f"owner-password-{index}-{owner_index}"
            record = await service.create_user(
                admin.token, f"owner-{index}-{owner_index}", password
            )
            owners.append(
                await _authenticated_actor(
                    service,
                    record,
                    password,
                    client=f"tenant-{index}-owner-{owner_index}",
                )
            )
        tenants.append(
            TenantActors(
                tenant_id=tenant_id,
                identity_service=service,
                admin=admin,
                owners=(owners[0], owners[1]),
            )
        )
    return BusinessActors(tenants=(tenants[0], tenants[1]))


@pytest.fixture
def pg_scope_factory(business_actors: BusinessActors) -> Callable[[TestActor], TenantScope]:
    """只从已由产品 IdentityService 认证的测试 actor 取得可信 scope。"""

    issued_actors = tuple(
        actor for tenant in business_actors.tenants for actor in (tenant.admin, *tenant.owners)
    )

    def factory(actor: TestActor) -> TenantScope:
        if not isinstance(actor, TestActor) or not any(
            actor is issued_actor for issued_actor in issued_actors
        ):
            raise TypeError("actor must be issued by business_actors after product authentication")
        return actor.scope

    return factory


@pytest.fixture
def pg_session_store_factory(
    business_database: Database,
    pg_scope_factory: Callable[[TestActor], TenantScope],
) -> Callable[[TestActor], PostgresSessionStore]:
    """只构造已存在的真实 PG session Store；不兜底任何未迁移领域。"""

    def factory(actor: TestActor) -> PostgresSessionStore:
        return PostgresSessionStore(business_database, pg_scope_factory(actor))

    return factory


@pytest.fixture
def pg_learning_store_factory(business_sync_database, pg_scope_factory):
    """PG学习factory只接纳产品身份服务已发放actor，不接raw scope或fallback。"""
    from deeptutor.persistence.postgres.learning import AsyncLearningStore

    def factory(actor, *, authority=None):
        return AsyncLearningStore(
            business_sync_database, pg_scope_factory(actor), authority=authority
        )

    return factory
