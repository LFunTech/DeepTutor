# ruff: noqa: F811
"""离线导入 staging schema、维护门禁与 promotion 原子性。"""

from __future__ import annotations

import uuid

import psycopg
from psycopg import errors
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401
from tests.persistence.postgres.business.conftest import (
    business_actors,
    business_database,
    migrated_pg,
)

pytestmark = pytest.mark.asyncio


async def test_migration_stage_schema_is_private_to_migration_role(pg_dsn: str) -> None:
    """生产 migration 若把 staging 暴露给运行角色或不登记 schema 应失败。"""

    from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

    await MigrationRunner(pg_dsn).apply()
    runtime_dsn = pg_dsn.replace("user=postgres", "user=dt_enterprise_app")
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        tables = {
            row[0]
            for row in await (
                await connection.execute(
                    """
                    SELECT tablename
                    FROM pg_tables
                    WHERE schemaname='migration_stage'
                    """
                )
            ).fetchall()
        }
        assert {
            "batches",
            "sources",
            "id_mappings",
            "progress",
            "promotion_items",
        } <= tables
        usage = await (
            await connection.execute(
                "SELECT has_schema_privilege('dt_enterprise_app','migration_stage','USAGE')"
            )
        ).fetchone()
        assert usage[0] is False

    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        with pytest.raises(errors.InsufficientPrivilege):
            await connection.execute("SELECT count(*) FROM migration_stage.batches")


async def test_batch_progress_cancel_resume_and_cleanup_are_persistent(migrated_pg) -> None:
    """生产账本若不能分块恢复/取消或 cleanup 删除 batch 审计应失败。"""

    from deeptutor.persistence.postgres.offline_import.stage import (
        MigrationBatchCancelled,
        MigrationStageRepository,
    )

    repo = MigrationStageRepository(migrated_pg.admin_dsn)
    batch_id = await repo.create_batch(
        target_tenant_id="10000000-0000-0000-0000-000000000001",
        manifest_sha256="a" * 64,
        manifest={"manifest_version": 1},
        operator="unit-test",
    )
    await repo.record_source(
        batch_id,
        source_id="legacy-chat",
        source_type="sqlite",
        source_version="chat_history_sqlite/v1",
        source_owner_id="legacy-user",
        target_owner_id="pg-owner",
        fingerprint="f" * 64,
        manifest={"source_id": "legacy-chat"},
    )
    await repo.record_mapping(
        batch_id,
        domain="sessions",
        source_id="legacy-chat",
        source_owner_id="legacy-user",
        source_key="legacy-session",
        target_key="pg-session",
        metadata={"reason": "stable"},
    )
    await repo.record_progress(
        batch_id,
        domain="sessions",
        chunk_key="chunk-1",
        status="imported",
        rows_done=2,
        resume_cursor={"after_id": 10},
    )

    resumed = await repo.resume_batch(batch_id)
    assert resumed["batch"]["status"] == "planned"
    assert resumed["sources"][0]["source_id"] == "legacy-chat"
    assert resumed["mappings"][0]["target_key"] == "pg-session"
    assert resumed["progress"][0]["resume_cursor"] == {"after_id": 10}

    await repo.cancel_batch(batch_id, reason="operator stop")
    with pytest.raises(MigrationBatchCancelled):
        await repo.record_progress(
            batch_id,
            domain="sessions",
            chunk_key="chunk-2",
            status="imported",
            rows_done=1,
        )
    await repo.cleanup_batch(batch_id)
    cleaned = await repo.resume_batch(batch_id)
    assert cleaned["batch"]["status"] == "cancelled"
    assert cleaned["sources"] == []
    assert cleaned["mappings"] == []
    assert cleaned["progress"] == []


async def test_maintenance_gate_rejects_async_and_sync_business_transactions(
    migrated_pg, business_actors
) -> None:
    """生产运行入口若在维护态仍可读写业务表应失败。"""

    from deeptutor.persistence.postgres.connection import Database, SyncDatabase
    from deeptutor.persistence.postgres.offline_import.maintenance import (
        MaintenanceModeError,
        install_maintenance_guards,
    )
    from deeptutor.persistence.postgres.offline_import.stage import MigrationStageRepository

    actor = business_actors.tenants[0].owners[0]
    repo = MigrationStageRepository(migrated_pg.admin_dsn)
    batch_id = await repo.create_batch(
        target_tenant_id=actor.tenant_id,
        manifest_sha256="b" * 64,
        manifest={"manifest_version": 1},
        operator="unit-test",
    )
    await repo.enter_maintenance(batch_id, tenant_id=actor.tenant_id, reason="import")

    async with Database(migrated_pg.runtime_dsn, resource="gate-async") as db:
        install_maintenance_guards(db, tenant_id=actor.tenant_id)
        with pytest.raises(MaintenanceModeError):
            async with db.transaction(actor.scope) as connection:
                await connection.execute("SELECT 1")

    async with SyncDatabase(migrated_pg.runtime_dsn, resource="gate-sync") as db:
        install_maintenance_guards(db, tenant_id=actor.tenant_id)
        with pytest.raises(MaintenanceModeError):
            await db.run(actor.scope, lambda connection: connection.execute("SELECT 1").fetchone())

    await repo.release_maintenance(batch_id, tenant_id=actor.tenant_id)
    async with Database(migrated_pg.runtime_dsn, resource="gate-open") as db:
        install_maintenance_guards(db, tenant_id=actor.tenant_id)
        async with db.transaction(actor.scope) as connection:
            row = await (await connection.execute("SELECT 1 AS ok")).fetchone()
        assert row["ok"] == 1


async def test_promotion_is_single_transaction_and_failure_leaves_no_visible_rows(
    migrated_pg, business_actors
) -> None:
    """生产 promotion 若分多事务发布导致部分正式记录可见应失败。"""

    from deeptutor.persistence.postgres.offline_import.stage import (
        MigrationStageRepository,
        PromotionStep,
    )

    actor = business_actors.tenants[0].owners[0]
    repo = MigrationStageRepository(migrated_pg.admin_dsn)
    batch_id = await repo.create_batch(
        target_tenant_id=actor.tenant_id,
        manifest_sha256="c" * 64,
        manifest={"manifest_version": 1},
        operator="unit-test",
    )
    await repo.enter_maintenance(batch_id, tenant_id=actor.tenant_id, reason="promote")
    failed_session = f"failed-{uuid.uuid4().hex}"
    good_session = f"good-{uuid.uuid4().hex}"

    with pytest.raises(errors.ForeignKeyViolation):
        await repo.promote_batch(
            batch_id,
            steps=[
                PromotionStep(
                    """
                    INSERT INTO enterprise.sessions(tenant_id, owner_id, id, title)
                    VALUES (%s, %s, %s, 'partial must rollback')
                    """,
                    (actor.tenant_id, actor.user_id, failed_session),
                ),
                PromotionStep(
                    """
                    INSERT INTO enterprise.sessions(tenant_id, owner_id, id, title)
                    VALUES (%s, 'missing-owner', 'bad-fk', 'bad')
                    """,
                    (actor.tenant_id,),
                ),
            ],
        )

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT count(*) FROM enterprise.sessions WHERE id=%s",
                (failed_session,),
            )
        ).fetchone()
        assert row[0] == 0

    await repo.promote_batch(
        batch_id,
        steps=[
            PromotionStep(
                """
                INSERT INTO enterprise.sessions(tenant_id, owner_id, id, title)
                VALUES (%s, %s, %s, 'published')
                """,
                (actor.tenant_id, actor.user_id, good_session),
            )
        ],
    )
    resumed = await repo.resume_batch(batch_id)
    assert resumed["batch"]["status"] == "published"
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT title FROM enterprise.sessions WHERE id=%s",
                (good_session,),
            )
        ).fetchone()
    assert row[0] == "published"
