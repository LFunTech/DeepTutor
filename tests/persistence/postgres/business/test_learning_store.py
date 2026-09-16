"""学习聚合真实 PG 合同；每次公开操作均经过有界 worker 和可信 actor。"""

import asyncio
import importlib.util
import threading

import pytest

from deeptutor.learning.event_hub import mastery_topic_event_hub
from deeptutor.learning.models import (
    InteractionStatus,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    MasteryInteraction,
    PendingQuestion,
    TopicMetadata,
    TopicSource,
    TopicSourceKind,
)

pytestmark = pytest.mark.asyncio


def _modules():
    return [
        LearningModule(
            id="m",
            name="模块",
            order=0,
            knowledge_points=[
                KnowledgePoint(id="kp", name="知识点", type=KnowledgeType.MEMORY, module_id="m")
            ],
        )
    ]


def _factory(database, pg_scope_factory, actor):
    assert importlib.util.find_spec("deeptutor.persistence.postgres.learning") is not None, (
        "PG LearningStore 尚未实现"
    )
    from deeptutor.persistence.postgres.learning import AsyncLearningStore

    return AsyncLearningStore(database, pg_scope_factory(actor))


async def test_aggregate_cas_atomic_mutation_and_committed_signal(
    business_sync_database, business_actors, pg_scope_factory
):
    store = _factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    progress = LearningProgress(book_id="algebra", modules=_modules())
    sub = mastery_topic_event_hub.subscribe("algebra", scope=store.event_scope)
    try:
        await store.run(lambda unit: unit.save(progress))
        assert progress.version == 1
        assert (await asyncio.wait_for(sub.get(), 1)).revision == 1
        a = await store.run(lambda unit: unit.load("algebra"))
        b = await store.run(lambda unit: unit.load("algebra"))
        a.name = "线性代数"
        await store.run(lambda unit: unit.save(a))
        from deeptutor.learning.contracts import LearningConflictError

        with pytest.raises(LearningConflictError) as caught:
            await store.run(lambda unit: unit.save(b))
        assert (caught.value.expected, caught.value.actual) == (1, 2)
        await asyncio.wait_for(sub.get(), 1)

        def fail(unit):
            with unit.transaction("algebra") as tx:
                tx.progress.name = "不应提交"
                tx.put_topic(TopicMetadata(path_id="algebra", goal="rollback"), [])
                tx.put_interaction(
                    MasteryInteraction(
                        interaction_id="q",
                        path_id="algebra",
                        question=PendingQuestion(question_id="q", knowledge_point_id="kp"),
                    )
                )
                tx.emit("question.registered", {"question_id": "q"})
                raise ValueError("rollback all")

        with pytest.raises(ValueError, match="rollback all"):
            await store.run(fail)
        await asyncio.sleep(0)
        assert sub.queue.empty()
        loaded = await store.run(lambda unit: unit.load("algebra"))
        assert loaded.name == "线性代数" and loaded.version == 2
        assert await store.run(lambda unit: unit.get_interaction("algebra", "q")) is None
        assert (await store.run(lambda unit: unit.get_topic("algebra"))).metadata.goal == ""
        assert len(await store.run(lambda unit: unit.list_events("algebra"))) == 2
    finally:
        sub.close()


async def test_mutations_serialize_and_noop_does_not_bump_revision(
    business_sync_database, business_actors, pg_scope_factory
):
    store = _factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    await store.run(lambda unit: unit.save(LearningProgress(book_id="p")))

    def mutate(unit, key):
        with unit.transaction("p") as tx:
            tx.progress.mastery_levels[key] = 0.5
            tx.touch()

    await asyncio.gather(
        *(store.run(lambda unit, key=key: mutate(unit, key)) for key in ("a", "b"))
    )
    loaded = await store.run(lambda unit: unit.load("p"))
    assert loaded.version == 3 and loaded.mastery_levels == {"a": 0.5, "b": 0.5}
    await store.run(lambda unit: unit.mutate("p", lambda tx: None))
    assert (await store.run(lambda unit: unit.load("p"))).version == 3


async def test_owner_isolation_same_ids_and_factory_rejects_forged_actor(
    business_sync_database, business_actors, pg_scope_factory
):
    actors = [*business_actors.tenants[0].owners, business_actors.tenants[1].owners[0]]
    stores = [_factory(business_sync_database, pg_scope_factory, actor) for actor in actors]
    for i, store in enumerate(stores):
        await store.run(
            lambda unit, i=i: unit.save(LearningProgress(book_id="same", name=f"private-{i}"))
        )
    assert len({store.event_scope for store in stores}) == 3
    for i, store in enumerate(stores):
        assert (await store.run(lambda unit: unit.load("same"))).name == f"private-{i}"
        assert await store.run(lambda unit: unit.list_all()) == ["same"]
    admin = _factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].admin)
    assert await admin.run(lambda unit: unit.load("same")) is None
    with pytest.raises(TypeError):
        _factory(business_sync_database, pg_scope_factory, actors[0].scope)


async def test_interaction_state_machine_event_cursor_and_redaction(
    business_sync_database, business_actors, pg_scope_factory
):
    store = _factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])

    def create(unit):
        with unit.transaction("p", create=True) as tx:
            tx.progress.modules = _modules()
            tx.put_interaction(
                MasteryInteraction(
                    interaction_id="q",
                    path_id="p",
                    question=PendingQuestion(
                        question_id="q", knowledge_point_id="kp", expected_answer="SECRET"
                    ),
                )
            )
            for i in range(7):
                tx.emit(
                    "question.changed",
                    {"i": i, "expected_answer": "SECRET", "nested": {"expected_answer": "SECRET"}},
                )

    await store.run(create)
    events = []
    cursor = None
    while True:
        page = await store.run(lambda unit: unit.list_event_page("p", cursor=cursor, limit=2))
        events.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(events) == 8 and len({e.id for e in events}) == 8
    assert {e.revision for e in events} == {1}
    assert "SECRET" not in str([e.payload for e in events])
    assert await store.run(lambda unit: unit.list_events("p", after_revision=1)) == []

    def grade(unit):
        with unit.transaction("p") as tx:
            q = tx.get_interaction("q")
            q.status = InteractionStatus.GRADED
            tx.put_interaction(q)

    await store.run(grade)
    from deeptutor.learning.contracts import LearningStoreError

    def reopen(unit):
        with unit.transaction("p") as tx:
            q = tx.get_interaction("q")
            q.status = InteractionStatus.REGISTERED
            tx.put_interaction(q)

    with pytest.raises(LearningStoreError, match="transition"):
        await store.run(reopen)
    assert await store.run(lambda unit: unit.get_active_interaction("p")) is None


async def test_transaction_handles_expire_and_cannot_cross_threads(
    business_sync_database, business_actors, pg_scope_factory
):
    store = _factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    saved = []

    def capture(unit):
        saved.append(unit)
        with unit.transaction("p", create=True) as tx:
            saved.append(tx)
            errors = []

            def bad():
                try:
                    tx.touch()
                except RuntimeError as exc:
                    errors.append(str(exc))

            thread = threading.Thread(target=bad)
            thread.start()
            thread.join()
            assert errors and "owner" in errors[0]

    await store.run(capture)
    for operation in (lambda: saved[0].load("p"), saved[1].touch, lambda: saved[1].emit("late")):
        with pytest.raises(RuntimeError, match="inactive"):
            operation()


async def test_poison_rolls_back_caught_error_and_does_not_advance_saved_input(
    business_sync_database, business_actors, pg_scope_factory
):
    store = _factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    progress = LearningProgress(book_id="p")

    def caught(unit):
        unit.save(progress)
        try:
            with unit.transaction("p") as tx:
                tx.put_topic(TopicMetadata(path_id="p", goal="partial"), [])
                tx.put_topic(TopicMetadata(path_id="other"), [])
        except ValueError:
            pass

    from deeptutor.learning.contracts import LearningStoreError

    with pytest.raises(LearningStoreError, match="poisoned"):
        await store.run(caught)
    assert progress.version == 0
    assert await store.run(lambda unit: unit.load("p")) is None


async def test_topic_pages_and_compat_list_overflow_are_explicit(
    business_sync_database, business_actors, pg_scope_factory
):
    store = _factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])

    def seed(unit):
        for i in range(1001):
            with unit.transaction(f"p{i:04}", create=True) as tx:
                tx.put_topic(TopicMetadata(path_id=f"p{i:04}"), [])
                if i == 0:
                    for j in range(1001):
                        tx.emit("event", {"i": j})

    await store.run(seed)
    from deeptutor.learning.contracts import LearningPaginationRequired

    for query in (
        lambda u: u.list_events("p0000"),
        lambda u: u.list_topic_snapshots(),
        lambda u: u.list_all(),
    ):
        with pytest.raises(LearningPaginationRequired):
            await store.run(query)
    seen = []
    cursor = None
    while True:
        page = await store.run(lambda u: u.list_topic_page(cursor=cursor, limit=73))
        assert len(page.items) <= 73
        seen.extend(x[0].book_id for x in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(seen) == 1001 and len(set(seen)) == 1001
    assert await store.run(lambda u: u.has_active_topics()) is True


async def test_cancelled_worker_rolls_back_and_delays_input_and_signal(
    business_sync_database, business_actors, pg_scope_factory
):
    store = _factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    progress = LearningProgress(book_id="p")
    ready = threading.Event()
    release = threading.Event()
    sub = mastery_topic_event_hub.subscribe("p", scope=store.event_scope)

    def operation(unit):
        unit.save(progress)
        ready.set()
        assert release.wait(3)

    task = asyncio.create_task(store.run(operation))
    try:
        async with asyncio.timeout(3):
            while not ready.is_set():
                await asyncio.sleep(0.005)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and progress.version == 0
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert progress.version == 0 and sub.queue.empty()
        assert await store.run(lambda u: u.load("p")) is None
    finally:
        release.set()
        sub.close()


async def test_every_capped_list_has_a_real_page_alternative():
    from deeptutor.persistence.postgres.learning import PostgresLearningStore

    assert all(
        hasattr(PostgresLearningStore, name)
        for name in ("list_path_page", "list_session_page", "list_interaction_page")
    )


async def test_session_membership_scratch_ownership_and_bounded_pages(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    actor = business_actors.tenants[0].owners[0]
    store = _factory(business_sync_database, pg_scope_factory, actor)
    sessions = pg_session_store_factory(actor)
    a = (await sessions.create_session("a"))["id"]
    b = (await sessions.create_session("b"))["id"]
    await store.run(lambda u: u.bind_session("scratch", a, owns_path=True))
    await store.run(lambda u: u.bind_session("scratch", b))
    assert set(await store.run(lambda u: u.list_session_ids("scratch"))) == {a, b}
    assert await store.run(lambda u: u.detach_session(a)) == []
    assert await store.run(lambda u: u.detach_session(b)) == []
    assert await store.run(lambda u: u.exists("scratch"))
    await store.run(lambda u: u.bind_session("built", a, owns_path=True))
    p = await store.run(lambda u: u.load("built"))
    p.modules = _modules()
    await store.run(lambda u: u.save(p))
    await store.run(lambda u: u.bind_session("moved", a))
    assert await store.run(lambda u: u.list_session_ids("built")) == []
    assert await store.run(lambda u: u.path_id_for_session(a)) == "moved"
    assert await store.run(lambda u: u.detach_session(a)) == []
    assert await store.run(lambda u: u.exists("built"))
    page = await store.run(lambda u: u.list_path_page(limit=1))
    assert page.items == ["built"] and page.next_cursor
    assert (
        await store.run(lambda u: u.list_path_page(cursor=page.next_cursor, limit=1))
    ).items == ["moved"]


@pytest.mark.parametrize("outcome", ["committed", "connection_lost"])
async def test_real_commit_boundary_preserves_input_and_signal_semantics(
    outcome, migrated_pg, business_sync_database, business_actors, pg_scope_factory
):
    import psycopg

    from deeptutor.persistence.postgres.connection import CommitCompletedAfterCancellation

    store = _factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    progress = LearningProgress(book_id="boundary")
    sub = mastery_topic_event_hub.subscribe("boundary", scope=store.event_scope)
    with psycopg.connect(migrated_pg.admin_dsn, autocommit=True) as admin:
        admin.execute(
            "CREATE FUNCTION enterprise.delay_learning_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_lock(11673193); PERFORM pg_advisory_unlock(11673193); RETURN NEW; END $$"
        )
        admin.execute(
            "CREATE CONSTRAINT TRIGGER delayed AFTER INSERT ON enterprise.mastery_paths DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enterprise.delay_learning_commit()"
        )
        admin.execute("SELECT pg_advisory_lock(11673193)")
        task = asyncio.create_task(store.run(lambda u: (u.save(progress), "result")[1]))
        try:
            async with asyncio.timeout(3):
                while True:
                    row = admin.execute(
                        "SELECT pid FROM pg_stat_activity WHERE datname=current_database() AND wait_event='advisory'"
                    ).fetchone()
                    if row:
                        break
                    await asyncio.sleep(0.005)
            assert progress.version == 0 and sub.queue.empty()
            task.cancel()
            await asyncio.sleep(0)
            if outcome == "connection_lost":
                admin.execute("SELECT pg_terminate_backend(%s)", (row[0],))
            admin.execute("SELECT pg_advisory_unlock(11673193)")
            if outcome == "committed":
                with pytest.raises(CommitCompletedAfterCancellation) as caught:
                    await task
                assert caught.value.result == "result"
                assert progress.version == 1
                assert (await asyncio.wait_for(sub.get(), 1)).revision == 1
                assert (await store.run(lambda u: u.load("boundary"))).version == 1
            else:
                with pytest.raises(psycopg.OperationalError):
                    await task
                assert progress.version == 0 and sub.queue.empty()
                assert await store.run(lambda u: u.load("boundary")) is None
        finally:
            admin.execute("SELECT pg_advisory_unlock_all()")
            sub.close()


async def test_precommit_guard_failure_and_callback_lazy_results_are_rejected(
    business_sync_database, business_actors, pg_scope_factory
):
    store = _factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    progress = LearningProgress(book_id="guard")
    calls = []

    def guard():
        calls.append(1)
        if len(calls) == 2:
            raise PermissionError("execution lost")

    business_sync_database.execution_guard = guard
    try:
        with pytest.raises(PermissionError, match="execution lost"):
            await store.run(lambda u: u.save(progress))
    finally:
        business_sync_database.execution_guard = None
    assert progress.version == 0 and await store.run(lambda u: u.load("guard")) is None

    def lazy(u):
        u.save(progress)
        return u.iter_events("guard")

    with pytest.raises(TypeError, match="synchronously"):
        await store.run(lazy)
    assert progress.version == 0 and await store.run(lambda u: u.load("guard")) is None


async def test_two_connections_only_one_active_question_and_cross_path_id_rejected(
    business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.learning.contracts import LearningStoreError

    store = _factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    await store.run(lambda u: u.save(LearningProgress(book_id="p", modules=_modules())))

    def put(u, qid, path="p"):
        with u.transaction(path, create=True) as tx:
            tx.progress.modules = _modules()
            tx.put_interaction(
                MasteryInteraction(
                    interaction_id=qid,
                    path_id=path,
                    question=PendingQuestion(question_id=qid, knowledge_point_id="kp"),
                )
            )
            tx.emit("question", {"question_id": qid})

    results = await asyncio.gather(
        *(store.run(lambda u, qid=qid: put(u, qid)) for qid in ("a", "b")), return_exceptions=True
    )
    assert sum(isinstance(r, LearningStoreError) for r in results) == 1
    active = await store.run(lambda u: u.get_active_interaction("p"))
    with pytest.raises(ValueError, match="another path"):
        await store.run(lambda u: put(u, active.interaction_id, "other"))
    assert await store.run(lambda u: u.load("other")) is None
    assert len(await store.run(lambda u: u.list_events("p"))) == 2


async def test_all_learning_tables_are_private_to_owner_even_for_admin(
    migrated_pg, business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    from deeptutor.persistence.postgres.executor import ExecutorLease
    from deeptutor.persistence.postgres.learning import AsyncLearningStore, ExecutionAuthority

    actor = business_actors.tenants[0].owners[0]
    scope = pg_scope_factory(actor)
    executor = ExecutorLease(migrated_pg.runtime_dsn, resource=business_sync_database.resource)
    await executor.acquire()
    try:
        store = AsyncLearningStore(
            business_sync_database, scope, authority=ExecutionAuthority(executor)
        )
        sid = (await pg_session_store_factory(actor).create_session("private"))["id"]

        def seed(u):
            with u.transaction("p", create=True) as tx:
                tx.progress.modules = _modules()
                tx.put_topic(
                    TopicMetadata(path_id="p", goal="PRIVATE"),
                    [TopicSource(id="goal", kind=TopicSourceKind.GOAL, label="PRIVATE")],
                )
                tx.put_interaction(
                    MasteryInteraction(
                        interaction_id="i",
                        path_id="p",
                        question=PendingQuestion(question_id="i", knowledge_point_id="kp"),
                    )
                )
            u.bind_session("p", sid, owns_path=True)
            return u.begin_path_operation("p")

        await store.run(seed)
        tables = [
            "mastery_paths",
            "mastery_knowledge_points",
            "mastery_path_sessions",
            "mastery_topic_meta",
            "mastery_topic_sources",
            "mastery_interactions",
            "mastery_events",
            "mastery_path_operations",
            "mastery_path_leases",
        ]
        for other in (
            business_actors.tenants[0].owners[1],
            business_actors.tenants[0].admin,
            business_actors.tenants[1].owners[0],
        ):

            def query(c):
                from psycopg import sql

                for table in tables:
                    assert (
                        c.execute(
                            sql.SQL("SELECT * FROM enterprise.{}").format(sql.Identifier(table))
                        ).fetchall()
                        == []
                    )
                    assert (
                        c.execute(
                            sql.SQL("DELETE FROM enterprise.{}").format(sql.Identifier(table))
                        ).rowcount
                        == 0
                    )

            await business_sync_database.run(pg_scope_factory(other), query)
        assert (await store.run(lambda u: u.load("p"))).version == 1
    finally:
        await executor.close()


async def test_factory_and_sync_entry_fail_closed(
    pg_learning_store_factory, business_actors, business_sync_database, pg_scope_factory
):
    from deeptutor.persistence.postgres.learning import PostgresLearningStore

    actor = business_actors.tenants[0].owners[0]
    store = pg_learning_store_factory(actor)
    assert await store.run(lambda u: u.load("missing")) is None
    with pytest.raises(TypeError):
        pg_learning_store_factory(actor.scope)
    sync = PostgresLearningStore(business_sync_database, pg_scope_factory(actor))
    with pytest.raises(RuntimeError, match="event loop"):
        sync.load("p")


async def test_close_waits_for_learning_unit_and_returns_no_fake_success(
    migrated_pg, business_actors, pg_scope_factory
):
    from psycopg_pool import PoolClosed

    from deeptutor.persistence.postgres.connection import SyncDatabase
    from deeptutor.persistence.postgres.learning import AsyncLearningStore

    scope = pg_scope_factory(business_actors.tenants[0].owners[0])
    db = SyncDatabase(migrated_pg.runtime_dsn, resource="learning-close", max_size=1)
    await db.__aenter__()
    store = AsyncLearningStore(db, scope)
    progress = LearningProgress(book_id="p")
    entered = threading.Event()
    release = threading.Event()

    def work(u):
        u.save(progress)
        entered.set()
        assert release.wait(3)

    task = asyncio.create_task(store.run(work))
    async with asyncio.timeout(3):
        while not entered.is_set():
            await asyncio.sleep(0.005)
    close = asyncio.create_task(db.__aexit__(None, None, None))
    await asyncio.sleep(0.02)
    assert not close.done() and progress.version == 0
    with pytest.raises(PoolClosed):
        await store.run(lambda u: u.load("p"))
    release.set()
    await task
    await close
    assert progress.version == 1 and db.pool.closed


async def test_real_learning_service_duplicate_grade_and_legacy_choice_repair(
    business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.learning.service import LearningService

    store = _factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    await store.run(lambda u: u.save(LearningProgress(book_id="p", modules=_modules())))
    pending = PendingQuestion(
        question_id="q",
        knowledge_point_id="kp",
        question_type="choice",
        expected_answer="A",
        prompt="选择甲",
    )
    _, question, created = await store.run(
        lambda u: LearningService(u).register_question("p", pending)
    )
    assert created
    duplicate = pending.model_copy(update={"expected_answer": "B", "prompt": "not replacement"})
    _, replayed, created = await store.run(
        lambda u: LearningService(u).register_question("p", duplicate)
    )
    assert not created and replayed.question.prompt == question.question.prompt
    progress, graded, replayed = await store.run(
        lambda u: LearningService(u).grade_interaction(
            "p",
            answer="A",
            question_id="q",
            expected_answer="A",
            resolved_choice_options={"A": "甲", "B": "乙"},
        )
    )
    assert (
        not replayed
        and graded.result["is_correct"]
        and graded.question.choice_map == {"A": "甲", "B": "乙"}
    )
    again, stored, replayed = await store.run(
        lambda u: LearningService(u).grade_interaction("p", answer="B", question_id="q")
    )
    assert (
        replayed
        and stored.result == graded.result
        and len(again.quiz_attempts) == len(progress.quiz_attempts) == 1
    )


@pytest.mark.parametrize("read_kind", ["page", "get_topic"])
@pytest.mark.parametrize("mutation", ["delete", "replace"])
async def test_topic_reads_keep_one_snapshot_during_concurrent_unit(
    pg_learning_store_factory,
    pg_session_store_factory,
    business_actors,
    monkeypatch,
    read_kind,
    mutation,
):
    """首条真实路径读取完成后另unit提交；整页与单topic不能拼接前后版本。"""
    from deeptutor.persistence.postgres.learning.base import StoreBase

    actor = business_actors.tenants[0].owners[0]
    store = pg_learning_store_factory(actor)
    sessions = pg_session_store_factory(actor)
    before_session = await sessions.create_session("before")
    after_session = await sessions.create_session("after")

    def write(unit, label, *, create=False):
        with unit.transaction("snapshot", create=create) as tx:
            tx.progress.name = label
            tx.progress.modules = _modules()
            tx.abandon_active_interactions()
            tx.put_interaction(
                MasteryInteraction(
                    interaction_id=label,
                    path_id="snapshot",
                    question=PendingQuestion(question_id=label, knowledge_point_id="kp"),
                )
            )
            tx.put_topic(
                TopicMetadata(path_id="snapshot", goal=label),
                [TopicSource(id=label, kind=TopicSourceKind.GOAL, label=label)],
            )
            tx.touch()
        unit.bind_session("snapshot", (before_session if create else after_session)["id"])

    await store.run(lambda unit: write(unit, "before", create=True))
    ready, release = threading.Event(), threading.Event()
    original = StoreBase._execute

    def execute(unit, sql, params=()):
        result = original(unit, sql, params)
        # 只控制真实SQL返回时机；不改语句、结果、异常或共享事务隔离。
        if "FROM enterprise.mastery_paths" in sql and not ready.is_set():
            ready.set()
            assert release.wait(10), "topic snapshot coordination timed out"
        return result

    monkeypatch.setattr(StoreBase, "_execute", execute)
    read = asyncio.create_task(
        store.run(
            lambda unit: (
                unit.list_topic_page(limit=1) if read_kind == "page" else unit.get_topic("snapshot")
            )
        )
    )
    try:
        async with asyncio.timeout(10):
            while not ready.is_set():
                await asyncio.sleep(0.005)
        if mutation == "delete":
            await store.run(lambda unit: unit.delete("snapshot"))
        else:
            await store.run(lambda unit: write(unit, "after"))
        release.set()
        result = await read
        if read_kind == "page":
            assert len(result.items) == 1 and result.next_cursor is None
            progress, topic, count, active = result.items[0]
            assert (progress.name, progress.version, count) == ("before", 1, 1)
            assert active.interaction_id == "before"
            assert active.status == InteractionStatus.REGISTERED
        else:
            topic = result
        assert topic.metadata.goal == "before"
        assert [(source.id, source.label) for source in topic.sources] == [("before", "before")]
        current = await store.run(lambda unit: unit.get_topic("snapshot"))
        if mutation == "delete":
            assert current is None
        else:
            assert current.metadata.goal == "after"
            assert [source.label for source in current.sources] == ["after"]
            current_page = await store.run(lambda unit: unit.list_topic_page())
            assert current_page.items[0][2] == 2
            assert current_page.items[0][3].interaction_id == "after"
    finally:
        release.set()
        await asyncio.gather(read, return_exceptions=True)


@pytest.mark.parametrize("kind", ["topics:active", "sessions:p", "interactions:p"])
async def test_cursor_numeric_overflow_is_a_value_error_through_pg_facade(
    pg_learning_store_factory, business_actors, kind
):
    from deeptutor.learning.contracts import LearningPage

    store = pg_learning_store_factory(business_actors.tenants[0].owners[0])
    await store.run(lambda unit: unit.save(LearningProgress(book_id="p")))

    def query(unit, number):
        cursor = unit._cursor(kind, [number, "p"])
        if kind.startswith("topics:"):
            return unit.list_topic_page(cursor=cursor)
        if kind.startswith("sessions:"):
            return unit.list_session_page("p", cursor=cursor)
        return unit.list_interaction_page("p", cursor=cursor)

    with pytest.raises(ValueError, match="invalid learning cursor"):
        await store.run(lambda unit: query(unit, 10**1000))
    # 有限大整数/浮点数仍是合法游标，不能用粗暴长度或整数禁用代替溢出归一。
    for number in (0, 10**308, 1e308):
        result = await store.run(lambda unit: query(unit, number))
        assert isinstance(result, LearningPage)


async def test_get_topic_fallback_uses_persisted_snapshot_not_stale_progress(
    pg_learning_store_factory, business_actors
):
    store = pg_learning_store_factory(business_actors.tenants[0].owners[0])
    await store.run(lambda unit: unit.save(LearningProgress(book_id="p")))
    persisted = await store.run(lambda unit: unit.load("p"))
    stale = persisted.model_copy(update={"created_at": 1, "updated_at": 1})
    topic = await store.run(lambda unit: unit.get_topic("p", progress=stale))
    assert topic.metadata.created_at == persisted.created_at
    assert topic.metadata.updated_at == persisted.updated_at
    with pytest.raises(ValueError, match="does not belong"):
        await store.run(lambda unit: unit.get_topic("other", progress=stale))
