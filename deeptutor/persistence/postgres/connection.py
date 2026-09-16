"""有界 PostgreSQL 池和完整事务 worker，不从环境或 ContextVar 推断身份。

需 PostgreSQL 17+（使用 transaction_timeout）。run() 的回调只做同步数据库
工作，不得手工提交、转交连接或执行无界外部 I/O。Python 无法强杀线程：取消
等待回调退出后回滚，期间继续占用容量。提交一旦开始不能承诺撤回；取消遇到
已确认提交会抛出 CommitCompletedAfterCancellation，附带原结果，禁止盲目重试。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from contextvars import Context
import inspect
import math
import threading
from typing import TypeVar

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool, PoolClosed, TooManyRequests

from ._ownership import Lease
from .scope import TenantScope

T = TypeVar("T")

# 检查所有非系统 schema，不能在从企业包提取后保留 enterprise 专用安全边界。
_RESTRICTED_ROLE_SQL = """
WITH RECURSIVE reachable(oid) AS (
    SELECT oid FROM pg_roles WHERE rolname IN (current_user, session_user)
    UNION
    SELECT m.roleid FROM pg_auth_members m JOIN reachable a ON a.oid=m.member
    WHERE m.inherit_option OR m.set_option OR m.admin_option
)
SELECT EXISTS (
    SELECT 1 FROM reachable a JOIN pg_roles r ON r.oid=a.oid
    WHERE r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb
       OR EXISTS (
           SELECT 1 FROM pg_class cl JOIN pg_namespace n ON n.oid=cl.relnamespace
           WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
             AND cl.relowner=r.oid)
       OR EXISTS (
           SELECT 1 FROM pg_namespace n
           WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
             AND n.nspowner=r.oid)
       OR EXISTS (
           SELECT 1 FROM pg_database d
           WHERE d.datname=current_database() AND d.datdba=r.oid)
) AS unsafe
"""
_SCOPE_SQL = """
SELECT set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true),
       set_config('statement_timeout', %s, true),
       set_config('transaction_timeout', %s, true)
"""


class CommitCompletedAfterCancellation(RuntimeError):
    """取消发生在提交边界后；事务已确认提交，result 可用于幂等恢复。"""

    def __init__(self, result):
        super().__init__("PostgreSQL commit completed after cancellation; do not retry blindly")
        self.result = result


class _CancelledOperation(Exception):
    pass


class _Operation:
    def __init__(self):
        self.lock = threading.Lock()
        self.cancelled = False
        self.committing = False

    def cancel(self):
        with self.lock:
            self.cancelled = True

    def check(self):
        with self.lock:
            if self.cancelled:
                raise _CancelledOperation()

    def begin_commit(self):
        with self.lock:
            if self.cancelled:
                raise _CancelledOperation()
            self.committing = True


async def _drain(future):
    """重复取消不能跳过资源清理；返回期间是否收到过取消。"""
    cancelled = False
    while not future.done():
        try:
            await asyncio.wait((future,))
        except asyncio.CancelledError:
            cancelled = True
    return cancelled


class _Configuration:
    def __init__(
        self,
        dsn: str,
        *,
        resource: str,
        max_size: int = 8,
        max_waiting: int = 16,
        timeout: float = 10,
        statement_timeout_ms: int = 15_000,
        transaction_timeout_ms: int = 30_000,
    ):
        if not isinstance(resource, str) or not resource or "://" in resource or "=" in resource:
            raise ValueError("resource must be a non-secret deployment identifier")
        for name, value in (("max_size", max_size), ("max_waiting", max_waiting)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name, value in (
            ("statement_timeout_ms", statement_timeout_ms),
            ("transaction_timeout_ms", transaction_timeout_ms),
        ):
            if type(value) is not int or not 1 <= value <= 3_600_000:
                raise ValueError(f"{name} must be between 1 and 3600000")
        if isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ValueError("timeout must be finite and between 0 and 3600 seconds")
        self.resource = resource
        self.execution_guard = None
        self.timeout = timeout
        self._statement_timeout = str(statement_timeout_ms)
        self._transaction_timeout = str(transaction_timeout_ms)
        self._pool_options = dict(
            conninfo=dsn,
            min_size=1,
            max_size=max_size,
            max_waiting=max_waiting,
            open=False,
            kwargs={"row_factory": dict_row, "autocommit": True},
            timeout=timeout,
        )

    def _scope_values(self, scope):
        if not isinstance(scope, TenantScope):
            raise ValueError("trusted scope is required")
        return scope.tenant_id, scope.user_id, self._statement_timeout, self._transaction_timeout


class Database(_Configuration):
    """原异步 Database 接口；每次 checkout 都是独立 scoped 事务。"""

    def __init__(self, dsn: str, **kwargs):
        super().__init__(dsn, **kwargs)
        self.pool = AsyncConnectionPool(**self._pool_options)
        self._closing = True
        self._active = 0
        self._idle = asyncio.Event()
        self._idle.set()

    async def __aenter__(self):
        try:
            await self.pool.open(wait=True, timeout=self.timeout)
            async with self.pool.connection() as c:
                row = await (await c.execute(_RESTRICTED_ROLE_SQL)).fetchone()
                if not row or row["unsafe"]:
                    raise RuntimeError("application requires a restricted PostgreSQL role")
        except BaseException:
            close = asyncio.create_task(self.pool.close())
            await _drain(close)
            close.result()
            raise
        self._closing = False
        return self

    async def __aexit__(self, *exc):
        self._closing = True

        async def close():
            await self._idle.wait()
            await self.pool.close()

        pending = asyncio.create_task(close())
        cancelled = await _drain(pending)
        pending.result()
        if cancelled:
            raise asyncio.CancelledError()

    @asynccontextmanager
    async def transaction(self, scope: TenantScope):
        values = self._scope_values(scope)
        if self._closing:
            raise PoolClosed("database is closed")
        self._active += 1
        self._idle.clear()
        c = None
        committed = False
        owner = asyncio.current_task()
        initial_cancels = owner.cancelling()
        lease = Lease()
        try:
            if self.execution_guard is not None:
                await self.execution_guard()
            c = await self.pool.getconn()
            tx = c.transaction()
            await tx.__aenter__()
            error = (None, None, None)
            try:
                await c.execute(_SCOPE_SQL, values)
                yield lease.wrap(c)
                if owner.cancelling() > initial_cancels:
                    raise asyncio.CancelledError()
                if self.execution_guard is not None:
                    await self.execution_guard()
                # 最后一次 guard await 也可能吞掉取消，提交前必须重新复验。
                if owner.cancelling() > initial_cancels:
                    raise asyncio.CancelledError()
            except BaseException as exc:
                error = (type(exc), exc, exc.__traceback__)
                raise
            finally:
                lease.active = False
                # rollback/commit + 归还必须完整完成，不能被第二次 cancel 截断。
                pending = asyncio.create_task(tx.__aexit__(*error))
                cancelled = await _drain(pending)
                pending.result()
                committed = error[0] is None
                if cancelled and committed:
                    raise CommitCompletedAfterCancellation(None)
        finally:
            try:
                if c is not None:
                    pending = asyncio.create_task(self.pool.putconn(c))
                    cancelled = await _drain(pending)
                    pending.result()
                    if cancelled and committed:
                        raise CommitCompletedAfterCancellation(None)
            finally:
                self._active -= 1
                if not self._active:
                    self._idle.set()


class SyncDatabase(_Configuration):
    """同步池 + 异步 run(scope, operation)；队列达到上限立即拒绝。"""

    def __init__(self, dsn: str, **kwargs):
        super().__init__(dsn, **kwargs)
        self.pool = ConnectionPool(**self._pool_options)
        max_size = self._pool_options["max_size"]
        self._executor = ThreadPoolExecutor(max_workers=max_size, thread_name_prefix="deeptutor-pg")
        self._capacity = threading.BoundedSemaphore(max_size + self._pool_options["max_waiting"])
        self._condition = threading.Condition()
        self._closing = True
        self._active = 0
        self._pending = set()

    def _open(self):
        try:
            self.pool.open(wait=True, timeout=self.timeout)
            with self.pool.connection() as c:
                row = c.execute(_RESTRICTED_ROLE_SQL).fetchone()
                if not row or row["unsafe"]:
                    raise RuntimeError("application requires a restricted PostgreSQL role")
        except BaseException:
            self.pool.close()
            raise
        with self._condition:
            self._closing = False
        return self

    def __enter__(self):
        try:
            return self._open()
        except BaseException:
            self._executor.shutdown(wait=True)
            raise

    def __exit__(self, *exc):
        with self._condition:
            self._closing = True
        self._executor.shutdown(wait=True)
        self._close_pool()

    def _close_pool(self):
        with self._condition:
            self._closing = True
            while self._active:
                self._condition.wait()
        self.pool.close()

    async def __aenter__(self):
        pending = asyncio.wrap_future(self._executor.submit(self._open))
        cancelled = await _drain(pending)
        try:
            pending.result()
            if cancelled:
                raise asyncio.CancelledError()
        except BaseException:
            close = asyncio.wrap_future(self._executor.submit(self._close_pool))
            await _drain(close)
            self._executor.shutdown(wait=True)
            close.result()
            raise
        return self

    async def __aexit__(self, *exc):
        with self._condition:
            self._closing = True
            running = tuple(self._pending)
        cancelled = False
        for future in running:
            pending = asyncio.wrap_future(future)
            cancelled |= await _drain(pending)
            # run() 的调用者持有原错误；close 仅等待并取走自己 wrapper 的异常。
            if not pending.cancelled():
                pending.exception()
        close = asyncio.wrap_future(self._executor.submit(self._close_pool))
        cancelled |= await _drain(close)
        self._executor.shutdown(wait=True)
        close.result()
        if cancelled:
            raise asyncio.CancelledError()

    def _check_execution(self):
        if self.execution_guard is not None:
            result = self.execution_guard()
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):
                    result.close()
                raise TypeError("SyncDatabase execution_guard must be synchronous")

    @contextmanager
    def transaction(self, scope: TenantScope, *, _operation=None):
        values = self._scope_values(scope)
        with self._condition:
            if self._closing and _operation is None:
                raise PoolClosed("database is closed")
            self._active += 1
        try:
            if _operation is not None:
                _operation.check()
            self._check_execution()
            with self.pool.connection() as c:
                with c.transaction():
                    if _operation is not None:
                        _operation.check()
                    c.execute(_SCOPE_SQL, values)
                    lease = Lease()
                    try:
                        yield lease.wrap(c)
                    finally:
                        lease.active = False
                    self._check_execution()
                    if _operation is not None:
                        _operation.begin_commit()
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    async def run(self, scope: TenantScope, operation: Callable[..., T]) -> T:
        """一个回调拥有完整事务；取消等回滚完成，不把线程余留 scope 带入。"""
        self._scope_values(scope)
        state = _Operation()

        def work():
            with self.transaction(scope, _operation=state) as c:
                result = operation(c)
                if (
                    inspect.isawaitable(result)
                    or inspect.isgenerator(result)
                    or inspect.isasyncgen(result)
                ):
                    if inspect.iscoroutine(result) or inspect.isgenerator(result):
                        result.close()
                    raise TypeError(
                        "operation must complete synchronous work inside the transaction"
                    )
            return result

        with self._condition:
            if self._closing:
                raise PoolClosed("database is closed")
            if not self._capacity.acquire(blocking=False):
                raise TooManyRequests("bounded PostgreSQL worker queue is full")
            try:
                future = self._executor.submit(Context().run, work)
            except BaseException:
                self._capacity.release()
                raise
            self._pending.add(future)

        def finished(done):
            with self._condition:
                self._pending.discard(done)
            self._capacity.release()

        future.add_done_callback(finished)
        pending = asyncio.wrap_future(future)
        try:
            await asyncio.wait((pending,))
            return pending.result()
        except asyncio.CancelledError:
            state.cancel()
            await _drain(pending)
            try:
                result = pending.result()
            except _CancelledOperation:
                raise asyncio.CancelledError() from None
            except BaseException as exc:
                if not state.committing:
                    raise asyncio.CancelledError() from exc
                # 提交时数据库异常仍保留，不能把连接丢失误报为已回滚。
                raise
            raise CommitCompletedAfterCancellation(result) from None
