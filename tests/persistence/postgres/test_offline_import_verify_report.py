# ruff: noqa: F811
"""离线导入 verify/report 语义校验。"""

from __future__ import annotations

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
from tests.persistence.postgres.test_pocketbase_import import _pocketbase_manifest
from tests.persistence.postgres.test_sqlite_chat_history_import import (
    _make_legacy_source as _make_chat_source,
)
from tests.persistence.postgres.test_sqlite_chat_history_import import (
    _snapshot as _chat_snapshot,
)
from tests.persistence.postgres.test_sqlite_learning_reading_import import (
    _make_mastery_v2_source,
    _make_reading_source,
    _seed_existing_mapping,
)
from tests.persistence.postgres.test_sqlite_learning_reading_import import (
    _snapshot as _learning_snapshot,
)
from tests.persistence.postgres.test_sqlite_learning_reading_import import (
    _write_combined_manifest as _write_learning_manifest,
)
from tests.persistence.postgres.test_sqlite_matrix_store_import import (
    _make_matrix_sqlite_store,
    _secrets,
)
from tests.persistence.postgres.test_sqlite_matrix_store_import import (
    _snapshot as _matrix_snapshot,
)
from tests.persistence.postgres.test_sqlite_runtime_projection_import import (
    _make_cron_source,
    _make_marginnote_source,
    _make_partner_status_source,
    _seed_session_mapping,
)
from tests.persistence.postgres.test_sqlite_runtime_projection_import import (
    _snapshot as _sqlite_snapshot,
)
from tests.persistence.postgres.test_sqlite_runtime_projection_import import (
    _write_combined_manifest as _write_runtime_manifest,
)

pytestmark = pytest.mark.asyncio


async def test_verify_report_detects_message_relation_drift_with_same_counts(
    tmp_path,
    migrated_pg,
    business_actors,
) -> None:
    """行数相同但 PB message metadata 指向不存在消息时必须阻断。"""

    from deeptutor.persistence.postgres.offline_import.pocketbase_import import (
        PocketBaseOfflineImporter,
    )
    from deeptutor.persistence.postgres.offline_import.verify_report import OfflineImportVerifier

    actor = business_actors.tenants[0].owners[0]
    manifest = _pocketbase_manifest(tmp_path / "pb", actor)
    import_report = await PocketBaseOfflineImporter(migrated_pg.admin_dsn).import_manifest(
        manifest, operator="unit-test"
    )

    verifier = OfflineImportVerifier(migrated_pg.admin_dsn)
    clean = await verifier.verify_batch(import_report["batch_id"])
    assert clean.ok is True
    assert clean.sources[0]["domain_counts"]["messages"]["source"] == 2

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            """
            UPDATE enterprise.messages
               SET metadata='{"message_id":999999}'::jsonb
             WHERE tenant_id=%s AND owner_id=%s AND role='assistant'
            """,
            (actor.tenant_id, actor.user_id),
        )

    drift = await verifier.verify_batch(import_report["batch_id"])
    assert drift.ok is False
    assert any(issue["code"] == "message_reference_missing" for issue in drift.issues)


async def test_verify_report_detects_cron_timezone_drift_with_same_counts(
    tmp_path,
    migrated_pg,
    business_actors,
    pg_session_store_factory,
) -> None:
    """行数相同但 cron timezone 与 source 语义不一致时必须阻断。"""

    from deeptutor.persistence.postgres.offline_import.runtime_sqlite import (
        SQLiteRuntimeProjectionImporter,
    )
    from deeptutor.persistence.postgres.offline_import.verify_report import OfflineImportVerifier

    actor = business_actors.tenants[0].owners[0]
    await _seed_session_mapping(migrated_pg, actor, pg_session_store_factory)
    now_ms = 4_000_000
    manifest = _sqlite_snapshot(
        _make_cron_source(tmp_path / "cron.sqlite3", now_ms=now_ms),
        tmp_path / "artifact",
        source_id="legacy-cron",
        source_version="cron_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    import_report = await SQLiteRuntimeProjectionImporter(migrated_pg.admin_dsn).import_manifest(
        manifest, operator="unit-test"
    )

    verifier = OfflineImportVerifier(migrated_pg.admin_dsn)
    assert (await verifier.verify_batch(import_report["batch_id"])).ok is True

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            """
            UPDATE enterprise.cron_jobs
               SET tz='UTC'
             WHERE tenant_id=%s AND owner_id=%s AND job_id='paused-cron'
            """,
            (actor.tenant_id, actor.user_id),
        )

    drift = await verifier.verify_batch(import_report["batch_id"])
    assert drift.ok is False
    assert any(issue["code"] == "cron_timezone_mismatch" for issue in drift.issues)


async def test_verify_report_detects_matrix_secret_drift_with_same_counts(
    tmp_path,
    migrated_pg,
    business_actors,
) -> None:
    """行数相同但 Matrix Secret 元数据不匹配时必须阻断。"""

    from deeptutor.persistence.postgres.offline_import.matrix_sqlite import (
        SQLiteMatrixStoreImporter,
    )
    from deeptutor.persistence.postgres.offline_import.verify_report import OfflineImportVerifier

    actor = business_actors.tenants[0].owners[0]
    source = _make_matrix_sqlite_store(tmp_path / "legacy-matrix")
    manifest = _matrix_snapshot(
        source["db_path"],
        tmp_path / "artifact-matrix",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    import_report = await SQLiteMatrixStoreImporter(
        migrated_pg.admin_dsn,
        secret_resolver=_secrets(),
    ).import_manifest(manifest, operator="unit-test")

    verifier = OfflineImportVerifier(migrated_pg.admin_dsn)
    assert (await verifier.verify_batch(import_report["batch_id"])).ok is True

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            """
            UPDATE enterprise.matrix_accounts
               SET secret_id='matrix-import:wrong'
             WHERE tenant_id=%s AND owner_id=%s
            """,
            (actor.tenant_id, actor.user_id),
        )

    drift = await verifier.verify_batch(import_report["batch_id"])
    assert drift.ok is False
    assert any(issue["code"] == "matrix_secret_mismatch" for issue in drift.issues)


async def test_verify_report_covers_chat_notebook_source_without_unknown_skip(
    tmp_path,
    migrated_pg,
    business_actors,
) -> None:
    """chat_history/notebook 已登记源必须产出域报告，不能作为未知源跳过。"""

    from deeptutor.persistence.postgres.offline_import.chat_sqlite import (
        SQLiteChatHistoryImporter,
    )
    from deeptutor.persistence.postgres.offline_import.verify_report import OfflineImportVerifier

    actor = business_actors.tenants[0].owners[0]
    source = tmp_path / "chat_history.sqlite3"
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

    report = await OfflineImportVerifier(migrated_pg.admin_dsn).verify_batch(
        import_report["batch_id"]
    )

    assert report.ok is True
    assert report.domains["notebook_entries"] == {"source": 1, "target": 1}
    assert report.domains["notebook_entry_categories"] == {"source": 1, "target": 1}

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "ALTER TABLE enterprise.notebook_entries "
                "DROP CONSTRAINT IF EXISTS notebook_entries_source_check"
            )
            await connection.execute(
                "UPDATE enterprise.notebook_entries SET source='future-source' "
                "WHERE tenant_id=%s AND owner_id=%s",
                (actor.tenant_id, actor.user_id),
            )
    drift = await OfflineImportVerifier(migrated_pg.admin_dsn).verify_batch(
        import_report["batch_id"]
    )
    assert drift.ok is False
    assert any(
        issue["code"] == "source_verify_failed" and "source" in issue["detail"]["error"]
        for issue in drift.issues
    )


async def test_verify_report_covers_learning_reading_sources_without_unknown_skip(
    tmp_path,
    migrated_pg,
    business_actors,
    pg_session_store_factory,
) -> None:
    """mastery/reading 已登记源必须验证跨域引用并输出域计数。"""

    from deeptutor.persistence.postgres.offline_import.learning_reading_sqlite import (
        SQLiteLearningReadingImporter,
    )
    from deeptutor.persistence.postgres.offline_import.verify_report import OfflineImportVerifier

    actor = business_actors.tenants[0].owners[0]
    await _seed_existing_mapping(migrated_pg, actor, pg_session_store_factory)
    artifact = tmp_path / "learning-artifact"
    mastery_manifest = _learning_snapshot(
        _make_mastery_v2_source(tmp_path / "mastery"),
        artifact,
        source_id="legacy-mastery",
        source_version="mastery_sqlite/v2",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    reading_manifest = _learning_snapshot(
        _make_reading_source(tmp_path / "reading"),
        artifact,
        source_id="legacy-reading",
        source_version="reading_catalog_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    manifest = _write_learning_manifest(
        artifact / "combined-learning.json", [mastery_manifest, reading_manifest]
    )
    import_report = await SQLiteLearningReadingImporter(migrated_pg.admin_dsn).import_manifest(
        manifest,
        operator="unit-test",
    )

    report = await OfflineImportVerifier(migrated_pg.admin_dsn).verify_batch(
        import_report["batch_id"]
    )

    assert report.ok is True
    assert report.domains["mastery_paths"] == {"source": 1, "target": 1}
    assert report.domains["reading_links"] == {"source": 1, "target": 1}

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "ALTER TABLE enterprise.reading_materials "
                "DROP CONSTRAINT IF EXISTS reading_materials_status_check"
            )
            await connection.execute(
                "UPDATE enterprise.reading_materials SET status='future-state',progress=0 "
                "WHERE tenant_id=%s AND owner_id=%s",
                (actor.tenant_id, actor.user_id),
            )
    drift = await OfflineImportVerifier(migrated_pg.admin_dsn).verify_batch(
        import_report["batch_id"]
    )
    assert drift.ok is False
    assert any(
        issue["code"] == "source_verify_failed" and "state" in issue["detail"]["error"]
        for issue in drift.issues
    )


@pytest.mark.parametrize(
    ("table", "constraint", "corruption", "message"),
    [
        ("mastery_interactions", "mastery_interactions_status_check", "status='future-state'", "interaction status is unknown"),
        ("mastery_topic_meta", "mastery_topic_meta_status_check", "status='future-state'", "topic status is unknown"),
        ("mastery_topic_sources", "mastery_topic_sources_kind_check", "kind='future-kind'", "source kind is unknown"),
        ("mastery_topic_sources", "mastery_topic_sources_check", "kind='chat',external_id=''", "chat source id is required"),
    ],
)
async def test_verify_report_rejects_unknown_mastery_target_without_database_checks(
    tmp_path,
    migrated_pg,
    business_actors,
    pg_session_store_factory,
    table,
    constraint,
    corruption,
    message,
) -> None:
    from deeptutor.persistence.postgres.offline_import.learning_reading_sqlite import (
        SQLiteLearningReadingImporter,
    )
    from deeptutor.persistence.postgres.offline_import.verify_report import OfflineImportVerifier

    actor = business_actors.tenants[0].owners[0]
    await _seed_existing_mapping(migrated_pg, actor, pg_session_store_factory)
    manifest = _learning_snapshot(
        _make_mastery_v2_source(tmp_path / "mastery"),
        tmp_path / "artifact",
        source_id="legacy-mastery",
        source_version="mastery_sqlite/v2",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    report = await SQLiteLearningReadingImporter(migrated_pg.admin_dsn).import_manifest(
        manifest, operator="unit-test"
    )
    verifier = OfflineImportVerifier(migrated_pg.admin_dsn)
    assert (await verifier.verify_batch(report["batch_id"])).ok is True
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                f"ALTER TABLE enterprise.{table} DROP CONSTRAINT IF EXISTS {constraint}"
            )
            await connection.execute(
                f"UPDATE enterprise.{table} SET {corruption} "
                "WHERE tenant_id=%s AND owner_id=%s",
                (actor.tenant_id, actor.user_id),
            )
    drift = await verifier.verify_batch(report["batch_id"])
    assert drift.ok is False
    assert any(
        issue["code"] == "source_verify_failed" and message in issue["detail"]["error"]
        for issue in drift.issues
    )


async def test_verify_report_covers_runtime_projection_sources_without_unknown_skip(
    tmp_path,
    migrated_pg,
    business_actors,
    pg_session_store_factory,
) -> None:
    """cron/Partners/MarginNote 已登记源必须逐域验证，不允许未知源静默通过。"""

    from deeptutor.persistence.postgres.offline_import.runtime_sqlite import (
        SQLiteRuntimeProjectionImporter,
    )
    from deeptutor.persistence.postgres.offline_import.verify_report import OfflineImportVerifier

    actor = business_actors.tenants[0].owners[0]
    await _seed_session_mapping(migrated_pg, actor, pg_session_store_factory)
    artifact = tmp_path / "runtime-artifact"
    cron_manifest = _sqlite_snapshot(
        _make_cron_source(tmp_path / "cron.sqlite3", now_ms=4_000_000),
        artifact,
        source_id="legacy-cron",
        source_version="cron_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    partner_manifest = _sqlite_snapshot(
        _make_partner_status_source(tmp_path / "partner.sqlite3"),
        artifact,
        source_id="legacy-partner-status",
        source_version="partner_runtime_status_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    marginnote_manifest = _sqlite_snapshot(
        _make_marginnote_source(tmp_path / "mn4.sqlite3"),
        artifact,
        source_id="legacy-mn4",
        source_version="marginnote_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
        source_fields={"resource_mappings": {"kb_id": "biology"}},
    )
    manifest = _write_runtime_manifest(
        artifact / "combined-runtime.json",
        [cron_manifest, partner_manifest, marginnote_manifest],
    )
    import_report = await SQLiteRuntimeProjectionImporter(
        migrated_pg.admin_dsn
    ).import_manifest(manifest, operator="unit-test")

    report = await OfflineImportVerifier(migrated_pg.admin_dsn).verify_batch(
        import_report["batch_id"]
    )

    assert report.ok is True
    assert report.domains["cron_uncertain_executions"] == {"source": 1, "target": 1}
    assert report.domains["partner_status"] == {"source": 2, "target": 2}
    assert report.domains["marginnote_tombstones"] == {"source": 1, "target": 1}

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "ALTER TABLE enterprise.marginnote_objects "
                "DROP CONSTRAINT IF EXISTS marginnote_objects_object_type_check"
            )
            await connection.execute(
                "UPDATE enterprise.marginnote_objects SET object_type='future-type' "
                "WHERE tenant_id=%s AND owner_id=%s AND kb_id='biology' "
                "AND object_id='shared-note'",
                (actor.tenant_id, actor.user_id),
            )
    drift = await OfflineImportVerifier(migrated_pg.admin_dsn).verify_batch(
        import_report["batch_id"]
    )
    assert drift.ok is False
    assert any(
        issue["code"] == "source_verify_failed" and "MarginNote" in issue["detail"]["error"]
        for issue in drift.issues
    )
