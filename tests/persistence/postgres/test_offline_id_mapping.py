# ruff: noqa: F811
"""离线导入 ID 映射、DAG 分配、typed JSON 引用重写。"""

from __future__ import annotations

import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401
from tests.persistence.postgres.business.conftest import (
    business_actors,
    business_database,
    migrated_pg,
)

pytestmark = pytest.mark.asyncio


async def test_text_id_mapping_is_stable_per_source_owner_and_avoids_target_collisions(
    migrated_pg, business_actors
) -> None:
    """生产映射若把两个用户同 ID 串线或重试生成不同目标 ID 应失败。"""

    import psycopg

    from deeptutor.persistence.postgres.offline_import.id_mapping import (
        MigrationIdAllocator,
        stable_text_id,
    )
    from deeptutor.persistence.postgres.offline_import.stage import MigrationStageRepository

    actor_a, actor_b = business_actors.tenants[0].owners
    repo = MigrationStageRepository(migrated_pg.admin_dsn)
    batch_id = await repo.create_batch(
        target_tenant_id=actor_a.tenant_id,
        manifest_sha256="d" * 64,
        manifest={"manifest_version": 1},
        operator="unit-test",
    )
    colliding = stable_text_id(
        domain="sessions",
        source_id="chat-db",
        source_owner_id=actor_a.user_id,
        source_key="42",
        prefix="sess",
    )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            """
            INSERT INTO enterprise.sessions(tenant_id, owner_id, id, title)
            VALUES (%s, %s, %s, 'already here')
            """,
            (actor_a.tenant_id, actor_a.user_id, colliding),
        )

    allocator = MigrationIdAllocator(migrated_pg.admin_dsn)
    mapped_a = await allocator.allocate_session_id(
        batch_id,
        tenant_id=actor_a.tenant_id,
        source_id="chat-db",
        source_owner_id=actor_a.user_id,
        source_session_id="42",
    )
    mapped_a_retry = await allocator.allocate_session_id(
        batch_id,
        tenant_id=actor_a.tenant_id,
        source_id="chat-db",
        source_owner_id=actor_a.user_id,
        source_session_id="42",
    )
    mapped_b = await allocator.allocate_session_id(
        batch_id,
        tenant_id=actor_a.tenant_id,
        source_id="chat-db",
        source_owner_id=actor_b.user_id,
        source_session_id="42",
    )

    assert mapped_a == mapped_a_retry
    assert mapped_a != colliding
    assert mapped_a != mapped_b


async def test_message_dag_allocation_rejects_bad_parents_and_advances_identity_sequence(
    migrated_pg, business_actors
) -> None:
    """生产导入若不保证 parent<child、坏引用拒绝或 sequence 推进应失败。"""

    import psycopg

    from deeptutor.persistence.postgres.offline_import.id_mapping import (
        SourceMessage,
        advance_identity_sequence,
        allocate_message_dag_ids,
    )
    from deeptutor.persistence.postgres.session import PostgresSessionStore

    actor = business_actors.tenants[0].owners[0]
    store = PostgresSessionStore(await _open_runtime_db(migrated_pg.runtime_dsn), actor.scope)
    try:
        await store.create_session(session_id="target-session")
    finally:
        await store.db.__aexit__(None, None, None)

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            """
            INSERT INTO enterprise.messages(
                tenant_id, owner_id, session_id, id, role, content
            ) OVERRIDING SYSTEM VALUE
            VALUES (%s, %s, 'target-session', 100, 'user', 'existing')
            """,
            (actor.tenant_id, actor.user_id),
        )
        mapping = allocate_message_dag_ids(
            [
                SourceMessage(source_id=20, parent_id=10, created_at=2.0),
                SourceMessage(source_id=10, parent_id=None, created_at=1.0),
                SourceMessage(source_id=30, parent_id=20, created_at=3.0),
            ],
            start_after=100,
        )
        assert mapping == {10: 101, 20: 102, 30: 103}
        await connection.execute(
            """
            INSERT INTO enterprise.messages(
                tenant_id, owner_id, session_id, id, role, content, parent_message_id
            ) OVERRIDING SYSTEM VALUE
            VALUES
              (%s, %s, 'target-session', 101, 'user', 'q', NULL),
              (%s, %s, 'target-session', 102, 'assistant', 'a', 101),
              (%s, %s, 'target-session', 103, 'user', 'next', 102)
            """,
            (
                actor.tenant_id,
                actor.user_id,
                actor.tenant_id,
                actor.user_id,
                actor.tenant_id,
                actor.user_id,
            ),
        )
        await advance_identity_sequence(connection, "enterprise.messages", "id")
        row = await (
            await connection.execute(
                """
                INSERT INTO enterprise.messages(
                    tenant_id, owner_id, session_id, role, content
                ) VALUES (%s, %s, 'target-session', 'assistant', 'new')
                RETURNING id
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
    assert row[0] > 103

    with pytest.raises(ValueError, match="missing parent"):
        allocate_message_dag_ids([SourceMessage(source_id=2, parent_id=1, created_at=1.0)])
    with pytest.raises(ValueError, match="cycle"):
        allocate_message_dag_ids(
            [
                SourceMessage(source_id=1, parent_id=2, created_at=1.0),
                SourceMessage(source_id=2, parent_id=1, created_at=2.0),
            ]
        )


async def _open_runtime_db(runtime_dsn):
    from deeptutor.persistence.postgres.connection import Database

    db = Database(runtime_dsn, resource="id-map-test")
    await db.__aenter__()
    return db


def test_typed_reference_rewriter_updates_registered_paths_without_full_text_replacement() -> None:
    """生产重写若全文替换普通文本、漏重写 typed JSON 或吞坏引用应失败。"""

    from deeptutor.persistence.postgres.offline_import.id_mapping import (
        MissingReferenceError,
        TypedReferenceRewriter,
        UnknownMachineReferenceError,
    )

    rewriter = TypedReferenceRewriter("chat_history_sqlite/v1")
    result = rewriter.rewrite(
        "messages",
        {
            "id": 1,
            "session_id": "old-session",
            "parent_message_id": 2,
            "content": "plain text mentions old-session and message 2",
            "events_json": [
                {"turn_id": "turn-1", "metadata": {"assistant_message_id": 2}},
            ],
            "attachments_json": [{"id": "file-1", "caption": "message 2 stays text"}],
            "metadata_json": {"source_message_id": 1, "note": "id 1 stays text"},
        },
        {
            "sessions.id": {"old-session": "new-session"},
            "messages.id": {1: 101, 2: 102},
            "turns.id": {"turn-1": "turn-new"},
            "resources.attachment_id": {"file-1": "resource-new"},
        },
    )

    rewritten = result.record
    assert rewritten["session_id"] == "new-session"
    assert rewritten["parent_message_id"] == 102
    assert rewritten["events_json"][0]["turn_id"] == "turn-new"
    assert rewritten["events_json"][0]["metadata"]["assistant_message_id"] == 102
    assert rewritten["attachments_json"][0]["id"] == "resource-new"
    assert rewritten["metadata_json"]["source_message_id"] == 101
    assert rewritten["content"] == "plain text mentions old-session and message 2"
    assert rewritten["attachments_json"][0]["caption"] == "message 2 stays text"

    with pytest.raises(MissingReferenceError):
        rewriter.rewrite(
            "messages",
            {"session_id": "missing", "events_json": [], "attachments_json": [], "metadata_json": {}},
            {"sessions.id": {}, "messages.id": {}, "turns.id": {}, "resources.attachment_id": {}},
        )
    with pytest.raises(UnknownMachineReferenceError):
        rewriter.rewrite(
            "messages",
            {
                "session_id": "old-session",
                "events_json": [],
                "attachments_json": [],
                "metadata_json": {"unregistered_message_id": 2},
            },
            {
                "sessions.id": {"old-session": "new-session"},
                "messages.id": {2: 102},
                "turns.id": {},
                "resources.attachment_id": {},
            },
        )


def test_old_link_report_preserves_audit_only_fields() -> None:
    from deeptutor.persistence.postgres.offline_import.id_mapping import TypedReferenceRewriter

    result = TypedReferenceRewriter("chat_history_sqlite/v1").rewrite(
        "sessions",
        {
            "id": "legacy-session",
            "summary_up_to_msg_id": 5,
            "preferences_json": {"import": {"external_id": "old-link"}},
        },
        {"messages.id": {5: 55}},
    )

    assert result.record["summary_up_to_msg_id"] == 55
    assert result.old_links == [
        {
            "path": "sessions.preferences_json.import.external_id",
            "value": "old-link",
            "target": "migration_link",
        }
    ]
