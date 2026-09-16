# ruff: noqa: F811
"""SQLite chat_history 离线导入到 PG 会话/题库域。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import psycopg
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401
from tests.persistence.postgres.business.conftest import (
    business_actors,
    business_database,
    migrated_pg,
)

pytestmark = pytest.mark.asyncio


def _make_legacy_source(path: Path, *, cycle: bool = False) -> None:
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    token = set_current_user(
        CurrentUser(
            id="legacy-user",
            username="legacy-user",
            role="user",
            scope=UserScope(kind="user", user_id="legacy-user", root=path.parent / "owner"),
        )
    )
    try:
        SQLiteSessionStore(db_path=path)
    finally:
        reset_current_user(token)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            INSERT INTO sessions(
                id,title,created_at,updated_at,compressed_summary,
                summary_up_to_msg_id,preferences_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                "legacy-session",
                "Legacy",
                10.0,
                20.0,
                "summary",
                2,
                json.dumps({"import": {"external_id": "old-url"}, "note": "message 2"}),
            ),
        )
        parents = {1: 2, 2: 1} if cycle else {1: None, 2: 1}
        for msg_id, parent in parents.items():
            connection.execute(
                """
                INSERT INTO messages(
                    id,session_id,role,content,capability,events_json,
                    attachments_json,metadata_json,created_at,parent_message_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    msg_id,
                    "legacy-session",
                    "user" if msg_id == 1 else "assistant",
                    f"message {msg_id} mentions legacy-session",
                    "chat",
                    json.dumps([{"turn_id": "turn-1", "type": "delta"}]),
                    json.dumps([]),
                    json.dumps({"source_message_id": 1} if msg_id == 2 else {}),
                    float(msg_id),
                    parent,
                ),
            )
        connection.execute(
            """
            INSERT INTO turns(
                id,session_id,capability,status,error,created_at,updated_at,
                finished_at,owner_id,fencing_token,state_version,failure_code,
                retryable,assistant_message_id
            ) VALUES(
                'turn-1','legacy-session','chat','completed','',11.0,12.0,
                13.0,'legacy-worker',7,2,'',0,2
            )
            """
        )
        connection.execute(
            """
            INSERT INTO turn_events(
                turn_id,seq,type,source,stage,content,metadata_json,timestamp,created_at
            ) VALUES('turn-1',1,'done','assistant','responding','ok',?,12.5,12.5)
            """,
            (json.dumps({"assistant_message_id": 2}),),
        )
        connection.execute(
            """
            INSERT INTO notebook_entries(
                id,session_id,turn_id,question_id,question,question_type,
                options_json,correct_answer,explanation,difficulty,user_answer,
                user_answer_images_json,source,score_trend,is_correct,resolved,
                bookmarked,created_at,updated_at
            ) VALUES(5,'legacy-session','turn-1','q1','2+2?','single',
                     '{}','4','because','easy','4','[]','deep_question',
                     'new',1,1,1,15.0,16.0)
            """
        )
        connection.execute("INSERT INTO notebook_categories(id,name,created_at) VALUES(7,'Math',14.0)")
        connection.execute(
            "INSERT INTO notebook_entry_categories(entry_id,category_id) VALUES(5,7)"
        )
        connection.execute("CREATE TABLE legacy_tokens(token text)")
        connection.execute("INSERT INTO legacy_tokens(token) VALUES('legacy-token')")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.commit()


def _snapshot(path: Path, out: Path, *, tenant_id: str, source_owner: str, target_owner: str):
    from deeptutor.persistence.postgres.offline_import import create_sqlite_source_snapshot

    return create_sqlite_source_snapshot(
        source_db=path,
        output_dir=out,
        source_id=f"source-{source_owner}",
        source_version="chat_history_sqlite/v1",
        source_owner_id=source_owner,
        target_tenant_id=tenant_id,
        owner_mappings={source_owner: target_owner},
        freeze_id=f"freeze-{source_owner}",
        stopped_writers=["web", "cli", "cron"],
        operator="unit-test",
    )


async def test_sqlite_chat_history_import_preserves_sessions_messages_turns_and_notebook(
    tmp_path: Path, migrated_pg, business_actors
) -> None:
    """生产导入若丢分支/摘要/metadata/题库/分类或导入旧 token 应失败。"""

    from deeptutor.persistence.postgres.offline_import.chat_sqlite import (
        SQLiteChatHistoryImporter,
    )

    actor = business_actors.tenants[0].owners[0]
    source = tmp_path / "chat_history.db"
    _make_legacy_source(source)
    before_hash = source.read_bytes()
    result = _snapshot(
        source,
        tmp_path / "artifact",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        auth_before = (
            await (
                await connection.execute(
                    "SELECT count(*) FROM enterprise.auth_sessions WHERE tenant_id=%s",
                    (actor.tenant_id,),
                )
            ).fetchone()
        )[0]

    report = await SQLiteChatHistoryImporter(migrated_pg.admin_dsn).import_manifest(
        result.manifest_path,
        operator="unit-test",
    )

    assert report["imported"]["sessions"] == 1
    assert report["imported"]["messages"] == 2
    assert report["imported"]["notebook_entries"] == 1
    assert source.read_bytes() == before_hash
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        session = await (
            await connection.execute(
                """
                SELECT id,title,summary,summary_up_to_msg_id,preferences
                  FROM enterprise.sessions
                 WHERE tenant_id=%s AND owner_id=%s AND title='Legacy'
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        messages = await (
            await connection.execute(
                """
                SELECT id,role,content,parent_message_id,metadata
                  FROM enterprise.messages
                 WHERE tenant_id=%s AND owner_id=%s AND session_id=%s
                 ORDER BY id
                """,
                (actor.tenant_id, actor.user_id, session[0]),
            )
        ).fetchall()
        turn = await (
            await connection.execute(
                """
                SELECT id,session_id,status,assistant_message_id,user_message_id
                  FROM enterprise.turns
                 WHERE tenant_id=%s AND user_id=%s
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        event = await (
            await connection.execute(
                """
                SELECT event
                  FROM enterprise.turn_events
                 WHERE tenant_id=%s AND owner_id=%s AND turn_id=%s
                """,
                (actor.tenant_id, actor.user_id, turn[0]),
            )
        ).fetchone()
        entry = await (
            await connection.execute(
                """
                SELECT question,user_answer,is_correct,bookmarked,turn_id
                  FROM enterprise.notebook_entries
                 WHERE tenant_id=%s AND owner_id=%s
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        category = await (
            await connection.execute(
                """
                SELECT c.name
                  FROM enterprise.notebook_categories c
                  JOIN enterprise.notebook_entry_categories ec
                    ON ec.tenant_id=c.tenant_id AND ec.owner_id=c.owner_id
                   AND ec.category_id=c.id
                 WHERE c.tenant_id=%s AND c.owner_id=%s
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        auth_after = (
            await (
                await connection.execute(
                    "SELECT count(*) FROM enterprise.auth_sessions WHERE tenant_id=%s",
                    (actor.tenant_id,),
                )
            ).fetchone()
        )[0]

    assert session[1:] == ("Legacy", "summary", messages[1][0], {"import": {"external_id": "old-url"}, "note": "message 2"})
    assert messages[0][3] is None
    assert messages[1][3] == messages[0][0]
    assert messages[1][4]["source_message_id"] == messages[0][0]
    assert turn[1:] == (session[0], "completed", messages[1][0], messages[0][0])
    assert event[0]["metadata"]["assistant_message_id"] == messages[1][0]
    assert entry == ("2+2?", "4", True, True, turn[0])
    assert category[0] == "Math"
    assert auth_after == auth_before


async def test_two_owners_with_same_legacy_ids_import_to_distinct_targets(
    tmp_path: Path, migrated_pg, business_actors
) -> None:
    from deeptutor.persistence.postgres.offline_import.chat_sqlite import (
        SQLiteChatHistoryImporter,
    )

    owner_a, owner_b = business_actors.tenants[0].owners
    importer = SQLiteChatHistoryImporter(migrated_pg.admin_dsn)
    targets = []
    for index, actor in enumerate((owner_a, owner_b), start=1):
        source = tmp_path / f"chat-{index}.db"
        _make_legacy_source(source)
        result = _snapshot(
            source,
            tmp_path / f"artifact-{index}",
            tenant_id=actor.tenant_id,
            source_owner="legacy-user",
            target_owner=actor.user_id,
        )
        await importer.import_manifest(result.manifest_path, operator="unit-test")
        async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT id FROM enterprise.sessions
                     WHERE tenant_id=%s AND owner_id=%s AND title='Legacy'
                    """,
                    (actor.tenant_id, actor.user_id),
                )
            ).fetchone()
        targets.append(row[0])
    assert targets[0] != targets[1]


async def test_bad_sqlite_references_fail_without_partial_visible_rows(
    tmp_path: Path, migrated_pg, business_actors
) -> None:
    from deeptutor.persistence.postgres.offline_import.chat_sqlite import (
        SQLiteChatHistoryImporter,
    )

    actor = business_actors.tenants[0].owners[0]
    source = tmp_path / "bad.db"
    _make_legacy_source(source, cycle=True)
    result = _snapshot(
        source,
        tmp_path / "bad-artifact",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    with pytest.raises(ValueError, match="cycle"):
        await SQLiteChatHistoryImporter(migrated_pg.admin_dsn).import_manifest(
            result.manifest_path,
            operator="unit-test",
        )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        row = await (
            await connection.execute(
                """
                SELECT count(*) FROM enterprise.sessions
                 WHERE tenant_id=%s AND owner_id=%s AND title='Legacy'
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
    assert row[0] == 0
