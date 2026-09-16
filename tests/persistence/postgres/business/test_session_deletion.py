"""删除门禁、既有跨域 FK 受控拒绝与代际回调。"""

import pytest

from deeptutor.services.session.question_bank import QuestionBankReferenceConflict

pytestmark = pytest.mark.asyncio


async def test_known_reference_conflict_releases_gate_without_losing_reference(
    pg_session_store_factory, pg_learning_store_factory, business_actors
):
    actor = business_actors.tenants[0].owners[0]
    store, learning = pg_session_store_factory(actor), pg_learning_store_factory(actor)
    await store.create_session(session_id="s")
    await learning.run(lambda u: u.bind_session("path", "s", owns_path=True))
    token = await store.claim_deletion("s")
    assert token
    with pytest.raises(QuestionBankReferenceConflict):
        await store.delete_session("s", deletion_token=token)
    assert not (await store.get_session("s"))["deleting"]
    assert await learning.run(lambda u: u.path_id_for_session("s")) == "path"
    assert await store.begin_turn("s")


async def test_old_delete_token_cannot_delete_recreated_session(
    pg_session_store_factory, business_actors
):
    store = pg_session_store_factory(business_actors.tenants[0].owners[0])
    await store.create_session(session_id="s")
    old = await store.claim_deletion("s")
    assert await store.delete_session("s", deletion_token=old)
    await store.create_session(session_id="s")
    with pytest.raises(RuntimeError, match="generation|token"):
        await store.delete_session("s", deletion_token=old)
    assert await store.get_session("s")
    assert not (await store.get_session("s"))["deleting"]


async def test_gate_blocks_new_dispatch_and_learning_binding(
    pg_session_store_factory, pg_learning_store_factory, business_actors
):
    actor = business_actors.tenants[0].owners[0]
    store, learning = pg_session_store_factory(actor), pg_learning_store_factory(actor)
    await store.create_session(session_id="s")
    await store.mark_deleting("s")
    with pytest.raises(RuntimeError):
        await store.begin_turn("s")
    with pytest.raises((ValueError, RuntimeError)):
        await learning.run(lambda u: u.bind_session("path", "s"))
    assert await learning.run(lambda u: u.path_id_for_session("s")) == ""


async def test_application_deletion_gates_before_cancelling_and_cleans_files(
    pg_session_store_factory, business_actors, tmp_path
):
    from types import SimpleNamespace

    from deeptutor.app.service import TurnApplicationService
    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.persistence.postgres.session_resources import PostgresAttachmentStore
    from deeptutor.persistence.resources import OwnerResourceProvider

    store = pg_session_store_factory(business_actors.tenants[0].owners[0])
    resources = OwnerResourceProvider(tmp_path.absolute())
    files = PostgresAttachmentStore(store, resources)
    await store.create_session(session_id="s")
    url = await files.put(session_id="s", attachment_id="a", filename="a.txt", data=b"bytes")
    await store.add_message("s", "user", "x", attachments=[{"url": url}])
    physical = list(tmp_path.rglob("*.blob"))[0]
    turn = await store.begin_turn("s")

    async def cancel(turn_id):
        assert (await store.get_session("s"))["deleting"]
        with pytest.raises(RuntimeError):
            await store.begin_turn("s")
        await store.transition_turn(turn_id, "cancelled")
        return True

    service = TurnApplicationService(
        SimpleNamespace(get=lambda: store),
        SimpleNamespace(get=lambda _: SimpleNamespace(cancel_turn=cancel)),
        None,
    )
    # 单独替换取消外部执行机制，不替换 PG Store 或删除事务。
    service.cancel_turn = cancel
    with provider_context(ApplicationProviders(store=store, resources=resources)):
        assert await service.delete_session("s")
    assert await store.get_session("s") is None
    assert not physical.exists()


async def test_default_http_reference_conflict_is_409(
    pg_session_store_factory, pg_learning_store_factory, business_actors
):
    from types import SimpleNamespace

    from fastapi import FastAPI
    import httpx

    from deeptutor.api.routers.sessions import router
    from deeptutor.app.service import TurnApplicationService
    from deeptutor.core.providers import ApplicationProviders, provider_context

    actor = business_actors.tenants[0].owners[0]
    store, learning = pg_session_store_factory(actor), pg_learning_store_factory(actor)
    await store.create_session(session_id="s")
    await learning.run(lambda u: u.bind_session("path", "s", owns_path=True))
    service = TurnApplicationService(
        SimpleNamespace(get=lambda: store), SimpleNamespace(get=lambda _: None), None
    )
    app = FastAPI()
    app.include_router(router, prefix="/sessions")
    with provider_context(
        ApplicationProviders(store=store, container=SimpleNamespace(turns=service))
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            response = await client.delete("/sessions/s")
    assert response.status_code == 409
    assert not (await store.get_session("s"))["deleting"]


async def test_new_notebook_followup_and_reading_links_rejected_after_gate(
    pg_session_store_factory, business_actors, business_sync_database, pg_scope_factory
):
    from tests.persistence.postgres.business.test_reading_catalog import factory

    actor = business_actors.tenants[0].owners[0]
    store = pg_session_store_factory(actor)
    reading = factory(business_sync_database, pg_scope_factory, actor)
    for sid in ("source", "target"):
        await store.create_session(session_id=sid)
    await store.begin_turn("source", turn_id="synthetic")
    await store.transition_turn("synthetic", "completed")
    await store.upsert_notebook_entries(
        "source", [{"question_id": "q", "question": "Q", "turn_id": "synthetic"}]
    )
    entry = await store.find_notebook_entry("source", "q", "synthetic")

    def setup(u):
        u.create_workspace("w", [], workspace_id="w")
        u.attach_session("w", "source")
        u.attach_session("w", "target")

    await reading.run(setup)
    await store.mark_deleting("target")
    with pytest.raises((ValueError, RuntimeError)):
        await store.update_notebook_entry(entry["id"], {"followup_session_id": "target"})
    with pytest.raises((ValueError, RuntimeError)):
        await reading.run(lambda u: u.link_session("w", "source", "target"))
    assert (await store.get_notebook_entry(entry["id"]))["followup_session_id"] == ""


async def test_new_learning_event_rejected_after_gate(
    pg_session_store_factory, pg_learning_store_factory, business_actors
):
    actor = business_actors.tenants[0].owners[0]
    store, learning = pg_session_store_factory(actor), pg_learning_store_factory(actor)
    await store.create_session(session_id="s")
    await store.mark_deleting("s")

    def event(u):
        with u.transaction("path", create=True) as tx:
            tx.emit("synthetic", session_id="s")

    with pytest.raises((ValueError, RuntimeError)):
        await learning.run(event)
    assert await learning.run(lambda u: u.load("path")) is None


async def test_message_route_cleans_last_object_and_reports_pending(
    pg_session_store_factory, business_actors, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from fastapi import FastAPI
    import httpx

    from deeptutor.api.routers.sessions import router
    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.persistence.postgres.session_resources import PostgresAttachmentStore
    from deeptutor.persistence.resources import OwnerResourceProvider

    actor = business_actors.tenants[0].owners[0]
    store = pg_session_store_factory(actor)
    resources = OwnerResourceProvider(tmp_path.absolute())
    files = PostgresAttachmentStore(store, resources)
    await store.create_session(session_id="s")
    url = await files.put(session_id="s", attachment_id="a", filename="a", data=b"x")
    mid = await store.add_message("s", "user", "x", attachments=[{"url": url}])
    physical = list(tmp_path.rglob("*.blob"))[0]

    def failure(*args):
        raise OSError("synthetic physical cleanup failure")

    monkeypatch.setattr(PostgresAttachmentStore, "_delete_object", failure)
    app = FastAPI()
    app.include_router(router, prefix="/sessions")
    with provider_context(
        ApplicationProviders(store=SimpleNamespace(get=lambda: store), resources=resources)
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.delete(f"/sessions/s/messages/{mid}")
    assert response.status_code == 202
    assert response.json()["cleanup"]["pending"] == 1
    assert physical.exists()
    assert await store.get_messages("s") == []


async def test_compatibility_mark_then_delete_conflict_recovers_gate(
    pg_session_store_factory, pg_learning_store_factory, business_actors
):
    actor = business_actors.tenants[0].owners[0]
    store, learning = pg_session_store_factory(actor), pg_learning_store_factory(actor)
    await store.create_session(session_id="s")
    await learning.run(lambda u: u.bind_session("path", "s", owns_path=True))
    assert await store.mark_deleting("s")
    with pytest.raises(QuestionBankReferenceConflict):
        await store.delete_session("s")
    assert not (await store.get_session("s"))["deleting"]


async def test_active_cancel_pending_is_typed_conflict(pg_session_store_factory, business_actors):
    from deeptutor.services.session.deletion import delete_session_lifecycle

    store = pg_session_store_factory(business_actors.tenants[0].owners[0])
    await store.create_session(session_id="s")
    await store.begin_turn("s")

    async def not_stopped(_):
        return False

    with pytest.raises(QuestionBankReferenceConflict, match="not stopped"):
        await delete_session_lifecycle(store, not_stopped, "s")
    assert (await store.get_session("s"))["deleting"]


@pytest.mark.parametrize("method", ["delete_message", "delete_turn_by_message"])
async def test_message_delete_learning_event_fk_is_controlled_and_atomic(
    method, pg_session_store_factory, pg_learning_store_factory, business_actors
):
    actor = business_actors.tenants[0].owners[0]
    store, learning = pg_session_store_factory(actor), pg_learning_store_factory(actor)
    await store.create_session(session_id="s")
    mid = await store.add_message("s", "user", "x")
    await store.begin_turn("s", turn_id="t")
    await store.link_turn_user_message("t", mid)
    await store.transition_turn("t", "completed")

    def event(u):
        with u.transaction("path", create=True) as tx:
            tx.emit("synthetic", session_id="s", turn_id="t")

    await learning.run(event)
    with pytest.raises(QuestionBankReferenceConflict):
        if method == "delete_message":
            await store.delete_message(mid)
        else:
            await store.delete_turn_by_message("s", mid)
    assert (await store.get_messages("s"))[0]["id"] == mid
    assert await store.get_turn("t")


async def test_missing_resource_provider_reports_persisted_cleanup_pending(
    pg_session_store_factory, business_actors, tmp_path
):
    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.persistence.postgres.session_resources import PostgresAttachmentStore
    from deeptutor.persistence.resources import OwnerResourceProvider
    from deeptutor.services.session.deletion import SessionCleanupPending, delete_session_lifecycle

    store = pg_session_store_factory(business_actors.tenants[0].owners[0])
    files = PostgresAttachmentStore(store, OwnerResourceProvider(tmp_path.absolute()))
    await store.create_session(session_id="s")
    url = await files.put(session_id="s", attachment_id="a", filename="a", data=b"x")
    await store.add_message("s", "user", "x", attachments=[{"url": url}])
    physical = list(tmp_path.rglob("*.blob"))[0]

    async def cancel(_):
        return True

    with provider_context(ApplicationProviders(store=store)):
        with pytest.raises(SessionCleanupPending) as pending:
            await delete_session_lifecycle(store, cancel, "s")
    assert pending.value.report["pending"] == 1
    assert await store.get_session("s") is None and physical.exists()
    assert (await files.cleanup_pending())["pending"] == 0
    assert not physical.exists()


async def test_new_question_bank_topic_source_rejected_after_session_gate(
    pg_session_store_factory, pg_learning_store_factory, business_actors
):
    from deeptutor.learning.models import (
        LearningProgress,
        TopicMetadata,
        TopicSource,
        TopicSourceKind,
    )

    actor = business_actors.tenants[0].owners[0]
    store, learning = pg_session_store_factory(actor), pg_learning_store_factory(actor)
    await store.create_session(session_id="s")
    await store.upsert_notebook_entries("s", [{"question_id": "q", "question": "Q"}])
    entry = await store.find_notebook_entry("s", "q")
    await learning.run(lambda u: u.save(LearningProgress(book_id="p")))
    await store.mark_deleting("s")
    with pytest.raises((ValueError, RuntimeError)):
        await learning.run(
            lambda u: u.put_topic(
                TopicMetadata(path_id="p"),
                [
                    TopicSource(
                        id="q",
                        kind=TopicSourceKind.QUESTION_BANK,
                        source_id=str(entry["id"]),
                        label="Q",
                    )
                ],
            )
        )


async def test_sync_learning_notebook_writer_obeys_session_gate(
    migrated_pg, business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    from deeptutor.learning.models import LearningProgress
    from deeptutor.persistence.postgres.executor import ExecutorLease
    from deeptutor.persistence.postgres.learning import AsyncLearningStore, ExecutionAuthority
    from tests.persistence.postgres.business.test_learning_store import _modules

    actor = business_actors.tenants[0].owners[0]
    scope = pg_scope_factory(actor)
    sessions = pg_session_store_factory(actor)
    await sessions.create_session(session_id="s")
    executor = ExecutorLease(migrated_pg.runtime_dsn, resource=business_sync_database.resource)
    await executor.acquire()
    try:
        turn = await sessions.begin_turn("s", owner_id=executor.execution_id, fencing_token=9)
        authority = await ExecutionAuthority.for_turn(
            executor, business_sync_database, scope, "s", turn["id"]
        )
        learning = AsyncLearningStore(business_sync_database, scope, authority=authority)
        await learning.run(lambda u: u.save(LearningProgress(book_id="p", modules=_modules())))
        await learning.run(lambda u: u.acquire_path_lease("p", "s", turn["id"]))
        await sessions.mark_deleting("s")

        def write(u):
            with u.transaction("p"):
                u.upsert_mastery_notebook_entries(
                    "s",
                    [
                        {
                            "question_id": "q",
                            "question": "Q",
                            "source": "mastery_path",
                            "material_id": "p",
                            "section_id": "kp",
                            "turn_id": turn["id"],
                        }
                    ],
                )

        with pytest.raises((ValueError, RuntimeError)):
            await learning.run(write)
        assert await sessions.find_notebook_entry("s", "q", turn_id=turn["id"]) is None
    finally:
        await executor.close()
