"""真实 PG + 实际文件的取消/未知提交交错；不使用 SQLite 或模型。"""

import asyncio
from contextlib import asynccontextmanager
import threading

import pytest

from deeptutor.persistence.postgres.session_resources import PostgresAttachmentStore
from deeptutor.persistence.resources import OwnerResourceProvider

pytestmark = pytest.mark.asyncio


async def test_cancel_inflight_writer_drains_before_delete_cleanup(
    pg_session_store_factory, business_actors, tmp_path, monkeypatch
):
    store = pg_session_store_factory(business_actors.tenants[0].owners[0])
    files = PostgresAttachmentStore(store, OwnerResourceProvider(tmp_path.absolute()))
    await store.create_session(session_id="s")
    started, finish = threading.Event(), threading.Event()
    real_write = files._write_object

    def blocked_write(key, data):
        real_write(key, data)
        started.set()
        assert finish.wait(15), "test must release the real file writer"

    monkeypatch.setattr(files, "_write_object", blocked_write)
    writer = asyncio.create_task(
        files.put(session_id="s", attachment_id="a", filename="a", data=b"inflight")
    )
    try:
        assert await asyncio.to_thread(started.wait, 10)
        physical = list(tmp_path.rglob("*.blob"))[0]
        writer.cancel()
        assert await store.delete_session("s")
        cleanup = asyncio.create_task(files.cleanup_pending())
        await asyncio.sleep(0.05)
        assert not cleanup.done(), "cleanup must wait for the in-flight object lock"
    finally:
        finish.set()
    with pytest.raises(asyncio.CancelledError):
        await writer
    assert (await cleanup)["pending"] == 0
    assert not physical.exists()
    rows = await files.list_operations()
    assert rows == []


async def test_unknown_delete_commit_keeps_cleanup_and_old_token_cannot_touch_recreation(
    pg_session_store_factory, business_actors, tmp_path, monkeypatch
):
    store = pg_session_store_factory(business_actors.tenants[0].owners[0])
    files = PostgresAttachmentStore(store, OwnerResourceProvider(tmp_path.absolute()))
    await store.create_session(session_id="s")
    old_url = await files.put(session_id="s", attachment_id="a", filename="a", data=b"old")
    await store.add_message("s", "user", "old", attachments=[{"url": old_url}])
    old_path = list(tmp_path.rglob("*.blob"))[0]
    token = await store.claim_deletion("s")
    original = store.db.transaction

    @asynccontextmanager
    async def commit_then_unknown(scope):
        async with original(scope) as c:
            yield c
        async with original(scope) as c:
            row = await (
                await c.execute(
                    "SELECT 1 FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s AND id='s'",
                    store._owner,
                )
            ).fetchone()
        if row is None:
            raise ConnectionError("synthetic lost delete commit response")

    monkeypatch.setattr(store.db, "transaction", commit_then_unknown)
    with pytest.raises(ConnectionError):
        await store.delete_session("s", deletion_token=token)
    monkeypatch.setattr(store.db, "transaction", original)
    assert await store.get_session("s") is None
    assert old_path.exists() and len(await files.list_cleanup()) == 1
    await store.create_session(session_id="s")
    new_url = await files.put(session_id="s", attachment_id="a", filename="a", data=b"new")
    await store.add_message("s", "user", "new", attachments=[{"url": new_url}])
    with pytest.raises(RuntimeError, match="token/generation"):
        await store.delete_session("s", deletion_token=token)
    assert (await files.cleanup_pending())["pending"] == 0
    assert not old_path.exists()
    assert (
        await files.read_attachment(
            session_id="s", attachment_id=new_url.split("/")[-2], filename="a"
        )
        == b"new"
    )


async def test_unknown_gate_commit_remains_gated_and_reconciles_existing_token(
    pg_session_store_factory, business_actors, monkeypatch
):
    store = pg_session_store_factory(business_actors.tenants[0].owners[0])
    await store.create_session(session_id="s")
    original = store.db.transaction

    @asynccontextmanager
    async def commit_then_unknown(scope):
        async with original(scope) as c:
            yield c
        raise ConnectionError("synthetic lost gate commit response")

    monkeypatch.setattr(store.db, "transaction", commit_then_unknown)
    with pytest.raises(ConnectionError):
        await store.claim_deletion("s")
    monkeypatch.setattr(store.db, "transaction", original)
    assert (await store.get_session("s"))["deleting"]
    with pytest.raises(RuntimeError, match="deleting"):
        await store.begin_turn("s")
    token = await store.claim_deletion("s")
    assert await store.delete_session("s", deletion_token=token)
