"""PG-only 运行维护门禁。"""

from __future__ import annotations

from typing import Any

from deeptutor.persistence.postgres.connection import Database, SyncDatabase


class MaintenanceModeError(RuntimeError):
    """目标 tenant 正处于离线导入/切换维护态，业务入口必须拒绝。"""


async def _check_async(pool: Any, tenant_id: str) -> None:
    async with pool.connection() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.tenant_id', %s, true), "
                "set_config('app.user_id', %s, true)",
                (tenant_id, "@maintenance-gate"),
            )
            row = await (
                await connection.execute(
                    """
                    SELECT EXISTS(
                        SELECT 1
                          FROM enterprise.maintenance_locks
                         WHERE tenant_id=%s AND active
                    ) AS locked
                    """,
                    (tenant_id,),
                )
            ).fetchone()
    if row and row["locked"]:
        raise MaintenanceModeError("PostgreSQL target is in maintenance mode")


def _check_sync(pool: Any, tenant_id: str) -> None:
    with pool.connection() as connection:
        with connection.transaction():
            connection.execute(
                "SELECT set_config('app.tenant_id', %s, true), "
                "set_config('app.user_id', %s, true)",
                (tenant_id, "@maintenance-gate"),
            )
            row = connection.execute(
                """
                SELECT EXISTS(
                    SELECT 1
                      FROM enterprise.maintenance_locks
                     WHERE tenant_id=%s AND active
                ) AS locked
                """,
                (tenant_id,),
            ).fetchone()
    if row and row["locked"]:
        raise MaintenanceModeError("PostgreSQL target is in maintenance mode")


def install_maintenance_guards(database: Database | SyncDatabase, *, tenant_id: str) -> None:
    """Install per-transaction maintenance checks on a Database/SyncDatabase."""

    if isinstance(database, Database):
        async def guard() -> None:
            await _check_async(database.pool, tenant_id)

        database.execution_guard = guard
        return
    if isinstance(database, SyncDatabase):
        def guard() -> None:
            _check_sync(database.pool, tenant_id)

        database.execution_guard = guard
        return
    raise TypeError("unsupported PostgreSQL database type")


__all__ = ["MaintenanceModeError", "install_maintenance_guards"]
