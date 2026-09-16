from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.core.providers import ApplicationProviders, provider_context
from deeptutor.multi_user.context import (
    reset_current_user,
    set_current_user,
    user_from_token_payload,
)
from deeptutor.persistence.postgres.scope import TenantScope
from deeptutor.persistence.postgres.session import PostgresSessionStore
from deeptutor.services.memory.snapshot import adapters

pytestmark = pytest.mark.asyncio


class _Runtime:
    def __init__(self, sync_db, tenant_id: str) -> None:
        self.sync_db = sync_db
        self.config = SimpleNamespace(tenant_id=tenant_id)

    def scope_for_current_user(self):
        from deeptutor.multi_user.context import get_current_user

        user = get_current_user()
        return TenantScope(user.scope.tenant_id, user.id)


class _Container:
    def __init__(self, runtime: _Runtime) -> None:
        self.postgres_runtime = runtime


async def test_memory_chat_quiz_snapshot_and_probe_read_pg_without_sqlite(
    monkeypatch,
    business_database,
    business_sync_database,
    business_actors,
) -> None:
    actor, other = business_actors.tenants[0].owners
    store = PostgresSessionStore(business_database, actor.scope)
    other_store = PostgresSessionStore(business_database, other.scope)

    await store.create_session("Chain rule", session_id="mem-s1")
    first_id = await store.add_message("mem-s1", "user", "asked first")
    last_id = await store.add_message("mem-s1", "assistant", "answered last")
    backfill_id = await store.add_message("mem-s1", "user", "backfilled")
    await other_store.create_session("Other user", session_id="mem-other")
    await other_store.add_message("mem-other", "user", "other private chat")

    await store.upsert_notebook_entries(
        "mem-s1",
        [
            {
                "question_id": "q1",
                "question": "What is the derivative of x^2?",
                "turn_id": "book-block-1",
                "source": "book",
                "correct_answer": "2x",
                "user_answer": "x",
                "is_correct": False,
            }
        ],
    )
    entry = await store.find_notebook_entry("mem-s1", "q1", turn_id="book-block-1")
    assert entry is not None
    assert await store.update_notebook_entry(int(entry["id"]), {"bookmarked": True}) is True

    async with business_database.transaction(actor.scope) as connection:
        await connection.execute(
            "UPDATE enterprise.sessions SET updated_at=%s WHERE tenant_id=%s AND owner_id=%s AND id=%s",
            (1200.0, actor.tenant_id, actor.user_id, "mem-s1"),
        )
        await connection.execute(
            "UPDATE enterprise.messages SET created_at=%s WHERE tenant_id=%s AND owner_id=%s AND id=%s",
            (1000.0, actor.tenant_id, actor.user_id, first_id),
        )
        await connection.execute(
            "UPDATE enterprise.messages SET created_at=%s WHERE tenant_id=%s AND owner_id=%s AND id=%s",
            (1010.0, actor.tenant_id, actor.user_id, last_id),
        )
        await connection.execute(
            "UPDATE enterprise.messages SET created_at=%s WHERE tenant_id=%s AND owner_id=%s AND id=%s",
            (500.0, actor.tenant_id, actor.user_id, backfill_id),
        )

    monkeypatch.setattr(adapters, "_PG_SNAPSHOT_PAGE_SIZE", 1)

    def _forbid_sqlite_path():
        raise AssertionError("Memory snapshot must read PostgreSQL, not chat_history.db")

    monkeypatch.setattr(adapters, "get_path_service", _forbid_sqlite_path)

    token = set_current_user(user_from_token_payload(actor.identity))
    try:
        runtime = _Runtime(business_sync_database, actor.tenant_id)
        with provider_context(ApplicationProviders(container=_Container(runtime))):
            full = adapters.read_chat_entities()
            probed = adapters.probe_chat_entities()
            quiz = adapters.read_quiz_entities()

            assert [(row.id, row.label, row.fingerprint) for row in probed] == [
                (row.id, row.label, row.fingerprint) for row in full
            ]
            assert [entity.id for entity in full] == ["mem-s1"]
            assert "answered last" in full[0].content
            assert "other private chat" not in full[0].content
            assert probed[0].fingerprint == adapters._sha1(last_id, 1200.0)
            assert probed[0].fingerprint != adapters._sha1(backfill_id, 1200.0)

            assert [entity.id for entity in quiz] == ["mem-s1:q1"]
            assert quiz[0].metadata["bookmarked"] is True
            assert "What is the derivative" in quiz[0].content

            assert await store.delete_notebook_entry(int(entry["id"])) is True
            assert adapters.read_quiz_entities() == []
    finally:
        reset_current_user(token)
