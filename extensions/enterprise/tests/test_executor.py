import importlib.util

from deeptutor_enterprise.migrations.runner import MigrationRunner
import psycopg
import pytest

from tests.fixtures.postgres import single_database_user_dsn


async def test_single_executor_and_explicit_crash_recovery(pg_dsn):
    assert importlib.util.find_spec("deeptutor_enterprise.executor"), "单执行者防线尚未实现"
    from deeptutor_enterprise.executor import ExecutorLease

    await MigrationRunner(pg_dsn).apply()
    dsn = single_database_user_dsn(pg_dsn)
    one = ExecutorLease(dsn, resource="same")
    await one.acquire()
    second = ExecutorLease(dsn, resource="same")
    with pytest.raises(RuntimeError):
        await second.acquire()
    await one.check()
    await one.close()
    await second.acquire()
    identity = second.execution_id
    # 模拟进程退出但来不及写 stopped；不能靠锁释放自动接管。
    await second.connection.close()
    with pytest.raises(RuntimeError):
        await second.check()
    third = ExecutorLease(dsn, resource="same")
    with pytest.raises(RuntimeError, match="confirmed"):
        await third.acquire()
    await ExecutorLease.confirm_stopped(dsn, resource="same", execution_id=identity)
    await third.acquire()
    await third.close()


async def test_cancelled_health_probe_does_not_fence_healthy_executor(pg_dsn):
    import asyncio

    from deeptutor_enterprise.executor import ExecutorLease

    await MigrationRunner(pg_dsn).apply()
    lease = ExecutorLease(
        single_database_user_dsn(pg_dsn), resource="cancel-test"
    )
    await lease.acquire()
    query = asyncio.create_task(lease.connection.execute("SELECT pg_sleep(0.2)"))
    probe = asyncio.create_task(lease.check())
    await asyncio.sleep(0.02)
    probe.cancel()
    with pytest.raises(asyncio.CancelledError):
        await probe
    await query
    await lease.check()
    await lease.close()


async def test_different_resource_name_cannot_bypass_single_executor(pg_dsn):
    from deeptutor_enterprise.executor import ExecutorLease

    await MigrationRunner(pg_dsn).apply()
    dsn = single_database_user_dsn(pg_dsn)
    first = ExecutorLease(dsn, resource="first")
    second = ExecutorLease(dsn, resource="second")
    await first.acquire()
    try:
        with pytest.raises(RuntimeError):
            await second.acquire()
    finally:
        await second.close()
        await first.close()
