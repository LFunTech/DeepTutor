"""Task 1.17 fix1：真实 PG 拒绝边界与取消提交回归。"""

import asyncio
from types import SimpleNamespace

import pytest

from tests.persistence.postgres.business.test_learning_runtime import _seed_path
from tests.persistence.postgres.business.test_learning_runtime import (
    learning_runtime as _runtime_fixture,
)

learning_runtime = _runtime_fixture

pytestmark = pytest.mark.asyncio


async def test_generators_reject_before_model(learning_runtime, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from deeptutor.api.routers.mastery_path import router
    from deeptutor.learning import topic_naming
    from deeptutor.services import llm

    calls = []

    async def model(**kw):
        calls.append(kw)
        return (
            '{"modules": [{"name":"module","knowledge_points":[{"name":"point","type":"memory"}]}]}'
        )

    async def name(*a, **kw):
        calls.append(kw)
        return "named"

    monkeypatch.setattr(llm, "complete", model)
    monkeypatch.setattr(topic_naming, "suggest_topic_name", name)
    monkeypatch.setattr("deeptutor.api.routers.mastery_path.get_response_language", lambda: "en")
    app = FastAPI()
    app.include_router(router)
    async with (
        learning_runtime.bind(),
        AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client,
    ):
        response = await client.post(
            "/progress/p/generate-from-notebook",
            json={"notebook_id": "missing", "records": [{"id": "r", "output": "untrusted"}]},
        )
        assert calls == [], response.text
        assert response.status_code == 503
        await learning_runtime.executor.close()
        response = await client.post("/topics", json={"goal": "test"})
        assert response.status_code >= 400
        assert calls == []


async def test_unbuilt_hint_finds_built_path_after_two_hundred_scratch(learning_runtime):
    from deeptutor.capabilities.mastery.tools import _unbuilt_status_message
    from deeptutor.learning.models import LearningProgress
    from deeptutor.persistence.postgres.learning import ExecutionAuthority

    runtime = learning_runtime
    await _seed_path(runtime)
    owner = runtime._with_authority(ExecutionAuthority(runtime.executor))

    def seeds(unit):
        for i in range(205):
            unit.save(LearningProgress(book_id=f"scratch-{i}"))

    await owner.run(seeds)
    async with runtime.bind():
        text = await _unbuilt_status_message(runtime, "scratch-204", None)
    assert "No mastery path has been built yet" not in text
    assert "built elsewhere" in text


async def test_post_commit_authorization_keeps_learning_result(learning_runtime):
    from deeptutor.persistence.postgres.connection import CommitCompletedAfterCancellation
    from deeptutor.persistence.postgres.learning import ExecutionAuthority

    runtime = learning_runtime._with_authority(ExecutionAuthority(learning_runtime.executor))
    calls = 0

    async def authorize():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CommitCompletedAfterCancellation("AUTH RESULT, NOT LEARNING")

    runtime.authorize = authorize
    with pytest.raises(Exception) as caught:
        await runtime.run(lambda unit: unit.begin_path_operation("p"))
    assert caught.value.result.path_id == "p"
    assert caught.value.stage == "post_authorization"


@pytest.mark.parametrize("entry", ["capability", "adapter"])
async def test_acquire_commit_cancellation_cleans_actual_lease(
    learning_runtime, migrated_pg, monkeypatch, entry
):
    import psycopg

    from deeptutor.capabilities.mastery import capability
    from deeptutor.core.context import UnifiedContext
    from deeptutor.persistence.postgres.connection import CommitCompletedAfterCancellation
    from deeptutor.runtime.stream_bus import StreamBus
    from deeptutor.services.session._turn_runtime_shared import _TurnExecution
    from deeptutor.services.session.turns.learning_adapter import LearningTurnAdapter

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("cancel")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=12
    )

    async def no_model(*a):
        raise AssertionError("cancelled acquisition cannot start model")

    monkeypatch.setattr(
        capability, "MasteryLoopPipeline", lambda **kw: SimpleNamespace(run=no_model)
    )
    adapter = LearningTurnAdapter()
    adapter._executions = {
        turn["id"]: _TurnExecution(
            turn_id=turn["id"], session_id=session["id"], capability="mastery_path", payload={}
        )
    }
    with psycopg.connect(migrated_pg.admin_dsn, autocommit=True) as admin:
        admin.execute(
            "CREATE FUNCTION enterprise.task117_delay() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_lock(11702001); PERFORM pg_advisory_unlock(11702001); RETURN NEW; END $$"
        )
        admin.execute(
            "CREATE CONSTRAINT TRIGGER task117_delay AFTER INSERT ON enterprise.mastery_path_leases DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enterprise.task117_delay()"
        )
        admin.execute("SELECT pg_advisory_lock(11702001)")
        async with runtime.bind():
            if entry == "adapter":
                action = adapter._acquire_mastery_path_lease(
                    path_id="p", session_id=session["id"], turn_id=turn["id"], owns_path=False
                )
            else:
                action = capability.MasteryPathCapability().run(
                    UnifiedContext(
                        session_id=session["id"],
                        user_message="x",
                        metadata={"mastery_path_id": "p", "turn_id": turn["id"]},
                    ),
                    StreamBus(),
                )
            task = asyncio.create_task(action)
            try:
                async with asyncio.timeout(5):
                    while not admin.execute(
                        "SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event='advisory'"
                    ).fetchone():
                        await asyncio.sleep(0.005)
                task.cancel()
                await asyncio.sleep(0)
                admin.execute("SELECT pg_advisory_unlock(11702001)")
                with pytest.raises(CommitCompletedAfterCancellation):
                    await task
                assert await runtime.run(lambda u: u.get_path_lease("p")) is None
            finally:
                admin.execute("SELECT pg_advisory_unlock_all()")
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("failure", [PermissionError, asyncio.CancelledError])
@pytest.mark.parametrize("entry", ["capability", "adapter", "operation"])
async def test_post_commit_auth_failure_releases_owned_resources(
    learning_runtime, monkeypatch, failure, entry
):
    from deeptutor.capabilities.mastery import capability
    from deeptutor.core.context import UnifiedContext
    from deeptutor.learning.runtime import LearningPostCommitAuthorizationError
    from deeptutor.runtime.stream_bus import StreamBus
    from deeptutor.services.session._turn_runtime_shared import _TurnExecution
    from deeptutor.services.session.turns.learning_adapter import LearningTurnAdapter

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("post-auth")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=13
    )

    async def authorize():
        if await runtime._store.run(lambda unit: unit.get_path_lease("p")) is not None:
            raise failure("authorization failed after commit")

    runtime.authorize = authorize

    async def no_model(*a):
        raise AssertionError("failed authorization cannot start model")

    monkeypatch.setattr(
        capability, "MasteryLoopPipeline", lambda **kw: SimpleNamespace(run=no_model)
    )
    async with runtime.bind():
        with pytest.raises(LearningPostCommitAuthorizationError) as caught:
            if entry == "operation":
                async with runtime.operation("p"):
                    raise AssertionError("authorization failed")
            elif entry == "adapter":
                adapter = LearningTurnAdapter()
                adapter._executions = {
                    turn["id"]: _TurnExecution(
                        turn_id=turn["id"],
                        session_id=session["id"],
                        capability="mastery_path",
                        payload={},
                    )
                }
                await adapter._acquire_mastery_path_lease(
                    path_id="p", session_id=session["id"], turn_id=turn["id"], owns_path=False
                )
            else:
                await capability.MasteryPathCapability().run(
                    UnifiedContext(
                        session_id=session["id"],
                        user_message="x",
                        metadata={"mastery_path_id": "p", "turn_id": turn["id"]},
                    ),
                    StreamBus(),
                )
        assert caught.value.stage == "post_authorization"
        assert isinstance(caught.value.__cause__, failure)
        assert await runtime._store.run(lambda u: u.get_path_lease("p")) is None


async def test_authorization_ccac_is_not_a_learning_lease(learning_runtime):
    from deeptutor.persistence.postgres.connection import CommitCompletedAfterCancellation

    async def authorize():
        raise CommitCompletedAfterCancellation("unrelated authorization result")

    learning_runtime.authorize = authorize
    with pytest.raises(RuntimeError, match="before the learning unit"):
        async with learning_runtime.operation("never-created"):
            raise AssertionError("cannot enter")
    assert not await learning_runtime._store.run(lambda u: u.exists("never-created"))


async def test_notebook_generation_checks_conflict_before_content_and_model(
    learning_runtime, monkeypatch
):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from deeptutor.api.routers.mastery_path import router
    from deeptutor.services import llm

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("busy")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=14
    )
    teaching = await runtime.for_turn(session["id"], turn["id"])
    await teaching.run(lambda u: u.acquire_path_lease("p", session["id"], turn["id"]))
    ids = []

    async def authorize(scope, source):
        assert scope == runtime.scope
        ids.append(source.source_id)

    async def forbidden(*a, **kw):
        raise AssertionError("busy path cannot read external content or call model")

    runtime.source_provider = SimpleNamespace(authorize=authorize, notebook_records=forbidden)
    monkeypatch.setattr(llm, "complete", forbidden)
    app = FastAPI()
    app.include_router(router)
    async with (
        runtime.bind(),
        AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client,
    ):
        response = await client.post(
            "/progress/p/generate-from-notebook",
            json={"notebook_id": "authorized-id", "records": [{"id": "r", "output": "untrusted"}]},
        )
        assert response.status_code == 409, response.text
    assert ids == ["authorized-id"]


@pytest.mark.parametrize("source_kind", ["notebook", "reading"])
async def test_generation_holds_operation_and_uses_provider_content(
    learning_runtime, monkeypatch, source_kind
):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from deeptutor.api.routers.mastery_path import router
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.services import llm

    runtime = learning_runtime
    seen = []

    async def authorize(scope, source):
        assert scope == runtime.scope
        seen.append(source.source_id)

    async def notebook_records(scope, notebook_id, *, record_ids):
        assert notebook_id == "notebook-id" and record_ids == ["record-id"]
        return [{"id": "record-id", "output": "provider-owned-text"}]

    async def reading_records(scope, workspace, *, material_ids):
        assert workspace.workspace_id == "workspace-id"
        return [{"id": "record-id", "output": "provider-owned-text"}]

    runtime.source_provider = SimpleNamespace(
        authorize=authorize, notebook_records=notebook_records, reading_records=reading_records
    )
    if source_kind == "reading":
        catalog = AsyncReadingCatalogStore(runtime.database, runtime.scope)
        await catalog.run(lambda u: u.create_workspace("reading", workspace_id="workspace-id"))
    calls = []

    async def model(**kwargs):
        assert (
            "provider-owned-text" in kwargs["prompt"] and "client-untrusted" not in kwargs["prompt"]
        )
        lease = await runtime._store.run(lambda u: u.get_path_lease("p"))
        assert lease.kind == "operation"
        calls.append(kwargs)
        return (
            '{"modules":[{"name":"module","knowledge_points":[{"name":"point","type":"memory"}]}]}'
        )

    monkeypatch.setattr(llm, "complete", model)
    monkeypatch.setattr("deeptutor.api.routers.mastery_path.get_response_language", lambda: "en")
    app = FastAPI()
    app.include_router(router)
    body = (
        {
            "notebook_id": "notebook-id",
            "records": [{"id": "record-id", "output": "client-untrusted"}],
        }
        if source_kind == "notebook"
        else {"workspace_id": "workspace-id"}
    )
    async with (
        runtime.bind(),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(f"/progress/p/generate-from-{source_kind}", json=body)
        assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert await runtime.run(lambda u: u.get_path_lease("p")) is None
    assert (await runtime.run(lambda u: u.load("p"))).modules[0].name == "module"


async def test_topic_name_generation_holds_reserved_operation(learning_runtime, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from deeptutor.api.routers.mastery_path import router
    from deeptutor.learning import topic_naming

    runtime = learning_runtime
    calls = []

    async def model(*a, **kw):
        paths = await runtime.run(lambda u: u.list_path_page())
        assert len(paths.items) == 1
        lease = await runtime.run(lambda u: u.get_path_lease(paths.items[0]))
        assert lease.kind == "operation"
        calls.append(lease.path_id)
        return "generated-name"

    monkeypatch.setattr(topic_naming, "suggest_topic_name", model)
    app = FastAPI()
    app.include_router(router)
    async with (
        runtime.bind(),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post("/topics", json={"goal": "goal"})
        assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert (await runtime.run(lambda u: u.load(calls[0]))).name == "generated-name"
    assert await runtime.run(lambda u: u.get_path_lease(calls[0])) is None
