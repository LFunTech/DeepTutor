"""Task 1.2：共用业务 PostgreSQL fixture 的真实数据库契约。"""

from __future__ import annotations

from dataclasses import replace

import psycopg
import pytest

pytestmark = pytest.mark.asyncio


async def test_migrated_database_uses_product_runner_and_restricted_runtime_role(
    migrated_pg,
    business_database,
    business_actors,
):
    assert migrated_pg.schema_versions[0] == "0001_identity_sessions"

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        role = await (
            await connection.execute(
                """SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls
                     FROM pg_roles WHERE rolname = %s""",
                (migrated_pg.runtime_role,),
            )
        ).fetchone()
    assert role == (migrated_pg.runtime_role, False, False, False, False)

    actor = business_actors.tenants[0].owners[0]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with business_database.transaction(actor.scope) as connection:
            await connection.execute("CREATE TABLE enterprise.fixture_must_not_exist(id int)")

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        relation = await (
            await connection.execute("SELECT to_regclass('enterprise.fixture_must_not_exist')")
        ).fetchone()
    assert relation == (None,)


async def test_actor_and_existing_session_store_factories_enforce_owner_scope(
    migrated_pg,
    business_database,
    business_actors,
    pg_session_store_factory,
):
    assert len(business_actors.tenants) == 2
    assert all(len(tenant.owners) == 2 for tenant in business_actors.tenants)
    assert all(tenant.admin.role == "tenant_admin" for tenant in business_actors.tenants)
    assert all(
        actor.role == "user" for tenant in business_actors.tenants for actor in tenant.owners
    )

    expected = {}
    for tenant_index, tenant in enumerate(business_actors.tenants):
        for owner_index, actor in enumerate(tenant.owners):
            store = pg_session_store_factory(actor)
            session_id = f"tenant-{tenant_index}-owner-{owner_index}"
            created = await store.create_session(
                f"T{tenant_index} O{owner_index}", session_id=session_id
            )
            expected[actor.scope] = created["id"]

    for tenant in business_actors.tenants:
        assert await pg_session_store_factory(tenant.admin).list_sessions() == []
        for actor in tenant.owners:
            rows = await pg_session_store_factory(actor).list_sessions()
            assert [row["id"] for row in rows] == [expected[actor.scope]]

    # 直接使用受限连接也必须经过相同的 RLS，而非仅靠 Store 的 WHERE 条件。
    first = business_actors.tenants[0].owners[0]
    async with business_database.transaction(first.scope) as connection:
        visible = await (
            await connection.execute("SELECT owner_id, id FROM enterprise.sessions ORDER BY id")
        ).fetchall()
    assert visible == [{"owner_id": first.user_id, "id": expected[first.scope]}]

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        totals = await (
            await connection.execute(
                "SELECT count(DISTINCT tenant_id), count(*) FROM enterprise.sessions"
            )
        ).fetchone()
    assert totals == (2, 4)


async def test_scope_and_sync_database_fixture_use_explicit_authenticated_actor(
    business_sync_database,
    business_actors,
    pg_scope_factory,
):
    actor = business_actors.tenants[1].owners[1]
    scope = pg_scope_factory(actor)
    settings = await business_sync_database.run(
        scope,
        lambda connection: connection.execute(
            """SELECT current_setting('app.tenant_id') AS tenant_id,
                      current_setting('app.user_id') AS user_id"""
        ).fetchone(),
    )
    assert settings == {"tenant_id": actor.tenant_id, "user_id": actor.user_id}

    with pytest.raises(TypeError, match="issued by business_actors"):
        pg_scope_factory((actor.tenant_id, actor.user_id))


async def test_actor_factories_reject_unissued_scope_and_actor_copies(
    business_actors,
    pg_scope_factory,
    pg_session_store_factory,
):
    issued = business_actors.tenants[0].owners[0]
    raw_scope = issued.scope
    replaced_copy = replace(issued)
    constructed_copy = type(issued)(
        tenant_id=issued.tenant_id,
        user_id=issued.user_id,
        username=issued.username,
        role=issued.role,
        token=issued.token,
        identity=issued.identity,
        scope=issued.scope,
    )

    for unissued in (raw_scope, replaced_copy, constructed_copy):
        with pytest.raises(TypeError):
            pg_scope_factory(unissued)
        with pytest.raises(TypeError):
            pg_session_store_factory(unissued)


async def test_all_six_issued_actors_work_through_async_sync_session_and_rls(
    business_database,
    business_sync_database,
    business_actors,
    pg_scope_factory,
    pg_session_store_factory,
):
    actors = tuple(
        actor for tenant in business_actors.tenants for actor in (tenant.admin, *tenant.owners)
    )
    assert len(actors) == 6

    for index, actor in enumerate(actors):
        scope = pg_scope_factory(actor)
        async with business_database.transaction(scope) as connection:
            settings = await (
                await connection.execute(
                    """SELECT current_setting('app.tenant_id') AS tenant_id,
                              current_setting('app.user_id') AS user_id"""
                )
            ).fetchone()
        assert settings == {"tenant_id": actor.tenant_id, "user_id": actor.user_id}

        sync_settings = await business_sync_database.run(
            scope,
            lambda connection: connection.execute(
                """SELECT current_setting('app.tenant_id') AS tenant_id,
                          current_setting('app.user_id') AS user_id"""
            ).fetchone(),
        )
        assert sync_settings == settings

        store = pg_session_store_factory(actor)
        session_id = f"issued-{index}-{actor.user_id}"
        await store.create_session(f"Issued actor {index}", session_id=session_id)
        assert [row["id"] for row in await store.list_sessions()] == [session_id]

        # 同步直查同样由 RLS 收窄到当前 actor，包含 admin 的个人数据边界。
        assert (
            await business_sync_database.run(
                scope,
                lambda connection: connection.execute(
                    "SELECT count(*) AS count FROM enterprise.sessions"
                ).fetchone()["count"],
            )
            == 1
        )
