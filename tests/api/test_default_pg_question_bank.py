# ruff: noqa: F811
"""默认 question notebook / quiz results / question_bank 工具的 PG-only 契约。"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn, single_database_user_dsn  # noqa: F401


class _StaticStoreProvider:
    def __init__(self, store) -> None:
        self._store = store

    def get(self):
        return self._store


async def _prepare_pg_stores(pg_dsn: str, *, resource: str):
    tenant_id = str(uuid.uuid4())
    runtime_dsn = single_database_user_dsn(pg_dsn)

    from deeptutor.persistence.postgres.connection import Database
    from deeptutor.persistence.postgres.identity.service import IdentityService
    from deeptutor.persistence.postgres.migrations.runner import MigrationRunner
    from deeptutor.persistence.postgres.scope import TenantScope
    from deeptutor.persistence.postgres.session import PostgresSessionStore

    await MigrationRunner(runtime_dsn).apply()
    db = Database(runtime_dsn, resource=resource)
    db.test_runtime_dsn = runtime_dsn
    await db.__aenter__()
    try:
        identity = IdentityService(
            db,
            tenant_id=tenant_id,
            signing_key="s" * 48,
            auth_epoch="epoch-question-bank",
            bootstrap_secret="b" * 48,
        )
        await identity.bootstrap("admin", "administrator-123", secret="b" * 48)
        admin_token = await identity.login("admin", "administrator-123", client=resource)
        await identity.create_user(admin_token, "learner", "learner-password")
        learner_token = await identity.login("learner", "learner-password", client=resource)
        admin = await identity.authenticate(admin_token)
        learner = await identity.authenticate(learner_token)
        return (
            db,
            PostgresSessionStore(db, TenantScope(tenant_id, admin.user_id)),
            PostgresSessionStore(db, TenantScope(tenant_id, learner.user_id)),
        )
    except Exception:
        await db.__aexit__(None, None, None)
        raise


def _forbid_sqlite(*args, **kwargs):  # noqa: ANN002, ANN003
    raise AssertionError("question-bank path must not fall back to SQLite")


@pytest.mark.asyncio
async def test_question_notebook_api_uses_pg_provider_and_owner_scope(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """原 question notebook API 必须读写当前 PG provider，并保持 owner 隔离。"""

    db, admin_store, learner_store = await _prepare_pg_stores(
        pg_dsn, resource="test-pg-question-notebook-api"
    )
    try:
        from deeptutor.api.routers import question_notebook
        from deeptutor.core.providers import ApplicationProviders, provider_context

        monkeypatch.setattr(question_notebook, "get_sqlite_session_store", _forbid_sqlite, raising=False)

        session = await admin_store.create_session(title="PG Drill")
        app = FastAPI()
        app.include_router(question_notebook.router, prefix="/api/question-notebook")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with provider_context(ApplicationProviders(store=_StaticStoreProvider(admin_store))):
                created = await client.post(
                    "/api/question-notebook/entries/upsert",
                    json={
                        "session_id": session["id"],
                        "turn_id": "",
                        "question_id": "q1",
                        "question": "What is 50% of 8?",
                        "correct_answer": "4",
                        "user_answer": "5",
                        "is_correct": False,
                    },
                )
                assert created.status_code == 200, created.text
                entry_id = created.json()["id"]
                stats = (await client.get("/api/question-notebook/stats")).json()
                assert stats["total"] == 1 and stats["wrong"] == 1
                category = (
                    await client.post(
                        "/api/question-notebook/categories", json={"name": "PG mistakes"}
                    )
                ).json()
                bulk = await client.post(
                    "/api/question-notebook/entries/categories/bulk",
                    json={"entry_ids": [entry_id], "category_id": category["id"]},
                )
                assert bulk.status_code == 200, bulk.text
                items = (await client.get("/api/question-notebook/entries")).json()["items"]
                assert items[0]["session_id"] == session["id"]
                assert [item["name"] for item in items[0]["categories"]] == ["PG mistakes"]

            with provider_context(ApplicationProviders(store=_StaticStoreProvider(learner_store))):
                scoped = await client.get("/api/question-notebook/entries")
                assert scoped.status_code == 200, scoped.text
                assert scoped.json() == {"items": [], "total": 0}
                hidden = await client.get(f"/api/question-notebook/entries/{entry_id}")
                assert hidden.status_code == 404
    finally:
        await db.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_quiz_results_route_and_question_tool_use_pg_provider(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """quiz-results 路由和 question_bank 工具应消费同一 PG provider 数据。"""

    db, admin_store, _learner_store = await _prepare_pg_stores(
        pg_dsn, resource="test-pg-question-bank-tool"
    )
    try:
        from deeptutor.agents._shared.tool_composition import user_has_question_bank
        from deeptutor.api.routers import sessions
        from deeptutor.core.providers import ApplicationProviders, provider_context
        from deeptutor.services import session as session_module
        from deeptutor.tools.builtin import QuestionBankTool
        from deeptutor.tools.question_bank import run_question_bank

        monkeypatch.setattr(sessions, "get_sqlite_session_store", _forbid_sqlite, raising=False)
        monkeypatch.setattr(session_module, "get_sqlite_session_store", _forbid_sqlite)

        session = await admin_store.create_session(title="Quiz PG")
        app = FastAPI()
        app.include_router(sessions.router, prefix="/api/sessions")

        with provider_context(ApplicationProviders(store=_StaticStoreProvider(admin_store))):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                recorded = await client.post(
                    f"/api/sessions/{session['id']}/quiz-results",
                    json={
                        "turn_id": "",
                        "answers": [
                            {
                                "question_id": "q-tool",
                                "question": "Derivative of sin(x)?",
                                "user_answer": "-cos(x)",
                                "correct_answer": "cos(x)",
                                "is_correct": False,
                            }
                        ],
                    },
                )
                assert recorded.status_code == 200, recorded.text
                assert recorded.json()["notebook_count"] == 1

            outcome = await run_question_bank(action="list", filter_mode="wrong")
            assert outcome.ok, outcome.error
            assert outcome.summary["count"] == 1
            assert "Derivative of sin(x)?" in outcome.text
            assert user_has_question_bank() is True

            tool_result = await QuestionBankTool().execute(action="list", filter="wrong")
            assert tool_result.success
            assert tool_result.metadata["question_bank"]["count"] == 1
    finally:
        await db.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_quiz_history_loader_uses_pg_provider_without_sqlite_fallback(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """deep_question 历史加载应来自 PG question bank，而不是假空 SQLite 历史。"""

    db, admin_store, _learner_store = await _prepare_pg_stores(
        pg_dsn, resource="test-pg-question-history"
    )
    try:
        from deeptutor.agents.question.history import load_session_quiz_history
        from deeptutor.core.providers import ApplicationProviders, provider_context
        import deeptutor.services.session.sqlite_store as sqlite_store

        monkeypatch.setattr(sqlite_store, "get_sqlite_session_store", _forbid_sqlite)

        session = await admin_store.create_session(title="History PG")
        await admin_store.upsert_notebook_entries(
            session["id"],
            [
                {
                    "turn_id": "",
                    "question_id": "q1",
                    "question": "What is 2+2?",
                    "question_type": "written",
                    "correct_answer": "4",
                    "user_answer": "4",
                    "is_correct": True,
                }
            ],
        )
        with provider_context(ApplicationProviders(store=_StaticStoreProvider(admin_store))):
            history = await load_session_quiz_history(session["id"])
        assert [entry.question for entry in history] == ["What is 2+2?"]
        assert history[0].is_correct is True
    finally:
        await db.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_imports_route_uses_pg_provider_without_sqlite_fallback(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """chat-history imports route 应写入 PG session store，而非运行期 SQLite。"""

    db, admin_store, _learner_store = await _prepare_pg_stores(
        pg_dsn, resource="test-pg-imports-route"
    )
    try:
        from deeptutor.api.routers import imports as imports_router
        from deeptutor.core.providers import ApplicationProviders, provider_context

        monkeypatch.setattr(imports_router, "get_sqlite_session_store", _forbid_sqlite, raising=False)

        app = FastAPI()
        app.include_router(imports_router.router, prefix="/api/imports")

        with provider_context(ApplicationProviders(store=_StaticStoreProvider(admin_store))):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                imported = await client.post(
                    "/api/imports/chat-history",
                    json={
                        "source": "codex",
                        "agent_id": "agent-1",
                        "agent_name": "Codex",
                        "sessions": [
                            {
                                "external_id": "thread-1",
                                "title": "Imported PG",
                                "source_cwd": "/tmp/project",
                                "created_at": 1.0,
                                "updated_at": 2.0,
                                "messages": [
                                    {"role": "user", "content": "hello", "created_at": 1.0},
                                    {"role": "assistant", "content": "hi", "created_at": 2.0},
                                ],
                            }
                        ],
                    },
                )
                assert imported.status_code == 200, imported.text
                assert imported.json()["imported"] == 1

                listed = await client.get("/api/imports/chat-history")
                assert listed.status_code == 200, listed.text
                sessions = listed.json()["sessions"]
                assert len(sessions) == 1
                assert sessions[0]["title"] == "Imported PG"
                assert sessions[0]["preferences"]["import"]["agent_id"] == "agent-1"
    finally:
        await db.__aexit__(None, None, None)
