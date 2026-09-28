"""执行者历史状态未知时不得静默接管。"""

from uuid import uuid4

import psycopg
import pytest

from deeptutor.persistence.postgres.executor import ExecutorLease
from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

pytestmark = pytest.mark.asyncio


async def test_executor_lease_rejects_unknown_persisted_status_without_db_enum_check(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    original_execution = uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "ALTER TABLE enterprise.executor_state "
            "DROP CONSTRAINT IF EXISTS executor_state_status_check"
        )
        await c.execute(
            "INSERT INTO enterprise.executor_state(resource,execution_id,status) "
            "VALUES('synthetic-executor',%s,'unknown')",
            (original_execution,),
        )
    lease = ExecutorLease(pg_dsn, resource="synthetic-executor")
    try:
        with pytest.raises(RuntimeError, match="previous executor"):
            await lease.acquire()
    finally:
        await lease.close()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        row = await (
            await c.execute(
                "SELECT execution_id,status FROM enterprise.executor_state "
                "WHERE resource='synthetic-executor'"
            )
        ).fetchone()
    assert row == (original_execution, "unknown")
