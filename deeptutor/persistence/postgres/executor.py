"""单执行者锁 + 不随连接消失的登记；不自动接管未知旧进程。"""

import asyncio
import hashlib
import uuid

import psycopg
from psycopg.rows import dict_row


def lock_key(resource):
    return int.from_bytes(
        hashlib.sha256(b"dt-enterprise-database-executor").digest()[:8], signed=True
    )


class ExecutorLease:
    def __init__(self, dsn, *, resource):
        self._dsn = dsn
        self.resource = resource
        self.execution_id = str(uuid.uuid4())
        self.connection = None
        self.active = False

    async def acquire(self):
        c = await psycopg.AsyncConnection.connect(self._dsn, autocommit=True, row_factory=dict_row)
        try:
            await c.execute("SET statement_timeout='5s'")
            acquired = await (
                await c.execute(
                    "SELECT pg_try_advisory_lock(%s) AS acquired", (lock_key(self.resource),)
                )
            ).fetchone()
            if not acquired["acquired"]:
                raise RuntimeError("another executor is active")
            async with c.transaction():
                row = await (
                    await c.execute(
                        "SELECT * FROM enterprise.executor_state WHERE status='active' FOR UPDATE"
                    )
                ).fetchone()
                if row and row["status"] != "stopped":
                    raise RuntimeError(
                        "previous executor must be confirmed stopped before recovery"
                    )
                await c.execute(
                    "INSERT INTO enterprise.executor_state(resource,execution_id,status) VALUES(%s,%s,'active') ON CONFLICT(resource) DO UPDATE SET execution_id=EXCLUDED.execution_id,status='active',updated_at=now()",
                    (self.resource, self.execution_id),
                )
        except BaseException:
            await c.close()
            raise
        self.connection = c
        self.active = True

    async def check(self):
        if not self.active or self.connection is None or self.connection.closed:
            self.active = False
            raise RuntimeError("executor authority unavailable")
        try:
            async with asyncio.timeout(5):
                row = await (
                    await self.connection.execute(
                        "SELECT 1 AS ok FROM enterprise.executor_state WHERE resource=%s AND execution_id=%s AND status='active'",
                        (self.resource, self.execution_id),
                    )
                ).fetchone()
            if not row:
                raise RuntimeError("executor authority unavailable")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.active = False
            raise RuntimeError("executor authority unavailable") from None

    async def close(self):
        if self.connection and not self.connection.closed:
            try:
                if self.active:
                    await self.connection.execute(
                        "UPDATE enterprise.executor_state SET status='stopped',updated_at=now() WHERE resource=%s AND execution_id=%s",
                        (self.resource, self.execution_id),
                    )
            finally:
                await self.connection.close()
        self.active = False

    @staticmethod
    async def confirm_stopped(dsn, *, resource, execution_id):
        # 只在受保护运维 CLI、核实旧进程停止后调用，不能作为租约超时恢复。
        async with await psycopg.AsyncConnection.connect(dsn) as c:
            locked = await (
                await c.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_key(resource),))
            ).fetchone()
            if not locked[0]:
                raise RuntimeError("executor still holds its lock")
            result = await c.execute(
                "UPDATE enterprise.executor_state SET status='stopped',updated_at=now() WHERE resource=%s AND execution_id=%s",
                (resource, execution_id),
            )
            if not result.rowcount:
                raise ValueError("execution identity conflict")
