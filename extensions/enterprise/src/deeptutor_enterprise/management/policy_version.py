"""授权事实变动后的本产品权限版本栅栏。"""

from __future__ import annotations

from uuid import UUID

from .authorization import ManagementAuthorizationDenied


async def advance_principal_policy_version(
    connection, principal_id: UUID, *, expected_before: int
) -> int:
    """同事务保证版本恰好推进一次，兼容历史触发器与退役后的 schema。

    旧 schema 的赋权触发器可能已推进；新 schema 则由程序推进。无论哪种情况，
    只允许 ``expected_before + 1``，不得把多次变动或未知版本静默归并。
    """

    row = await (
        await connection.execute(
            "SELECT policy_version FROM management.principals WHERE id=%s FOR UPDATE",
            (principal_id,),
        )
    ).fetchone()
    if row is None:
        raise ManagementAuthorizationDenied("management principal disappeared during mutation")
    current = row["policy_version"] if isinstance(row, dict) else row[0]
    if current == expected_before + 1:
        return current
    if current != expected_before:
        raise ManagementAuthorizationDenied("management policy version changed unexpectedly")
    updated = await (
        await connection.execute(
            "UPDATE management.principals SET policy_version=policy_version+1,"
            "updated_at=clock_timestamp() WHERE id=%s AND policy_version=%s "
            "RETURNING policy_version",
            (principal_id, expected_before),
        )
    ).fetchone()
    if updated is None:
        raise ManagementAuthorizationDenied("management policy version changed unexpectedly")
    return updated["policy_version"] if isinstance(updated, dict) else updated[0]
