"""两 tenant 六主体、真实并发、生命周期和错误回滚。"""

import asyncio
import base64
import json
import threading

import psycopg
import pytest

from deeptutor.reading.catalog_contracts import ReadingConflictError, ReadingReferenceError
from deeptutor.reading.models import ReadingError
from tests.persistence.postgres.business.test_reading_catalog import factory

pytestmark = pytest.mark.asyncio


async def test_two_tenants_six_actors_same_ids_and_composite_references(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory,
    restricted_business_dsn,
):
    actors = [a for t in business_actors.tenants for a in (t.admin, *t.owners)]
    stores = []
    for i, a in enumerate(actors):
        store = factory(business_sync_database, pg_scope_factory, a)
        stores.append(store)
        await pg_session_store_factory(a).create_session(session_id=f"s{i}")

        def seed(u):
            u.upsert_material(
                content_id="same", filename="same", title=str(i), source_kind="file", status="ready"
            )
            u.upsert_material(
                content_id=f"only{i}", filename="only", title="only", source_kind="file"
            )
            u.create_workspace("same", ["same"], workspace_id="w")
            u.attach_session("w", f"s{i}", active_material_id="same")

        await store.run(seed)
    for i, store in enumerate(stores):
        assert (await store.run(lambda u: u.get_material("same"))).title == str(i)
        assert await store.run(lambda u: u.get_material(f"only{(i + 1) % 6}")) is None
        before = await store.run(lambda u: u.get_workspace("w"))
        with pytest.raises(ReadingError):
            await store.run(lambda u: u.add_material("w", f"only{(i + 1) % 6}"))
        # 绕过应用 require 仍由同 scope material FK 拒绝。
        with pytest.raises(ReadingReferenceError):
            await store.run(
                lambda u: u._execute(
                    """INSERT INTO enterprise.reading_workspace_materials(tenant_id,owner_id,workspace_id,material_id,tab_order,pinned,opened,added_at) VALUES(%s,%s,'w',%s,9,false,true,0)""",
                    (*u._owner, f"only{(i + 1) % 6}"),
                )
            )
        assert await store.run(lambda u: u.get_workspace("w")) == before
    # 使用非表 owner 的受限角色验收 RLS，避免只依赖迁移 owner 路径。
    from deeptutor.persistence.postgres.connection import SyncDatabase

    async with SyncDatabase(restricted_business_dsn, resource="reading-rls-negative") as db:
        restricted_store = factory(db, pg_scope_factory, actors[0])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await restricted_store.run(
                lambda u: u._execute(
                    "UPDATE enterprise.reading_materials SET owner_id=%s WHERE tenant_id=%s AND owner_id=%s AND material_id=%s",
                    (actors[1].user_id, *u._owner, "only0"),
                )
            )
        assert await restricted_store.run(lambda u: u.get_material("only0")) is not None


async def test_reading_material_unknown_persisted_state_cannot_be_read_or_overwritten(
    business_sync_database, business_actors, pg_scope_factory, pg_dsn,
):
    actor = business_actors.tenants[0].owners[0]
    store = factory(business_sync_database, pg_scope_factory, actor)
    await store.run(
        lambda u: u.upsert_material(
            content_id="unknown-state", filename="m", title="m",
            source_kind="file", status="queued",
        )
    )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "ALTER TABLE enterprise.reading_materials "
            "DROP CONSTRAINT IF EXISTS reading_materials_source_kind_check"
        )
        await c.execute(
            "UPDATE enterprise.reading_materials SET source_kind='future-source' "
            "WHERE tenant_id=%s AND owner_id=%s AND material_id='unknown-state'",
            (actor.tenant_id, actor.user_id),
        )
    with pytest.raises(ReadingError, match="source|state"):
        await store.run(lambda u: u.get_material("unknown-state"))
    with pytest.raises(ReadingError, match="source|state"):
        await store.run(
            lambda u: u.upsert_material(
                content_id="unknown-state", material_id="unknown-state",
                filename="m", title="overwrite", source_kind="file", status="ready",
            )
        )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        row = await (
            await c.execute(
                "SELECT source_kind,title FROM enterprise.reading_materials "
                "WHERE tenant_id=%s AND owner_id=%s AND material_id='unknown-state'",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        assert row == ("future-source", "m")
        await c.execute(
            "ALTER TABLE enterprise.reading_materials "
            "DROP CONSTRAINT IF EXISTS reading_materials_status_check"
        )
        await c.execute(
            "UPDATE enterprise.reading_materials SET source_kind='file',status='future-state' "
            "WHERE tenant_id=%s AND owner_id=%s AND material_id='unknown-state'",
            (actor.tenant_id, actor.user_id),
        )
    with pytest.raises(ReadingError, match="source|state"):
        await store.run(lambda u: u.get_material("unknown-state"))
    with pytest.raises(ReadingError, match="source|state"):
        await store.run(
            lambda u: u.upsert_material(
                content_id="unknown-state", material_id="unknown-state",
                filename="m", title="overwrite", source_kind="file", status="ready",
            )
        )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "ALTER TABLE enterprise.reading_materials "
            "DROP CONSTRAINT IF EXISTS reading_materials_check"
        )
        await c.execute(
            "UPDATE enterprise.reading_materials SET status='ready',progress=0 "
            "WHERE tenant_id=%s AND owner_id=%s AND material_id='unknown-state'",
            (actor.tenant_id, actor.user_id),
        )
    with pytest.raises(ReadingError, match="progress"):
        await store.run(lambda u: u.get_material("unknown-state"))


@pytest.mark.parametrize(
    ("constraint", "mutation"),
    [
        ("reading_materials_source_kind_check", "source_kind='future-source'"),
        ("reading_materials_status_check", "status='future-state'"),
        ("reading_materials_check", "status='ready',progress=0"),
    ],
)
async def test_reading_library_counts_rejects_unknown_material_state(
    migrated_pg, business_sync_database, business_actors, pg_scope_factory,
    constraint, mutation,
) -> None:
    """聚合计数不能将未知状态的材料当正常材料计入。"""

    actor = business_actors.tenants[0].owners[0]
    store = factory(business_sync_database, pg_scope_factory, actor)
    await store.run(
        lambda u: u.upsert_material(
            content_id="count-unknown", material_id="count-unknown",
            filename="m", title="m", source_kind="file",
        )
    )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "ALTER TABLE enterprise.reading_materials "
                f"DROP CONSTRAINT IF EXISTS {constraint}"
            )
            await connection.execute(
                f"UPDATE enterprise.reading_materials SET {mutation} "
                "WHERE tenant_id=%s AND owner_id=%s AND material_id='count-unknown'",
                (actor.tenant_id, actor.user_id),
            )

    with pytest.raises(ReadingError, match="source|state"):
        await store.run(lambda u: u.library_counts())


async def test_reading_library_counts_keeps_independent_media_dimensions(
    business_sync_database, business_actors, pg_scope_factory,
) -> None:
    """旧统计允许来源与呈现模式同时命中不同媒体类别。"""

    actor = business_actors.tenants[0].owners[0]
    store = factory(business_sync_database, pg_scope_factory, actor)

    def seed(unit):
        unit.upsert_material(
            content_id="video-audio", material_id="video-audio",
            filename="v", title="v", source_kind="video", render_mode="audio",
        )
        unit.upsert_material(
            content_id="audio-video", material_id="audio-video",
            filename="a", title="a", source_kind="audio", render_mode="video",
        )
        return unit.library_counts()

    counts = await store.run(seed)
    assert counts["all"] == 2
    assert counts["by_kind"] == {"document": 0, "web": 0, "video": 2, "audio": 2}


async def test_reading_summary_workspace_creation_rejects_unknown_material_source(
    migrated_pg, business_sync_database, business_actors, pg_scope_factory,
) -> None:
    actor = business_actors.tenants[0].owners[0]
    store = factory(business_sync_database, pg_scope_factory, actor)
    await store.run(
        lambda u: u.upsert_material(
            content_id="unknown-workspace", material_id="unknown-workspace",
            filename="m", title="m", source_kind="file",
        )
    )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "ALTER TABLE enterprise.reading_materials "
                "DROP CONSTRAINT IF EXISTS reading_materials_source_kind_check"
            )
            await connection.execute(
                "UPDATE enterprise.reading_materials SET source_kind='future-source' "
                "WHERE tenant_id=%s AND owner_id=%s AND material_id='unknown-workspace'",
                (actor.tenant_id, actor.user_id),
            )

    with pytest.raises(ReadingError, match="source|state"):
        await store.run(
            lambda u: u.create_workspace(
                "Synthetic", ["unknown-workspace"], workspace_id="reject-unknown",
                return_summary=True,
            )
        )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT 1 FROM enterprise.reading_workspaces "
                "WHERE tenant_id=%s AND owner_id=%s AND workspace_id='reject-unknown'",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
    assert row is None


async def test_reading_summary_active_material_rejects_unknown_existing_source(
    migrated_pg, business_sync_database, business_actors, pg_scope_factory,
) -> None:
    actor = business_actors.tenants[0].owners[0]
    store = factory(business_sync_database, pg_scope_factory, actor)

    def seed(unit):
        unit.upsert_material(
            content_id="active-unknown", material_id="active-unknown",
            filename="m", title="m", source_kind="file",
        )
        unit.create_workspace("Synthetic", ["active-unknown"], workspace_id="active-workspace")

    await store.run(seed)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "ALTER TABLE enterprise.reading_materials "
                "DROP CONSTRAINT IF EXISTS reading_materials_source_kind_check"
            )
            await connection.execute(
                "UPDATE enterprise.reading_materials SET source_kind='future-source' "
                "WHERE tenant_id=%s AND owner_id=%s AND material_id='active-unknown'",
                (actor.tenant_id, actor.user_id),
            )

    with pytest.raises(ReadingError, match="source|state"):
        await store.run(
            lambda u: u.set_active_material(
                "active-workspace", "active-unknown", expected_version=1,
                return_summary=True,
            )
        )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT version FROM enterprise.reading_workspaces "
                "WHERE tenant_id=%s AND owner_id=%s AND workspace_id='active-workspace'",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
    assert row == (1,)


@pytest.mark.parametrize("other", ["reorder", "add", "remove", "active", "update"])
async def test_two_real_connections_workspace_cas_has_exactly_one_winner(
    business_sync_database, business_actors, pg_scope_factory, other
):
    store = factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])

    def seed(u):
        for mid in ["a", "b", "c"]:
            u.upsert_material(content_id=mid, filename=mid, title=mid, source_kind="file")
        u.create_workspace("w", ["a", "b"], workspace_id="w")

    await store.run(seed)
    barrier = threading.Barrier(2)
    pids = []

    def race(u, which):
        pids.append(u._connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
        barrier.wait(timeout=5)
        if which == "reorder":
            return u.reorder_materials("w", ["b", "a"], expected_version=1)
        if which == "add":
            return u.add_material("w", "c", expected_version=1)
        if which == "remove":
            return u.remove_material("w", "a", expected_version=1)
        if which == "active":
            return u.set_active_material("w", "b", expected_version=1)
        return u.update_workspace("w", title="changed", expected_version=1)

    results = await asyncio.gather(
        store.run(lambda u: race(u, "reorder")),
        store.run(lambda u: race(u, other)),
        return_exceptions=True,
    )
    assert len(set(pids)) == 2
    conflicts = [r for r in results if isinstance(r, ReadingConflictError)]
    assert len(conflicts) == 1 and (conflicts[0].expected, conflicts[0].actual) == (1, 2)
    assert sum(not isinstance(r, BaseException) for r in results) == 1
    w = await store.run(lambda u: u.get_workspace("w"))
    assert w.version == 2
    assert [t.tab_order for t in w.tabs] == list(range(len(w.tabs)))
    assert w.active_material_id in [t.material.material_id for t in w.tabs]
    for invalid in [["a", "a"], ["missing"], []]:
        with pytest.raises(ReadingError):
            await store.run(lambda u: u.reorder_materials("w", invalid, expected_version=2))
        assert await store.run(lambda u: u.get_workspace("w")) == w


async def test_content_last_reference_serializes_new_duplicate_and_rolls_back(
    business_sync_database, business_actors, pg_scope_factory
):
    store = factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    await store.run(
        lambda u: u.upsert_material(
            content_id="shared", material_id="a", filename="a", title="a", source_kind="file"
        )
    )
    entered = threading.Event()
    release = threading.Event()
    started = threading.Event()
    plans = []

    def delete(u):
        with u.locked_content("a") as plan:
            plans.append(plan)
            entered.set()
            assert release.wait(5)
            assert u.delete_material("a", expected_version=plan.material_version)
            raise ValueError("restore catalog; external stage compensation belongs to 1.19")

    def duplicate(u):
        started.set()
        return u.upsert_material(
            content_id="shared", material_id="b", filename="b", title="b", source_kind="file"
        )

    task = asyncio.create_task(store.run(delete))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        other = asyncio.create_task(store.run(duplicate))
        assert await asyncio.to_thread(started.wait, 5)
        await asyncio.sleep(0.05)
        assert not other.done() and plans[0].last_reference
        release.set()
        with pytest.raises(ValueError):
            await task
        await other
    finally:
        release.set()
    assert await store.run(lambda u: u.count_materials_for_content("shared")) == 2
    assert await store.run(lambda u: u.get_material("a")) is not None


async def test_cursor_errors_scope_binding_and_ascii_exact_filename(
    business_sync_database, business_actors, pg_scope_factory
):
    a, b = business_actors.tenants[0].owners
    store = factory(business_sync_database, pg_scope_factory, a)
    other = factory(business_sync_database, pg_scope_factory, b)

    def seed(u):
        for mid, name, mime in [("a", "Name", "ok"), ("b", "NAME", "wrong"), ("c", "Ä", "ok")]:
            u.upsert_material(
                content_id=mid,
                filename=name,
                title=name,
                source_kind="file",
                mime=mime,
                status="ready",
            )

    await store.run(seed)
    assert (
        await store.run(lambda u: u.find_ready_material_by_filename("name", mime="ok"))
    ).material_id == "a"
    assert await store.run(lambda u: u.find_ready_material_by_filename("ä")) is None
    page = await store.run(lambda u: u.list_materials_page(limit=1))
    for action in [
        lambda: other.run(lambda u: u.list_materials_page(cursor=page.next_cursor)),
        lambda: store.run(lambda u: u.list_materials_page(search="x", cursor=page.next_cursor)),
    ]:
        with pytest.raises(ReadingError, match="cursor"):
            await action()
    for bad in [
        "bad",
        "x" * 4097,
        base64.urlsafe_b64encode(b"null").decode(),
        base64.urlsafe_b64encode(b"[]").decode(),
        False,
    ]:
        with pytest.raises(ReadingError, match="cursor"):
            await store.run(lambda u: u.list_materials_page(cursor=bad))
    fp, _ = json.loads(base64.urlsafe_b64decode(page.next_cursor))
    for values in [[True, "a"], [float("nan"), "a"], [1, "../bad"], [1], [1, "a", "extra"]]:
        cursor = base64.urlsafe_b64encode(json.dumps([fp, values]).encode()).decode()
        with pytest.raises(ReadingError, match="cursor"):
            await store.run(lambda u: u.list_materials_page(cursor=cursor))


async def test_sync_entry_thread_lease_async_callback_and_cancellation(
    business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.persistence.postgres.reading import PostgresReadingCatalogStore

    a = business_actors.tenants[0].owners[0]
    scope = pg_scope_factory(a)
    store = factory(business_sync_database, pg_scope_factory, a)
    with pytest.raises(RuntimeError, match="cannot block event loop"):
        PostgresReadingCatalogStore(business_sync_database, scope).get_material("m")
    errors = []

    def cross(u):
        def other_thread():
            try:
                u.get_material("m")
            except RuntimeError as exc:
                errors.append(str(exc))

        t = threading.Thread(target=other_thread)
        t.start()
        t.join()

    await store.run(cross)
    assert errors and "owner" in errors[0]

    async def invalid(u):
        return u.get_material("m")

    with pytest.raises(TypeError, match="synchronously"):
        await store.run(invalid)
    with pytest.raises(TypeError, match="synchronously"):
        await store.run(lambda u: (x for x in []))
    entered = threading.Event()
    release = threading.Event()
    escaped = []

    def write(u):
        escaped.append(u)
        u.upsert_material(content_id="cancelled", filename="c", title="c", source_kind="file")
        entered.set()
        assert release.wait(5)

    task = asyncio.create_task(store.run(write))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    assert await store.run(lambda u: u.get_material("cancelled")) is None
    with pytest.raises(RuntimeError, match="inactive"):
        escaped[0].get_material("m")


async def test_attach_locks_real_chat_before_existing_reading_row(
    business_sync_database,
    business_database,
    business_actors,
    pg_scope_factory,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    scope = pg_scope_factory(actor)
    store = factory(business_sync_database, pg_scope_factory, actor)
    await pg_session_store_factory(actor).create_session(session_id="s")
    await store.run(
        lambda u: (u.create_workspace("w", workspace_id="w"), u.attach_session("w", "s"))
    )
    started = threading.Event()
    pids = []
    task = None

    def attach(u):
        pids.append(u._connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
        started.set()
        return u.attach_session("w", "s", title="again")

    try:
        async with business_database.transaction(scope) as c:
            await c.execute(
                "SELECT id FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s AND id=%s FOR UPDATE",
                (*store._store._owner, "s"),
            )
            task = asyncio.create_task(store.run(attach))
            assert await asyncio.to_thread(started.wait, 5)
            # 等真实 worker 在 chat lock 上阻塞，而不是靠固定 sleep 猜交错。
            async with asyncio.timeout(5):
                while not (
                    await (
                        await c.execute(
                            "SELECT %s=ANY(pg_blocking_pids(%s)) AS blocked",
                            (c.info.backend_pid, pids[0]),
                        )
                    ).fetchone()
                )["blocked"]:
                    await asyncio.sleep(0.005)
            await c.execute(
                "SELECT workspace_id FROM enterprise.reading_workspaces WHERE tenant_id=%s AND owner_id=%s AND workspace_id='w' FOR UPDATE NOWAIT",
                store._store._owner,
            )
            await c.execute(
                "SELECT session_id FROM enterprise.reading_workspace_sessions WHERE tenant_id=%s AND owner_id=%s AND session_id=%s FOR UPDATE NOWAIT",
                (*store._store._owner, "s"),
            )
    finally:
        if task is not None:
            await task


async def test_close_waits_for_complete_reading_unit_and_reopen_recovers(
    migrated_pg, business_actors, pg_scope_factory
):
    from psycopg_pool import PoolClosed

    from deeptutor.persistence.postgres.connection import SyncDatabase
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore

    scope = pg_scope_factory(business_actors.tenants[0].owners[0])
    db = SyncDatabase(migrated_pg.runtime_dsn, resource="reading-close", max_size=1)
    await db.__aenter__()
    store = AsyncReadingCatalogStore(db, scope)
    entered = threading.Event()
    release = threading.Event()

    def write(u):
        u.upsert_material(content_id="m", filename="m", title="m", source_kind="file")
        u.create_workspace("w", ["m"], workspace_id="w")
        entered.set()
        assert release.wait(5)

    task = asyncio.create_task(store.run(write))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        close = asyncio.create_task(db.__aexit__(None, None, None))
        await asyncio.sleep(0.02)
        assert not close.done()
        with pytest.raises(PoolClosed):
            await store.run(lambda u: u.get_material("m"))
        release.set()
        await task
        await close
    finally:
        release.set()
        if not db.pool.closed:
            await db.__aexit__(None, None, None)
    assert db.pool.closed
    async with SyncDatabase(migrated_pg.runtime_dsn, resource="reading-reopen") as reopened:
        w = await AsyncReadingCatalogStore(reopened, scope).run(lambda u: u.get_workspace("w"))
        assert w.active_material_id == "m" and w.tabs[0].material.content_id == "m"


async def test_session_foreign_owner_workspace_membership_and_links_fail_atomically(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    owner, other = business_actors.tenants[0].owners
    store = factory(business_sync_database, pg_scope_factory, owner)
    for actor, sid in [(owner, "s1"), (owner, "s2"), (other, "foreign")]:
        await pg_session_store_factory(actor).create_session(session_id=sid)

    def seed(u):
        for mid in ["a", "b"]:
            u.upsert_material(content_id=mid, filename=mid, title=mid, source_kind="file")
        u.create_workspace("w", ["a"], workspace_id="w")
        u.create_workspace("v", ["b"], workspace_id="v")
        u.attach_session("w", "s1", active_material_id="a")
        u.attach_session("v", "s2", active_material_id="b")

    await store.run(seed)
    before = await store.run(lambda u: u.list_sessions("w"))
    for operation in [
        lambda u: u.attach_session("w", "foreign"),
        lambda u: u.attach_session("v", "s1"),
        lambda u: u.attach_session("w", "s1", active_material_id="b"),
        lambda u: u.link_session("w", "s1", "s2"),
        lambda u: u.link_session("w", "s1", "s1"),
    ]:
        with pytest.raises(ReadingError):
            await store.run(operation)
        assert await store.run(lambda u: u.list_sessions("w")) == before
    assert await store.run(lambda u: u.list_session_links("w", "s1")) == []
    # 直接 SQL 也必须拒绝跨 workspace active，不依赖 provider 自觉验证。
    with pytest.raises(ReadingError):
        await store.run(
            lambda u: u._execute(
                "UPDATE enterprise.reading_workspaces SET active_material_id='b' WHERE tenant_id=%s AND owner_id=%s AND workspace_id='w'",
                u._owner,
            )
        )


async def test_ready_filename_ties_preserve_old_ascending_material_id(
    business_sync_database, business_actors, pg_scope_factory
):
    store = factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])

    def seed(u):
        for mid in ["a", "b"]:
            u.upsert_material(
                content_id=mid, filename="same.pdf", title=mid, source_kind="file", status="ready"
            )
        u._execute(
            "UPDATE enterprise.reading_materials SET updated_at=1 WHERE tenant_id=%s AND owner_id=%s",
            u._owner,
        )

    await store.run(seed)
    assert (
        await store.run(lambda u: u.find_ready_material_by_filename("SAME.PDF"))
    ).material_id == "a"


async def test_content_plan_requires_bound_unit_and_nonfinite_duration_rejected(
    business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.persistence.postgres.reading import PostgresReadingCatalogStore

    actor = business_actors.tenants[0].owners[0]
    sync = PostgresReadingCatalogStore(business_sync_database, pg_scope_factory(actor))
    with pytest.raises(RuntimeError, match="bound"):
        with sync.locked_content("m"):
            pass
    store = factory(business_sync_database, pg_scope_factory, actor)
    for value in [float("nan"), float("inf")]:
        with pytest.raises(ReadingError, match="finite"):
            await store.run(
                lambda u: u.upsert_material(
                    content_id="m",
                    filename="m",
                    title="m",
                    source_kind="file",
                    duration_seconds=value,
                )
            )
    assert await store.run(lambda u: u.get_material("m")) is None


async def test_sync_public_operation_is_one_transaction_off_event_loop(
    business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.persistence.postgres.reading import PostgresReadingCatalogStore

    actor = business_actors.tenants[0].owners[0]
    sync = PostgresReadingCatalogStore(business_sync_database, pg_scope_factory(actor))
    m = await asyncio.to_thread(
        sync.upsert_material, content_id="m", filename="m", title="m", source_kind="file"
    )
    assert m.version == 1
    w = await asyncio.to_thread(sync.create_workspace, "w", ["m"])
    assert w.active_material_id == "m"
    with pytest.raises(ReadingError):
        await asyncio.to_thread(
            sync.create_workspace, "invalid", ["m", "unknown"], workspace_id="rollback"
        )
    assert await asyncio.to_thread(sync.get_workspace, "rollback") is None
