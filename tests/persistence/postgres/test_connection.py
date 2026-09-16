"""真实 PG 验证事务归属、回滚、受限角色和有界生命周期。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import importlib
import threading
import time
import uuid

import psycopg
from psycopg import sql
from psycopg_pool import PoolClosed, PoolTimeout, TooManyRequests
import pytest


def core():
    try:
        return importlib.import_module("deeptutor.persistence.postgres.connection")
    except ModuleNotFoundError as exc:
        pytest.fail(f"core PostgreSQL connection implementation missing: {exc}")


def scope(owner="alice", tenant=None):
    core()
    return importlib.import_module("deeptutor.persistence.postgres.scope").TenantScope(
        tenant or "00000000-0000-0000-0000-000000000001", owner
    )


def insert(c, s, value="one"):
    c.execute("INSERT INTO core_test.items VALUES (%s,%s,%s)", (s.tenant_id, s.user_id, value))


def count(dsn):
    with psycopg.connect(dsn) as c:
        return c.execute("SELECT count(*) FROM core_test.items").fetchone()[0]


def test_sync_scope_reuse_rls_rollback_and_scope_validation(restricted_dsn, pg_dsn):
    a, b = scope(), scope("bob")
    with core().SyncDatabase(restricted_dsn, resource="core", max_size=1) as db:
        with db.transaction(a) as c:
            pid = c.info.backend_pid
            insert(c, a)
        with db.transaction(b) as c:
            assert c.info.backend_pid == pid
            assert c.execute("SELECT * FROM core_test.items").fetchall() == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction(b) as c:
                insert(c, a)
        with pytest.raises(RuntimeError, match="rollback"):
            with db.transaction(a) as c:
                insert(c, a, "rolled-back")
                raise RuntimeError("rollback")
        with pytest.raises(ValueError, match="scope"):
            with db.transaction(None):
                pass
        with db.pool.connection() as c:
            assert (
                c.execute(
                    "SELECT nullif(current_setting('app.user_id',true),'') AS owner"
                ).fetchone()["owner"]
                is None
            )
    assert count(pg_dsn) == 1
    with pytest.raises(PoolClosed):
        with db.transaction(a):
            pass


@pytest.mark.asyncio
async def test_async_scope_reuse_exception_and_cancel_rollback(restricted_dsn, pg_dsn):
    a, b = scope(), scope("bob")
    async with core().Database(restricted_dsn, resource="core", max_size=1) as db:
        async with db.transaction(a) as c:
            pid = c.info.backend_pid
            await c.execute(
                "INSERT INTO core_test.items VALUES (%s,%s,'one')", (a.tenant_id, a.user_id)
            )
        async with db.transaction(b) as c:
            assert c.info.backend_pid == pid
            assert await (await c.execute("SELECT * FROM core_test.items")).fetchall() == []
        entered = asyncio.Event()

        async def write_then_wait():
            async with db.transaction(a) as c:
                await c.execute(
                    "INSERT INTO core_test.items VALUES (%s,%s,'cancelled')",
                    (a.tenant_id, a.user_id),
                )
                entered.set()
                await c.execute("SELECT pg_sleep(5)")

        task = asyncio.create_task(write_then_wait())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with db.transaction(b) as c:
            assert await (await c.execute("SELECT * FROM core_test.items")).fetchall() == []
    assert count(pg_dsn) == 1


@pytest.mark.parametrize("kind", ["sync", "async"])
@pytest.mark.asyncio
async def test_guard_before_work_and_before_commit(restricted_dsn, pg_dsn, kind):
    s = scope()
    checks = []

    def guard():
        checks.append(1)
        if len(checks) == 2:
            raise PermissionError("execution lost")

    if kind == "sync":
        with core().SyncDatabase(restricted_dsn, resource="guard") as db:
            db.execution_guard = guard
            with pytest.raises(PermissionError):
                with db.transaction(s) as c:
                    insert(c, s)
    else:

        async def async_guard():
            guard()

        async with core().Database(restricted_dsn, resource="guard") as db:
            db.execution_guard = async_guard
            with pytest.raises(PermissionError):
                async with db.transaction(s) as c:
                    await c.execute(
                        "INSERT INTO core_test.items VALUES (%s,%s,'guard')",
                        (s.tenant_id, s.user_id),
                    )
    assert len(checks) == 2
    assert count(pg_dsn) == 0


@pytest.mark.parametrize("kind", ["sync", "async"])
@pytest.mark.asyncio
async def test_statement_timeout_rolls_back_write(restricted_dsn, pg_dsn, kind):
    s = scope()
    kwargs = dict(resource="timeout", statement_timeout_ms=60, transaction_timeout_ms=1000)
    if kind == "sync":
        with core().SyncDatabase(restricted_dsn, **kwargs) as db:
            with pytest.raises(psycopg.errors.QueryCanceled):
                with db.transaction(s) as c:
                    insert(c, s)
                    c.execute("SELECT pg_sleep(1)")
            with db.transaction(s) as c:
                assert c.execute("SELECT 42 AS answer").fetchone()["answer"] == 42
    else:
        async with core().Database(restricted_dsn, **kwargs) as db:
            with pytest.raises(psycopg.errors.QueryCanceled):
                async with db.transaction(s) as c:
                    await c.execute(
                        "INSERT INTO core_test.items VALUES (%s,%s,'timeout')",
                        (s.tenant_id, s.user_id),
                    )
                    await c.execute("SELECT pg_sleep(1)")
            async with db.transaction(s) as c:
                assert (await (await c.execute("SELECT 42 AS answer")).fetchone())["answer"] == 42
    assert count(pg_dsn) == 0


@pytest.mark.parametrize("kind", ["sync", "async"])
@pytest.mark.asyncio
async def test_total_transaction_timeout_not_just_one_statement(restricted_dsn, pg_dsn, kind):
    s = scope()
    kwargs = dict(resource="timeout", statement_timeout_ms=1000, transaction_timeout_ms=100)
    if kind == "sync":
        with core().SyncDatabase(restricted_dsn, **kwargs) as db:
            with pytest.raises(psycopg.errors.TransactionTimeout):
                with db.transaction(s) as c:
                    insert(c, s)
                    time.sleep(0.15)
                    c.execute("SELECT 1")
    else:
        async with core().Database(restricted_dsn, **kwargs) as db:
            with pytest.raises(psycopg.errors.TransactionTimeout):
                async with db.transaction(s) as c:
                    await c.execute(
                        "INSERT INTO core_test.items VALUES (%s,%s,'timeout')",
                        (s.tenant_id, s.user_id),
                    )
                    await asyncio.sleep(0.15)
                    await c.execute("SELECT 1")
    assert count(pg_dsn) == 0


@pytest.mark.asyncio
async def test_worker_threads_explicit_scope_and_bounded_execution(restricted_dsn, pg_dsn):
    ambient = ContextVar("untrusted_scope", default="clean")
    ambient.set("stale-user")
    rendezvous = threading.Barrier(2)
    owners = []

    def operation(c, expected):
        before = threading.get_ident()
        row = c.execute("SELECT current_setting('app.user_id') AS owner").fetchone()
        owners.append((before, c.info.backend_pid, row["owner"], ambient.get()))
        rendezvous.wait(timeout=3)
        insert(c, expected)
        assert threading.get_ident() == before
        return row["owner"]

    async with core().SyncDatabase(
        restricted_dsn, resource="workers", max_size=2, max_waiting=1
    ) as db:
        a, b = scope(), scope("bob")
        results = await asyncio.gather(
            db.run(a, lambda c: operation(c, a)), db.run(b, lambda c: operation(c, b))
        )
    assert results == ["alice", "bob"]
    assert len({owner[0] for owner in owners}) == 2
    assert len({owner[1] for owner in owners}) == 2
    assert {owner[2] for owner in owners} == {"alice", "bob"}
    assert {owner[3] for owner in owners} == {"clean"}
    assert count(pg_dsn) == 2


@pytest.mark.asyncio
async def test_worker_cancel_keeps_capacity_and_rolls_back_even_if_repeated(restricted_dsn, pg_dsn):
    entered, release = threading.Event(), threading.Event()
    s = scope()

    def operation(c):
        insert(c, s)
        entered.set()
        assert release.wait(timeout=5)

    async with core().SyncDatabase(
        restricted_dsn, resource="cancel", max_size=1, max_waiting=1
    ) as db:
        task = asyncio.create_task(db.run(s, operation))
        while not entered.is_set():
            await asyncio.sleep(0.005)
        task.cancel()
        await asyncio.sleep(0.03)
        task.cancel()
        queued = asyncio.create_task(
            db.run(
                scope("bob"),
                lambda c: c.execute("SELECT current_setting('app.user_id') AS owner").fetchone(),
            )
        )
        await asyncio.sleep(0.03)
        with pytest.raises(TooManyRequests):
            await db.run(s, lambda c: None)
        assert not task.done() and not queued.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await queued)["owner"] == "bob"
    assert count(pg_dsn) == 0


@pytest.mark.asyncio
async def test_cancel_queued_worker_does_not_execute(restricted_dsn, pg_dsn):
    entered, release = threading.Event(), threading.Event()
    s = scope()

    def operation(c):
        entered.set()
        assert release.wait(timeout=5)

    async with core().SyncDatabase(
        restricted_dsn, resource="queue", max_size=1, max_waiting=1
    ) as db:
        running = asyncio.create_task(db.run(s, operation))
        while not entered.is_set():
            await asyncio.sleep(0.005)
        queued = asyncio.create_task(db.run(s, lambda c: insert(c, s)))
        await asyncio.sleep(0.03)
        queued.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await queued
        await running
    assert count(pg_dsn) == 0


@pytest.mark.asyncio
async def test_async_pool_queue_limit_wait_timeout_and_cancel(restricted_dsn):
    s = scope()
    async with core().Database(
        restricted_dsn, resource="queue", max_size=1, max_waiting=1, timeout=0.12
    ) as db:
        async with db.transaction(s):

            async def wait_for_connection():
                async with db.transaction(s):
                    pass

            waiter = asyncio.create_task(wait_for_connection())
            await asyncio.sleep(0.02)
            with pytest.raises(TooManyRequests):
                await wait_for_connection()
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
        async with db.transaction(s):
            with pytest.raises(PoolTimeout):
                await wait_for_connection()
        async with db.transaction(scope("bob")) as c:
            assert (
                await (await c.execute("SELECT current_setting('app.user_id') AS owner")).fetchone()
            )["owner"] == "bob"


@pytest.mark.asyncio
async def test_async_close_drains_sync_workers_and_closes_pool(restricted_dsn, pg_dsn):
    s = scope()
    entered, release = threading.Event(), threading.Event()

    def operation(c):
        insert(c, s)
        entered.set()
        assert release.wait(timeout=5)

    db = core().SyncDatabase(restricted_dsn, resource="close", max_size=1)
    await db.__aenter__()
    task = asyncio.create_task(db.run(s, operation))
    while not entered.is_set():
        await asyncio.sleep(0.005)
    close = asyncio.create_task(db.__aexit__(None, None, None))
    await asyncio.sleep(0.03)
    assert not close.done()
    with pytest.raises(PoolClosed):
        await db.run(s, lambda c: None)
    release.set()
    await task
    await close
    assert db.pool.closed
    assert count(pg_dsn) == 1


@pytest.mark.parametrize("kind", ["sync", "async"])
@pytest.mark.parametrize(
    "privilege",
    [
        "SUPERUSER",
        "BYPASSRLS",
        "CREATEDB",
        "CREATEROLE",
        "table_owner",
        "schema_owner",
        "database_owner",
    ],
)
@pytest.mark.asyncio
async def test_recursive_privileged_roles_rejected_and_failed_pool_closed(pg_dsn, kind, privilege):
    suffix = uuid.uuid4().hex
    login, middle, target = [prefix + suffix for prefix in ("login_", "middle_", "target_")]
    with psycopg.connect(pg_dsn) as c:
        for name in (login, middle, target):
            c.execute(sql.SQL("CREATE ROLE {} LOGIN NOINHERIT").format(sql.Identifier(name)))
        if privilege.endswith("_owner"):
            c.execute("CREATE SCHEMA pgapp")
            c.execute("CREATE TABLE pgapp.items (id int)")
            if privilege == "database_owner":
                dbname = c.info.dbname
                c.execute(
                    sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                        sql.Identifier(dbname), sql.Identifier(target)
                    )
                )
            else:
                obj = "TABLE pgapp.items" if privilege == "table_owner" else "SCHEMA pgapp"
                c.execute(
                    sql.SQL("ALTER {} OWNER TO {}").format(sql.SQL(obj), sql.Identifier(target))
                )
        else:
            c.execute(
                sql.SQL("ALTER ROLE {} {}").format(sql.Identifier(target), sql.SQL(privilege))
            )
        c.execute(
            sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
                sql.Identifier(middle), sql.Identifier(login)
            )
        )
        c.execute(
            sql.SQL("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE").format(
                sql.Identifier(target), sql.Identifier(middle)
            )
        )
    cls = core().SyncDatabase if kind == "sync" else core().Database
    db = cls(pg_dsn.replace("user=postgres", "user=" + login), resource="unsafe")
    with pytest.raises(RuntimeError, match="restricted"):
        if kind == "sync":
            with db:
                pass
        else:
            async with db:
                pass
    assert db.pool.closed


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_size": 0},
        {"max_waiting": 0},
        {"timeout": 0},
        {"timeout": float("inf")},
        {"statement_timeout_ms": 0},
        {"transaction_timeout_ms": 0},
        {"resource": "postgres://secret"},
    ],
)
@pytest.mark.parametrize("kind", ["Database", "SyncDatabase"])
def test_configuration_rejects_unbounded_or_invalid_values(kind, kwargs):
    with pytest.raises(ValueError):
        getattr(core(), kind)("", **({"resource": "test"} | kwargs))


def test_sync_handles_cannot_cross_threads_or_outlive_transaction(restricted_dsn):
    with core().SyncDatabase(restricted_dsn, resource="owner") as db:
        with db.transaction(scope()) as c:
            cursor = c.execute("SELECT 1")
            with ThreadPoolExecutor(max_workers=1) as executor:
                for use in (lambda: c.execute("SELECT 1"), cursor.fetchone):
                    with pytest.raises(RuntimeError, match="owner"):
                        executor.submit(use).result()
        with pytest.raises(RuntimeError, match="inactive"):
            c.execute("SELECT 1")
        with pytest.raises(RuntimeError, match="inactive"):
            cursor.fetchone()


@pytest.mark.asyncio
async def test_async_handles_cannot_cross_tasks_or_outlive_transaction(restricted_dsn):
    async with core().Database(restricted_dsn, resource="owner") as db:
        async with db.transaction(scope()) as c:
            cursor = await c.execute("SELECT 1")
            for use in (lambda: c.execute("SELECT 1"), cursor.fetchone):
                with pytest.raises(RuntimeError, match="owner"):
                    await asyncio.create_task(use())
        with pytest.raises(RuntimeError, match="inactive"):
            await c.execute("SELECT 1")
        with pytest.raises(RuntimeError, match="inactive"):
            await cursor.fetchone()


@pytest.mark.asyncio
async def test_swallowed_async_cancel_still_rolls_back(restricted_dsn, pg_dsn):
    entered = asyncio.Event()
    async with core().Database(restricted_dsn, resource="swallowed") as db:

        async def operation():
            async with db.transaction(scope()) as c:
                s = scope()
                await c.execute(
                    "INSERT INTO core_test.items VALUES (%s,%s,'cancelled')",
                    (s.tenant_id, s.user_id),
                )
                entered.set()
                try:
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    pass

        task = asyncio.create_task(operation())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert count(pg_dsn) == 0


@pytest.mark.asyncio
async def test_async_close_drains_transactions_despite_repeated_cancel(restricted_dsn, pg_dsn):
    db = core().Database(restricted_dsn, resource="drain")
    await db.__aenter__()
    entered, release = asyncio.Event(), asyncio.Event()

    async def operation():
        s = scope()
        async with db.transaction(s) as c:
            await c.execute(
                "INSERT INTO core_test.items VALUES (%s,%s,'drained')", (s.tenant_id, s.user_id)
            )
            entered.set()
            await release.wait()

    task = asyncio.create_task(operation())
    await entered.wait()
    close = asyncio.create_task(db.__aexit__(None, None, None))
    await asyncio.sleep(0.01)
    close.cancel()
    await asyncio.sleep(0.01)
    close.cancel()
    assert not close.done()
    release.set()
    await task
    with pytest.raises(asyncio.CancelledError):
        await close
    assert db.pool.closed
    assert count(pg_dsn) == 1


def test_sync_pool_queue_is_bounded_and_times_out(restricted_dsn):
    with core().SyncDatabase(
        restricted_dsn, resource="sync-queue", max_size=1, max_waiting=1, timeout=0.15
    ) as db:
        with db.transaction(scope()):

            def wait():
                with db.transaction(scope()):
                    pass

            with ThreadPoolExecutor(max_workers=2) as executor:
                waiter = executor.submit(wait)
                deadline = time.monotonic() + 2
                while db.pool.get_stats().get("requests_waiting", 0) != 1:
                    assert time.monotonic() < deadline
                    time.sleep(0.005)
                with pytest.raises(TooManyRequests):
                    executor.submit(wait).result()
                with pytest.raises(PoolTimeout):
                    waiter.result()


@pytest.mark.asyncio
async def test_sync_async_startup_failure_and_exit_join_owned_threads(pg_dsn, restricted_dsn):
    before = set(threading.enumerate())
    db = core().SyncDatabase(pg_dsn, resource="unsafe")
    with pytest.raises(RuntimeError, match="restricted"):
        async with db:
            pass
    assert db.pool.closed
    assert not (set(threading.enumerate()) - before)
    async with core().SyncDatabase(restricted_dsn, resource="safe") as db:
        await db.run(scope(), lambda c: c.execute("SELECT 1"))
    assert not (set(threading.enumerate()) - before)


@pytest.mark.parametrize("kind", ["sync", "async"])
@pytest.mark.asyncio
async def test_startup_session_user_superuser_cannot_hide_behind_role(restricted_dsn, pg_dsn, kind):
    role = psycopg.conninfo.conninfo_to_dict(restricted_dsn)["user"]
    dsn = psycopg.conninfo.make_conninfo(pg_dsn, options=f"-c role={role}")
    db = (core().SyncDatabase if kind == "sync" else core().Database)(dsn, resource="session-role")
    with pytest.raises(RuntimeError, match="restricted"):
        if kind == "sync":
            with db:
                pass
        else:
            async with db:
                pass
    assert db.pool.closed


@pytest.mark.parametrize("kind", ["sync", "async"])
@pytest.mark.asyncio
async def test_inaccessible_privileged_membership_is_allowed(restricted_dsn, pg_dsn, kind):
    role = psycopg.conninfo.conninfo_to_dict(restricted_dsn)["user"]
    target = "unavailable_" + uuid.uuid4().hex
    with psycopg.connect(pg_dsn) as c:
        c.execute(sql.SQL("CREATE ROLE {} BYPASSRLS").format(sql.Identifier(target)))
        c.execute(
            sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET FALSE, ADMIN FALSE").format(
                sql.Identifier(target), sql.Identifier(role)
            )
        )
    db = (core().SyncDatabase if kind == "sync" else core().Database)(
        restricted_dsn, resource="safe-role"
    )
    if kind == "sync":
        with db:
            with db.transaction(scope()) as c:
                assert c.execute("SELECT 42 AS value").fetchone()["value"] == 42
    else:
        async with db:
            async with db.transaction(scope()) as c:
                assert (await (await c.execute("SELECT 42 AS value")).fetchone())["value"] == 42


@pytest.mark.asyncio
async def test_cancel_worker_waiting_on_pool_waits_for_cleanup(restricted_dsn, pg_dsn):
    async with core().SyncDatabase(
        restricted_dsn, resource="pool-wait", max_size=1, timeout=0.12
    ) as db:
        with db.transaction(scope()):
            task = asyncio.create_task(db.run(scope(), lambda c: insert(c, scope())))
            while db.pool.get_stats().get("requests_waiting", 0) != 1:
                await asyncio.sleep(0.005)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert count(pg_dsn) == 0


@pytest.mark.parametrize("kind", ["sync", "async"])
@pytest.mark.asyncio
async def test_cancel_after_commit_boundary_reports_confirmed_commit(restricted_dsn, pg_dsn, kind):
    # 延迟触发器只在真实 COMMIT 阶段等待；不 mock 驱动或提交状态。
    with psycopg.connect(pg_dsn, autocommit=True) as admin:
        admin.execute(
            "CREATE FUNCTION core_test.delay_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_lock(73193); PERFORM pg_advisory_unlock(73193); RETURN NEW; END $$"
        )
        admin.execute(
            "CREATE CONSTRAINT TRIGGER delayed AFTER INSERT ON core_test.items DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION core_test.delay_commit()"
        )
        admin.execute("SELECT pg_advisory_lock(73193)")
        db = (core().SyncDatabase if kind == "sync" else core().Database)(
            restricted_dsn, resource="commit"
        )
        async with db:
            s = scope()
            if kind == "sync":

                def operation(c):
                    insert(c, s)
                    return "confirmed"

                task = asyncio.create_task(db.run(s, operation))
            else:

                async def operation():
                    async with db.transaction(s) as c:
                        await c.execute(
                            "INSERT INTO core_test.items VALUES (%s,%s,'committing')",
                            (s.tenant_id, s.user_id),
                        )

                task = asyncio.create_task(operation())
            deadline = time.monotonic() + 3
            while not admin.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event='advisory')"
            ).fetchone()[0]:
                assert time.monotonic() < deadline
                await asyncio.sleep(0.005)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done()
            admin.execute("SELECT pg_advisory_unlock(73193)")
            with pytest.raises(core().CommitCompletedAfterCancellation) as error:
                await task
            assert error.value.result == ("confirmed" if kind == "sync" else None)
    assert count(pg_dsn) == 1


@pytest.mark.parametrize("invalid_operation", ["coroutine", "generator"])
@pytest.mark.asyncio
async def test_worker_rejects_lazy_operations_instead_of_committing_nothing(
    restricted_dsn, pg_dsn, invalid_operation
):
    async def asynchronous(c):
        insert(c, scope())

    def generator(c):
        yield c

    async with core().SyncDatabase(restricted_dsn, resource="sync-only") as db:
        with pytest.raises(TypeError, match="synchronous"):
            await db.run(scope(), asynchronous if invalid_operation == "coroutine" else generator)
    assert count(pg_dsn) == 0


@pytest.mark.asyncio
async def test_async_cancel_during_return_reports_commit_and_releases_capacity(
    restricted_dsn, pg_dsn
):
    async with core().Database(restricted_dsn, resource="return", max_size=1) as db:
        entered, release = asyncio.Event(), asyncio.Event()

        async def operation():
            s = scope()
            async with db.transaction(s) as c:
                await c.execute(
                    "INSERT INTO core_test.items VALUES (%s,%s,'returning')",
                    (s.tenant_id, s.user_id),
                )
                entered.set()
                await release.wait()

        task = asyncio.create_task(operation())
        await entered.wait()
        # 保持真实池锁，延迟已提交连接的归还；不替换驱动或 pool.putconn。
        async with db.pool._lock:
            release.set()
            deadline = time.monotonic() + 3
            while count(pg_dsn) != 1:
                assert time.monotonic() < deadline
                await asyncio.sleep(0.005)
            await asyncio.sleep(0.02)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done()
        with pytest.raises(core().CommitCompletedAfterCancellation):
            await task
        async with db.transaction(scope("bob")) as c:
            assert await (await c.execute("SELECT * FROM core_test.items")).fetchall() == []


@pytest.mark.asyncio
async def test_worker_reuse_does_not_inherit_previous_contextvars(restricted_dsn):
    ambient = ContextVar("legacy_thread_scope", default="empty")
    async with core().SyncDatabase(restricted_dsn, resource="context", max_size=1) as db:
        await db.run(scope(), lambda c: ambient.set("stale-alice"))
        value = await db.run(
            scope("bob"),
            lambda c: (
                ambient.get(),
                c.execute("SELECT current_setting('app.user_id') AS owner").fetchone()["owner"],
            ),
        )
        assert value == ("empty", "bob")


def test_sync_guard_cannot_silently_skip_async_authorization(restricted_dsn, pg_dsn):
    async def guard():
        raise PermissionError("execution lost")

    with core().SyncDatabase(restricted_dsn, resource="guard-type") as db:
        db.execution_guard = guard
        with pytest.raises(TypeError, match="synchronous"):
            with db.transaction(scope()) as c:
                insert(c, scope())
    assert count(pg_dsn) == 0


@pytest.mark.asyncio
async def test_cancelled_sync_pool_startup_closes_threads_and_rejects_work(restricted_dsn):
    entered, release = threading.Event(), threading.Event()
    before = set(threading.enumerate())

    class DelayedOpen(core().SyncDatabase):
        def _open(self):
            result = super()._open()
            # 真实启动/角色检查之后控制交接时序，不替代池或连接。
            entered.set()
            assert release.wait(timeout=5)
            return result

    db = DelayedOpen(restricted_dsn, resource="cancel-open", max_size=1)
    task = asyncio.create_task(db.__aenter__())
    while not entered.is_set():
        await asyncio.sleep(0.005)
    task.cancel()
    await asyncio.sleep(0.02)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert db.pool.closed
    assert not (set(threading.enumerate()) - before)
    with pytest.raises(PoolClosed):
        await db.run(scope(), lambda c: None)
