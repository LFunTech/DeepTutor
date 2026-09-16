"""Task 1.3 审查回归：公开延迟 API、同步 task 归属和最后 guard 取消。"""

import asyncio

import pytest

from tests.persistence.postgres.test_connection import core, count, scope


@pytest.mark.parametrize("kind", ["sync", "async"])
@pytest.mark.parametrize("api", ["stream", "copy", "results", "notifies", "pipeline"])
@pytest.mark.asyncio
async def test_unsupported_delayed_api_fails_closed_before_handle_escapes(
    restricted_dsn, kind, api
):
    cls = core().SyncDatabase if kind == "sync" else core().Database

    def invoke(c):
        target = c if api in ("notifies", "pipeline") else c.cursor()
        arguments = {
            "stream": ("SELECT current_setting('app.user_id') AS owner",),
            "copy": ("COPY (SELECT current_setting('app.user_id')) TO STDOUT",),
            "results": (),
            "notifies": (),
            "pipeline": (),
        }[api]
        with pytest.raises(RuntimeError, match="unsupported"):
            getattr(target, api)(*arguments)

    async with cls(restricted_dsn, resource="delayed-api", max_size=1) as db:
        if kind == "sync":
            with db.transaction(scope()) as c:
                invoke(c)
            with db.transaction(scope("bob")) as c:
                assert (
                    c.execute("SELECT current_setting('app.user_id') AS owner").fetchone()["owner"]
                    == "bob"
                )
        else:
            async with db.transaction(scope()) as c:
                invoke(c)
            async with db.transaction(scope("bob")) as c:
                assert (
                    await (
                        await c.execute("SELECT current_setting('app.user_id') AS owner")
                    ).fetchone()
                )["owner"] == "bob"


@pytest.mark.parametrize("kind", ["sync", "async"])
@pytest.mark.asyncio
async def test_connection_context_lifecycle_is_not_public_scoped_api(restricted_dsn, kind):
    cls = core().SyncDatabase if kind == "sync" else core().Database
    async with cls(restricted_dsn, resource="context-owner") as db:
        if kind == "sync":
            with db.transaction(scope()) as c:
                with pytest.raises(RuntimeError, match="lifecycle"):
                    c.__enter__()
                with c.cursor() as cursor:
                    assert cursor.execute("SELECT 42 AS value").fetchone()["value"] == 42
        else:
            async with db.transaction(scope()) as c:
                with pytest.raises(RuntimeError, match="lifecycle"):
                    await c.__aenter__()
                async with c.cursor() as cursor:
                    assert (await (await cursor.execute("SELECT 42 AS value")).fetchone())[
                        "value"
                    ] == 42


@pytest.mark.asyncio
async def test_sync_connection_and_cursor_reject_other_async_task(restricted_dsn):
    async with core().SyncDatabase(restricted_dsn, resource="sync-task-owner") as db:
        with db.transaction(scope()) as c:
            cursor = c.execute("SELECT current_setting('app.user_id') AS owner")

            async def child(use):
                return use()

            for use in (lambda: c.execute("SELECT 1"), cursor.fetchone):
                with pytest.raises(RuntimeError, match="owner"):
                    await asyncio.create_task(child(use))
            assert cursor.fetchone()["owner"] == "alice"


@pytest.mark.asyncio
async def test_precommit_guard_cannot_swallow_cancellation_and_commit(restricted_dsn, pg_dsn):
    entered = asyncio.Event()
    calls = 0

    async def guard():
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                pass

    async with core().Database(restricted_dsn, resource="cancel-guard") as db:
        db.execution_guard = guard

        async def operation():
            s = scope()
            async with db.transaction(s) as c:
                await c.execute(
                    "INSERT INTO core_test.items VALUES (%s,%s,'must-rollback')",
                    (s.tenant_id, s.user_id),
                )

        task = asyncio.create_task(operation())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert calls == 2
    assert count(pg_dsn) == 0


@pytest.mark.parametrize("kind", ["sync", "async"])
@pytest.mark.asyncio
async def test_connection_info_does_not_expose_unscoped_lowlevel_connection(restricted_dsn, kind):
    cls = core().SyncDatabase if kind == "sync" else core().Database

    def verify(c):
        info = c.info
        assert info.backend_pid > 0
        with pytest.raises(RuntimeError, match="unsupported"):
            info.pgconn

    async with cls(restricted_dsn, resource="metadata-owner") as db:
        if kind == "sync":
            with db.transaction(scope()) as c:
                verify(c)
        else:
            async with db.transaction(scope()) as c:
                verify(c)
