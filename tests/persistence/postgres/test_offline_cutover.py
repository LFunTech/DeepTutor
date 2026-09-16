# ruff: noqa: F811
"""离线导入 cutover / rollback 检查。"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401
from tests.persistence.postgres.business.conftest import (  # noqa: F401
    business_actors,
    business_database,
    business_sync_database,
    migrated_pg,
    pg_scope_factory,
    pg_session_store_factory,
)
from tests.persistence.postgres.test_sqlite_chat_history_import import (
    _make_legacy_source as _make_chat_source,
)
from tests.persistence.postgres.test_sqlite_chat_history_import import (
    _snapshot as _chat_snapshot,
)
from tests.persistence.postgres.test_sqlite_runtime_projection_import import (
    _make_cron_source,
    _seed_session_mapping,
)
from tests.persistence.postgres.test_sqlite_runtime_projection_import import (
    _snapshot as _runtime_snapshot,
)

pytestmark = pytest.mark.asyncio


async def _chat_batch(tmp_path: Path, migrated_pg, actor) -> str:
    from deeptutor.persistence.postgres.offline_import.chat_sqlite import (
        SQLiteChatHistoryImporter,
    )
    from deeptutor.persistence.postgres.offline_import.verify_report import OfflineImportVerifier

    source = tmp_path / "chat.sqlite3"
    _make_chat_source(source)
    manifest = _chat_snapshot(
        source,
        tmp_path / "chat-artifact",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    import_report = await SQLiteChatHistoryImporter(migrated_pg.admin_dsn).import_manifest(
        manifest.manifest_path,
        operator="unit-test",
    )
    verify = await OfflineImportVerifier(migrated_pg.admin_dsn).verify_batch(
        import_report["batch_id"]
    )
    assert verify.ok is True
    return str(import_report["batch_id"])


async def _auth_version(dsn: str, *, tenant_id: str, user_id: str) -> int:
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT auth_version FROM enterprise.users WHERE tenant_id=%s AND id=%s",
                (tenant_id, user_id),
            )
        ).fetchone()
    return int(row[0])


async def _insert_device_credential(dsn: str, *, tenant_id: str, user_id: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute(
            """
            INSERT INTO enterprise.device_credentials(
                tenant_id,user_id,id,device_name,pairing_code_hash,pin_hash,
                auth_version,auth_epoch,expires_at,daily_limit_minutes,
                used_seconds,generation
            ) VALUES (
                %s,%s,'device-cutover','Pad','code','pin',1,'epoch',
                now()+interval '1 day',30,0,9
            )
            """,
            (tenant_id, user_id),
        )


async def test_cutover_release_requires_verified_batch_stopped_writers_and_identity_generation(
    tmp_path,
    migrated_pg,
    business_actors,
) -> None:
    """开放业务前必须确认 batch/verify/维护态、全部 writer 停止和身份世代。"""

    from deeptutor.persistence.postgres.offline_import.cutover import (
        CutoverReleaseRequest,
        OfflineCutoverCoordinator,
    )

    actor = business_actors.tenants[0].owners[0]
    batch_id = await _chat_batch(tmp_path, migrated_pg, actor)
    generation = await _auth_version(
        migrated_pg.admin_dsn, tenant_id=actor.tenant_id, user_id=actor.user_id
    )
    coordinator = OfflineCutoverCoordinator(migrated_pg.admin_dsn)

    missing_writer = await coordinator.prepare_release(
        batch_id,
        CutoverReleaseRequest(
            stopped_writers={"web"},
            identity_generations={actor.user_id: generation},
        ),
    )
    assert missing_writer.ok is False
    assert any(issue["code"] == "writer_not_stopped" for issue in missing_writer.issues)

    wrong_generation = await coordinator.prepare_release(
        batch_id,
        CutoverReleaseRequest(
            stopped_writers={"web", "cli", "cron"},
            identity_generations={actor.user_id: generation - 1},
        ),
    )
    assert wrong_generation.ok is False
    assert any(issue["code"] == "identity_generation_mismatch" for issue in wrong_generation.issues)

    released = await coordinator.release(
        batch_id,
        CutoverReleaseRequest(
            stopped_writers={"web", "cli", "cron"},
            identity_generations={actor.user_id: generation},
        ),
    )
    assert released.ok is True

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        lock = await (
            await connection.execute(
                "SELECT active FROM enterprise.maintenance_locks WHERE tenant_id=%s",
                (actor.tenant_id,),
            )
        ).fetchone()
        stored = await (
            await connection.execute(
                "SELECT verify_report FROM migration_stage.batches WHERE batch_id=%s",
                (batch_id,),
            )
        ).fetchone()
    assert lock[0] is False
    assert stored[0]["cutover"]["opened"] is True
    assert stored[0]["cutover"]["target_baseline_digest"]


async def test_rollback_blocks_legacy_backends_after_pg_new_write_and_old_schema1_build(
    tmp_path,
    migrated_pg,
    business_actors,
) -> None:
    """PG 新写后不能回 SQLite/PocketBase；schema1 原地升级不能直接启旧构建。"""

    from deeptutor.persistence.postgres.offline_import.cutover import (
        CutoverReleaseRequest,
        OfflineCutoverCoordinator,
        RollbackCheckRequest,
    )

    actor = business_actors.tenants[0].owners[0]
    batch_id = await _chat_batch(tmp_path, migrated_pg, actor)
    generation = await _auth_version(
        migrated_pg.admin_dsn, tenant_id=actor.tenant_id, user_id=actor.user_id
    )
    coordinator = OfflineCutoverCoordinator(migrated_pg.admin_dsn)
    await coordinator.release(
        batch_id,
        CutoverReleaseRequest(
            stopped_writers={"web", "cli", "cron"},
            identity_generations={actor.user_id: generation},
        ),
    )

    clean_legacy = await coordinator.check_rollback(
        batch_id,
        RollbackCheckRequest(
            target="legacy_sqlite",
            source_backends_unchanged=True,
            identity_generations={actor.user_id: generation},
        ),
    )
    assert clean_legacy.ok is True

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            """
            INSERT INTO enterprise.sessions(tenant_id, owner_id, id, title)
            VALUES (%s,%s,'after-cutover','new PG write')
            """,
            (actor.tenant_id, actor.user_id),
        )

    dirty_legacy = await coordinator.check_rollback(
        batch_id,
        RollbackCheckRequest(
            target="legacy_pocketbase",
            source_backends_unchanged=True,
            identity_generations={actor.user_id: generation},
        ),
    )
    assert dirty_legacy.ok is False
    assert any(
        issue["code"] == "pg_new_writes_block_legacy_rollback"
        for issue in dirty_legacy.issues
    )

    old_build = await coordinator.check_rollback(
        batch_id,
        RollbackCheckRequest(
            target="schema1_legacy_build",
            source_backends_unchanged=True,
            identity_generations={actor.user_id: generation},
        ),
    )
    assert old_build.ok is False
    assert any(issue["code"] == "schema1_legacy_build_incompatible" for issue in old_build.issues)


async def test_cutover_blocks_unreconciled_external_actions_and_revoked_devices(
    tmp_path,
    migrated_pg,
    business_actors,
    pg_session_store_factory,
) -> None:
    """不确定外部动作必须先对账；账号/设备撤销后回退不得复活。"""

    from deeptutor.persistence.postgres.offline_import.cutover import (
        CutoverReleaseRequest,
        OfflineCutoverCoordinator,
        RollbackCheckRequest,
    )
    from deeptutor.persistence.postgres.offline_import.runtime_sqlite import (
        SQLiteRuntimeProjectionImporter,
    )
    from deeptutor.persistence.postgres.offline_import.verify_report import OfflineImportVerifier

    actor = business_actors.tenants[0].owners[0]
    await _seed_session_mapping(migrated_pg, actor, pg_session_store_factory)
    cron_manifest = _runtime_snapshot(
        _make_cron_source(tmp_path / "cron.sqlite3", now_ms=4_000_000),
        tmp_path / "runtime-artifact",
        source_id="legacy-cron",
        source_version="cron_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    cron_batch = await SQLiteRuntimeProjectionImporter(migrated_pg.admin_dsn).import_manifest(
        cron_manifest,
        operator="unit-test",
    )
    assert (
        await OfflineImportVerifier(migrated_pg.admin_dsn).verify_batch(cron_batch["batch_id"])
    ).ok is True
    generation = await _auth_version(
        migrated_pg.admin_dsn, tenant_id=actor.tenant_id, user_id=actor.user_id
    )
    coordinator = OfflineCutoverCoordinator(migrated_pg.admin_dsn)

    blocked = await coordinator.prepare_release(
        cron_batch["batch_id"],
        CutoverReleaseRequest(
            stopped_writers={"web", "cron", "partners", "marginnote"},
            identity_generations={actor.user_id: generation},
        ),
    )
    assert blocked.ok is False
    assert any(issue["code"] == "external_action_unresolved" for issue in blocked.issues)

    chat_batch = await _chat_batch(tmp_path / "chat-case", migrated_pg, actor)
    await _insert_device_credential(
        migrated_pg.admin_dsn, tenant_id=actor.tenant_id, user_id=actor.user_id
    )
    await coordinator.release(
        chat_batch,
        CutoverReleaseRequest(
            stopped_writers={"web", "cli", "cron"},
            identity_generations={actor.user_id: generation},
            device_generations={"device-cutover": 9},
            reconciled_external_actions={"*"},
        ),
    )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            """
            UPDATE enterprise.device_credentials
               SET revoked_at=now(), generation=10
             WHERE tenant_id=%s AND user_id=%s AND id='device-cutover'
            """,
            (actor.tenant_id, actor.user_id),
        )
        await connection.execute(
            """
            UPDATE enterprise.users SET auth_version=auth_version+1
             WHERE tenant_id=%s AND id=%s
            """,
            (actor.tenant_id, actor.user_id),
        )

    rollback = await coordinator.check_rollback(
        chat_batch,
        RollbackCheckRequest(
            target="compatible_pg_build",
            source_backends_unchanged=True,
            identity_generations={actor.user_id: generation},
            device_generations={"device-cutover": 9},
            compatible_pg_build=True,
        ),
    )
    assert rollback.ok is False
    assert {issue["code"] for issue in rollback.issues} >= {
        "identity_generation_mismatch",
        "device_generation_mismatch",
    }
