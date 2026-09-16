"""有限的 scoped 查询接口，不是完整 psycopg 代理。

仅允许已逐次检查 lease 的普通查询、cursor 及结果访问。stream/copy/results、
notifies/pipeline 等延迟接口尚未支持，必须在产生原生延迟句柄前 fail closed。
"""

import asyncio
import inspect
import threading

from psycopg import AsyncConnection, AsyncCursor, Connection, ConnectionInfo, Cursor


def _current_task():
    try:
        return asyncio.current_task()
    except RuntimeError:
        # 纯同步线程没有事件循环，依旧通过 thread owner 隔离。
        return None


class Lease:
    def __init__(self):
        self.active = True
        self.thread = threading.get_ident()
        self.task = _current_task()

    def check(self):
        if not self.active:
            raise RuntimeError("transaction handle is inactive")
        if threading.get_ident() != self.thread or _current_task() is not self.task:
            raise RuntimeError("transaction handle used by a different owner")

    def wrap(self, value):
        if isinstance(value, (Connection, AsyncConnection, Cursor, AsyncCursor, ConnectionInfo)):
            return _Handle(value, self)
        return value


# 采用允许列表，避免新增驱动 API 或延迟资源未经封装自动穿过代理。
_CONNECTION_API = frozenset(
    {
        "execute",
        "cursor",
        "info",
        "closed",
        "broken",
        "autocommit",
        "isolation_level",
        "read_only",
        "deferrable",
    }
)
_CURSOR_API = frozenset(
    {
        "execute",
        "executemany",
        "fetchone",
        "fetchmany",
        "fetchall",
        "nextset",
        "scroll",
        "set_result",
        "setinputsizes",
        "setoutputsize",
        "close",
        "connection",
        "description",
        "rowcount",
        "rownumber",
        "statusmessage",
        "closed",
        "arraysize",
        "name",
        "scrollable",
        "withhold",
        "format",
    }
)


# ConnectionInfo.pgconn 是公开原生连接，不能随着只读元数据一起原样泄漏。
_INFO_API = frozenset(
    {
        "backend_pid",
        "server_version",
        "dbname",
        "user",
        "host",
        "hostaddr",
        "port",
        "status",
        "transaction_status",
        "pipeline_status",
        "timezone",
        "encoding",
        "parameter_status",
        "full_protocol_version",
    }
)


class _Handle:
    def __init__(self, handle, lease):
        self._handle = handle
        self._lease = lease

    def __getattr__(self, name):
        self._lease.check()
        if isinstance(self._handle, (Connection, AsyncConnection)) and name in (
            "commit",
            "rollback",
            "close",
            "transaction",
            "set_autocommit",
            "set_isolation_level",
        ):
            raise RuntimeError("transaction lifecycle belongs to the database owner")
        if isinstance(self._handle, (Connection, AsyncConnection)):
            supported = _CONNECTION_API
        elif isinstance(self._handle, ConnectionInfo):
            supported = _INFO_API
        else:
            supported = _CURSOR_API
        if name not in supported:
            raise RuntimeError(f"unsupported scoped PostgreSQL API: {name}")
        value = getattr(self._handle, name)
        if inspect.iscoroutinefunction(value):

            async def call(*args, **kwargs):
                self._lease.check()
                return self._lease.wrap(await value(*args, **kwargs))

            return call
        if callable(value):

            def call(*args, **kwargs):
                self._lease.check()
                return self._lease.wrap(value(*args, **kwargs))

            return call
        return self._lease.wrap(value)

    def _check_cursor_context(self):
        self._lease.check()
        if isinstance(self._handle, (Connection, AsyncConnection)):
            raise RuntimeError("transaction lifecycle belongs to the database owner")

    def __enter__(self):
        self._check_cursor_context()
        return self._lease.wrap(self._handle.__enter__())

    def __exit__(self, *exc):
        self._check_cursor_context()
        return self._handle.__exit__(*exc)

    async def __aenter__(self):
        self._check_cursor_context()
        return self._lease.wrap(await self._handle.__aenter__())

    async def __aexit__(self, *exc):
        self._check_cursor_context()
        return await self._handle.__aexit__(*exc)

    def __iter__(self):
        self._lease.check()
        return self

    def __next__(self):
        self._lease.check()
        return next(self._handle)

    def __aiter__(self):
        self._lease.check()
        return self

    async def __anext__(self):
        self._lease.check()
        return await anext(self._handle)
