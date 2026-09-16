"""真实 PG 权威资源及物理文件；不以 helper 的不可见假冒文件删除。"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


def provider(store, tmp_path):
    assert importlib.util.find_spec("deeptutor.persistence.postgres.session_resources"), (
        "缺少 PG 资源生命周期"
    )
    from deeptutor.persistence.postgres.session_resources import PostgresAttachmentStore
    from deeptutor.persistence.resources import OwnerResourceProvider

    return PostgresAttachmentStore(store, OwnerResourceProvider(tmp_path.absolute()))


@pytest.fixture
def store(pg_session_store_factory, business_actors):
    return pg_session_store_factory(business_actors.tenants[0].owners[0])


async def upload(store, files):
    await store.create_session(session_id="s")
    url = await files.put(
        session_id="s", attachment_id="same", filename="a.txt", data=b"actual bytes"
    )
    aid = url.split("/")[-2]
    return url, aid


async def test_candidate_invisible_link_reopen_and_delete_physical(store, tmp_path):
    files = provider(store, tmp_path)
    url, aid = await upload(store, files)
    physical = list(tmp_path.rglob("*.blob"))
    assert len(physical) == 1 and physical[0].read_bytes() == b"actual bytes"
    with pytest.raises(FileNotFoundError):
        await files.read_attachment(session_id="s", attachment_id=aid, filename="a.txt")
    mid = await store.add_message(
        "s", "user", "attachment", attachments=[{"id": "same", "url": url, "filename": "a.txt"}]
    )
    assert (
        await files.read_attachment(session_id="s", attachment_id=aid, filename="a.txt")
        == b"actual bytes"
    )
    assert (await store.get_messages("s"))[0]["attachments"][0]["url"] == url
    assert await store.delete_message(mid)
    with pytest.raises(FileNotFoundError):
        await files.read_attachment(session_id="s", attachment_id=aid, filename="a.txt")
    assert (await files.cleanup_pending())["pending"] == 0
    assert not physical[0].exists()


async def test_shared_attachment_last_reference_and_scope(
    store, tmp_path, pg_session_store_factory, business_actors
):
    files = provider(store, tmp_path)
    url, aid = await upload(store, files)
    attachment = {"id": "same", "url": url, "filename": "a.txt"}
    first = await store.add_message(
        "s", "assistant", "one", attachments=[attachment], parent_message_id=None
    )
    second = await store.add_message(
        "s", "assistant", "two", attachments=[attachment], parent_message_id=None
    )
    foreign = pg_session_store_factory(business_actors.tenants[0].owners[1])
    await foreign.create_session(session_id="foreign")
    with pytest.raises(ValueError):
        await foreign.add_message("foreign", "user", "x", attachments=[attachment])
    await store.delete_message(first)
    await files.cleanup_pending()
    assert (
        await files.read_attachment(session_id="s", attachment_id=aid, filename="a.txt")
        == b"actual bytes"
    )
    await store.delete_message(second)
    await files.cleanup_pending()
    assert not list(tmp_path.rglob("*.blob"))


async def test_cleanup_failure_persisted_retry_same_id_recreate(store, tmp_path, monkeypatch):
    files = provider(store, tmp_path)
    url, aid = await upload(store, files)
    await store.add_message("s", "user", "x", attachments=[{"url": url, "filename": "a.txt"}])
    old = list(tmp_path.rglob("*.blob"))[0]
    await store.delete_session("s")
    real = files._delete_object
    monkeypatch.setattr(
        files,
        "_delete_object",
        lambda _: (_ for _ in ()).throw(OSError("synthetic cleanup failure")),
    )
    report = await files.cleanup_pending()
    assert report["pending"] == 1 and report["errors"]
    assert old.exists()
    rows = await files.list_cleanup()
    assert rows[0]["attempts"] == 1 and rows[0]["last_error"]
    new_url, new_aid = await upload(store, files)
    assert new_aid != aid
    await store.add_message("s", "user", "new", attachments=[{"url": new_url, "filename": "a.txt"}])
    monkeypatch.setattr(files, "_delete_object", real)
    await files.cleanup_pending()
    assert not old.exists()
    assert (
        await files.read_attachment(session_id="s", attachment_id=new_aid, filename="a.txt")
        == b"actual bytes"
    )


async def test_deleting_rejects_upload_and_generated_unknown_atomically(store, tmp_path):
    files = provider(store, tmp_path)
    await store.create_session(session_id="s")
    with pytest.raises(ValueError):
        await store.add_message(
            "s",
            "assistant",
            "bad",
            attachments=[{"url": "/files/outputs/unowned", "generated": True}],
        )
    assert await store.get_messages("s") == []
    await store.mark_deleting("s")
    with pytest.raises(RuntimeError):
        await files.put(session_id="s", attachment_id="x", filename="x", data=b"x")
    assert not list(tmp_path.rglob("*.blob"))


async def test_real_attachment_http_provider_and_revocation(store, tmp_path, migrated_pg):
    from fastapi import FastAPI
    import httpx
    import psycopg

    from deeptutor.api.routers.attachments import router
    from deeptutor.core.providers import ApplicationProviders, provider_context

    files = provider(store, tmp_path)
    url, aid = await upload(store, files)
    await store.add_message("s", "user", "x", attachments=[{"url": url, "filename": "a.txt"}])
    app = FastAPI()
    app.include_router(router, prefix="/files/attachments")
    with provider_context(ApplicationProviders(store=store, resources=files.resources)):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.get(url)
            assert response.status_code == 200 and response.content == b"actual bytes"
            assert "no-store" in response.headers["cache-control"]
            async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as c:
                await c.execute(
                    "UPDATE enterprise.users SET disabled=true WHERE tenant_id=%s AND id=%s",
                    store._owner,
                )
            response = await client.get(url)
            assert response.status_code in (401, 403)


async def test_symlink_payload_rejected_without_reading_outside(store, tmp_path):
    files = provider(store, tmp_path / "root")
    url, aid = await upload(store, files)
    await store.add_message("s", "user", "x", attachments=[{"url": url, "filename": "a.txt"}])
    physical = list((tmp_path / "root").rglob("*.blob"))[0]
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside private")
    physical.unlink()
    physical.symlink_to(outside)
    with pytest.raises(OSError):
        await files.read_attachment(session_id="s", attachment_id=aid, filename="a.txt")
    await store.delete_session("s")
    assert (await files.cleanup_pending())["pending"] == 1
    assert outside.read_bytes() == b"outside private"


async def test_unknown_publish_commit_preserves_referenced_object(store, tmp_path, monkeypatch):
    from contextlib import asynccontextmanager

    files = provider(store, tmp_path)
    await store.create_session(session_id="s")
    original = store.db.transaction

    @asynccontextmanager
    async def commit_then_unknown(scope):
        async with original(scope) as c:
            yield c
        # 此探针仅在已提交 ready 存在后模拟未知响应，不模拟 PG 本身。
        async with original(scope) as c:
            ready = await (
                await c.execute(
                    "SELECT 1 FROM enterprise.session_objects WHERE tenant_id=%s AND owner_id=%s AND state='ready'",
                    store._owner,
                )
            ).fetchone()
        if ready:
            raise ConnectionError("synthetic unknown commit response")

    monkeypatch.setattr(store.db, "transaction", commit_then_unknown)
    with pytest.raises(ConnectionError) as failure:
        await files.put(
            session_id="s", attachment_id="a", filename="a.txt", data=b"committed bytes"
        )
    monkeypatch.setattr(store.db, "transaction", original)
    async with original(store.scope) as c:
        row = await (
            await c.execute(
                "SELECT object_id,state FROM enterprise.session_objects WHERE tenant_id=%s AND owner_id=%s",
                store._owner,
            )
        ).fetchone()
    assert row["state"] == "ready"
    assert failure.value.resource_operation_id == str(row["object_id"])
    physical = list(tmp_path.rglob("*.blob"))[0]
    assert physical.read_bytes() == b"committed bytes"


async def test_download_checks_pg_before_resource_io(store, tmp_path, monkeypatch):
    files = provider(store, tmp_path)
    from uuid import uuid4

    def forbid(*args, **kwargs):
        raise AssertionError("unauthorized request must not open resource directory")

    monkeypatch.setattr(files.directory, "open", forbid)
    with pytest.raises(FileNotFoundError):
        await files.read_attachment(session_id="missing", attachment_id=str(uuid4()), filename="x")


async def test_generated_preview_refuses_missing_authority_before_path_read(
    store, tmp_path, monkeypatch
):
    from deeptutor.core.providers import ApplicationProviders, provider_context
    import deeptutor.services.session.artifact_attachments as module

    files = provider(store, tmp_path)

    def forbid(*args):
        raise AssertionError("must not resolve legacy generated file under PG")

    monkeypatch.setattr(module, "_resolve_artifact_path", forbid)
    with provider_context(ApplicationProviders(store=store, resources=files.resources)):
        with pytest.raises(ValueError, match="authority"):
            await module.fill_preview_text(
                [
                    {
                        "url": "/files/outputs/foreign.pptx",
                        "filename": "foreign.pptx",
                        "generated": True,
                    }
                ]
            )


async def test_unreferenced_candidate_is_reportable_and_explicitly_withdrawable(store, tmp_path):
    files = provider(store, tmp_path)
    url, key = await upload(store, files)
    row = await files.get_operation(key)
    assert row["state"] == "ready" and row["referenced"] is False
    physical = list(tmp_path.rglob("*.blob"))[0]
    assert (await files.withdraw_operation(key))["pending"] == 0
    assert not physical.exists()
    assert (await files.get_operation(key))["state"] == "deleted"
    # 新同 ID 对象不能被上一次操作的撤回删除。
    new_url = await files.put(session_id="s", attachment_id="same", filename="a.txt", data=b"new")
    new_key = new_url.split("/")[-2]
    await store.add_message("s", "user", "x", attachments=[{"url": new_url}])
    with pytest.raises(ValueError, match="referenced"):
        await files.withdraw_operation(new_key)
    await files.withdraw_operation(key)
    assert (
        await files.read_attachment(session_id="s", attachment_id=new_key, filename="a.txt")
        == b"new"
    )


async def test_duplicate_object_attachment_rejected_atomically(store, tmp_path):
    files = provider(store, tmp_path)
    url, key = await upload(store, files)
    with pytest.raises(ValueError, match="duplicate"):
        await store.add_message("s", "user", "x", attachments=[{"url": url}, {"url": url}])
    assert await store.get_messages("s") == []


async def test_payload_read_is_bounded_by_published_size(store, tmp_path):
    files = provider(store, tmp_path)
    url, key = await upload(store, files)
    await store.add_message("s", "user", "x", attachments=[{"url": url}])
    physical = list(tmp_path.rglob("*.blob"))[0]
    with physical.open("r+b") as output:
        output.truncate(100 * 1024 * 1024)
    with pytest.raises(OSError, match="limit"):
        await files.read_attachment(session_id="s", attachment_id=key, filename="a.txt")


async def test_operation_http_reports_withdraws_and_retries(store, tmp_path):
    from fastapi import FastAPI
    import httpx

    from deeptutor.api.routers.attachments import router
    from deeptutor.core.providers import ApplicationProviders, provider_context

    files = provider(store, tmp_path)
    url, key = await upload(store, files)
    physical = list(tmp_path.rglob("*.blob"))[0]
    app = FastAPI()
    app.include_router(router, prefix="/files/attachments")
    with provider_context(ApplicationProviders(store=store, resources=files.resources)):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            listing = await client.get("/files/attachments/operations")
            assert listing.status_code == 200 and listing.json()[0]["object_id"] == key
            response = await client.get(f"/files/attachments/operations/{key}")
            assert response.status_code == 200
            assert response.json()["state"] == "ready"
            response = await client.delete(f"/files/attachments/operations/{key}")
            assert response.status_code == 200 and response.json()["pending"] == 0
            response = await client.post("/files/attachments/cleanup")
            assert response.status_code == 200 and response.json()["pending"] == 0
    assert not physical.exists()


async def test_cleanup_directory_lock_failure_is_persisted_pending(store, tmp_path, monkeypatch):
    files = provider(store, tmp_path)
    await upload(store, files)
    await store.delete_session("s")

    def failure(*args, **kwargs):
        raise PermissionError("synthetic unavailable resource directory")

    monkeypatch.setattr(files.directory, "open", failure)
    report = await files.cleanup_pending()
    assert report["pending"] == 1 and report["errors"][0]["error"] == "PermissionError"
    row = (await files.list_cleanup())[0]
    assert row["attempts"] == 1 and row["last_error"] == "PermissionError"
