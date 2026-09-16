"""真实 PG learning 入口，不启动模型或旧存储。"""

import asyncio
import importlib
import json

import pytest

from deeptutor.learning.models import LearningProgress
from deeptutor.persistence.postgres.executor import ExecutorLease

pytestmark = pytest.mark.asyncio


class _Socket:
    def __init__(self, application, token, origin="https://school.example"):
        self.app = application
        self.token = token
        self.origin = origin
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()

    async def __aenter__(self):
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "wss",
            "path": "/ws/mastery-paths",
            "raw_path": b"/ws/mastery-paths",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"origin", self.origin.encode()),
                (b"authorization", ("Bearer " + self.token).encode()),
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("school.example", 443),
            "subprotocols": [],
            "state": {},
        }
        self.task = asyncio.create_task(self.app(scope, self.incoming.get, self.outgoing.put))
        await self.incoming.put({"type": "websocket.connect"})
        assert (await asyncio.wait_for(self.outgoing.get(), 10))["type"] == "websocket.accept"
        return self

    async def send(self, value):
        await self.incoming.put(
            {"type": "websocket.receive", "text": json.dumps({"protocol_version": "2.0", **value})}
        )

    async def receive(self):
        message = await asyncio.wait_for(self.outgoing.get(), 30)
        if message["type"] == "websocket.close":
            return {"type": "closed", "code": message.get("code")}
        return json.loads(message["text"])

    async def __aexit__(self, *args):
        await self.incoming.put({"type": "websocket.disconnect", "code": 1000})
        try:
            await asyncio.wait_for(self.task, 5)
        except (TimeoutError, asyncio.CancelledError):
            self.task.cancel()


async def test_explicit_learning_provider_operations_and_failure_closed(
    migrated_pg, business_sync_database, business_actors, pg_session_store_factory
):
    module = importlib.import_module("deeptutor.learning.runtime")
    actor = business_actors.tenants[0].owners[0]
    tenant = business_actors.tenants[0]
    executor = ExecutorLease(migrated_pg.runtime_dsn, resource=business_sync_database.resource)
    await executor.acquire()

    async def authorize():
        await tenant.identity_service.authenticate(actor.token)

    try:
        runtime = module.LearningRuntime(
            business_sync_database,
            actor.scope,
            executor=executor,
            session_store=pg_session_store_factory(actor),
            authorize=authorize,
        )
        async with runtime.operation("p") as client:
            from deeptutor.learning.service import LearningService

            await client.run(lambda u: LearningService(u).rename_path("p", "本人路径"))
        assert (await runtime.run(lambda u: u.load("p"))).name == "本人路径"
        assert await runtime.run(lambda u: u.get_path_lease("p")) is None
        assert not await runtime.session_store.get_session("__path_api__")
        await tenant.identity_service.logout(actor.token)
        with pytest.raises(PermissionError):
            await runtime.run(lambda u: u.load("p"))
    finally:
        await executor.close()


@pytest.fixture
async def learning_runtime(
    migrated_pg, business_sync_database, business_actors, pg_session_store_factory
):
    from deeptutor.learning.runtime import LearningRuntime

    actor = business_actors.tenants[0].owners[0]
    executor = ExecutorLease(migrated_pg.runtime_dsn, resource=business_sync_database.resource)
    await executor.acquire()

    async def authorize():
        await business_actors.tenants[0].identity_service.authenticate(actor.token)

    runtime = LearningRuntime(
        business_sync_database,
        actor.scope,
        executor=executor,
        session_store=pg_session_store_factory(actor),
        authorize=authorize,
    )
    try:
        yield runtime
    finally:
        await executor.close()


async def _seed_path(runtime):
    from deeptutor.learning.models import KnowledgePoint, LearningModule
    from deeptutor.learning.service import LearningService

    async with runtime.operation("p") as owner:
        await owner.run(
            lambda u: LearningService(u).replace_modules_for_path(
                "p",
                [
                    LearningModule(
                        id="m",
                        name="数学",
                        order=0,
                        knowledge_points=[
                            KnowledgePoint(id="k", module_id="m", name="加法", type="memory")
                        ],
                    )
                ],
            )
        )


async def test_real_api_reads_and_typed_mutations(learning_runtime, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from deeptutor.api.routers.mastery_path import router
    from tests.fixtures.legacy_connection_guard import forbid_legacy_connections

    runtime = learning_runtime
    await _seed_path(runtime)

    forbid_legacy_connections(monkeypatch)
    app = FastAPI()
    app.include_router(router, prefix="/api/mastery-paths")
    async with (
        runtime.bind(),
        AsyncClient(transport=ASGITransport(app), base_url="http://test") as client,
    ):
        response = await client.get("/api/mastery-paths/progress/p")
        assert response.status_code == 200, response.text
        assert response.json()["book_id"] == "p"
        response = await client.patch("/api/mastery-paths/progress/p", json={"name": "新名称"})
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "新名称"
        assert await runtime.run(lambda u: u.get_path_lease("p")) is None


async def test_real_quiz_grade_and_notebook_are_atomic(learning_runtime, monkeypatch):
    from deeptutor.capabilities.mastery.tools import MasteryGradeTool, MasteryQuizTool
    from tests.fixtures.legacy_connection_guard import forbid_legacy_connections

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("教学")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=7
    )
    teaching = await runtime.for_turn(session["id"], turn["id"])
    await teaching.run(lambda u: u.acquire_path_lease("p", session["id"], turn["id"]))

    forbid_legacy_connections(monkeypatch)
    kwargs = {"_mastery_path_id": "p", "_session_id": session["id"], "_turn_id": turn["id"]}
    async with teaching.bind():
        quiz = await MasteryQuizTool().execute(
            **kwargs,
            knowledge_point_id="k",
            question="1+1=?",
            expected_answer="2",
            question_type="short",
        )
        assert quiz.success, quiz.content
        question_id = quiz.metadata["mastery_quiz"]["question_id"]
        grade = await MasteryGradeTool().execute(**kwargs, question_id=question_id, answer="2")
        assert grade.success, grade.content
        replay = await MasteryGradeTool().execute(**kwargs, question_id=question_id, answer="2")
        assert replay.metadata["mastery_grade"]["replayed"] is True
        assert (
            replay.metadata["mastery_grade"]["path_revision"]
            == (await teaching.run(lambda u: u.load("p"))).version
        )
    assert (
        len((await runtime.session_store.list_notebook_entries(session_id=session["id"]))["items"])
        == 1
    )


async def test_event_api_paginates_same_revision_without_loss(learning_runtime):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from deeptutor.api.routers.mastery_path import router

    runtime = learning_runtime
    async with runtime.operation("p") as owner:

        def emit(unit):
            with unit.transaction("p") as tx:
                for i in range(451):
                    tx.emit("test.event", {"n": i})

        await owner.run(emit)
    app = FastAPI()
    app.include_router(router)
    seen, cursor = [], None
    async with (
        runtime.bind(),
        AsyncClient(transport=ASGITransport(app), base_url="http://test") as client,
    ):
        while True:
            params = {"cursor": cursor, "limit": 37} if cursor else {"limit": 37}
            response = await client.get("/progress/p/events", params=params)
            assert response.status_code == 200, response.text
            data = response.json()
            assert len(data["events"]) <= 37
            seen.extend(event["id"] for event in data["events"])
            cursor = data["next_cursor"]
            if not cursor:
                break
    assert len(seen) == len(set(seen)) and len(seen) >= 451


async def test_navigation_pg_gate_and_consistent_snapshot(learning_runtime):
    from deeptutor.learning import navigation
    from deeptutor.learning.models import TopicMetadata

    runtime = learning_runtime
    await _seed_path(runtime)
    async with runtime.operation("p") as owner:
        await owner.run(lambda u: u.put_topic(TopicMetadata(path_id="p", goal="加法"), []))
    async with runtime.bind():
        assert await navigation.learner_has_topics()
        cards = await navigation.topic_cards()
        assert cards["topics"][0]["path_id"] == "p"
        assert (await navigation.find_topic("p"))["goal"] == "加法"


async def test_turn_handoff_is_atomic_and_lease_conflict_keeps_original(learning_runtime):
    from deeptutor.capabilities.mastery.binding import PathBindingError, rebind_active_path

    runtime = learning_runtime
    await _seed_path(runtime)
    async with runtime.operation("q"):
        pass
    first = await runtime.session_store.create_session("first")
    second = await runtime.session_store.create_session("second")
    t1 = await runtime.session_store.begin_turn(
        first["id"], owner_id=runtime.executor.execution_id, fencing_token=2
    )
    t2 = await runtime.session_store.begin_turn(
        second["id"], owner_id=runtime.executor.execution_id, fencing_token=3
    )
    one = await runtime.for_turn(first["id"], t1["id"])
    two = await runtime.for_turn(second["id"], t2["id"])
    await one.run(lambda u: u.acquire_path_lease("p", first["id"], t1["id"]))
    await two.run(lambda u: u.acquire_path_lease("q", second["id"], t2["id"]))
    async with one.bind():
        with pytest.raises(PathBindingError):
            await rebind_active_path(
                path_id="q", session_id=first["id"], turn_id=t1["id"], bind_turn=None
            )
    assert (await one.run(lambda u: u.get_path_lease("p"))).turn_id == t1["id"]
    await two.run(lambda u: u.release_leases_for_turn(t2["id"]))
    async with one.bind():
        await rebind_active_path(
            path_id="q", session_id=first["id"], turn_id=t1["id"], bind_turn=None
        )
    assert (await runtime.session_store.get_session(first["id"]))["preferences"][
        "mastery_path_id"
    ] == "q"
    assert await one.run(lambda u: u.path_id_for_session(first["id"])) == "q"


async def test_runtime_adapter_acquires_real_turn_and_releases_without_swallowing(learning_runtime):
    from deeptutor.services.session._turn_runtime_shared import _TurnExecution
    from deeptutor.services.session.turns.learning_adapter import LearningTurnAdapter

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("runtime")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=5
    )
    execution = _TurnExecution(
        turn_id=turn["id"], session_id=session["id"], capability="mastery_path", payload={}
    )
    adapter = LearningTurnAdapter()
    adapter._executions = {turn["id"]: execution}
    adapter.store = runtime.session_store
    async with runtime.bind():
        await adapter._acquire_mastery_path_lease(
            path_id="p", session_id=session["id"], turn_id=turn["id"], owns_path=False
        )
        assert execution.learning_runtime.authority.fencing_token == 5
        await adapter._release_learning_lease(execution)
    assert await runtime.run(lambda u: u.get_path_lease("p")) is None


async def test_real_websocket_pages_reconnects_and_revalidates(learning_runtime, business_actors):
    from fastapi import FastAPI

    from deeptutor.api.routers.mastery_path import ws_router
    from deeptutor.services.auth import PostgresAuthProvider

    runtime = learning_runtime
    actor = business_actors.tenants[0].owners[0]
    async with runtime.operation("p") as owner:

        def emit(unit):
            with unit.transaction("p") as tx:
                for i in range(430):
                    tx.emit("test.event", {"n": i})

        await owner.run(emit)
    app = FastAPI()
    app.state.auth_provider = PostgresAuthProvider(
        business_actors.tenants[0].identity_service, resources=None
    )
    app.include_router(ws_router, prefix="/ws")

    async def application(scope, receive, send):
        async with runtime.bind():
            await app(
                {**scope, "path": "/ws/mastery-paths", "raw_path": b"/ws/mastery-paths"},
                receive,
                send,
            )

    seen = []
    async with _Socket(application, actor.token) as ws:
        await ws.send({"type": "subscribe", "path_id": "p"})
        first = await ws.receive()
        assert len(first["events"]) <= 200
        seen.extend(e["id"] for e in first["events"])
        cursor = first["cursor"]
    async with _Socket(application, actor.token) as ws:
        await ws.send({"type": "subscribe", "path_id": "p", "cursor": cursor})
        while True:
            page = await ws.receive()
            seen.extend(e["id"] for e in page["events"])
            if not page["next_cursor"]:
                break
        assert len(seen) == 431 and len(set(seen)) == 431
        await business_actors.tenants[0].identity_service.logout(actor.token)
        result = await ws.receive()
        assert result == {"type": "closed", "code": 1008}


async def test_unknown_source_authority_fails_before_topic_write(learning_runtime):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from deeptutor.api.routers.mastery_path import router

    app = FastAPI()
    app.include_router(router)
    async with (
        learning_runtime.bind(),
        AsyncClient(transport=ASGITransport(app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/topics",
            json={
                "name": "教材",
                "goal": "学习",
                "sources": [{"kind": "book", "source_id": "unverified-book", "label": "教材"}],
            },
        )
        assert response.status_code == 503, response.text
    assert (await learning_runtime.run(lambda u: u.list_path_page())).items == []


async def test_controlled_background_recovery_preserves_question_no_reexecution(
    learning_runtime, migrated_pg
):
    from deeptutor.capabilities.mastery.tools import MasteryQuizTool
    from deeptutor.learning.runtime import LearningRuntime

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("recovery")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=4
    )
    teaching = await runtime.for_turn(session["id"], turn["id"])
    await teaching.run(lambda u: u.acquire_path_lease("p", session["id"], turn["id"]))
    async with teaching.bind():
        quiz = await MasteryQuizTool().execute(
            _mastery_path_id="p",
            _session_id=session["id"],
            _turn_id=turn["id"],
            knowledge_point_id="k",
            question="1+1",
            expected_answer="2",
            question_type="short",
        )
    before = await teaching.run(lambda u: u.load("p"))
    await runtime.executor.close()
    new_executor = ExecutorLease(migrated_pg.runtime_dsn, resource=runtime.database.resource)
    await new_executor.acquire()
    resumed = LearningRuntime(
        runtime.database,
        runtime.scope,
        executor=new_executor,
        session_store=runtime.session_store,
        authorize=runtime.authorize,
    )
    try:
        await resumed.recover_once()
        assert (await runtime.session_store.get_turn(turn["id"]))["status"] == "failed"
        after = await resumed.run(lambda u: u.load("p"))
        assert (
            after.version == before.version
            and after.pending_question.question_id == quiz.metadata["mastery_quiz"]["question_id"]
        )
        assert await resumed.run(lambda u: u.get_path_lease("p")) is None
        await resumed.recover_once()
        assert (await resumed.run(lambda u: u.load("p"))).version == before.version
        with pytest.raises(RuntimeError):
            await teaching.run(lambda u: u.release_leases_for_turn(turn["id"]))
    finally:
        await new_executor.close()


async def test_session_delete_cleans_owned_scratch_in_same_pg_unit(learning_runtime):
    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.services.session.deletion import delete_session_lifecycle

    runtime = learning_runtime
    session = await runtime.session_store.create_session("scratch")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=2
    )
    teaching = await runtime.for_turn(session["id"], turn["id"])
    await teaching.run(lambda u: u.acquire_path_lease("scratch", session["id"], turn["id"]))
    await teaching.run(lambda u: u.bind_session("scratch", session["id"], owns_path=True))
    await teaching.run(lambda u: u.release_leases_for_turn(turn["id"]))
    await runtime.session_store.finalize_turn(turn["id"], status="completed")

    async def cancel(turn_id):
        raise AssertionError("no active execution")

    with provider_context(ApplicationProviders(learning=runtime)):
        assert await delete_session_lifecycle(runtime.session_store, cancel, session["id"])
    assert await runtime.session_store.get_session(session["id"]) is None
    assert await runtime.run(lambda u: u.load("scratch")) is None


async def test_unconfigured_api_and_service_fail_closed_without_legacy_constructor():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from deeptutor.api.routers.mastery_path import router
    from deeptutor.learning.service import LearningService

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        assert (await client.get("/topics")).status_code == 503
    with pytest.raises(RuntimeError, match="explicit"):
        LearningService()


async def test_actual_grade_notebook_failure_rolls_back_interaction_progress_events(
    learning_runtime, migrated_pg
):
    import psycopg

    from deeptutor.capabilities.mastery.tools import MasteryGradeTool, MasteryQuizTool
    from deeptutor.learning.event_hub import mastery_topic_event_hub

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("atomic")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=2
    )
    teaching = await runtime.for_turn(session["id"], turn["id"])
    await teaching.run(lambda u: u.acquire_path_lease("p", session["id"], turn["id"]))
    kwargs = {"_mastery_path_id": "p", "_session_id": session["id"], "_turn_id": turn["id"]}
    async with teaching.bind():
        quiz = await MasteryQuizTool().execute(
            **kwargs,
            knowledge_point_id="k",
            question="1+1",
            expected_answer="2",
            question_type="short",
        )
        question_id = quiz.metadata["mastery_quiz"]["question_id"]
        before = await teaching.run(lambda u: u.load("p"))
        events = await teaching.event_page("p")
        async with await psycopg.AsyncConnection.connect(
            migrated_pg.admin_dsn, autocommit=True
        ) as admin:
            await admin.execute(
                "CREATE FUNCTION public.task117_reject() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic notebook failure'; END $$"
            )
            await admin.execute(
                "CREATE TRIGGER task117_reject BEFORE INSERT OR UPDATE ON enterprise.notebook_entries FOR EACH ROW EXECUTE FUNCTION public.task117_reject()"
            )
            sub = mastery_topic_event_hub.subscribe("p", scope=teaching.event_scope)
            try:
                with pytest.raises(
                    psycopg.errors.RaiseException, match="synthetic notebook failure"
                ):
                    await MasteryGradeTool().execute(**kwargs, question_id=question_id, answer="2")
                assert (
                    await teaching.run(lambda u: u.load("p"))
                ).model_dump() == before.model_dump()
                assert await teaching.event_page("p") == events
                assert not sub.queue.qsize()
                assert (
                    await runtime.session_store.list_notebook_entries(session_id=session["id"])
                )["total"] == 0
            finally:
                sub.close()
                await admin.execute("DROP TRIGGER task117_reject ON enterprise.notebook_entries")
                await admin.execute("DROP FUNCTION public.task117_reject()")
        result = await MasteryGradeTool().execute(**kwargs, question_id=question_id, answer="2")
        assert result.success
        assert (await runtime.session_store.list_notebook_entries(session_id=session["id"]))[
            "total"
        ] == 1


async def test_future_event_cursor_cannot_pin_live_subscription(learning_runtime):
    await _seed_path(learning_runtime)
    cursor = await learning_runtime.run(lambda u: u._cursor("events:p", [10**12, 10**12]))
    with pytest.raises(ValueError, match="cursor"):
        await learning_runtime.event_page("p", cursor=cursor)


async def test_delete_session_detaches_completed_history_and_preserves_learning(learning_runtime):
    from deeptutor.capabilities.mastery.tools import MasteryQuizTool
    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.services.session.deletion import delete_session_lifecycle

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("history")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=2
    )
    teaching = await runtime.for_turn(session["id"], turn["id"])
    await teaching.run(lambda u: u.acquire_path_lease("p", session["id"], turn["id"]))
    async with teaching.bind():
        result = await MasteryQuizTool().execute(
            _mastery_path_id="p",
            _session_id=session["id"],
            _turn_id=turn["id"],
            knowledge_point_id="k",
            question="1+1",
            expected_answer="2",
            question_type="short",
        )
    qid = result.metadata["mastery_quiz"]["question_id"]
    await teaching.run(lambda u: u.release_leases_for_turn(turn["id"]))
    await runtime.session_store.finalize_turn(turn["id"], status="completed")

    async def cancel(_):
        raise AssertionError("no active execution")

    with provider_context(ApplicationProviders(learning=runtime)):
        assert await delete_session_lifecycle(runtime.session_store, cancel, session["id"])
    interaction = await runtime.run(lambda u: u.get_interaction("p", qid))
    assert interaction.question.prompt == "1+1"
    assert interaction.session_id == interaction.turn_id == ""
    assert interaction.result["detached_provenance"] == {
        "session_id": session["id"],
        "turn_id": turn["id"],
    }
    assert (await runtime.run(lambda u: u.load("p"))).pending_question.question_id == qid
    events = (await runtime.event_page("p"))["events"]
    assert any(e["event_type"] == "session.history_detached" for e in events)
    assert all(e["session_id"] == e["turn_id"] == "" for e in events)


async def test_history_detach_rejects_active_and_other_owner(
    learning_runtime, business_actors, pg_session_store_factory
):
    from deeptutor.learning.contracts import LearningStoreError, PathLeaseConflictError
    from deeptutor.learning.runtime import LearningRuntime
    from deeptutor.persistence.postgres.learning import ExecutionAuthority

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("live")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=3
    )
    teaching = await runtime.for_turn(session["id"], turn["id"])
    await teaching.run(lambda u: u.acquire_path_lease("p", session["id"], turn["id"]))

    def history(u):
        with u.transaction("p") as tx:
            tx.emit("test.history", session_id=session["id"], turn_id=turn["id"])

    await teaching.run(history)
    token = await runtime.session_store.claim_deletion(session["id"])
    manager = runtime._with_authority(ExecutionAuthority(runtime.executor))
    with pytest.raises(LearningStoreError, match="active execution"):
        await manager.run(lambda u: u.detach_session_history(session["id"], deletion_token=token))
    await runtime.session_store.finalize_turn(turn["id"], status="completed")
    with pytest.raises(PathLeaseConflictError):
        await manager.run(lambda u: u.detach_session_history(session["id"], deletion_token=token))
    other_actor = business_actors.tenants[1].owners[0]

    async def authorize_other():
        await business_actors.tenants[1].identity_service.authenticate(other_actor.token)

    other = LearningRuntime(
        runtime.database,
        other_actor.scope,
        executor=runtime.executor,
        session_store=pg_session_store_factory(other_actor),
        authorize=authorize_other,
        authority=ExecutionAuthority(runtime.executor),
    )
    assert not await other.run(
        lambda u: u.detach_session_history(session["id"], deletion_token=token)
    )
    assert not await other.delete_session(session["id"], token)
    events = (await runtime.event_page("p"))["events"]
    assert events[-1]["session_id"] == session["id"]
    await teaching.run(lambda u: u.release_leases_for_turn(turn["id"]))
    async with runtime.operation("p"):
        with pytest.raises(PathLeaseConflictError):
            await manager.run(
                lambda u: u.detach_session_history(session["id"], deletion_token=token)
            )
    with pytest.raises(RuntimeError, match="token"):
        await manager.run(lambda u: u.detach_session_history(session["id"], deletion_token="wrong"))


async def test_hint_cache_is_scoped_and_course_reads_pg(
    learning_runtime, business_actors, pg_session_store_factory
):
    from deeptutor.learning.runtime import LearningRuntime
    from deeptutor.services.courses_state import _mastery_path_index
    from deeptutor.services.mastery_hints import _cache_key, _load_position

    runtime = learning_runtime
    await _seed_path(runtime)
    async with runtime.bind():
        first = _cache_key("p", "k", "0")
        position = await _load_position("p")
        assert position[-1] == "k"
        assert "p" in await _mastery_path_index()
    actor = business_actors.tenants[1].owners[0]

    async def authorize_other():
        await business_actors.tenants[1].identity_service.authenticate(actor.token)

    other = LearningRuntime(
        runtime.database,
        actor.scope,
        executor=runtime.executor,
        session_store=pg_session_store_factory(actor),
        authorize=authorize_other,
    )
    async with other.bind():
        assert _cache_key("p", "k", "0") != first
        assert await _load_position("p") == ("", "", "", "", "", "", "")
        assert "p" not in await _mastery_path_index()


async def test_delete_source_conflict_rolls_back_history_detach(learning_runtime):
    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.learning.models import TopicMetadata, TopicSource, TopicSourceKind
    from deeptutor.services.session.deletion import delete_session_lifecycle
    from deeptutor.services.session.question_bank import QuestionBankReferenceConflict

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("source")
    async with runtime.operation("p") as manager:

        def link(u):
            with u.transaction("p") as tx:
                tx.put_topic(
                    TopicMetadata(path_id="p"),
                    [
                        TopicSource(
                            id="source",
                            kind=TopicSourceKind.CHAT,
                            source_id=session["id"],
                            label="history",
                        )
                    ],
                )
                tx.emit("test.history", session_id=session["id"])

        await manager.run(link)
    before = (await runtime.event_page("p"))["events"]

    async def cancel(_):
        raise AssertionError("no active execution")

    with provider_context(ApplicationProviders(learning=runtime)):
        with pytest.raises(QuestionBankReferenceConflict):
            await delete_session_lifecycle(runtime.session_store, cancel, session["id"])
    assert (await runtime.event_page("p"))["events"] == before
    assert (await runtime.session_store.get_session(session["id"]))["deleting"] is False


async def test_real_api_conflict_and_cross_owner_source(
    learning_runtime, business_actors, pg_session_store_factory
):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from deeptutor.api.routers.mastery_path import router

    runtime = learning_runtime
    await _seed_path(runtime)
    other_session = await pg_session_store_factory(
        business_actors.tenants[1].owners[0]
    ).create_session("foreign")
    session = await runtime.session_store.create_session("active")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=3
    )
    teaching = await runtime.for_turn(session["id"], turn["id"])
    await teaching.run(lambda u: u.acquire_path_lease("p", session["id"], turn["id"]))
    app = FastAPI()
    app.include_router(router)
    async with (
        runtime.bind(),
        AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client,
    ):
        assert (await client.patch("/progress/p", json={"name": "blocked"})).status_code == 409
        response = await client.post(
            "/topics",
            json={
                "name": "foreign",
                "goal": "g",
                "sources": [{"kind": "chat", "source_id": other_session["id"], "label": "foreign"}],
            },
        )
        assert response.status_code == 403, response.text


async def test_stale_card_reply_is_rejected_before_model_start(learning_runtime):
    from types import SimpleNamespace

    from deeptutor.capabilities.mastery.tools import MasteryQuizTool, MasterySkipQuestionTool
    from deeptutor.learning.service import StaleInteractionError
    from deeptutor.services.session.turns.learning_adapter import LearningTurnAdapter

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("stale")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=8
    )
    teaching = await runtime.for_turn(session["id"], turn["id"])
    await teaching.run(lambda u: u.acquire_path_lease("p", session["id"], turn["id"]))
    kwargs = {"_mastery_path_id": "p", "_session_id": session["id"], "_turn_id": turn["id"]}
    async with teaching.bind():
        old = await MasteryQuizTool().execute(
            **kwargs,
            knowledge_point_id="k",
            question="old",
            expected_answer="old",
            question_type="short",
        )
        await MasterySkipQuestionTool().execute(**kwargs)
        new = await MasteryQuizTool().execute(
            **kwargs,
            knowledge_point_id="k",
            question="new",
            expected_answer="new",
            question_type="short",
        )
    before = await runtime.run(lambda u: u.load("p"))
    adapter = LearningTurnAdapter()
    adapter._executions = {turn["id"]: SimpleNamespace(learning_runtime=teaching)}
    with pytest.raises(StaleInteractionError):
        await adapter._commit_mastery_card_answer(
            path_id="p",
            session_id=session["id"],
            turn_id=turn["id"],
            question_id=old.metadata["mastery_quiz"]["question_id"],
            answer="late",
        )
    after = await runtime.run(lambda u: u.load("p"))
    assert after.version == before.version
    assert after.pending_question.question_id == new.metadata["mastery_quiz"]["question_id"]


async def test_actual_capability_binds_real_turn_and_releases_on_failure(
    learning_runtime, monkeypatch
):
    from deeptutor.capabilities.mastery.capability import MasteryLoopPipeline, MasteryPathCapability
    from deeptutor.capabilities.mastery.tools import MasteryQuizTool
    from deeptutor.core.context import UnifiedContext
    from deeptutor.learning.runtime import get_learning_runtime
    from deeptutor.runtime.stream_bus import StreamBus

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("capability")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=9
    )

    async def deterministic_turn(_self, context, stream):
        # 仅替换模型驱动的loop：capability、authority、tools和PG全用产品实现。
        bound = get_learning_runtime()
        assert bound.authority.turn_id == turn["id"]
        result = await MasteryQuizTool().execute(
            _mastery_path_id="p",
            _session_id=session["id"],
            _turn_id=turn["id"],
            knowledge_point_id="k",
            question="synthetic",
            expected_answer="synthetic",
            question_type="short",
        )
        assert result.success
        raise ValueError("synthetic loop failure")

    from types import SimpleNamespace

    from deeptutor.agents.loop import pipeline as loop_module

    monkeypatch.setattr(
        loop_module, "get_llm_config", lambda: SimpleNamespace(model="synthetic-no-call")
    )
    monkeypatch.setattr(loop_module, "get_chat_params", lambda: {})
    monkeypatch.setattr(MasteryLoopPipeline, "run", deterministic_turn)
    context = UnifiedContext(
        session_id=session["id"],
        user_message="synthetic",
        metadata={"mastery_path_id": "p", "turn_id": turn["id"]},
    )
    async with runtime.bind():
        with pytest.raises(ValueError, match="synthetic loop failure"):
            await MasteryPathCapability().run(context, StreamBus())
    assert await runtime.run(lambda u: u.get_path_lease("p")) is None
    assert (await runtime.run(lambda u: u.load("p"))).pending_question.prompt == "synthetic"


async def test_course_unsupported_source_index_is_explicit_upgrade_error(learning_runtime):
    from deeptutor.learning.runtime import LearningProviderUnavailable
    from deeptutor.services.courses_state import _safe_index

    async def old_loader():
        raise AssertionError("legacy source must not be probed")

    async with learning_runtime.bind():
        with pytest.raises(LearningProviderUnavailable):
            await _safe_index("book", old_loader)


async def test_teaching_tool_requires_typed_turn_not_client_ids(learning_runtime):
    from deeptutor.capabilities.mastery.tools import MasteryQuizTool

    runtime = learning_runtime
    await _seed_path(runtime)
    session = await runtime.session_store.create_session("not-authority")
    turn = await runtime.session_store.begin_turn(
        session["id"], owner_id=runtime.executor.execution_id, fencing_token=11
    )
    before = await runtime.run(lambda u: u.load("p"))
    async with runtime.bind():
        with pytest.raises(RuntimeError, match="turn authority"):
            await MasteryQuizTool().execute(
                _mastery_path_id="p",
                _session_id=session["id"],
                _turn_id=turn["id"],
                knowledge_point_id="k",
                question="untrusted",
                expected_answer="a",
                question_type="short",
            )
    assert (await runtime.run(lambda u: u.load("p"))).version == before.version


async def test_managed_capability_flag_is_not_execution_authority(learning_runtime, monkeypatch):
    from deeptutor.capabilities.mastery import capability
    from deeptutor.core.context import UnifiedContext
    from deeptutor.runtime.stream_bus import StreamBus

    def forbidden(*a, **kw):
        raise AssertionError("model configuration must not be loaded before authority check")

    monkeypatch.setattr(capability, "MasteryLoopPipeline", forbidden)
    async with learning_runtime.bind():
        with pytest.raises(RuntimeError, match="turn authority"):
            await capability.MasteryPathCapability().run(
                UnifiedContext(
                    session_id="client",
                    user_message="x",
                    metadata={"mastery_path_id": "p", "mastery_path_lease_managed": True},
                ),
                StreamBus(),
            )
