"""学习来源FK/当前活跃引用验证，retired历史保持同scope合法引用。"""

import pytest

from deeptutor.learning.models import LearningProgress, TopicMetadata, TopicSource, TopicSourceKind
from tests.persistence.postgres.business.test_learning_store import _factory, _modules

pytestmark = pytest.mark.asyncio


async def test_retired_kp_keeps_history_but_new_notebook_provenance_is_rejected(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    actor = business_actors.tenants[0].owners[0]
    learning = _factory(business_sync_database, pg_scope_factory, actor)
    sessions = pg_session_store_factory(actor)
    session = await sessions.create_session("source")
    await learning.run(lambda u: u.save(LearningProgress(book_id="path", modules=_modules())))
    item = dict(
        question_id="q", question="问题", source="mastery_path", material_id="path", section_id="kp"
    )
    await sessions.upsert_notebook_entries(session["id"], [item])
    progress = await learning.run(lambda u: u.load("path"))
    progress.modules = []
    await learning.run(lambda u: u.save(progress))
    assert (
        await sessions.upsert_notebook_entries(session["id"], [dict(item, user_answer="历史重试")])
        == 1
    )
    from deeptutor.services.session.question_bank import QuestionBankReferenceConflict

    with pytest.raises(QuestionBankReferenceConflict):
        await sessions.upsert_notebook_entries(session["id"], [dict(item, question_id="new")])
    with pytest.raises(QuestionBankReferenceConflict):
        await sessions.upsert_notebook_entries(session["id"], [dict(item, section_id="unknown")])
    from deeptutor.learning.contracts import LearningReferenceError

    with pytest.raises(LearningReferenceError):
        await learning.run(lambda u: u.delete("path"))
    assert (await learning.run(lambda u: u.load("path"))).version == 2


async def test_mixed_sources_typed_fk_owner_and_delete_consistency(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    actor = business_actors.tenants[0].owners[0]
    learning = _factory(business_sync_database, pg_scope_factory, actor)
    sessions = pg_session_store_factory(actor)
    session = await sessions.create_session("chat")
    await sessions.upsert_notebook_entries(session["id"], [dict(question_id="q", question="问题")])
    entry = await sessions.find_notebook_entry(session["id"], "q")
    await learning.run(lambda u: u.save(LearningProgress(book_id="p")))
    sources = [
        TopicSource(id="chat", kind=TopicSourceKind.CHAT, source_id=session["id"], label="会话"),
        TopicSource(
            id="entry", kind=TopicSourceKind.QUESTION_BANK, source_id=str(entry["id"]), label="错题"
        ),
    ]
    for kind in TopicSourceKind:
        if kind in (TopicSourceKind.CHAT, TopicSourceKind.QUESTION_BANK):
            continue
        sources.append(
            TopicSource(
                id=kind.value,
                kind=kind,
                source_id="external",
                label=kind.value,
                available=False,
                metadata={"provider": "later"},
            )
        )
    sources.append(
        TopicSource(
            id="partner", kind=TopicSourceKind.CHAT, source_id="partner:pid:key", label="伙伴"
        )
    )
    topic = await learning.run(lambda u: u.put_topic(TopicMetadata(path_id="p"), sources))
    assert len(topic.sources) == 10 and [s.position for s in topic.sources] == list(range(10))
    assert topic.sources[-1].source_id == "partner:pid:key"
    other = business_actors.tenants[0].owners[1]
    foreign = await pg_session_store_factory(other).create_session("foreign")
    from deeptutor.learning.contracts import LearningReferenceError

    with pytest.raises(LearningReferenceError):
        await learning.run(
            lambda u: u.put_topic(
                TopicMetadata(path_id="p"),
                [
                    TopicSource(
                        id="x",
                        kind=TopicSourceKind.CHAT,
                        source_id=foreign["id"],
                        label="forbidden",
                    )
                ],
            )
        )
    assert len((await learning.run(lambda u: u.get_topic("p"))).sources) == 10
    from deeptutor.services.session.question_bank import QuestionBankReferenceConflict

    with pytest.raises(QuestionBankReferenceConflict):
        await sessions.delete_notebook_entry(entry["id"])
    await learning.run(lambda u: u.delete("p"))
    assert await sessions.delete_notebook_entry(entry["id"]) is True


async def test_learning_atomic_notebook_boundary_exists():
    from deeptutor.persistence.postgres.learning import PostgresLearningStore

    assert hasattr(PostgresLearningStore, "upsert_mastery_notebook_entries")


@pytest.mark.parametrize("writer", ["notebook", "learning"])
async def test_shared_upsert_preserves_full_fields_and_atomicity(
    writer,
    migrated_pg,
    business_sync_database,
    business_actors,
    pg_scope_factory,
    pg_session_store_factory,
):
    from deeptutor.learning.models import MasteryInteraction, PendingQuestion
    from deeptutor.persistence.postgres.executor import ExecutorLease
    from deeptutor.persistence.postgres.learning import AsyncLearningStore, ExecutionAuthority

    actor = business_actors.tenants[0].owners[0]
    scope = pg_scope_factory(actor)
    sessions = pg_session_store_factory(actor)
    session = await sessions.create_session("atomic")
    executor = ExecutorLease(migrated_pg.runtime_dsn, resource=business_sync_database.resource)
    await executor.acquire()
    try:
        turn = await sessions.begin_turn(
            session["id"], owner_id=executor.execution_id, fencing_token=9
        )
        authority = await ExecutionAuthority.for_turn(
            executor, business_sync_database, scope, session["id"], turn["id"]
        )
        store = AsyncLearningStore(business_sync_database, scope, authority=authority)
        await store.run(lambda u: u.save(LearningProgress(book_id="p", modules=_modules())))
        await store.run(lambda u: u.acquire_path_lease("p", session["id"], turn["id"]))
        item = dict(
            question_id="q",
            question="测试问题",
            source="mastery_path",
            material_id="p",
            material_title="路径",
            section_id="kp",
            section_title="知识点",
            turn_id=turn["id"],
            question_type="choice",
            options={"A": "甲"},
            correct_answer="A",
            explanation="详解",
            difficulty="hard",
            user_answer="B",
            user_answer_images=[{"id": "image"}],
        )

        async def write(items):
            if writer == "notebook":
                return await sessions.upsert_notebook_entries(session["id"], items)

            def unit_work(u):
                with u.transaction("p"):
                    return u.upsert_mastery_notebook_entries(session["id"], items)

            return await store.run(unit_work)

        assert await write([item]) == 1
        first = await sessions.find_notebook_entry(session["id"], "q", turn_id=turn["id"])
        for key, value in item.items():
            assert first[key] == value
        update = dict(item, is_correct=True, user_answer="A")
        update.pop("user_answer_images")
        assert await write([update]) == 1
        improved = await sessions.find_notebook_entry(session["id"], "q", turn_id=turn["id"])
        assert (
            improved["id"] == first["id"]
            and improved["version"] == 2
            and improved["score_trend"] == "improved"
            and improved["resolved"]
        )
        assert improved["user_answer_images"] == item["user_answer_images"]
        assert await write([dict(update, user_answer_images=[])]) == 1
        assert (await sessions.get_notebook_entry(first["id"]))["user_answer_images"] == []
        if writer == "learning":
            before = await store.run(lambda u: u.load("p"))
            events = await store.run(lambda u: u.list_events("p"))

            def fail(u):
                with u.transaction("p") as tx:
                    tx.progress.name = "partial"
                    tx.put_interaction(
                        MasteryInteraction(
                            interaction_id="i",
                            path_id="p",
                            question=PendingQuestion(question_id="i", knowledge_point_id="kp"),
                        )
                    )
                    tx.emit("attempt", {"question_id": "i"})
                    u.upsert_mastery_notebook_entries(
                        session["id"],
                        [
                            dict(item, question_id="new"),
                            dict(item, question_id="bad", material_id="another"),
                        ],
                    )

            with pytest.raises(ValueError, match="path"):
                await store.run(fail)
            assert (await store.run(lambda u: u.load("p"))).version == before.version
            assert len(await store.run(lambda u: u.list_events("p"))) == len(events)
            assert await store.run(lambda u: u.get_interaction("p", "i")) is None
            assert (
                await sessions.find_notebook_entry(session["id"], "new", turn_id=turn["id"]) is None
            )

            def succeed(u):
                with u.transaction("p") as tx:
                    tx.progress.name = "committed together"
                    tx.put_interaction(
                        MasteryInteraction(
                            interaction_id="i",
                            path_id="p",
                            question=PendingQuestion(question_id="i", knowledge_point_id="kp"),
                        )
                    )
                    tx.emit("attempt", {"question_id": "i"})
                    return u.upsert_mastery_notebook_entries(
                        session["id"], [dict(item, question_id="new")]
                    )

            checkouts = business_sync_database.pool.get_stats()["requests_num"]
            assert await store.run(succeed) == 1
            assert business_sync_database.pool.get_stats()["requests_num"] == checkouts + 1
            assert (await store.run(lambda u: u.load("p"))).name == "committed together"
            assert await store.run(lambda u: u.get_interaction("p", "i")) is not None
            assert len(await store.run(lambda u: u.list_events("p"))) == len(events) + 1
            assert (
                await sessions.find_notebook_entry(session["id"], "new", turn_id=turn["id"])
                is not None
            )
    finally:
        await executor.close()


async def test_retire_and_new_notebook_insert_serialize_on_shared_owner_lock(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    import asyncio
    import threading

    from deeptutor.services.session.question_bank import QuestionBankReferenceConflict

    actor = business_actors.tenants[0].owners[0]
    learning = _factory(business_sync_database, pg_scope_factory, actor)
    sessions = pg_session_store_factory(actor)
    session = await sessions.create_session("race")
    await learning.run(lambda u: u.save(LearningProgress(book_id="p", modules=_modules())))
    entered = threading.Event()
    release = threading.Event()

    def retire(u):
        p = u.load("p")
        p.modules = []
        u.save(p)
        entered.set()
        assert release.wait(3)

    task = asyncio.create_task(learning.run(retire))
    try:
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.005)
        insert = asyncio.create_task(
            sessions.upsert_notebook_entries(
                session["id"],
                [
                    dict(
                        question_id="new",
                        question="q",
                        source="mastery_path",
                        material_id="p",
                        section_id="kp",
                    )
                ],
            )
        )
        await asyncio.sleep(0.04)
        assert not insert.done()
        release.set()
        await task
        with pytest.raises(QuestionBankReferenceConflict):
            await insert
        assert await sessions.find_notebook_entry(session["id"], "new") is None
    finally:
        release.set()
