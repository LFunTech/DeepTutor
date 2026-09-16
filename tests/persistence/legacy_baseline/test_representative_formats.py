"""旧 SQLite/JSON 格式的代表行为；严禁被 PG adapter 测试导入。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
import time

import pytest


@pytest.fixture
def offline_owner(tmp_path):
    """旧源格式测试显式授权临时离线 scope，不恢复默认 local-admin。"""
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    token = set_current_user(
        CurrentUser(
            id="offline-source",
            username="offline-source",
            role="user",
            scope=UserScope(
                kind="user", user_id="offline-source", root=tmp_path / "offline-source"
            ),
        )
    )
    try:
        yield
    finally:
        reset_current_user(token)


def test_question_notebook_conflict_updates_in_place(tmp_path: Path, offline_owner) -> None:
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    store = SQLiteSessionStore(db_path=tmp_path / "chat-history.sqlite3")
    session = asyncio.run(store.create_session(session_id="legacy-session"))
    original = {
        "question_id": "q1",
        "question": "2+2?",
        "user_answer": "3",
        "correct_answer": "4",
        "is_correct": False,
    }
    assert asyncio.run(store.upsert_notebook_entries(session["id"], [original])) == 1
    first = asyncio.run(store.list_notebook_entries())["items"][0]

    changed = {**original, "user_answer": "4", "is_correct": True}
    assert asyncio.run(store.upsert_notebook_entries(session["id"], [changed])) == 1
    rows = asyncio.run(store.list_notebook_entries())
    assert rows["total"] == 1
    assert rows["items"][0]["id"] == first["id"]
    assert rows["items"][0]["user_answer"] == "4"


def test_learning_stale_snapshot_preserves_committed_progress(tmp_path: Path) -> None:
    from deeptutor.learning.models import LearningProgress
    from deeptutor.learning.storage import LearningConflictError, LearningStore

    store = LearningStore(root=tmp_path / "learning")
    store.save(LearningProgress(book_id="path-1"))
    winner = store.load("path-1")
    stale = store.load("path-1")
    assert winner is not None and stale is not None
    winner.mastery_levels["kp-winner"] = 0.8
    store.save(winner)
    stale.qualitative_mastery["kp-stale"] = True
    with pytest.raises(LearningConflictError):
        store.save(stale)
    restored = store.load("path-1")
    assert restored is not None
    assert restored.mastery_levels == {"kp-winner": 0.8}
    assert restored.qualitative_mastery == {}


def test_reading_workspace_preserves_tab_order_and_active_material(tmp_path: Path) -> None:
    from deeptutor.reading.catalog_models import IngestionStatus, SourceKind
    from deeptutor.reading.catalog_store import ReadingCatalogStore

    catalog = ReadingCatalogStore(root=tmp_path / "reading")

    def material(content: str, title: str):
        return catalog.upsert_material(
            content_id=content,
            filename=f"{title}.pdf",
            title=title,
            source_kind=SourceKind.FILE,
            mime="application/pdf",
            render_mode="pdf",
            status=IngestionStatus.READY,
        )

    one = material("1" * 16, "One")
    two = material("2" * 16, "Two")
    three = material("3" * 16, "Three")
    workspace = catalog.create_workspace("Legacy", [one.material_id, two.material_id])
    catalog.add_material(workspace.workspace_id, three.material_id, make_active=True)
    catalog.reorder_materials(
        workspace.workspace_id, [three.material_id, one.material_id, two.material_id]
    )
    restored = catalog.get_workspace(workspace.workspace_id)
    assert restored is not None
    assert restored.active_material_id == three.material_id
    assert [tab.material.material_id for tab in restored.tabs] == [
        three.material_id,
        one.material_id,
        two.material_id,
    ]


def test_cron_imports_legacy_json_once_and_archives_source(tmp_path: Path) -> None:
    from deeptutor.services.cron.service import CronService

    legacy = tmp_path / "jobs.json"
    database = tmp_path / "jobs.sqlite3"
    future = int(time.time() * 1000) + 60_000
    legacy.write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": [
                    {
                        "id": "legacy-job",
                        "name": "legacy",
                        "message": "remember",
                        "schedule": {"kind": "at", "at_ms": future},
                        "owner": {
                            "kind": "chat",
                            "user_id": "legacy-owner",
                            "session_id": "legacy-session",
                        },
                        "enabled": True,
                        "delete_after_run": True,
                        "created_at_ms": future - 1_000,
                        "state": {"next_run_at_ms": future, "run_history": []},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service = CronService(store_path=database, legacy_store_path=legacy)
    assert [job.id for job in service.list_jobs()] == ["legacy-job"]
    assert not legacy.exists()
    assert len(list(tmp_path.glob("jobs.legacy-*.json"))) == 1


def test_partner_status_redacts_channel_credentials(tmp_path: Path) -> None:
    from deeptutor.services.partners.runtime_status import PartnerRuntimeStatusRepository

    path = tmp_path / "partner-status.sqlite3"
    writer = PartnerRuntimeStatusRepository(path)
    reader = PartnerRuntimeStatusRepository(path)
    writer.set(
        "ada",
        owner_id="worker-a",
        running=True,
        state="running",
        payload={"name": "Ada", "channels": {"telegram": {"token": "secret"}}},
    )
    restored = reader.get("ada")
    assert restored is not None
    assert restored["runtime_owner_id"] == "worker-a"
    assert "channels" not in restored
    assert "secret" not in str(restored)


def test_marginnote_delete_records_tombstone_and_removes_object(tmp_path: Path) -> None:
    from deeptutor.capabilities.marginnote4.models import NOTE, MarginNoteObject, SyncBatch
    from deeptutor.capabilities.marginnote4.store import MarginNoteStore

    store = MarginNoteStore(tmp_path / "marginnote.sqlite3")
    item = MarginNoteObject(
        object_id="note-1", object_type=NOTE, title="Legacy note", device_id="device-1"
    )
    store.ingest(SyncBatch(device_id="device-1", objects=[item]))
    result = store.ingest(SyncBatch(device_id="device-1", deleted_ids=["note-1"]))
    assert result.deleted == 1
    assert store.get("note-1") is None
    with sqlite3.connect(tmp_path / "marginnote.sqlite3") as connection:
        assert connection.execute("SELECT object_id, device_id FROM mn4_tombstones").fetchall() == [
            ("note-1", "device-1")
        ]


def test_legacy_memory_sqlite_probe_ordering_fixture(tmp_path: Path) -> None:
    """Legacy SQLite fixture documents the old last-message ordering only.

    Runtime adapters now read PostgreSQL; this baseline keeps the representative
    old schema/query shape for the offline importer work without invoking the
    live adapter.
    """
    from deeptutor.services.memory.snapshot import adapters

    database = tmp_path / "chat-history.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions(id TEXT PRIMARY KEY,title TEXT,created_at REAL,updated_at REAL);
            CREATE TABLE messages(
              id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT,role TEXT,content TEXT,
              capability TEXT,created_at REAL
            );
            INSERT INTO sessions VALUES('s1','Chain rule',1000,1200);
            INSERT INTO messages VALUES(10,'s1','user','first','chat',1000);
            INSERT INTO messages VALUES(20,'s1','assistant','last','chat',1010);
            INSERT INTO messages VALUES(30,'s1','user','backfilled','chat',500);
            """
        )
        last_id = connection.execute(
            "SELECT id FROM messages WHERE session_id='s1' ORDER BY created_at DESC,id DESC LIMIT 1"
        ).fetchone()[0]
    assert adapters._sha1(last_id, 1200.0) == adapters._sha1(20, 1200.0)
