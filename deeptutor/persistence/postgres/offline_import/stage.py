"""离线导入 staging 账本与单事务 promotion。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class MigrationBatchCancelled(RuntimeError):
    """批次已经被取消，不能继续导入分块。"""


@dataclass(frozen=True, slots=True)
class PromotionStep:
    """promotion 事务中的一条 SQL 操作。"""

    sql: str
    params: tuple[Any, ...] = ()


class MigrationStageRepository:
    """维护 migration_stage schema；不由运行角色使用。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def _connect(self):
        return await psycopg.AsyncConnection.connect(self._dsn, row_factory=dict_row)

    async def _batch_status(self, connection, batch_id: uuid.UUID | str) -> str:
        row = await (
            await connection.execute(
                "SELECT status FROM migration_stage.batches WHERE batch_id=%s",
                (str(batch_id),),
            )
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown migration batch: {batch_id}")
        return str(row["status"])

    async def _ensure_mutable(self, connection, batch_id: uuid.UUID | str) -> None:
        status = await self._batch_status(connection, batch_id)
        if status == "cancelled":
            raise MigrationBatchCancelled(f"migration batch {batch_id} is cancelled")
        if status == "published":
            raise RuntimeError(f"migration batch {batch_id} is already published")

    async def create_batch(
        self,
        *,
        target_tenant_id: str,
        manifest_sha256: str,
        manifest: dict[str, Any],
        operator: str,
    ) -> uuid.UUID:
        batch_id = uuid.uuid4()
        async with await self._connect() as connection:
            await connection.execute(
                """
                INSERT INTO migration_stage.batches(
                    batch_id, target_tenant_id, manifest_sha256,
                    source_manifest, operator
                ) VALUES (%s, %s, %s, %s::jsonb, %s)
                """,
                (
                    str(batch_id),
                    target_tenant_id,
                    manifest_sha256,
                    Jsonb(manifest),
                    operator,
                ),
            )
        return batch_id

    async def record_source(
        self,
        batch_id: uuid.UUID | str,
        *,
        source_id: str,
        source_type: str,
        source_version: str,
        source_owner_id: str,
        target_owner_id: str,
        fingerprint: str,
        manifest: dict[str, Any],
        rows_total: int = 0,
        rows_done: int = 0,
        status: str = "planned",
    ) -> None:
        async with await self._connect() as connection:
            await self._ensure_mutable(connection, batch_id)
            await connection.execute(
                """
                INSERT INTO migration_stage.sources(
                    batch_id, source_id, source_type, source_version,
                    source_owner_id, target_owner_id, fingerprint, manifest,
                    rows_total, rows_done, status
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                ON CONFLICT (batch_id, source_id) DO UPDATE SET
                    source_type=EXCLUDED.source_type,
                    source_version=EXCLUDED.source_version,
                    source_owner_id=EXCLUDED.source_owner_id,
                    target_owner_id=EXCLUDED.target_owner_id,
                    fingerprint=EXCLUDED.fingerprint,
                    manifest=EXCLUDED.manifest,
                    rows_total=EXCLUDED.rows_total,
                    rows_done=EXCLUDED.rows_done,
                    status=EXCLUDED.status
                """,
                (
                    str(batch_id),
                    source_id,
                    source_type,
                    source_version,
                    source_owner_id,
                    target_owner_id,
                    fingerprint,
                    Jsonb(manifest),
                    rows_total,
                    rows_done,
                    status,
                ),
            )

    async def record_mapping(
        self,
        batch_id: uuid.UUID | str,
        *,
        domain: str,
        source_id: str,
        source_owner_id: str,
        source_key: str,
        target_key: str | None = None,
        target_int: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with await self._connect() as connection:
            await self._ensure_mutable(connection, batch_id)
            await connection.execute(
                """
                INSERT INTO migration_stage.id_mappings(
                    batch_id, domain, source_id, source_owner_id, source_key,
                    target_key, target_int, metadata
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (batch_id, domain, source_id, source_owner_id, source_key)
                DO UPDATE SET
                    target_key=EXCLUDED.target_key,
                    target_int=EXCLUDED.target_int,
                    metadata=EXCLUDED.metadata
                """,
                (
                    str(batch_id),
                    domain,
                    source_id,
                    source_owner_id,
                    source_key,
                    target_key,
                    target_int,
                    Jsonb(metadata or {}),
                ),
            )

    async def record_progress(
        self,
        batch_id: uuid.UUID | str,
        *,
        domain: str,
        chunk_key: str,
        status: str,
        rows_done: int,
        resume_cursor: dict[str, Any] | None = None,
        checksum: str = "",
    ) -> None:
        async with await self._connect() as connection:
            await self._ensure_mutable(connection, batch_id)
            await connection.execute(
                """
                INSERT INTO migration_stage.progress(
                    batch_id, domain, chunk_key, status, rows_done,
                    resume_cursor, checksum
                ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT (batch_id, domain, chunk_key) DO UPDATE SET
                    status=EXCLUDED.status,
                    rows_done=EXCLUDED.rows_done,
                    resume_cursor=EXCLUDED.resume_cursor,
                    checksum=EXCLUDED.checksum,
                    updated_at=now()
                """,
                (
                    str(batch_id),
                    domain,
                    chunk_key,
                    status,
                    rows_done,
                    Jsonb(resume_cursor or {}),
                    checksum,
                ),
            )

    async def resume_batch(self, batch_id: uuid.UUID | str) -> dict[str, Any]:
        async with await self._connect() as connection:
            batch = await (
                await connection.execute(
                    "SELECT * FROM migration_stage.batches WHERE batch_id=%s",
                    (str(batch_id),),
                )
            ).fetchone()
            if batch is None:
                raise KeyError(f"unknown migration batch: {batch_id}")
            sources = await (
                await connection.execute(
                    """
                    SELECT * FROM migration_stage.sources
                    WHERE batch_id=%s ORDER BY source_id
                    """,
                    (str(batch_id),),
                )
            ).fetchall()
            mappings = await (
                await connection.execute(
                    """
                    SELECT * FROM migration_stage.id_mappings
                    WHERE batch_id=%s ORDER BY domain, source_id, source_key
                    """,
                    (str(batch_id),),
                )
            ).fetchall()
            progress = await (
                await connection.execute(
                    """
                    SELECT * FROM migration_stage.progress
                    WHERE batch_id=%s ORDER BY domain, chunk_key
                    """,
                    (str(batch_id),),
                )
            ).fetchall()
        return {
            "batch": dict(batch),
            "sources": [dict(row) for row in sources],
            "mappings": [dict(row) for row in mappings],
            "progress": [dict(row) for row in progress],
        }

    async def cancel_batch(self, batch_id: uuid.UUID | str, *, reason: str) -> None:
        async with await self._connect() as connection:
            await connection.execute(
                """
                UPDATE migration_stage.batches
                   SET status='cancelled', error=%s, updated_at=now()
                 WHERE batch_id=%s AND status <> 'published'
                """,
                (reason, str(batch_id)),
            )
            await connection.execute(
                """
                UPDATE migration_stage.progress
                   SET status='cancelled', updated_at=now()
                 WHERE batch_id=%s AND status NOT IN ('verified','failed')
                """,
                (str(batch_id),),
            )

    async def enter_maintenance(
        self,
        batch_id: uuid.UUID | str,
        *,
        tenant_id: str,
        reason: str,
    ) -> None:
        async with await self._connect() as connection:
            await self._ensure_mutable(connection, batch_id)
            await connection.execute(
                """
                INSERT INTO enterprise.maintenance_locks(
                    tenant_id, batch_id, active, reason, entered_at,
                    updated_at, released_at, generation
                ) VALUES (%s,%s,true,%s,now(),now(),NULL,1)
                ON CONFLICT (tenant_id) DO UPDATE SET
                    batch_id=EXCLUDED.batch_id,
                    active=true,
                    reason=EXCLUDED.reason,
                    updated_at=now(),
                    released_at=NULL,
                    generation=enterprise.maintenance_locks.generation + 1
                """,
                (tenant_id, str(batch_id), reason),
            )
            await connection.execute(
                """
                UPDATE migration_stage.batches
                   SET status='importing', updated_at=now()
                 WHERE batch_id=%s AND status='planned'
                """,
                (str(batch_id),),
            )

    async def release_maintenance(
        self,
        batch_id: uuid.UUID | str,
        *,
        tenant_id: str,
    ) -> None:
        async with await self._connect() as connection:
            await connection.execute(
                """
                UPDATE enterprise.maintenance_locks
                   SET active=false, released_at=now(), updated_at=now()
                 WHERE tenant_id=%s AND batch_id=%s
                """,
                (tenant_id, str(batch_id)),
            )

    async def promote_batch(
        self,
        batch_id: uuid.UUID | str,
        *,
        steps: list[PromotionStep],
    ) -> None:
        async with await self._connect() as connection:
            async with connection.transaction():
                batch = await (
                    await connection.execute(
                        """
                        SELECT batch_id, target_tenant_id, status
                          FROM migration_stage.batches
                         WHERE batch_id=%s
                         FOR UPDATE
                        """,
                        (str(batch_id),),
                    )
                ).fetchone()
                if batch is None:
                    raise KeyError(f"unknown migration batch: {batch_id}")
                if batch["status"] == "cancelled":
                    raise MigrationBatchCancelled(f"migration batch {batch_id} is cancelled")
                if batch["status"] == "published":
                    return
                locked = await (
                    await connection.execute(
                        """
                        SELECT active
                          FROM enterprise.maintenance_locks
                         WHERE tenant_id=%s AND batch_id=%s
                         FOR UPDATE
                        """,
                        (batch["target_tenant_id"], str(batch_id)),
                    )
                ).fetchone()
                if not locked or not locked["active"]:
                    raise RuntimeError("maintenance lock is required before promotion")
                await connection.execute(
                    """
                    UPDATE migration_stage.batches
                       SET status='promoting', updated_at=now()
                     WHERE batch_id=%s
                    """,
                    (str(batch_id),),
                )
                for step in steps:
                    await connection.execute(step.sql, step.params, prepare=False)
                await connection.execute(
                    """
                    UPDATE migration_stage.batches
                       SET status='published', updated_at=now()
                     WHERE batch_id=%s
                    """,
                    (str(batch_id),),
                )

    async def cleanup_batch(self, batch_id: uuid.UUID | str) -> None:
        async with await self._connect() as connection:
            status = await self._batch_status(connection, batch_id)
            if status not in {"published", "cancelled", "failed"}:
                raise RuntimeError("only terminal batches can be cleaned")
            for table in ("promotion_items", "progress", "id_mappings", "sources"):
                await connection.execute(
                    f"DELETE FROM migration_stage.{table} WHERE batch_id=%s",
                    (str(batch_id),),
                    prepare=False,
                )


__all__ = [
    "MigrationBatchCancelled",
    "MigrationStageRepository",
    "PromotionStep",
]
