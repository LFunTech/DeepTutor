# ruff: noqa: F811
"""SQLite cron/Partners/MarginNote 离线导入到 PG 运行投影域。"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

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

pytestmark = pytest.mark.asyncio


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_combined_manifest(path: Path, manifests: list[Path]) -> Path:
    payload = _read_json(manifests[-1])
    payload["sources"] = [source for manifest in manifests for source in _read_json(manifest)["sources"]]
    return _write_json(path, payload)


def _snapshot(
    source: Path,
    out: Path,
    *,
    source_id: str,
    source_version: str,
    tenant_id: str,
    source_owner: str,
    target_owner: str,
    source_fields: dict | None = None,
) -> Path:
    from deeptutor.persistence.postgres.offline_import import create_sqlite_source_snapshot

    result = create_sqlite_source_snapshot(
        source_db=source,
        output_dir=out,
        source_id=source_id,
        source_version=source_version,
        source_owner_id=source_owner,
        target_tenant_id=tenant_id,
        owner_mappings={source_owner: target_owner},
        freeze_id=f"freeze-{source_id}",
        stopped_writers=["web", "cron", "partners", "marginnote"],
        operator="unit-test",
    )
    stable_manifest = out / f"{source_id}.manifest.json"
    payload = _read_json(result.manifest_path)
    if source_fields:
        payload["sources"][0].update(source_fields)
    return _write_json(stable_manifest, payload)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _make_cron_source(path: Path, *, now_ms: int) -> Path:
    from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule

    def payload(job: CronJob) -> dict:
        return asdict(job)

    paused = CronJob(
        id="paused-cron",
        name="早读提醒",
        message="review limits",
        schedule=CronSchedule(kind="cron", expr="15 8 * * *", tz="Asia/Shanghai"),
        owner=CronOwner(kind="chat", user_id="legacy-user", session_id="legacy-session"),
        enabled=False,
        created_at_ms=now_ms - 10_000,
    )
    paused.state.next_run_at_ms = now_ms + 3_600_000
    running = CronJob(
        id="running-every",
        name="正在派发",
        message="do not resend",
        schedule=CronSchedule(kind="every", every_seconds=60),
        owner=CronOwner(kind="chat", user_id="legacy-user", session_id="legacy-session"),
        created_at_ms=now_ms - 20_000,
    )
    running.state.next_run_at_ms = now_ms - 5_000
    running.state.last_status = "running"
    running_payload = payload(running)
    running_payload["state"]["dispatch_started_at_ms"] = now_ms - 4_000
    running_payload["state"]["worker_id"] = "legacy-worker"

    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE cron_jobs (
                id TEXT PRIMARY KEY,
                owner_key TEXT NOT NULL,
                next_run_at_ms INTEGER,
                payload TEXT NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );
            CREATE TABLE cron_meta (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                revision INTEGER NOT NULL
            );
            """
        )
        for item, updated in ((payload(paused), now_ms - 8_000), (running_payload, now_ms - 3_000)):
            connection.execute(
                """
                INSERT INTO cron_jobs(id,owner_key,next_run_at_ms,payload,updated_at_ms)
                VALUES(?,?,?,?,?)
                """,
                (
                    item["id"],
                    f"chat:{item['owner']['user_id']}",
                    item["state"].get("next_run_at_ms"),
                    json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                    updated,
                ),
            )
        connection.execute("INSERT INTO cron_meta(singleton, revision) VALUES(1, 2)")
        connection.commit()
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.commit()
    return path


def _make_partner_status_source(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE partner_runtime_status (
                partner_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                running INTEGER NOT NULL,
                state TEXT NOT NULL,
                started_at TEXT,
                last_reload_error TEXT,
                payload TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            """
        )
        rows = [
            (
                "ada",
                "legacy-user",
                1,
                "running",
                "2026-09-01T12:00:00Z",
                None,
                {"partner_id": "ada", "name": "old Ada", "channels": {"telegram": "secret"}, "runtime_worker_id": "old-worker"},
                2.0,
            ),
            (
                "legacy-only",
                "legacy-user",
                1,
                "running",
                "2026-09-01T12:00:00Z",
                None,
                {"partner_id": "legacy-only", "name": "Legacy", "channels": {"token": "secret"}},
                3.0,
            ),
        ]
        for row in rows:
            connection.execute(
                """
                INSERT INTO partner_runtime_status(
                    partner_id, owner_id, running, state, started_at,
                    last_reload_error, payload, updated_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (*row[:6], json.dumps(row[6], ensure_ascii=False, separators=(",", ":")), row[7]),
            )
        connection.commit()
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.commit()
    return path


def _make_marginnote_source(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE mn4_objects (
                object_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                object_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                excerpt TEXT,
                document_id TEXT,
                document_title TEXT,
                page INTEGER,
                tags TEXT NOT NULL DEFAULT '[]',
                links TEXT NOT NULL DEFAULT '[]',
                color TEXT,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                synced_at TEXT NOT NULL DEFAULT '',
                raw TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (object_id, device_id)
            );
            CREATE TABLE mn4_devices (
                device_id TEXT PRIMARY KEY,
                device_name TEXT NOT NULL DEFAULT '',
                device_kind TEXT NOT NULL DEFAULT 'macos',
                token_hash TEXT NOT NULL,
                paired_at TEXT NOT NULL DEFAULT '',
                last_seen TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE mn4_cursors (
                device_id TEXT PRIMARY KEY,
                cursor TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE mn4_tombstones (
                object_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                deleted_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (object_id, device_id)
            );
            """
        )
        devices = [
            ("dev-existing", "Mac", "macos", _token_hash("old-token"), "2025-01-01T00:00:00Z", "2025-01-03T00:00:00Z", 1),
            ("dev-revoked", "iPad", "ipados", _token_hash("revoked-token"), "2025-01-01T00:00:00Z", "2025-01-04T00:00:00Z", 0),
        ]
        connection.executemany(
            """
            INSERT INTO mn4_devices(device_id,device_name,device_kind,token_hash,paired_at,last_seen,active)
            VALUES(?,?,?,?,?,?,?)
            """,
            devices,
        )
        connection.executemany(
            "INSERT INTO mn4_cursors(device_id,cursor) VALUES(?,?)",
            [("dev-existing", "old-cursor"), ("dev-revoked", "revoked-cursor")],
        )
        objects = [
            (
                "shared-note",
                "dev-existing",
                "note",
                "old source title",
                "old content",
                None,
                "doc1",
                "Doc",
                1,
                ["old"],
                [],
                "yellow",
                "2025-01-01T00:00:00Z",
                "2025-01-02T00:00:00Z",
                "2025-01-02T00:00:00Z",
                {"source": "sqlite"},
            ),
            (
                "revoked-note",
                "dev-revoked",
                "note",
                "revoked device object",
                "content",
                None,
                "doc2",
                "Doc 2",
                2,
                ["revoked"],
                [],
                None,
                "2025-01-01T00:00:00Z",
                "2025-01-03T00:00:00Z",
                "2025-01-03T00:00:00Z",
                {"source": "sqlite"},
            ),
        ]
        for row in objects:
            connection.execute(
                """
                INSERT INTO mn4_objects(
                    object_id,device_id,object_type,title,content,excerpt,document_id,
                    document_title,page,tags,links,color,created_at,updated_at,synced_at,raw
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (*row[:9], json.dumps(row[9], ensure_ascii=False), json.dumps(row[10], ensure_ascii=False), *row[11:15], json.dumps(row[15], ensure_ascii=False)),
            )
        connection.execute(
            "INSERT INTO mn4_tombstones(object_id,device_id,deleted_at) VALUES(?,?,?)",
            ("deleted-note", "dev-revoked", "2025-01-05T00:00:00Z"),
        )
        connection.commit()
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.commit()
    return path


async def _seed_session_mapping(migrated_pg, actor, pg_session_store_factory) -> None:
    sessions = pg_session_store_factory(actor)
    await sessions.create_session("Cron target", session_id="target-session")
    batch_id = str(uuid.uuid4())
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                """
                INSERT INTO migration_stage.batches(
                    batch_id,target_tenant_id,manifest_sha256,source_manifest,status,operator
                ) VALUES (%s,%s,%s,'{}'::jsonb,'published','unit-test')
                """,
                (batch_id, actor.tenant_id, "c" * 64),
            )
            await connection.execute(
                """
                INSERT INTO migration_stage.sources(
                    batch_id,source_id,source_type,source_version,source_owner_id,
                    target_owner_id,fingerprint,status,rows_total,rows_done
                ) VALUES (%s,'legacy-chat','sqlite','chat_history_sqlite/v1','legacy-user',%s,%s,'verified',1,1)
                """,
                (batch_id, actor.user_id, "d" * 64),
            )
            await connection.execute(
                """
                INSERT INTO migration_stage.id_mappings(
                    batch_id,domain,source_id,source_owner_id,source_key,target_key
                ) VALUES (%s,'sessions','legacy-chat','legacy-user','legacy-session','target-session')
                """,
                (batch_id,),
            )


async def _seed_target_newer_rows(migrated_pg, actor) -> None:
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                """
                INSERT INTO enterprise.partner_runtime_status(
                    tenant_id,owner_id,partner_id,worker_id,version,running,state,
                    started_at,last_reload_error,payload,updated_at_ms,expires_at_ms,ttl_ms
                ) VALUES (%s,%s,'ada','target-worker',7,true,'running',NULL,NULL,
                          %s::jsonb,15000,20000,5000)
                """,
                (actor.tenant_id, actor.user_id, json.dumps({"name": "target Ada"})),
            )
            await connection.execute(
                """
                INSERT INTO enterprise.marginnote_devices(
                    tenant_id,owner_id,kb_id,device_id,device_name,device_kind,
                    token_hash,paired_at,last_seen,active
                ) VALUES (%s,%s,'biology','dev-existing','Target Mac','macos',%s,
                          '2099-01-01T00:00:00Z','2099-01-02T00:00:00Z',true)
                """,
                (actor.tenant_id, actor.user_id, _token_hash("target-token")),
            )
            await connection.execute(
                """
                INSERT INTO enterprise.marginnote_cursors(
                    tenant_id,owner_id,kb_id,device_id,cursor,updated_at
                ) VALUES (%s,%s,'biology','dev-existing','target-cursor','2099-01-02T00:00:00Z')
                """,
                (actor.tenant_id, actor.user_id),
            )
            await connection.execute(
                """
                INSERT INTO enterprise.marginnote_objects(
                    tenant_id,owner_id,kb_id,device_id,object_id,object_type,title,content,
                    tags,links,created_at,updated_at,synced_at,raw
                ) VALUES (%s,%s,'biology','dev-existing','shared-note','note','fresh target',
                          'target content','[]'::jsonb,'[]'::jsonb,'2099-01-01T00:00:00Z',
                          '2099-01-02T00:00:00Z','2099-01-02T00:00:00Z','{}'::jsonb)
                """,
                (actor.tenant_id, actor.user_id),
            )


async def test_runtime_projection_import_preserves_safe_state_and_skips_newer_target_updates(
    tmp_path: Path,
    migrated_pg,
    business_actors,
    business_database,
    business_sync_database,
    pg_scope_factory,
    pg_session_store_factory,
) -> None:
    """生产导入若重发运行中 cron、复活撤销设备或覆盖目标新更新应失败。"""

    from deeptutor.persistence.postgres.cron import AsyncPostgresCronRepository
    from deeptutor.persistence.postgres.marginnote import PostgresMarginNoteStore
    from deeptutor.persistence.postgres.offline_import.runtime_sqlite import (
        SQLiteRuntimeProjectionImporter,
    )
    from deeptutor.persistence.postgres.partner_runtime_status import (
        PostgresPartnerRuntimeStatusRepository,
    )

    actor = business_actors.tenants[0].owners[0]
    await _seed_session_mapping(migrated_pg, actor, pg_session_store_factory)
    await _seed_target_newer_rows(migrated_pg, actor)

    artifact = tmp_path / "artifact"
    now_ms = 4_000_000
    cron_manifest = _snapshot(
        _make_cron_source(tmp_path / "cron.sqlite3", now_ms=now_ms),
        artifact,
        source_id="legacy-cron",
        source_version="cron_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    partner_manifest = _snapshot(
        _make_partner_status_source(tmp_path / "partner.sqlite3"),
        artifact,
        source_id="legacy-partner-status",
        source_version="partner_runtime_status_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    marginnote_manifest = _snapshot(
        _make_marginnote_source(tmp_path / "mn4.sqlite3"),
        artifact,
        source_id="legacy-mn4",
        source_version="marginnote_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
        source_fields={"resource_mappings": {"kb_id": "biology"}},
    )
    manifest = _write_combined_manifest(
        artifact / "combined-runtime.json", [cron_manifest, partner_manifest, marginnote_manifest]
    )

    report = await SQLiteRuntimeProjectionImporter(migrated_pg.admin_dsn).import_manifest(
        manifest, operator="unit-test"
    )

    assert report["imported"]["cron_jobs"] == 2
    assert report["imported"]["cron_uncertain_executions"] == 1
    assert report["imported"]["partner_status"] == 1
    assert report["imported"]["marginnote_devices"] == 1
    assert report["imported"]["marginnote_objects"] == 1
    assert report["skipped_newer_target"] >= 3

    async with await psycopg.AsyncConnection.connect(
        migrated_pg.admin_dsn, row_factory=psycopg.rows.dict_row
    ) as connection:
        paused = await (
            await connection.execute(
                """
                SELECT enabled,schedule_kind,cron_expr,tz,payload
                  FROM enterprise.cron_jobs
                 WHERE tenant_id=%s AND owner_id=%s AND job_id='paused-cron'
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        running = await (
            await connection.execute(
                """
                SELECT next_run_at_ms,last_status,payload
                  FROM enterprise.cron_jobs
                 WHERE tenant_id=%s AND owner_id=%s AND job_id='running-every'
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        executions = await (
            await connection.execute(
                """
                SELECT status,worker_id
                  FROM enterprise.cron_executions
                 WHERE tenant_id=%s AND owner_id=%s AND job_id='running-every'
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchall()
        mn_rows = await (
            await connection.execute(
                """
                SELECT d.device_id,d.active,c.cursor,o.object_id,o.title,o.updated_at
                  FROM enterprise.marginnote_devices d
                  LEFT JOIN enterprise.marginnote_cursors c USING (tenant_id,owner_id,kb_id,device_id)
                  LEFT JOIN enterprise.marginnote_objects o USING (tenant_id,owner_id,kb_id,device_id)
                 WHERE d.tenant_id=%s AND d.owner_id=%s AND d.kb_id='biology'
                 ORDER BY d.device_id,o.object_id
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchall()
        tombstone = await (
            await connection.execute(
                """
                SELECT deleted_at
                  FROM enterprise.marginnote_tombstones
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id='biology'
                   AND device_id='dev-revoked' AND object_id='deleted-note'
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()

    assert (
        paused["enabled"],
        paused["schedule_kind"],
        paused["cron_expr"],
        paused["tz"],
    ) == (False, "cron", "15 8 * * *", "Asia/Shanghai")
    assert paused["payload"]["owner"]["user_id"] == actor.user_id
    assert paused["payload"]["owner"]["session_id"] == "target-session"
    assert running["next_run_at_ms"] is None
    assert running["last_status"] == "uncertain"
    assert running["payload"]["state"]["next_run_at_ms"] is None
    assert [(row["status"], row["worker_id"]) for row in executions] == [("uncertain", "legacy-worker")]

    cron_repo = AsyncPostgresCronRepository(business_sync_database, pg_scope_factory(actor))
    assert await cron_repo.run(lambda repo: repo.claim_due(now_ms + 86_400_000, worker_id="verifier", limit=10)) == []

    partner_repo = PostgresPartnerRuntimeStatusRepository(
        business_sync_database,
        tenant_id=actor.tenant_id,
        worker_id="reader",
        clock=lambda: 15.0,
    )
    target_status = partner_repo.get("ada", owner_id=actor.user_id)
    legacy_status = partner_repo.get("legacy-only", owner_id=actor.user_id)
    assert target_status["runtime_worker_id"] == "target-worker"
    assert target_status["runtime_version"] == 7
    assert legacy_status["runtime_expired"] is True
    assert legacy_status["running"] is False
    assert "channels" not in legacy_status

    mn_by_device = {row["device_id"]: row for row in mn_rows}
    assert mn_by_device["dev-existing"]["cursor"] == "target-cursor"
    assert mn_by_device["dev-existing"]["title"] == "fresh target"
    assert mn_by_device["dev-existing"]["updated_at"] == "2099-01-02T00:00:00Z"
    assert mn_by_device["dev-revoked"]["active"] is False
    assert mn_by_device["dev-revoked"]["cursor"] == "revoked-cursor"
    assert mn_by_device["dev-revoked"]["title"] == "revoked device object"
    assert tombstone["deleted_at"] == "2025-01-05T00:00:00Z"

    store = PostgresMarginNoteStore(business_sync_database, actor.scope, kb_id="biology")
    assert store.verify_token("dev-revoked", "revoked-token") is False
    assert store.get("shared-note", device_id="dev-existing").title == "fresh target"
