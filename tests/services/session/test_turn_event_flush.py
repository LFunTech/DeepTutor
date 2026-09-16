"""Post-stream turn-event flush against the PG-only session store."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.turn_runtime import TurnRuntimeManager, _TurnExecution
from tests.services.session.pg_helpers import pg_session_runtime

pytestmark = pytest.mark.asyncio


def _buffered(session_id: str, turn_id: str, count: int) -> list[dict]:
    return [
        {
            "type": "content",
            "source": "chat",
            "stage": "",
            "content": f"chunk-{i}",
            "metadata": {},
            "session_id": session_id,
            "turn_id": turn_id,
            "seq": i + 1,
            "timestamp": 1000.0 + i,
        }
        for i in range(count)
    ]


async def _execution(store, *, count: int):
    session = await store.ensure_session(None)
    turn = await store.begin_turn(session["id"], capability="chat")
    execution = _TurnExecution(
        turn_id=turn["id"],
        session_id=session["id"],
        capability="chat",
        payload={},
    )
    execution.events = _buffered(session["id"], turn["id"], count)
    return session, turn, execution


async def test_flush_persists_the_whole_batch_once(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="flush-batch") as runtime:
        store = runtime.store()
        manager = TurnRuntimeManager(store)
        _session, turn, execution = await _execution(store, count=5)

        await manager._flush_buffered_events(execution)

        persisted = await store.get_turn_events(turn["id"])
    assert [event["content"] for event in persisted] == [f"chunk-{i}" for i in range(5)]


async def test_flush_is_idempotent_per_execution(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="flush-idempotent") as runtime:
        store = runtime.store()
        manager = TurnRuntimeManager(store)
        _session, turn, execution = await _execution(store, count=3)

        await manager._flush_buffered_events(execution)
        await manager._flush_buffered_events(execution)

        persisted = await store.get_turn_events(turn["id"])
    assert len(persisted) == 3


async def test_concurrent_flush_callers_share_one_persistence_attempt(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="flush-concurrent") as runtime:
        store = runtime.store()
        manager = TurnRuntimeManager(store)
        _session, turn, execution = await _execution(store, count=4)

        await asyncio.gather(
            manager._flush_buffered_events(execution),
            manager._flush_buffered_events(execution),
        )

        persisted = await store.get_turn_events(turn["id"])
    assert len(persisted) == 4


async def test_non_batch_flush_retry_continues_after_committed_prefix(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="flush-prefix-retry") as runtime:
        store = runtime.store()
        _session, turn, execution = await _execution(store, count=3)

        class SingleEventStore:
            append_events = None
            append_turn_events = None

            def __init__(self, wrapped) -> None:
                self._wrapped = wrapped
                self.store_scope = wrapped.store_scope
                self._calls = 0

            def __getattr__(self, name):
                return getattr(self._wrapped, name)

            async def append_turn_event(self, turn_id, payload):
                self._calls += 1
                if self._calls == 2:
                    raise RuntimeError("transient persistence failure")
                return await self._wrapped.append_turn_event(turn_id, payload)

        manager = TurnRuntimeManager(SingleEventStore(store))

        with pytest.raises(RuntimeError, match="transient persistence failure"):
            await manager._flush_buffered_events(execution)
        await manager._flush_buffered_events(execution)

        persisted = await store.get_turn_events(turn["id"])
    assert [event["content"] for event in persisted] == ["chunk-0", "chunk-1", "chunk-2"]


async def test_pg_delete_refuses_active_turn_before_flush_and_preserves_runtime_state(
    pg_dsn: str,
) -> None:
    """PG cutover rejects deleting active executions instead of racing a flush."""

    async with pg_session_runtime(pg_dsn, resource="flush-active-delete") as runtime:
        store = runtime.store()
        manager = TurnRuntimeManager(store)
        session, turn, execution = await _execution(store, count=2)

        with pytest.raises(RuntimeError, match="active execution"):
            await store.delete_session(session["id"])

        await manager._flush_buffered_events(execution)
        persisted = await store.get_turn_events(turn["id"])

    assert [event["content"] for event in persisted] == ["chunk-0", "chunk-1"]


async def test_pg_append_turn_events_returns_durable_sequences(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="flush-durable-seq") as runtime:
        store = runtime.store()
        session = await store.create_session(title="t", session_id="s_flush")
        turn = await store.create_turn(session["id"], capability="chat")
        events = _buffered(session["id"], turn["id"], 4)

        persisted = await store.append_turn_events(turn["id"], events)
        rows = await store.get_turn_events(turn["id"])

    assert [payload["seq"] for payload in persisted] == [1, 2, 3, 4]
    assert [row["seq"] for row in rows] == [1, 2, 3, 4]


async def test_pg_append_turn_event_single_delegates_to_batch(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="flush-single") as runtime:
        store = runtime.store()
        session = await store.create_session(title="t", session_id="s_single")
        turn = await store.create_turn(session["id"], capability="chat")

        payload = await store.append_turn_event(turn["id"], {"type": "content", "content": "x"})
        rows = await store.get_turn_events(turn["id"])

    assert payload["turn_id"] == turn["id"]
    assert payload["seq"] == 1
    assert len(rows) == 1


async def test_pg_update_turn_status_no_longer_flushes_events(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="flush-status") as runtime:
        store = runtime.store()
        session = await store.create_session(title="t", session_id="s_status")
        turn = await store.create_turn(session["id"], capability="chat")

        assert await store.update_turn_status(turn["id"], "completed") is True
        assert await store.get_turn_events(turn["id"]) == []


async def test_pg_finalize_turn_preserves_assistant_attachments(
    pg_dsn: str, tmp_path
) -> None:
    from deeptutor.persistence.postgres.session_resources import PostgresAttachmentStore
    from deeptutor.persistence.resources import OwnerResourceProvider

    async with pg_session_runtime(pg_dsn, resource="finalize-attachments") as runtime:
        store = runtime.store()
        session = await store.create_session(title="t", session_id="s_finalize_files")
        files = PostgresAttachmentStore(store, OwnerResourceProvider(tmp_path.absolute()))
        attachment_url = await files.put(
            session_id=session["id"],
            attachment_id="generated",
            filename="generated.txt",
            data=b"generated bytes",
        )
        user_message_id = await store.add_message(session["id"], "user", "make a file")
        turn = await store.create_turn(session["id"], capability="chat")

        await store.finalize_turn(
            turn["id"],
            status="completed",
            content="created",
            capability="chat",
            parent_message_id=user_message_id,
            user_message_id=user_message_id,
            attachments=[
                {
                    "url": attachment_url,
                    "filename": "generated.txt",
                }
            ],
        )
        messages = await store.get_messages(session["id"])

    assert messages[-1]["attachments"][0]["filename"] == "generated.txt"
    assert messages[-1]["attachments"][0]["url"] == attachment_url


async def test_pg_legacy_runtime_commits_done_through_finalize_turn(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """旧执行器在 PG store 上也必须用 finalize_turn 提交 done。

    如果回退到 ``append_events(... done ...)``，PostgreSQL store 会拒绝并让
    浏览器看到 “done must be committed through finalize_turn”。
    """

    async def _noop_async(*_args, **_kwargs):
        return None

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **_kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, _context):
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="PG legacy answer",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder",
        FakeContextBuilder,
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_l3_concat=lambda: "", emit=_noop_async),
    )
    monkeypatch.setattr(
        "deeptutor.services.skill.get_skill_service",
        lambda: SimpleNamespace(
            summary_entries=lambda: [],
            load_always_for_context=lambda: "",
            load_for_context=lambda _skills: "",
            list_skills=lambda: [],
        ),
    )
    monkeypatch.setattr(
        "deeptutor.services.persona.get_persona_service",
        lambda: SimpleNamespace(load_for_context=lambda _name: ""),
    )

    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    async with pg_session_runtime(pg_dsn, resource="legacy-finalize") as runtime:
        token = set_current_user(
            CurrentUser(
                id=runtime.admin.user_id,
                username=runtime.admin.username,
                role="tenant_admin",
                scope=UserScope(
                    kind="tenant",
                    tenant_id=runtime.tenant_id,
                    user_id=runtime.admin.user_id,
                    root=None,
                ),
            )
        )
        try:
            store = runtime.store()
            manager = TurnRuntimeManager(store)
            monkeypatch.setattr(manager, "_maybe_generate_session_title", _noop_async)

            session, turn = await manager.start_turn(
                {
                    "type": "start_turn",
                    "session_id": None,
                    "content": "hello pg",
                    "capability": "chat",
                    "tools": [],
                    "knowledge_bases": [],
                    "attachments": [],
                    "language": "en",
                    "config": {},
                }
            )

            events = [event async for event in manager.subscribe_turn(turn["id"], after_seq=0)]
            persisted_turn = await store.get_turn(turn["id"])
            messages = await store.get_messages_for_context(session["id"])
            persisted_events = await store.get_turn_events(turn["id"])
        finally:
            reset_current_user(token)

    assert persisted_turn is not None
    assert persisted_turn["status"] == "completed"
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "PG legacy answer"
    done = next(event for event in events if event["type"] == "done")
    persisted_done = next(event for event in persisted_events if event["type"] == "done")
    assert done["seq"] == persisted_done["seq"]
    assert done["metadata"]["assistant_message_id"] == messages[-1]["id"]
    assert done["metadata"]["user_message_id"] == messages[0]["id"]


async def test_pg_legacy_runtime_failed_turn_commits_done_through_finalize_turn(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """异常终态也不能把 DONE 交给 append_events。"""

    async def _noop_async(*_args, **_kwargs):
        return None

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **_kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FailingOrchestrator:
        async def handle(self, _context):
            raise RuntimeError("provider exploded")
            yield  # pragma: no cover

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder",
        FakeContextBuilder,
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FailingOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_l3_concat=lambda: "", emit=_noop_async),
    )
    monkeypatch.setattr(
        "deeptutor.services.skill.get_skill_service",
        lambda: SimpleNamespace(
            summary_entries=lambda: [],
            load_always_for_context=lambda: "",
            load_for_context=lambda _skills: "",
            list_skills=lambda: [],
        ),
    )
    monkeypatch.setattr(
        "deeptutor.services.persona.get_persona_service",
        lambda: SimpleNamespace(load_for_context=lambda _name: ""),
    )

    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    async with pg_session_runtime(pg_dsn, resource="legacy-finalize-failed") as runtime:
        token = set_current_user(
            CurrentUser(
                id=runtime.admin.user_id,
                username=runtime.admin.username,
                role="tenant_admin",
                scope=UserScope(
                    kind="tenant",
                    tenant_id=runtime.tenant_id,
                    user_id=runtime.admin.user_id,
                    root=None,
                ),
            )
        )
        try:
            store = runtime.store()
            manager = TurnRuntimeManager(store)

            _session, turn = await manager.start_turn(
                {
                    "type": "start_turn",
                    "session_id": None,
                    "content": "hello pg",
                    "capability": "chat",
                    "tools": [],
                    "knowledge_bases": [],
                    "attachments": [],
                    "language": "en",
                    "config": {},
                }
            )

            events = [event async for event in manager.subscribe_turn(turn["id"], after_seq=0)]
            persisted_turn = await store.get_turn(turn["id"])
            persisted_events = await store.get_turn_events(turn["id"])
        finally:
            reset_current_user(token)

    assert persisted_turn is not None
    assert persisted_turn["status"] == "failed"
    assert [event["type"] for event in persisted_events[-2:]] == ["error", "done"]
    assert [event["type"] for event in events[-2:]] == ["error", "done"]
    assert events[-1]["metadata"]["status"] == "failed"


async def test_pg_add_message_returns_real_record_id(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="flush-message-id") as runtime:
        store = runtime.store()
        session = await store.create_session(title="t", session_id="s_ids")
        message_id = await store.add_message(session["id"], "assistant", "hello")
        messages = await store.get_messages(session["id"])

    assert message_id == messages[0]["id"]
