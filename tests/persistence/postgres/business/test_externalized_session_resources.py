"""附件资源外置到 ObjectStore + PG metadata 的底层契约。"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import psycopg
import pytest

from deeptutor.runtime.externalized_providers import ObjectBlobRef, ObjectStoreError

pytestmark = pytest.mark.asyncio


class RecordingObjectStore:
    def __init__(self) -> None:
        self.config = SimpleNamespace(bucket="test-bucket")
        self.objects: dict[str, bytes] = {}
        self.puts: list[tuple[str, str, int]] = []
        self.gets: list[str] = []
        self.deletes: list[str] = []
        self.fail_delete_once = False
        self.on_delete = None
        self.on_delete_failure = None

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        expected_sha256: str | None = None,
        content_type: str = "application/octet-stream",
    ) -> ObjectBlobRef:
        digest = hashlib.sha256(data).hexdigest()
        assert expected_sha256 == digest
        assert key not in self.objects
        self.puts.append((key, content_type, len(data)))
        self.objects[key] = bytes(data)
        return ObjectBlobRef(
            key=key,
            size_bytes=len(data),
            sha256=digest,
            content_type=content_type,
        )

    def get_bytes(self, ref: ObjectBlobRef) -> bytes:
        self.gets.append(ref.key)
        data = self.objects[ref.key]
        assert len(data) == ref.size_bytes
        assert hashlib.sha256(data).hexdigest() == ref.sha256
        return data

    def delete(self, ref: ObjectBlobRef) -> None:
        self.deletes.append(ref.key)
        if self.fail_delete_once:
            self.fail_delete_once = False
            if self.on_delete_failure is not None:
                self.on_delete_failure(ref.key)
            raise ObjectStoreError("objectstore_unavailable", retryable=True)
        if self.on_delete is not None:
            self.on_delete(ref.key)
        self.objects.pop(ref.key, None)


@pytest.fixture
def store(pg_session_store_factory, business_actors):
    return pg_session_store_factory(business_actors.tenants[0].owners[0])


def externalized_store(store, object_store):
    from deeptutor.persistence.postgres.session_resources import PostgresObjectAttachmentStore

    return PostgresObjectAttachmentStore(store, object_store, bucket="test-bucket")


async def _upload_and_link(store, files, *, payload: bytes = b"actual bytes"):
    await store.create_session(session_id="s")
    url = await files.put(
        session_id="s",
        attachment_id="same",
        filename="a.txt",
        data=payload,
        mime_type="text/plain",
    )
    key = url.split("/")[-2]
    message_id = await store.add_message(
        "s",
        "user",
        "attachment",
        attachments=[{"id": "same", "url": url, "filename": "a.txt"}],
    )
    return url, key, message_id


async def test_unknown_session_object_state_blocks_externalized_read_and_withdraw(
    store, migrated_pg
):
    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    _, object_id, _ = await _upload_and_link(store, files)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "ALTER TABLE enterprise.session_objects DROP CONSTRAINT IF EXISTS session_objects_state_check"
            )
            await connection.execute(
                "UPDATE enterprise.session_objects SET state='future-state' "
                "WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                (*store._owner, object_id),
            )
    with pytest.raises(ValueError, match="session object state is unknown"):
        await files.get_operation(object_id)
    with pytest.raises(ValueError, match="session object state is unknown"):
        await files.list_operations()
    with pytest.raises(ValueError, match="session object state is unknown"):
        await files.read_attachment(session_id="s", attachment_id=object_id, filename="a.txt")
    with pytest.raises(ValueError, match="session object state is unknown"):
        await files.withdraw_operation(object_id)
    assert object_store.gets == [] and object_store.deletes == []


async def test_unknown_session_object_state_blocks_externalized_cleanup(
    store, migrated_pg
):
    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    _, object_id, message_id = await _upload_and_link(store, files)
    await store.delete_message(message_id)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "ALTER TABLE enterprise.session_objects DROP CONSTRAINT IF EXISTS session_objects_state_check"
            )
            await connection.execute(
                "UPDATE enterprise.session_objects SET state='future-state' "
                "WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                (*store._owner, object_id),
            )
    with pytest.raises(ValueError, match="session object state is unknown"):
        await files.list_cleanup()
    with pytest.raises(ValueError, match="session object state is unknown"):
        await files.cleanup_pending()
    assert object_store.deletes == []


@pytest.mark.parametrize(
    ("constraint", "mutation", "message"),
    [
        ("resource_objects_state_check", "state='future-state'", "resource state is unknown"),
        (
            "resource_objects_retention_check",
            "retention='future-retention'",
            "resource retention is unknown",
        ),
    ],
)
async def test_unknown_resource_business_state_blocks_externalized_attachment_read(
    store, migrated_pg, constraint, mutation, message
):
    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    _, object_id, _ = await _upload_and_link(store, files)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                f"ALTER TABLE enterprise.resource_objects DROP CONSTRAINT IF EXISTS {constraint}"
            )
            await connection.execute(
                f"UPDATE enterprise.resource_objects SET {mutation} "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (*store._owner, object_id),
            )
    with pytest.raises(ValueError, match=message):
        await files.read_attachment(session_id="s", attachment_id=object_id, filename="a.txt")
    assert object_store.gets == []


@pytest.mark.parametrize(
    ("constraint", "mutation", "message"),
    [
        ("resource_objects_state_check", "state='future-state'", "resource state is unknown"),
        (
            "resource_objects_retention_check",
            "retention='future-retention'",
            "resource retention is unknown",
        ),
    ],
)
async def test_unknown_resource_business_state_blocks_externalized_cleanup(
    store, migrated_pg, constraint, mutation, message
):
    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    _, object_id, message_id = await _upload_and_link(store, files)
    await store.delete_message(message_id)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                f"ALTER TABLE enterprise.resource_objects DROP CONSTRAINT IF EXISTS {constraint}"
            )
            await connection.execute(
                f"UPDATE enterprise.resource_objects SET {mutation} "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (*store._owner, object_id),
            )
    with pytest.raises(ValueError, match=message):
        await files.list_cleanup()
    with pytest.raises(ValueError, match=message):
        await files.cleanup_pending()
    assert object_store.deletes == []


async def test_upload_publish_does_not_overwrite_unknown_session_object_state(
    store, migrated_pg, monkeypatch
):
    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    await store.create_session(session_id="s")
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            "ALTER TABLE enterprise.session_objects DROP CONSTRAINT IF EXISTS session_objects_state_check"
        )
    original_put = object_store.put_bytes

    def put_and_corrupt(*args, **kwargs):
        ref = original_put(*args, **kwargs)
        with psycopg.connect(migrated_pg.admin_dsn) as connection:
            connection.execute(
                "UPDATE enterprise.session_objects SET state='future-state' "
                "WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                (*store._owner, ref.key.rsplit("/", 1)[-1]),
            )
        return ref

    monkeypatch.setattr(object_store, "put_bytes", put_and_corrupt)
    with pytest.raises(ValueError, match="session object state is unknown") as failure:
        await files.put(session_id="s", attachment_id="a", filename="a.txt", data=b"bytes")
    object_id = failure.value.resource_operation_id
    async with store.db.transaction(store.scope) as connection:
        row = await (
            await connection.execute(
                "SELECT state FROM enterprise.session_objects "
                "WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                (*store._owner, object_id),
            )
        ).fetchone()
    assert row["state"] == "future-state"
    assert object_store.deletes == []


async def test_unknown_cleanup_job_state_blocks_externalized_attachment_deletion(
    store, migrated_pg
):
    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    _, object_id, message_id = await _upload_and_link(store, files)
    await store.delete_message(message_id)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "INSERT INTO enterprise.resource_cleanup_jobs(tenant_id,owner_id,object_id) "
                "VALUES(%s,%s,%s)",
                (*store._owner, object_id),
            )
            await connection.execute(
                "ALTER TABLE enterprise.resource_cleanup_jobs "
                "DROP CONSTRAINT IF EXISTS resource_cleanup_jobs_state_check"
            )
            await connection.execute(
                "UPDATE enterprise.resource_cleanup_jobs SET state='future-state' "
                "WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                (*store._owner, object_id),
            )
    with pytest.raises(ValueError, match="resource cleanup job state is unknown"):
        await files.list_cleanup()
    with pytest.raises(ValueError, match="resource cleanup job state is unknown"):
        await files.cleanup_pending()
    assert object_store.deletes == []


@pytest.mark.parametrize(
    ("table", "key_column", "constraint", "message"),
    [
        (
            "session_objects",
            "object_id",
            "session_objects_state_check",
            "session object state is unknown",
        ),
        (
            "resource_objects",
            "id",
            "resource_objects_state_check",
            "resource state is unknown",
        ),
        (
            "resource_cleanup_jobs",
            "object_id",
            "resource_cleanup_jobs_state_check",
            "resource cleanup job state is unknown",
        ),
    ],
)
async def test_externalized_cleanup_rechecks_state_after_object_delete(
    store, migrated_pg, table, key_column, constraint, message,
):
    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    _, object_id, message_id = await _upload_and_link(store, files)
    await store.delete_message(message_id)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(f"ALTER TABLE enterprise.{table} DROP CONSTRAINT IF EXISTS {constraint}")

    def corrupt_after_delete(_key):
        with psycopg.connect(migrated_pg.admin_dsn) as connection:
            connection.execute(
                f"UPDATE enterprise.{table} SET state='future-state' "
                f"WHERE tenant_id=%s AND owner_id=%s AND {key_column}=%s",
                (*store._owner, object_id),
            )

    object_store.on_delete = corrupt_after_delete
    with pytest.raises(ValueError, match=message):
        await files.cleanup_pending()
    async with store.db.transaction(store.scope) as connection:
        row = await (
            await connection.execute(
                "SELECT o.state AS session_state,r.state AS resource_state,j.state AS job_state "
                "FROM enterprise.session_objects o "
                "JOIN enterprise.resource_objects r "
                "ON (r.tenant_id,r.owner_id,r.id)=(o.tenant_id,o.owner_id,o.object_id) "
                "JOIN enterprise.resource_cleanup_jobs j "
                "ON (j.tenant_id,j.owner_id,j.object_id)=(o.tenant_id,o.owner_id,o.object_id) "
                "WHERE o.tenant_id=%s AND o.owner_id=%s AND o.object_id=%s",
                (*store._owner, object_id),
            )
        ).fetchone()
    assert row == {
        "session_state": "future-state" if table == "session_objects" else "cleanup",
        "resource_state": "future-state" if table == "resource_objects" else "delete-pending",
        "job_state": "future-state" if table == "resource_cleanup_jobs" else "running",
    }


@pytest.mark.parametrize(
    ("table", "key_column", "constraint", "message"),
    [
        (
            "session_objects",
            "object_id",
            "session_objects_state_check",
            "session object state is unknown",
        ),
        (
            "resource_objects",
            "id",
            "resource_objects_state_check",
            "resource state is unknown",
        ),
        (
            "resource_cleanup_jobs",
            "object_id",
            "resource_cleanup_jobs_state_check",
            "resource cleanup job state is unknown",
        ),
    ],
)
async def test_externalized_cleanup_failure_rechecks_state_after_object_error(
    store, migrated_pg, table, key_column, constraint, message,
):
    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    _, object_id, message_id = await _upload_and_link(store, files)
    await store.delete_message(message_id)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(f"ALTER TABLE enterprise.{table} DROP CONSTRAINT IF EXISTS {constraint}")

    def corrupt_on_delete_error(_key):
        with psycopg.connect(migrated_pg.admin_dsn) as connection:
            connection.execute(
                f"UPDATE enterprise.{table} SET state='future-state' "
                f"WHERE tenant_id=%s AND owner_id=%s AND {key_column}=%s",
                (*store._owner, object_id),
            )

    object_store.fail_delete_once = True
    object_store.on_delete_failure = corrupt_on_delete_error
    with pytest.raises(ValueError, match=message):
        await files.cleanup_pending()
    async with store.db.transaction(store.scope) as connection:
        row = await (
            await connection.execute(
                "SELECT o.state AS session_state,r.state AS resource_state,j.state AS job_state "
                "FROM enterprise.session_objects o "
                "JOIN enterprise.resource_objects r "
                "ON (r.tenant_id,r.owner_id,r.id)=(o.tenant_id,o.owner_id,o.object_id) "
                "JOIN enterprise.resource_cleanup_jobs j "
                "ON (j.tenant_id,j.owner_id,j.object_id)=(o.tenant_id,o.owner_id,o.object_id) "
                "WHERE o.tenant_id=%s AND o.owner_id=%s AND o.object_id=%s",
                (*store._owner, object_id),
            )
        ).fetchone()
    assert row == {
        "session_state": "future-state" if table == "session_objects" else "cleanup",
        "resource_state": "future-state" if table == "resource_objects" else "delete-pending",
        "job_state": "future-state" if table == "resource_cleanup_jobs" else "running",
    }
    assert list(object_store.objects.values()) == [b"actual bytes"]


async def test_externalized_delete_attachment_does_not_overwrite_unknown_state(
    store, migrated_pg
):
    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    await store.create_session(session_id="s")
    url = await files.put(session_id="s", attachment_id="a", filename="a.txt", data=b"bytes")
    object_id = url.split("/")[-2]
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "ALTER TABLE enterprise.session_objects DROP CONSTRAINT IF EXISTS session_objects_state_check"
            )
            await connection.execute(
                "UPDATE enterprise.session_objects SET state='future-state' "
                "WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                (*store._owner, object_id),
            )
    with pytest.raises(ValueError, match="session object state is unknown"):
        await files.delete_attachment("s", object_id)
    async with store.db.transaction(store.scope) as connection:
        row = await (
            await connection.execute(
                "SELECT state FROM enterprise.session_objects "
                "WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                (*store._owner, object_id),
            )
        ).fetchone()
    assert row["state"] == "future-state"
    assert object_store.deletes == []


async def test_externalized_attachment_writes_objectstore_and_pg_metadata_before_read(
    store,
):
    """若附件只落本地文件或绕过 PG resource_objects 授权，本测试应失败。"""

    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    await store.create_session(session_id="s")

    url = await files.put(
        session_id="s",
        attachment_id="same",
        filename="a.txt",
        data=b"actual bytes",
        mime_type="text/plain",
    )
    object_id = url.split("/")[-2]

    assert url == f"/files/attachments/s/{object_id}/a.txt"
    assert len(object_store.puts) == 1
    object_key, content_type, size = object_store.puts[0]
    assert object_id in object_key
    assert content_type == "text/plain"
    assert size == len(b"actual bytes")

    async with store.db.transaction(store.scope) as c:
        row = await (
            await c.execute(
                "SELECT resource_kind,bucket,object_key,content_hash,size_bytes,mime_type,state "
                "FROM enterprise.resource_objects "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (*store._owner, object_id),
            )
        ).fetchone()
    assert row["resource_kind"] == "chat_attachment"
    assert row["bucket"] == "test-bucket"
    assert row["object_key"] == object_key
    assert row["content_hash"] == hashlib.sha256(b"actual bytes").hexdigest()
    assert row["size_bytes"] == len(b"actual bytes")
    assert row["mime_type"] == "text/plain"
    assert row["state"] == "ready"

    with pytest.raises(FileNotFoundError):
        await files.read_attachment(session_id="s", attachment_id=object_id, filename="a.txt")

    await store.add_message(
        "s", "user", "attachment", attachments=[{"id": "same", "url": url, "filename": "a.txt"}]
    )
    assert (
        await files.read_attachment(session_id="s", attachment_id=object_id, filename="a.txt")
        == b"actual bytes"
    )
    assert object_store.gets == [object_key]


async def test_externalized_attachment_delete_failure_is_persisted_and_retried(store):
    """若 ObjectStore 删除失败丢失补偿任务或删除仍被引用对象，本测试应失败。"""

    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    url, object_id, message_id = await _upload_and_link(store, files)
    object_key = next(iter(object_store.objects))
    assert await store.delete_message(message_id)

    object_store.fail_delete_once = True
    report = await files.cleanup_pending()
    assert report["pending"] == 1
    assert report["errors"][0]["error"] == "objectstore_unavailable"
    assert object_store.objects[object_key] == b"actual bytes"

    async with store.db.transaction(store.scope) as c:
        row = await (
            await c.execute(
                "SELECT r.state AS resource_state,j.state AS job_state,j.last_error "
                "FROM enterprise.resource_objects r "
                "JOIN enterprise.resource_cleanup_jobs j "
                "ON (j.tenant_id,j.owner_id,j.object_id)=(r.tenant_id,r.owner_id,r.id) "
                "WHERE r.tenant_id=%s AND r.owner_id=%s AND r.id=%s",
                (*store._owner, object_id),
            )
        ).fetchone()
    assert row["resource_state"] == "delete-pending"
    assert row["job_state"] == "failed"
    assert row["last_error"] == "objectstore_unavailable"

    report = await files.cleanup_pending()
    assert report["pending"] == 0
    assert object_store.objects == {}
    assert object_store.deletes == [object_key, object_key]
    with pytest.raises(FileNotFoundError):
        await files.read_attachment(session_id="s", attachment_id=object_id, filename="a.txt")

    async with store.db.transaction(store.scope) as c:
        row = await (
            await c.execute(
                "SELECT r.state AS resource_state,j.state AS job_state "
                "FROM enterprise.resource_objects r "
                "JOIN enterprise.resource_cleanup_jobs j "
                "ON (j.tenant_id,j.owner_id,j.object_id)=(r.tenant_id,r.owner_id,r.id) "
                "WHERE r.tenant_id=%s AND r.owner_id=%s AND r.id=%s",
                (*store._owner, object_id),
            )
        ).fetchone()
    assert row["resource_state"] == "deleted"
    assert row["job_state"] == "done"


async def test_externalized_attachment_http_proxy_uses_pg_authorization_before_objectstore(
    store, pg_session_store_factory, business_actors
):
    """若 HTTP 下载仅凭 object key 或 bucket 存在就读对象，本测试应失败。"""

    from fastapi import FastAPI
    import httpx

    from deeptutor.api.routers.attachments import router
    from deeptutor.core.providers import ApplicationProviders, provider_context

    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    url, _object_id, _message_id = await _upload_and_link(store, files)
    object_key = next(iter(object_store.objects))

    app = FastAPI()
    app.include_router(router, prefix="/files/attachments")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        with provider_context(ApplicationProviders(store=store, object_store=object_store)):
            response = await client.get(url)
        assert response.status_code == 200
        assert response.content == b"actual bytes"
        assert "no-store" in response.headers["cache-control"]
        assert object_store.gets == [object_key]

        foreign = pg_session_store_factory(business_actors.tenants[0].owners[1])
        with provider_context(ApplicationProviders(store=foreign, object_store=object_store)):
            response = await client.get(url)
        assert response.status_code in (403, 404)
        assert object_store.gets == [object_key]


async def test_externalized_attachment_operation_api_withdraws_unreferenced_objectstore_object(
    store, pg_session_store_factory, business_actors
):
    """若附件操作 API 绕过 PG owner scope 或不触发 ObjectStore 清理，本测试应失败。"""

    from fastapi import FastAPI
    import httpx

    from deeptutor.api.routers.attachments import router
    from deeptutor.core.providers import ApplicationProviders, provider_context

    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    await store.create_session(session_id="s")
    url = await files.put(
        session_id="s",
        attachment_id="same",
        filename="a.txt",
        data=b"withdraw me",
        mime_type="text/plain",
    )
    object_id = url.split("/")[-2]
    object_key = next(iter(object_store.objects))

    app = FastAPI()
    app.include_router(router, prefix="/files/attachments")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        foreign = pg_session_store_factory(business_actors.tenants[0].owners[1])
        with provider_context(ApplicationProviders(store=foreign, object_store=object_store)):
            response = await client.delete(f"/files/attachments/operations/{object_id}")
        assert response.status_code == 404
        assert object_store.objects[object_key] == b"withdraw me"

        with provider_context(ApplicationProviders(store=store, object_store=object_store)):
            response = await client.delete(f"/files/attachments/operations/{object_id}")
        assert response.status_code == 200
        assert response.json()["pending"] == 0
        assert object_store.objects == {}
        assert object_store.deletes == [object_key]


async def test_externalized_attachment_delete_attachment_cleans_unreferenced_objectstore_object(store):
    """若直接删除未引用附件未清理 ObjectStore 或使用错误 PG 列，本测试应失败。"""

    object_store = RecordingObjectStore()
    files = externalized_store(store, object_store)
    await store.create_session(session_id="s")
    url = await files.put(
        session_id="s",
        attachment_id="same",
        filename="a.txt",
        data=b"orphan candidate",
        mime_type="text/plain",
    )
    object_id = url.split("/")[-2]
    object_key = next(iter(object_store.objects))

    report = await files.delete_attachment("s", object_id)

    assert report["pending"] == 0
    assert object_store.objects == {}
    assert object_store.deletes == [object_key]
    with pytest.raises(FileNotFoundError):
        await files.read_attachment(session_id="s", attachment_id=object_id, filename="a.txt")


async def test_externalized_attachment_publish_failure_records_cleanup_job_and_deletes_object(
    store, migrated_pg
):
    """若 ObjectStore 已写入后 PG ready 发布失败未补偿清理，本测试应失败。"""

    import psycopg

    class PublishFailingObjectStore(RecordingObjectStore):
        def put_bytes(self, key: str, data: bytes, **kwargs):
            ref = super().put_bytes(key, data, **kwargs)
            # 这里刻意用迁移/维护连接模拟“对象已写入后，PG 发布阶段的候选行被外部补偿/撤回”。
            # runtime_dsn 未绑定 TenantScope 时会被 RLS 拦截，无法稳定构造发布失败。
            with psycopg.connect(migrated_pg.admin_dsn) as connection:
                connection.execute(
                    "UPDATE enterprise.resource_objects SET state='delete-pending' WHERE object_key=%s",
                    (key,),
                )
            return ref

    object_store = PublishFailingObjectStore()
    files = externalized_store(store, object_store)
    await store.create_session(session_id="s")

    with pytest.raises(RuntimeError, match="resource object candidate") as failure:
        await files.put(
            session_id="s",
            attachment_id="same",
            filename="a.txt",
            data=b"publish fails after object upload",
            mime_type="text/plain",
        )

    object_id = failure.value.resource_operation_id
    object_key = next(iter(object_store.objects))
    async with store.db.transaction(store.scope) as c:
        row = await (
            await c.execute(
                "SELECT o.state AS object_state,o.last_error,r.state AS resource_state,r.cleanup_error,j.state AS job_state,j.last_error AS job_error "
                "FROM enterprise.session_objects o "
                "JOIN enterprise.resource_objects r ON (r.tenant_id,r.owner_id,r.id)=(o.tenant_id,o.owner_id,o.object_id) "
                "JOIN enterprise.resource_cleanup_jobs j ON (j.tenant_id,j.owner_id,j.object_id)=(o.tenant_id,o.owner_id,o.object_id) "
                "WHERE o.tenant_id=%s AND o.owner_id=%s AND o.object_id=%s",
                (*store._owner, object_id),
            )
        ).fetchone()
    assert row["object_state"] == "cleanup"
    assert row["last_error"] == "upload_publish_failed"
    assert row["resource_state"] == "delete-pending"
    assert row["cleanup_error"] == "upload_publish_failed"
    assert row["job_state"] == "pending"
    assert row["job_error"] == "upload_publish_failed"

    report = await files.cleanup_pending()

    assert report["pending"] == 0
    assert object_store.objects == {}
    assert object_store.deletes == [object_key]
