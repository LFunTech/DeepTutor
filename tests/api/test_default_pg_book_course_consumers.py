"""1.14: book/course/mastery/cron consumers must use the PG session provider."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
import pytest
from starlette.testclient import TestClient

from tests.api.test_book_quiz_attempt_notebook import _FakeResolvedBook
from tests.api.test_default_pg_question_bank import (  # noqa: F401
    _forbid_sqlite,
    _prepare_pg_stores,
    _StaticStoreProvider,
)

pytest_plugins = ("tests.fixtures.postgres",)


def _learning_runtime(sync_db, store):
    from deeptutor.learning.runtime import LearningRuntime

    async def _authorize():
        return None

    return LearningRuntime(
        sync_db,
        store.scope,
        executor=SimpleNamespace(execution_id="test-executor"),
        session_store=store,
        authorize=_authorize,
    )


@pytest.mark.asyncio
async def test_book_inputs_resolve_chat_and_question_bank_from_pg_provider(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Book ideation inputs must not return fake-empty context when only PG has data."""

    db, admin_store, _learner_store = await _prepare_pg_stores(
        pg_dsn, resource="test-pg-book-inputs"
    )
    try:
        from deeptutor.book.inputs import build_book_inputs
        from deeptutor.core.providers import ApplicationProviders, provider_context
        import deeptutor.services.session as session_module

        monkeypatch.setattr(session_module, "get_sqlite_session_store", _forbid_sqlite, raising=False)

        session = await admin_store.create_session(title="Book source chat")
        await admin_store.add_message(session["id"], "user", "Explain Bayes theorem")
        await admin_store.add_message(
            session["id"], "assistant", "Bayes theorem updates beliefs with evidence."
        )
        await admin_store.upsert_notebook_entries(
            session["id"],
            [
                {
                    "turn_id": "",
                    "question_id": "book-q1",
                    "question": "What does the posterior combine?",
                    "question_type": "short_answer",
                    "correct_answer": "prior and likelihood",
                    "user_answer": "only prior",
                    "is_correct": False,
                }
            ],
        )
        entries = await admin_store.list_notebook_entries(search="posterior")
        entry_id = entries["items"][0]["id"]

        with provider_context(ApplicationProviders(store=_StaticStoreProvider(admin_store))):
            _book_inputs, context = await build_book_inputs(
                user_intent="Make a short book about Bayes",
                chat_session_id=session["id"],
                question_entries=[entry_id],
            )

        rendered = context.render()
        assert context.chat_message_count == 2
        assert context.question_entry_count == 1
        assert "Bayes theorem updates beliefs" in rendered
        assert "What does the posterior combine?" in rendered
    finally:
        await db.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_book_quiz_attempt_syncs_focus_check_to_pg_question_bank(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Book focus-check attempts must write review entries through the active PG store."""

    db, admin_store, _learner_store = await _prepare_pg_stores(
        pg_dsn, resource="test-pg-book-quiz-attempt"
    )
    try:
        from deeptutor.api.routers import book as book_router
        from deeptutor.core.providers import ApplicationProviders, provider_context
        import deeptutor.services.session as session_module

        monkeypatch.setattr(session_module, "get_sqlite_session_store", _forbid_sqlite, raising=False)
        resolved = _FakeResolvedBook()
        monkeypatch.setattr(book_router, "_resolve_book_or_404", lambda *_args, **_kwargs: resolved)
        await admin_store.create_session(session_id="page-chat-1", title="Page 1 chat")

        app = FastAPI()
        app.include_router(book_router.router, prefix="/api")
        payload = {
            "book_id": "book-1",
            "page_id": "page-1",
            "block_id": "block-1",
            "question_id": "q1",
            "user_answer": "A",
            "is_correct": False,
        }
        with provider_context(ApplicationProviders(store=_StaticStoreProvider(admin_store))):
            response = TestClient(app).post("/api/books/quiz-attempt", json=payload)

        assert response.status_code == 200
        entries = await admin_store.list_notebook_entries(source="book")
        assert entries["total"] == 1
        entry = entries["items"][0]
        assert entry["session_id"] == "page-chat-1"
        assert entry["session_title"] == "Page 1 chat"
        assert entry["question"] == "Which chapter?"
        assert entry["material_id"] == "book-1"
    finally:
        await db.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_courses_state_counts_pg_question_bank_categories(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Course state should aggregate question-bank counts from PG session rows."""

    db, admin_store, _learner_store = await _prepare_pg_stores(
        pg_dsn, resource="test-pg-courses-state-question-bank"
    )
    sync_db = None
    try:
        from deeptutor.core.providers import ApplicationProviders, provider_context
        from deeptutor.persistence.postgres.connection import SyncDatabase
        from deeptutor.services.courses_state import _question_bank_state
        import deeptutor.services.session as session_module

        monkeypatch.setattr(session_module, "get_sqlite_session_store", _forbid_sqlite, raising=False)

        session = await admin_store.create_session(title="Course session")
        await admin_store.upsert_notebook_entries(
            session["id"],
            [
                {
                    "turn_id": "",
                    "question_id": "course-q1",
                    "question": "Which rule failed?",
                    "question_type": "short_answer",
                    "correct_answer": "product rule",
                    "user_answer": "chain rule",
                    "is_correct": False,
                },
                {
                    "turn_id": "",
                    "question_id": "course-q2",
                    "question": "2+2?",
                    "question_type": "short_answer",
                    "correct_answer": "4",
                    "user_answer": "4",
                    "is_correct": True,
                },
            ],
        )
        category = await admin_store.create_category("Derivatives")
        wrong = await admin_store.find_notebook_entry(session["id"], "course-q1")
        await admin_store.link_entries_to_category([wrong["id"]], category["id"])

        sync_db = SyncDatabase(
            pg_dsn.replace("user=postgres", "user=dt_enterprise_app"),
            resource="test-pg-courses-state-question-bank-sync",
        )
        await sync_db.__aenter__()
        runtime = _learning_runtime(sync_db, admin_store)
        with provider_context(ApplicationProviders(learning=runtime)):
            state = await _question_bank_state({session["id"]})

        assert state == {
            "total": 2,
            "wrong": 1,
            "weak_categories": [{"name": "Derivatives", "wrong": 1}],
        }
    finally:
        if sync_db is not None:
            await sync_db.__aexit__(None, None, None)
        await db.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_topic_materials_reads_chat_and_question_bank_from_pg_runtime(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Learning topic materials should expose PG chat/question-bank payloads."""

    db, admin_store, _learner_store = await _prepare_pg_stores(
        pg_dsn, resource="test-pg-topic-materials"
    )
    sync_db = None
    try:
        from deeptutor.learning.models import TopicSource, TopicSourceKind
        from deeptutor.learning.sources import topic_materials
        from deeptutor.persistence.postgres.connection import SyncDatabase
        import deeptutor.services.session as session_module

        monkeypatch.setattr(session_module, "get_sqlite_session_store", _forbid_sqlite, raising=False)

        session = await admin_store.create_session(title="Materials chat")
        await admin_store.add_message(session["id"], "user", "What is entropy?")
        await admin_store.add_message(
            session["id"], "assistant", "Entropy measures uncertainty in a distribution."
        )
        await admin_store.upsert_notebook_entries(
            session["id"],
            [
                {
                    "turn_id": "",
                    "question_id": "topic-q1",
                    "question": "What does entropy measure?",
                    "question_type": "short_answer",
                    "correct_answer": "uncertainty",
                    "user_answer": "energy",
                    "is_correct": False,
                }
            ],
        )
        entry = await admin_store.find_notebook_entry(session["id"], "topic-q1")
        sync_db = SyncDatabase(
            pg_dsn.replace("user=postgres", "user=dt_enterprise_app"),
            resource="test-pg-topic-materials-sync",
        )
        await sync_db.__aenter__()
        runtime = _learning_runtime(sync_db, admin_store)

        manifest, index = await topic_materials(
            runtime,
            [
                TopicSource(
                    id="chat",
                    kind=TopicSourceKind.CHAT,
                    source_id=session["id"],
                    label="Entropy chat",
                ),
                TopicSource(
                    id="qb",
                    kind=TopicSourceKind.QUESTION_BANK,
                    source_id=str(entry["id"]),
                    label="Entropy mistake",
                ),
            ],
        )

        assert "[Topic Materials]" in manifest
        assert "Entropy chat" in manifest
        assert "Entropy mistake" in manifest
        assert any("Entropy measures uncertainty" in value for value in index.values())
        assert any("What does entropy measure?" in value for value in index.values())
    finally:
        if sync_db is not None:
            await sync_db.__aexit__(None, None, None)
        await db.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_mastery_build_tool_uses_bound_pg_runtime_without_sqlite_fallback(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mastery tools should mutate the bound PG learning runtime, not legacy stores."""

    db, admin_store, _learner_store = await _prepare_pg_stores(
        pg_dsn, resource="test-pg-mastery-build-tool"
    )
    executor = None
    sync_db = None
    try:
        from deeptutor.capabilities.mastery.tools import MasteryBuildTool
        from deeptutor.learning.runtime import LearningRuntime
        from deeptutor.persistence.postgres.connection import SyncDatabase
        from deeptutor.persistence.postgres.executor import ExecutorLease
        import deeptutor.services.session as session_module

        monkeypatch.setattr(session_module, "get_sqlite_session_store", _forbid_sqlite, raising=False)

        runtime_dsn = pg_dsn.replace("user=postgres", "user=dt_enterprise_app")
        sync_db = SyncDatabase(runtime_dsn, resource="test-pg-mastery-build-tool-sync")
        await sync_db.__aenter__()
        executor = ExecutorLease(runtime_dsn, resource="test-pg-mastery-build-tool-sync")
        await executor.acquire()

        async def _authorize():
            return None

        runtime = LearningRuntime(
            sync_db,
            admin_store.scope,
            executor=executor,
            session_store=admin_store,
            authorize=_authorize,
        )
        session = await admin_store.create_session(title="Mastery turn")
        turn = await admin_store.begin_turn(
            session["id"], owner_id=executor.execution_id, fencing_token=11
        )
        teaching = await runtime.for_turn(session["id"], turn["id"])

        async with teaching.bind():
            result = await MasteryBuildTool().execute(
                _mastery_path_id="pg-mastery-path",
                _session_id=session["id"],
                _turn_id=turn["id"],
                path_name="PG Mastery",
                modules=[
                    {
                        "name": "概率",
                        "objective": "解释条件概率。",
                        "knowledge_points": [{"name": "Bayes rule", "type": "concept"}],
                    }
                ],
            )

        assert result.success, result.content
        progress = await runtime.run(lambda unit: unit.load("pg-mastery-path"))
        assert progress.name == "PG Mastery"
        assert progress.modules[0].knowledge_points[0].name == "Bayes rule"
    finally:
        if executor is not None:
            await executor.close()
        if sync_db is not None:
            await sync_db.__aexit__(None, None, None)
        await db.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_cron_chat_executor_appends_to_pg_session_without_sqlite_fallback(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cron chat reminders must consume the active PG session store."""

    db, admin_store, _learner_store = await _prepare_pg_stores(
        pg_dsn, resource="test-pg-cron-chat-executor"
    )
    try:
        from deeptutor.core.providers import ApplicationProviders, provider_context
        from deeptutor.core.stream import StreamEvent, StreamEventType
        from deeptutor.services.cron import executor
        from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule
        import deeptutor.services.session as session_module

        monkeypatch.setattr(session_module, "get_sqlite_session_store", _forbid_sqlite, raising=False)
        async def _no_notify(*_args, **_kwargs):
            return None

        monkeypatch.setattr(executor, "_maybe_send_desktop_notification", _no_notify)

        class _Engine:
            async def execute(self, _context):
                yield StreamEvent(
                    type=StreamEventType.RESULT,
                    source="chat",
                    content="",
                    metadata={"response": "Stand up and stretch."},
                )

        monkeypatch.setattr("deeptutor.runtime.turn_engine.get_turn_engine", lambda: _Engine())

        session = await admin_store.create_session(title="Cron target")
        job = CronJob(
            id="cron-pg-1",
            name="stretch",
            message="stretch now",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=CronOwner(kind="chat", is_admin=True, session_id=session["id"], language="en"),
        )

        with provider_context(ApplicationProviders(store=_StaticStoreProvider(admin_store))):
            status, error = await executor.execute_job(job)

        assert (status, error) == ("ok", None)
        messages = await admin_store.get_messages(session["id"])
        assert [message["role"] for message in messages[-2:]] == ["user", "assistant"]
        assert messages[-1]["content"] == "Stand up and stretch."
        assert messages[-1]["metadata"]["cron_job_id"] == "cron-pg-1"
    finally:
        await db.__aexit__(None, None, None)
