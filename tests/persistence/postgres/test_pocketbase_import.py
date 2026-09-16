# ruff: noqa: F811
"""PocketBase 离线 snapshot 导入到 PG。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import psycopg
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401
from tests.persistence.postgres.business.conftest import (  # noqa: F401
    business_actors,
    business_database,
    migrated_pg,
)
from tests.persistence.postgres.test_pocketbase_export import _SCHEMA, _FakePocketBase

pytestmark = pytest.mark.asyncio


def _records(*, bad_message_session: bool = False) -> dict[str, list[dict[str, Any]]]:
    session_id = "missing" if bad_message_session else "s1"
    return {
        "users": [
            {
                "id": "pb-user-1",
                "email": "learner@example.org",
                "username": "learner",
                "name": "Learner",
                "role": "user",
                "tokenKey": "PB_USER_TOKEN_SECRET",
                "created": "2026-01-01 00:00:00Z",
                "updated": "2026-01-02 00:00:00Z",
            }
        ],
        "sessions": [
            {
                "id": "pb-session-row-1",
                "session_id": "s1",
                "user_id": "pb-user-1",
                "title": "PocketBase Algebra",
                "compressed_summary": "summary",
                "summary_up_to_msg_id": 0,
                "preferences_json": {"layout": "default"},
                "capability": "chat",
                "status": "idle",
                "session_created_at": 10.0,
                "session_updated_at": 20.0,
            }
        ],
        "messages": [
            {
                "id": "pb-msg-a",
                "session_id": session_id,
                "role": "user",
                "content": "hello",
                "capability": "chat",
                "events_json": [],
                "attachments_json": [{"id": "att-1", "name": "diagram.png"}],
                "metadata_json": {"source": "pb"},
                "msg_created_at": 11.0,
            },
            {
                "id": "pb-msg-b",
                "session_id": "s1",
                "role": "assistant",
                "content": "hi",
                "capability": "chat",
                "events_json": [],
                "attachments_json": [],
                "metadata_json": {"message_id": "pb-msg-a"},
                "msg_created_at": 12.0,
            },
        ],
        "turns": [
            {
                "id": "pb-turn-row-1",
                "turn_id": "t1",
                "session_id": "s1",
                "capability": "chat",
                "status": "completed",
                "error": "",
                "failure_code": "",
                "retryable": False,
                "owner_id": "pb-worker",
                "fencing_token": 3,
                "state_version": 2,
                "turn_created_at": 11.0,
                "turn_updated_at": 13.0,
                "finished_at": 13.0,
                "assistant_message_id": "pb-msg-b",
            }
        ],
        "turn_events": [
            {
                "id": "pb-event-row-1",
                "turn_id": "t1",
                "session_id": "s1",
                "seq": 1,
                "type": "text_delta",
                "source": "assistant",
                "stage": "responding",
                "content": "hi",
                "metadata_json": {"message_id": "pb-msg-b"},
                "event_timestamp": 12.5,
            }
        ],
        "knowledge_bases": [
            {
                "id": "pb-kb-row-1",
                "kb_name": "math",
                "user_id": "pb-user-1",
                "description": "Math KB",
                "rag_provider": "lightrag",
                "needs_reindex": False,
                "status": "ready",
                "kb_created_at": "2026-01-01T00:00:00Z",
                "raw_files": ["intro.pdf"],
            }
        ],
    }


def _pocketbase_manifest(tmp_path: Path, actor, *, bad_message_session: bool = False) -> Path:
    from deeptutor.persistence.postgres.offline_import.pocketbase_export import (
        create_pocketbase_source_export,
    )

    result = create_pocketbase_source_export(
        pb_client=_FakePocketBase(_records(bad_message_session=bad_message_session), _SCHEMA),
        source_endpoint="https://admin:PB_ADMIN_PASSWORD@example.org?token=PB_TOKEN",
        output_dir=tmp_path,
        source_id="pb-main",
        source_owner_id="pb-user-1",
        target_tenant_id=actor.tenant_id,
        owner_mappings={"pb-user-1": actor.user_id},
        freeze_id="freeze-pb",
        stopped_writers=["web", "api", "pocketbase"],
        operator="unit-test",
        page_size=1,
    )
    return result.manifest_path


def _empty_chat_sqlite_snapshot(path: Path, out: Path, actor) -> dict:
    from deeptutor.persistence.postgres.offline_import import create_sqlite_source_snapshot

    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE sessions(id TEXT, title TEXT, created_at REAL, updated_at REAL, compressed_summary TEXT, summary_up_to_msg_id INTEGER, preferences_json TEXT)"
        )
        connection.execute(
            "CREATE TABLE messages(id INTEGER, session_id TEXT, role TEXT, content TEXT, capability TEXT, events_json TEXT, attachments_json TEXT, metadata_json TEXT, created_at REAL, parent_message_id INTEGER)"
        )
        connection.execute(
            "CREATE TABLE turns(id TEXT, session_id TEXT, capability TEXT, status TEXT, error TEXT, created_at REAL, updated_at REAL, finished_at REAL, owner_id TEXT, fencing_token INTEGER, state_version INTEGER, failure_code TEXT, retryable INTEGER, assistant_message_id INTEGER, user_message_id INTEGER)"
        )
        connection.execute(
            "CREATE TABLE turn_events(turn_id TEXT, seq INTEGER, type TEXT, source TEXT, stage TEXT, content TEXT, metadata_json TEXT, timestamp REAL, created_at REAL)"
        )
        connection.execute(
            "CREATE TABLE notebook_entries(id INTEGER, session_id TEXT, turn_id TEXT, question_id TEXT, question TEXT, question_type TEXT, options_json TEXT, correct_answer TEXT, explanation TEXT, difficulty TEXT, user_answer TEXT, user_answer_images_json TEXT, source TEXT, material_id TEXT, material_title TEXT, section_id TEXT, section_title TEXT, score_trend TEXT, is_correct INTEGER, resolved INTEGER, bookmarked INTEGER, followup_session_id TEXT, ai_judgment TEXT, created_at REAL, updated_at REAL)"
        )
        connection.execute("CREATE TABLE notebook_categories(id INTEGER, name TEXT, created_at REAL)")
        connection.execute("CREATE TABLE notebook_entry_categories(entry_id INTEGER, category_id INTEGER)")
        connection.commit()
    result = create_sqlite_source_snapshot(
        source_db=path,
        output_dir=out,
        source_id="empty-sqlite",
        source_version="chat_history_sqlite/v1",
        source_owner_id="legacy-user",
        target_tenant_id=actor.tenant_id,
        owner_mappings={"legacy-user": actor.user_id},
        freeze_id="freeze-sqlite",
        stopped_writers=["web"],
        operator="unit-test",
    )
    return json.loads(result.manifest_path.read_text(encoding="utf-8"))["sources"][0]


def _combine_with_sqlite_source(pb_manifest: Path, sqlite_source: dict) -> Path:
    payload = json.loads(pb_manifest.read_text(encoding="utf-8"))
    payload["sources"].append(sqlite_source)
    payload["owner_mappings"].append(
        {"source_owner_id": "legacy-user", "target_owner_id": payload["owner_mappings"][0]["target_owner_id"]}
    )
    combined = pb_manifest.with_name("combined-pocketbase-sqlite.manifest.json")
    combined.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return combined


async def test_pocketbase_import_maps_users_resets_credentials_and_preserves_chat_refs(
    tmp_path: Path,
    migrated_pg,
    business_actors,
) -> None:
    """生产导入若导入旧凭证、丢消息/turn 引用或文件引用应失败。"""

    from deeptutor.persistence.postgres.offline_import.pocketbase_import import (
        PocketBaseOfflineImporter,
    )

    actor = business_actors.tenants[0].owners[0]
    manifest = _pocketbase_manifest(tmp_path / "pb", actor)
    async with await psycopg.AsyncConnection.connect(
        migrated_pg.admin_dsn, row_factory=psycopg.rows.dict_row
    ) as connection:
        auth_before = await (
            await connection.execute(
                "SELECT auth_version FROM enterprise.users WHERE tenant_id=%s AND id=%s",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()

    report = await PocketBaseOfflineImporter(migrated_pg.admin_dsn).import_manifest(
        manifest,
        operator="unit-test",
    )

    assert report["imported"] == {
        "users": 1,
        "sessions": 1,
        "messages": 2,
        "turns": 1,
        "turn_events": 1,
        "knowledge_base_file_refs": 1,
    }
    assert report["credential_resets_required"] == [
        {"source_user_id": "pb-user-1", "target_owner_id": actor.user_id}
    ]

    async with await psycopg.AsyncConnection.connect(
        migrated_pg.admin_dsn, row_factory=psycopg.rows.dict_row
    ) as connection:
        auth_after = await (
            await connection.execute(
                "SELECT auth_version FROM enterprise.users WHERE tenant_id=%s AND id=%s",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        session = await (
            await connection.execute(
                "SELECT id,title,summary,summary_up_to_msg_id,preferences FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s AND title='PocketBase Algebra'",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        messages = await (
            await connection.execute(
                "SELECT id,role,content,attachments,metadata FROM enterprise.messages WHERE tenant_id=%s AND owner_id=%s AND session_id=%s ORDER BY id",
                (actor.tenant_id, actor.user_id, session["id"]),
            )
        ).fetchall()
        turn = await (
            await connection.execute(
                "SELECT id,status,assistant_message_id,user_message_id,owner_id,fencing_token,state_version FROM enterprise.turns WHERE tenant_id=%s AND user_id=%s AND session_id=%s",
                (actor.tenant_id, actor.user_id, session["id"]),
            )
        ).fetchone()
        event = await (
            await connection.execute(
                "SELECT event FROM enterprise.turn_events WHERE tenant_id=%s AND owner_id=%s AND turn_id=%s AND seq=1",
                (actor.tenant_id, actor.user_id, turn["id"]),
            )
        ).fetchone()
        mappings = await (
            await connection.execute(
                "SELECT domain,source_key,target_key,target_int,metadata FROM migration_stage.id_mappings WHERE batch_id=%s ORDER BY domain,source_key",
                (report["batch_id"],),
            )
        ).fetchall()
        leaked = await (
            await connection.execute(
                "SELECT count(*) AS n FROM enterprise.local_credentials WHERE tenant_id=%s AND password_hash LIKE '%%PB_USER_TOKEN_SECRET%%'",
                (actor.tenant_id,),
            )
        ).fetchone()

    assert int(auth_after["auth_version"]) == int(auth_before["auth_version"]) + 1
    assert session["summary"] == "summary"
    assert session["preferences"] == {"layout": "default"}
    assert messages[0]["content"] == "hello"
    assert messages[0]["attachments"][0]["id"] != "att-1"
    assert messages[1]["metadata"]["message_id"] == messages[0]["id"]
    assert turn["assistant_message_id"] == messages[1]["id"]
    assert turn["user_message_id"] == messages[0]["id"]
    assert turn["owner_id"] == "pb-worker"
    assert turn["fencing_token"] == 3
    assert turn["state_version"] == 2
    assert event["event"]["metadata"]["message_id"] == messages[1]["id"]
    assert any(
        row["domain"] == "pocketbase_users"
        and row["source_key"] == "pb-user-1"
        and row["target_key"] == actor.user_id
        and row["metadata"]["credential_reset_required"] is True
        for row in mappings
    )
    assert any(
        row["domain"] == "knowledge_base_file_refs"
        and row["source_key"] == "math/raw_files/intro.pdf"
        for row in mappings
    )
    assert leaked["n"] == 0


async def test_pocketbase_import_is_idempotent_and_accepts_manifest_with_sqlite_source(
    tmp_path: Path,
    migrated_pg,
    business_actors,
) -> None:
    """重复导入或 manifest 同时含 SQLite 来源若制造重复/冲突应失败。"""

    from deeptutor.persistence.postgres.offline_import.pocketbase_import import (
        PocketBaseOfflineImporter,
    )

    actor = business_actors.tenants[0].owners[0]
    pb_manifest = _pocketbase_manifest(tmp_path / "pb-idempotent", actor)
    sqlite_source = _empty_chat_sqlite_snapshot(
        tmp_path / "empty-chat.sqlite3",
        pb_manifest.parent,
        actor,
    )
    manifest = _combine_with_sqlite_source(pb_manifest, sqlite_source)
    importer = PocketBaseOfflineImporter(migrated_pg.admin_dsn)

    first = await importer.import_manifest(manifest, operator="unit-test")
    second = await importer.import_manifest(manifest, operator="unit-test-replay")

    assert first["imported"]["sessions"] == 1
    assert second["deduped_sources"] == 1
    assert second["imported"] == {
        "users": 0,
        "sessions": 0,
        "messages": 0,
        "turns": 0,
        "turn_events": 0,
        "knowledge_base_file_refs": 0,
    }
    async with await psycopg.AsyncConnection.connect(
        migrated_pg.admin_dsn, row_factory=psycopg.rows.dict_row
    ) as connection:
        counts = await (
            await connection.execute(
                "SELECT count(*) AS sessions FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s AND title='PocketBase Algebra'",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        source_rows = await (
            await connection.execute(
                "SELECT source_version,status FROM migration_stage.sources WHERE batch_id=%s ORDER BY source_version",
                (first["batch_id"],),
            )
        ).fetchall()
    assert counts["sessions"] == 1
    assert [row["source_version"] for row in source_rows] == ["pocketbase/v1"]


async def test_pocketbase_import_rejects_bad_session_reference(
    tmp_path: Path,
    migrated_pg,
    business_actors,
) -> None:
    """坏 message→session 引用若被静默跳过应失败。"""

    from deeptutor.persistence.postgres.offline_import.pocketbase_import import (
        PocketBaseOfflineImporter,
    )

    actor = business_actors.tenants[0].owners[0]
    manifest = _pocketbase_manifest(tmp_path / "pb-bad", actor, bad_message_session=True)

    with pytest.raises(ValueError, match="missing mapping"):
        await PocketBaseOfflineImporter(migrated_pg.admin_dsn).import_manifest(
            manifest,
            operator="unit-test",
        )
