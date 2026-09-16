"""R118-01：组合单位必须在执行前封闭 SQL 生命周期通道。"""

import importlib.util

import pytest

from deeptutor.reading.models import ReadingError
from tests.persistence.postgres.business.test_reading_catalog import factory

pytestmark = pytest.mark.asyncio


def statements():
    assert (
        importlib.util.find_spec("deeptutor.persistence.postgres.session_statements") is not None
    ), "缺少封闭 SessionStatement 合同"
    from deeptutor.persistence.postgres.session_statements import SessionStatement

    return SessionStatement


async def test_original_commit_probe_cannot_persist_before_callback_failure(
    business_sync_database, business_actors, pg_scope_factory
):
    store = factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])

    def operation(unit):
        unit.upsert_material(
            content_id="probe", filename="probe", title="probe", source_kind="file"
        )
        unit.compose(lambda _, execution: execution.execute("COMMIT"))
        raise ValueError("callback failed after SQL COMMIT")

    # 修复可以在非法 execute 时先拒绝，不要求运行到 callback 的故意异常。
    with pytest.raises((ValueError, ReadingError)):
        await store.run(operation)
    persisted = await store.run(lambda u: u.get_material("probe"))
    print("POST_FAILURE_MATERIAL_PERSISTED=", persisted is not None)
    assert persisted is None, "callback failure must roll back all earlier reading writes"


async def test_approved_session_operations_share_one_atomic_unit(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    S = statements()
    actor = business_actors.tenants[0].owners[0]
    store = factory(business_sync_database, pg_scope_factory, actor)
    title = "ordinary COMMIT; /* END */ ROLLBACK -- BEGIN set_config('app.user_id','other',true)"

    def write(u):
        u.upsert_material(content_id="m", filename="m", title="m", source_kind="file")

        def compose(unit, e):
            row = e.execute(S.CREATE_ROW, ("s", title)).fetchone()
            assert row["owner_id"] == actor.user_id and row["title"] == title
            assert e.execute(S.LOCK_ROW, ("s",)).fetchone()["id"] == "s"
            unit.create_workspace("w", ["m"], workspace_id="w")
            unit.attach_session("w", "s")
            return e.execute(S.GET_ROW, ("s",)).fetchone()["title"]

        return u.compose(compose)

    assert await store.run(write) == title
    assert (await pg_session_store_factory(actor).get_session("s"))["title"] == title
    assert (await store.run(lambda u: u.list_sessions("w")))[0].session_id == "s"

    def rollback(u):
        u.upsert_material(content_id="discarded", filename="d", title="d", source_kind="file")
        u.compose(lambda _, e: e.execute(S.CREATE_ROW, ("discarded-session", "text")))
        raise ValueError("rollback complete callback")

    with pytest.raises(ValueError, match="complete callback"):
        await store.run(rollback)
    assert await store.run(lambda u: u.get_material("discarded")) is None
    assert await pg_session_store_factory(actor).get_session("discarded-session") is None


FORBIDDEN_SQL = (
    "COMMIT",
    " eNd ;",
    "CoMmIt WoRk",
    "COMMIT AND CHAIN",
    "-- header\nCOMMIT",
    "/* nested /* x */ comments */ END",
    "ROLLBACK",
    "ABORT WORK",
    "ROLLBACK AND CHAIN",
    "ROLLBACK TO SAVEPOINT x",
    "BEGIN",
    "START TRANSACTION",
    "SAVEPOINT x",
    "RELEASE SAVEPOINT x",
    "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE",
    "SET LOCAL app.user_id='other'",
    "SET app.tenant_id='other'",
    "SELECT set_config('app.user_id','other',true)",
    "SELECT pg_catalog.set_config('app.tenant_id','other',false)",
    "WITH x AS (SELECT set_config('app.user_id','other',true)) SELECT * FROM x",
    "SET ROLE postgres",
    "RESET ROLE",
    "RESET ALL",
    "SET SESSION AUTHORIZATION postgres",
    "DISCARD ALL",
    "DO $$ BEGIN PERFORM set_config('app.user_id','other',true); END $$",
    "SELECT 1; COMMIT",
    "SELECT 1; /* comment */ eNd",
    "SELECT ';COMMIT' AS harmless; ROLLBACK",
    "/* x */ SELECT 1;\n-- y\nSTART TRANSACTION",
    "SELECT 1; SELECT 2",
    "SELECT 1",
)


async def test_all_sql_text_aliases_and_batches_rejected_and_swallowed_rejection_poisons(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    S = statements()
    actor = business_actors.tenants[0].owners[0]
    store = factory(business_sync_database, pg_scope_factory, actor)
    for index, sql in enumerate(FORBIDDEN_SQL):
        mid = f"m{index}"
        sid = f"s{index}"

        def operation(u):
            u.upsert_material(content_id=mid, filename="m", title="m", source_kind="file")

            def compose(unit, e):
                e.execute(S.CREATE_ROW, (sid, "safe"))
                try:
                    e.execute(sql)
                except ReadingError:
                    pass

            u.compose(compose)
            return "caught refusal must not allow commit"

        with pytest.raises(ReadingError, match="poisoned"):
            await store.run(operation)
        assert await store.run(lambda u: u.get_material(mid)) is None, sql
        assert await pg_session_store_factory(actor).get_session(sid) is None, sql


async def test_only_exact_tokens_and_string_values_no_scope_or_adaptation_escape(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    from enum import Enum

    from psycopg import sql

    S = statements()
    actor, other = business_actors.tenants[0].owners
    store = factory(business_sync_database, pg_scope_factory, actor)
    await pg_session_store_factory(other).create_session(session_id="other-owner")
    assert (
        await store.run(
            lambda u: u.compose(lambda _, e: e.execute(S.GET_ROW, ("other-owner",)).fetchone())
        )
        is None
    )

    class Fake(Enum):
        CREATE_ROW = 1

    class PretendStatement:
        sql = "COMMIT"

    class Adaptable:
        def __str__(self):
            return "COMMIT"

    invalid = [
        ("CREATE_ROW", ("s", "t")),
        (S.CREATE_ROW.value, ("s", "t")),
        (Fake.CREATE_ROW, ("s", "t")),
        (PretendStatement(), ()),
        (sql.SQL("COMMIT"), ()),
        (sql.SQL("SELECT 1;") + sql.SQL("COMMIT"), ()),
        ([S.GET_ROW, S.GET_ROW], ("s",)),
        (S.CREATE_ROW, {"id": "s", "title": "t"}),
        (S.CREATE_ROW, ("s", "t", other.user_id)),
        (S.GET_ROW, (other.tenant_id, other.user_id, "other-owner")),
        (S.CREATE_ROW, ("s", Adaptable())),
        (S.CREATE_ROW, ("s", sql.SQL("COMMIT"))),
        (S.GET_ROW, ()),
        (S.GET_ROW, (None,)),
    ]
    for statement, params in invalid:

        def fail(u):
            u.upsert_material(content_id="discarded", filename="x", title="x", source_kind="file")
            try:
                u.compose(lambda _, e: e.execute(statement, params))
            except ReadingError:
                pass

        with pytest.raises(ReadingError, match="poisoned"):
            await store.run(fail)
        assert await store.run(lambda u: u.get_material("discarded")) is None
    assert (await pg_session_store_factory(other).get_session("other-owner"))[
        "session_id"
    ] == "other-owner"


async def test_statement_and_result_handles_expire_and_reject_cross_thread(
    business_sync_database, business_actors, pg_scope_factory
):
    import threading

    S = statements()
    store = factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    handles = []
    errors = []

    def operation(u):
        def compose(_, e):
            result = e.execute(S.GET_ROW, ("missing",))
            handles.extend([e, result])

            def other():
                for action in (lambda: e.execute(S.GET_ROW, ("missing",)), result.fetchone):
                    try:
                        action()
                    except RuntimeError as exc:
                        errors.append(str(exc))

            t = threading.Thread(target=other)
            t.start()
            t.join()

        u.compose(compose)

    await store.run(operation)
    assert len(errors) == 2 and all("owner" in e for e in errors)
    for action in [
        lambda: handles[0].execute(S.GET_ROW, ("missing",)),
        handles[1].fetchone,
        handles[1].fetchall,
        lambda: handles[1].rowcount,
    ]:
        with pytest.raises(RuntimeError, match="inactive"):
            action()


async def test_rejected_commit_keeps_owner_lock_until_poisoned_unit_rolls_back(
    business_sync_database, business_database, business_actors, pg_scope_factory
):
    import asyncio
    import threading

    actor = business_actors.tenants[0].owners[0]
    scope = pg_scope_factory(actor)
    store = factory(business_sync_database, pg_scope_factory, actor)
    entered = threading.Event()
    started = threading.Event()
    release = threading.Event()
    pids = []

    def rejected(u):
        u.upsert_material(content_id="discarded", filename="d", title="d", source_kind="file")
        pids.append(u._connection.info.backend_pid)
        try:
            u.compose(lambda _, e: e.execute("/* cannot release owner lock */ COMMIT"))
        except ReadingError:
            pass
        entered.set()
        assert release.wait(5)

    def writer(u):
        pids.append(u._connection.info.backend_pid)
        started.set()
        return u.upsert_material(content_id="later", filename="l", title="l", source_kind="file")

    first = asyncio.create_task(store.run(rejected))
    second = None
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        second = asyncio.create_task(store.run(writer))
        assert await asyncio.to_thread(started.wait, 5)
        async with business_database.transaction(scope) as c:
            async with asyncio.timeout(5):
                while not (
                    await (
                        await c.execute(
                            "SELECT %s=ANY(pg_blocking_pids(%s)) AS blocked", (pids[0], pids[1])
                        )
                    ).fetchone()
                )["blocked"]:
                    await asyncio.sleep(0.005)
        assert not second.done()
    finally:
        release.set()
        with pytest.raises(ReadingError, match="poisoned"):
            await first
        if second is not None:
            await second
    assert await store.run(lambda u: u.get_material("discarded")) is None
    assert await store.run(lambda u: u.get_material("later")) is not None


async def test_cancel_and_close_preserve_composed_material_and_session_atomicity(
    migrated_pg, business_actors, pg_scope_factory, pg_session_store_factory
):
    import asyncio
    import threading

    from psycopg_pool import PoolClosed

    from deeptutor.persistence.postgres.connection import SyncDatabase
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore

    S = statements()
    actor = business_actors.tenants[0].owners[0]
    scope = pg_scope_factory(actor)
    chat = pg_session_store_factory(actor)
    db = SyncDatabase(migrated_pg.runtime_dsn, resource="reading-composition-close", max_size=1)
    await db.__aenter__()
    store = AsyncReadingCatalogStore(db, scope)
    release = threading.Event()
    entered = threading.Event()

    def write(u, sid):
        u.upsert_material(content_id=sid, filename="m", title="m", source_kind="file")
        u.compose(lambda _, e: e.execute(S.CREATE_ROW, (sid, "COMMIT is only data")))
        entered.set()
        assert release.wait(5)

    try:
        task = asyncio.create_task(store.run(lambda u: write(u, "cancelled")))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await store.run(lambda u: u.get_material("cancelled")) is None
        assert await chat.get_session("cancelled") is None
        entered.clear()
        release.clear()
        task = asyncio.create_task(store.run(lambda u: write(u, "committed")))
        assert await asyncio.to_thread(entered.wait, 5)
        close = asyncio.create_task(db.__aexit__(None, None, None))
        await asyncio.sleep(0.02)
        assert not close.done()
        with pytest.raises(PoolClosed):
            await store.run(lambda u: u.get_material("committed"))
        release.set()
        await task
        await close
    finally:
        release.set()
        if not db.pool.closed:
            await db.__aexit__(None, None, None)
    async with SyncDatabase(
        migrated_pg.runtime_dsn, resource="reading-composition-reopen"
    ) as reopened:
        assert (
            await AsyncReadingCatalogStore(reopened, scope).run(
                lambda u: u.get_material("committed")
            )
            is not None
        )
    assert (await chat.get_session("committed"))["title"] == "COMMIT is only data"
