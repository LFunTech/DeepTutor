"""真实 PG 已提交只读订阅的取消分类；不改变共享连接异常契约。"""

import asyncio
from contextlib import asynccontextmanager
import contextvars
import inspect
from types import SimpleNamespace

from deeptutor_enterprise.api.application import SocketAuthentication
from psycopg.pq import TransactionStatus
from psycopg_pool import AsyncConnectionPool
import pytest
from test_application import app as app
from test_flows import Socket

from deeptutor.persistence.postgres.connection import CommitCompletedAfterCancellation
from deeptutor.persistence.postgres.session import PostgresSessionStore
from deeptutor.services.session import get_session_store


@pytest.fixture
async def journal(app):
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="ws-lifecycle")
    async with enterprise.sdk(token):
        store = get_session_store()
        session = await store.create_session("合成订阅")
        turn = await store.begin_turn(session["id"])
        # waiting_input 保持真实 active session，订阅仅读持久化 content。
        await store.transition_turn(turn["id"], "waiting_input")
        await store.append_events(
            turn["id"],
            [
                {"type": "content", "content": "合成内容"},
            ],
        )
    return SimpleNamespace(app=app, token=token, turn=turn["id"], session=session["id"])


@asynccontextmanager
async def paused_committed_read(monkeypatch, turn_id, *, send_auth=False):
    """只调度真实 putconn 的时间：已提交后取消，绝不伪造 CCAC。"""
    marker = contextvars.ContextVar("committed_subscription_read", default=False)
    state = SimpleNamespace(ready=asyncio.Event(), release=asyncio.Event(), task=None, error=None)
    original_get = PostgresSessionStore.get_turn
    original_put = AsyncConnectionPool.putconn
    original_revalidate = SocketAuthentication.revalidate

    async def get_turn(self, value):
        caller = inspect.currentframe().f_back
        selected = (
            value == turn_id
            and state.task is None
            and caller.f_code.co_name == "subscribe_turn"
            and caller.f_code.co_filename.endswith("/turns/lifecycle.py")
        )
        if not selected:
            return await original_get(self, value)
        state.task = asyncio.current_task()
        token = marker.set(True)
        try:
            return await original_get(self, value)
        except BaseException as exc:
            state.error = exc
            raise
        finally:
            marker.reset(token)

    async def revalidate(self, ws):
        caller = inspect.currentframe().f_back
        selected = (
            state.task is None
            and caller.f_code.co_name == "safe_send"
            and caller.f_locals["data"].get("type") == "content"
        )
        if not selected:
            return await original_revalidate(self, ws)
        state.task = asyncio.current_task()
        token = marker.set(True)
        try:
            return await original_revalidate(self, ws)
        except BaseException as exc:
            state.error = exc
            raise
        finally:
            marker.reset(token)

    async def putconn(self, connection):
        if marker.get():
            assert connection.info.transaction_status == TransactionStatus.IDLE
            state.ready.set()
            await state.release.wait()
        return await original_put(self, connection)

    with monkeypatch.context() as patch:
        if send_auth:
            patch.setattr(SocketAuthentication, "revalidate", revalidate)
        else:
            patch.setattr(PostgresSessionStore, "get_turn", get_turn)
        patch.setattr(AsyncConnectionPool, "putconn", putconn)
        try:
            yield state
        finally:
            # 任意断言失败也释放归还，不把测试失败变成池关闭死锁。
            state.release.set()
            if state.task is not None:
                await asyncio.wait_for(asyncio.gather(state.task, return_exceptions=True), 10)


def subscription(journal, kind, after_seq=0):
    return {
        "type": f"subscribe_{kind}",
        f"{kind}_id": getattr(journal, kind),
        "after_seq": after_seq,
    }


@pytest.mark.parametrize("kind", ["turn", "session"])
async def test_replacing_committed_read_retires_only_the_old_pump(journal, monkeypatch, kind):
    async with Socket(journal.app, journal.token) as ws:
        async with paused_committed_read(monkeypatch, journal.turn) as read:
            await ws.send(subscription(journal, kind))
            first = await ws.until("content")
            assert [item["type"] for item in first] == ["content"]
            await asyncio.wait_for(read.ready.wait(), 10)
            await ws.send(subscription(journal, kind))
            async with asyncio.timeout(10):
                while not read.task.cancelling():
                    await asyncio.sleep(0)
            read.release.set()
            replay = await ws.until("content")
            assert len(replay) == 1 and replay[0]["seq"] == first[-1]["seq"]
            assert isinstance(read.error, CommitCompletedAfterCancellation)
            # 同 key 的下一代订阅不能继承退休状态；重复重放不丢持久化事件。
            await ws.send(subscription(journal, kind))
            assert (await ws.until("content"))[-1]["seq"] == first[-1]["seq"]
            await ws.send({"type": "ping"})
            assert (await ws.receive())["type"] == "pong"


@pytest.mark.parametrize("kind", ["turn", "session"])
async def test_nonretired_commit_cancellation_still_reports_failure(journal, monkeypatch, kind):
    async with Socket(journal.app, journal.token) as ws:
        async with paused_committed_read(monkeypatch, journal.turn) as read:
            await ws.send(subscription(journal, kind))
            await ws.until("content")
            await asyncio.wait_for(read.ready.wait(), 10)
            # 不是 WS stop_subscription 退休：即使正在取消，也不隐藏已提交异常。
            read.task.cancel()
            read.release.set()
            error = await ws.receive()
            assert error["type"] == "protocol_error"
            assert error["error_code"] == "subscription_failed"
            assert isinstance(read.error, CommitCompletedAfterCancellation)


@pytest.mark.parametrize("kind", ["turn", "session"])
async def test_real_pg_read_failure_is_not_hidden(journal, monkeypatch, kind):
    original_get = PostgresSessionStore.get_turn

    async def broken_read(self, value):
        caller = inspect.currentframe().f_back
        if value == journal.turn and caller.f_code.co_filename.endswith("/turns/lifecycle.py"):
            async with self.db.transaction(self.scope) as connection:
                await connection.execute("SELECT 1/0")
        return await original_get(self, value)

    monkeypatch.setattr(PostgresSessionStore, "get_turn", broken_read)
    async with Socket(journal.app, journal.token) as ws:
        await ws.send(subscription(journal, kind))
        await ws.until("content")
        error = await ws.receive()
        assert error["type"] == "protocol_error"
        assert error["error_code"] == "subscription_failed"
        assert error["message"] == "Service unavailable"


@pytest.mark.parametrize("kind", ["turn", "session"])
async def test_retired_send_revalidation_does_not_close_the_replacement(journal, monkeypatch, kind):
    async with Socket(journal.app, journal.token) as ws:
        async with paused_committed_read(monkeypatch, journal.turn, send_auth=True) as read:
            await ws.send(subscription(journal, kind))
            await asyncio.wait_for(read.ready.wait(), 10)
            # 第一个 content 尚在 safe_send 的真实身份复验归还阶段。
            await ws.send(subscription(journal, kind))
            async with asyncio.timeout(10):
                while not read.task.cancelling():
                    await asyncio.sleep(0)
            read.release.set()
            replay = await asyncio.wait_for(ws.receive(), 2)
            assert replay["type"] == "content" and replay["seq"] == 1
            assert isinstance(read.error, CommitCompletedAfterCancellation)
            await ws.send({"type": "ping"})
            assert (await ws.receive())["type"] == "pong"


@pytest.mark.parametrize("kind", ["turn", "session"])
async def test_nonretired_send_revalidation_cancel_remains_fail_closed(journal, monkeypatch, kind):
    async with Socket(journal.app, journal.token) as ws:
        async with paused_committed_read(monkeypatch, journal.turn, send_auth=True) as read:
            await ws.send(subscription(journal, kind))
            await asyncio.wait_for(read.ready.wait(), 10)
            read.task.cancel()
            read.release.set()
            await asyncio.wait_for(asyncio.gather(read.task, return_exceptions=True), 10)
            assert isinstance(read.error, CommitCompletedAfterCancellation)
            await ws.send({"type": "ping"})
            await asyncio.wait_for(ws.task, 10)
            assert ws.outgoing.empty()
