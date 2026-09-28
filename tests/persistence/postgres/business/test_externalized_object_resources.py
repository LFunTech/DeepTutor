"""Generic ObjectStore + PG metadata resources for non-attachment file classes."""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import quote

import psycopg
import pytest

pytestmark = pytest.mark.asyncio


class RecordingObjectStore:
    def __init__(self) -> None:
        self.config = SimpleNamespace(bucket="resource-bucket")
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.gets: list[str] = []
        self.heads: list[str] = []
        self.presigns: list[str] = []
        self.deletes: list[str] = []
        self.fail_delete_once = False
        self.on_head = None
        self.on_put = None
        self.on_delete = None
        self.on_delete_failure = None

    def presign_put(self, key, *, expires_seconds, content_type, size_bytes, expected_sha256):
        self.presigns.append(key)
        return SimpleNamespace(
            url=f"https://synthetic.invalid/{key}",
            headers={},
            expires_seconds=expires_seconds,
        )

    def head_object(self, key):
        import hashlib

        from deeptutor.runtime.externalized_providers import ObjectBlobRef

        self.heads.append(key)
        payload = self.objects[key]
        if self.on_head is not None:
            self.on_head(key)
        return ObjectBlobRef(
            key=key,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            content_type="application/octet-stream",
        )

    def put_bytes(self, key, data, *, expected_sha256=None, content_type="application/octet-stream"):
        import hashlib

        from deeptutor.runtime.externalized_providers import ObjectBlobRef

        digest = hashlib.sha256(data).hexdigest()
        assert expected_sha256 == digest
        self.puts.append(key)
        self.objects[key] = bytes(data)
        if self.on_put is not None:
            self.on_put(key)
        return ObjectBlobRef(key=key, size_bytes=len(data), sha256=digest, content_type=content_type)

    def get_bytes(self, ref):
        self.gets.append(ref.key)
        return self.objects[ref.key]

    def delete(self, ref) -> None:
        from deeptutor.runtime.externalized_providers import ObjectStoreError

        self.deletes.append(ref.key)
        if self.fail_delete_once:
            self.fail_delete_once = False
            if self.on_delete_failure is not None:
                self.on_delete_failure(ref.key)
            raise ObjectStoreError("objectstore_unavailable", retryable=True)
        if self.on_delete is not None:
            self.on_delete(ref.key)
        self.objects.pop(ref.key, None)


@pytest.mark.parametrize(
    ("constraint", "corruption", "message"),
    [
        ("resource_objects_state_check", "state='future-state'", "resource state is unknown"),
        (
            "resource_objects_retention_check",
            "retention='future-retention'",
            "resource retention is unknown",
        ),
    ],
)
async def test_presigned_completion_rejects_unknown_existing_business_state_before_head(
    pg_session_store_factory, business_actors, migrated_pg, constraint, corruption, message,
):
    import hashlib

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(store, object_store)
    payload = b"signed-payload"
    intent = await resources.create_upload_intent(
        modality="file",
        mime_type="application/octet-stream",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        purpose="chat_turn",
    )
    object_store.objects[object_store.presigns[-1]] = payload
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                f"ALTER TABLE enterprise.resource_objects DROP CONSTRAINT IF EXISTS {constraint}"
            )
            await connection.execute(
                f"UPDATE enterprise.resource_objects SET {corruption} "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (actor.tenant_id, actor.user_id, intent["object_id"]),
            )
    with pytest.raises(ValueError, match=message):
        await resources.complete_upload_intent(resource_id=intent["resource_id"])
    assert object_store.heads == []
    async with store.db.transaction(store.scope) as connection:
        row = await (
            await connection.execute(
                "SELECT state,retention FROM enterprise.resource_objects "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (*store._owner, intent["object_id"]),
            )
        ).fetchone()
    assert row == {
        "state": "future-state" if "state=" in corruption else "pending",
        "retention": "future-retention" if "retention=" in corruption else "temporary",
    }


@pytest.mark.parametrize(
    ("constraint", "corruption", "message"),
    [
        ("resource_objects_state_check", "state='future-state'", "resource state is unknown"),
        (
            "resource_objects_retention_check",
            "retention='future-retention'",
            "resource retention is unknown",
        ),
    ],
)
async def test_ready_reference_rejects_unknown_existing_business_state_before_head(
    pg_session_store_factory, business_actors, migrated_pg, constraint, corruption, message,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(store, object_store)
    handle = await resources.put(
        resource_kind="turn_input",
        resource_id="ready-reference",
        filename="body.bin",
        data=b"ready-reference-payload",
    )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                f"ALTER TABLE enterprise.resource_objects DROP CONSTRAINT IF EXISTS {constraint}"
            )
            await connection.execute(
                f"UPDATE enterprise.resource_objects SET {corruption} "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (actor.tenant_id, actor.user_id, handle.object_id),
            )
    with pytest.raises(ValueError, match=message):
        await resources.verify_ready_reference(resource_id="ready-reference")
    assert object_store.heads == []


async def test_presigned_completion_rechecks_retention_after_object_head(
    pg_session_store_factory, business_actors, migrated_pg,
):
    import hashlib

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(store, object_store)
    payload = b"signed-race"
    intent = await resources.create_upload_intent(
        modality="file",
        mime_type="application/octet-stream",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        purpose="chat_turn",
    )
    object_store.objects[object_store.presigns[-1]] = payload
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            "ALTER TABLE enterprise.resource_objects DROP CONSTRAINT IF EXISTS resource_objects_retention_check"
        )

    def corrupt_after_head(_key):
        with psycopg.connect(migrated_pg.admin_dsn) as connection:
            connection.execute(
                "UPDATE enterprise.resource_objects SET retention='future-retention' "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (actor.tenant_id, actor.user_id, intent["object_id"]),
            )

    object_store.on_head = corrupt_after_head
    with pytest.raises(ValueError, match="resource retention is unknown"):
        await resources.complete_upload_intent(resource_id=intent["resource_id"])
    async with store.db.transaction(store.scope) as connection:
        row = await (
            await connection.execute(
                "SELECT state,retention FROM enterprise.resource_objects "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (*store._owner, intent["object_id"]),
            )
        ).fetchone()
    assert row == {"state": "pending", "retention": "future-retention"}


async def test_object_publish_does_not_overwrite_unknown_state_during_cleanup_request(
    pg_session_store_factory, business_actors, migrated_pg,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            "ALTER TABLE enterprise.resource_objects DROP CONSTRAINT IF EXISTS resource_objects_state_check"
        )

    def corrupt_after_put(key):
        with psycopg.connect(migrated_pg.admin_dsn) as connection:
            connection.execute(
                "UPDATE enterprise.resource_objects SET state='future-state' "
                "WHERE tenant_id=%s AND owner_id=%s AND object_key=%s",
                (actor.tenant_id, actor.user_id, key),
            )

    object_store.on_put = corrupt_after_put
    with pytest.raises(ValueError, match="resource state is unknown"):
        await resources.put(
            resource_kind="workspace_output",
            resource_id="publish-state-race",
            filename="body.txt",
            data=b"body",
        )
    async with resources.store.db.transaction(resources.store.scope) as connection:
        row = await (
            await connection.execute(
                "SELECT r.state,j.state AS job_state FROM enterprise.resource_objects r "
                "LEFT JOIN enterprise.resource_cleanup_jobs j "
                "ON (j.tenant_id,j.owner_id,j.object_id)=(r.tenant_id,r.owner_id,r.id) "
                "WHERE r.tenant_id=%s AND r.owner_id=%s AND r.resource_id=%s",
                (*resources.store._owner, "publish-state-race"),
            )
        ).fetchone()
    assert row == {"state": "future-state", "job_state": None}
    assert list(object_store.objects.values()) == [b"body"]


async def test_ready_reference_rechecks_state_after_object_head(
    pg_session_store_factory, business_actors, migrated_pg,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    handle = await resources.put(
        resource_kind="turn_input",
        resource_id="reference-race",
        filename="body.bin",
        data=b"reference-race-payload",
    )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            "ALTER TABLE enterprise.resource_objects DROP CONSTRAINT IF EXISTS resource_objects_state_check"
        )

    def corrupt_after_head(_key):
        with psycopg.connect(migrated_pg.admin_dsn) as connection:
            connection.execute(
                "UPDATE enterprise.resource_objects SET state='future-state' "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (actor.tenant_id, actor.user_id, handle.object_id),
            )

    object_store.on_head = corrupt_after_head
    with pytest.raises(ValueError, match="resource state is unknown"):
        await resources.verify_ready_reference(resource_id="reference-race")


async def test_ready_reference_rechecks_session_binding_after_object_head(
    pg_session_store_factory, business_actors, migrated_pg,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    handle = await resources.put(
        resource_kind="turn_input",
        resource_id="reference-binding-race",
        filename="body.bin",
        data=b"reference-payload",
        metadata={"session_id": "original-session", "purpose": "chat_turn"},
    )

    def change_binding_after_head(_key):
        with psycopg.connect(migrated_pg.admin_dsn) as connection:
            connection.execute(
                "UPDATE enterprise.resource_objects "
                "SET metadata=jsonb_set(metadata,'{session_id}','\"other-session\"') "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (actor.tenant_id, actor.user_id, handle.object_id),
            )

    object_store.on_head = change_binding_after_head
    with pytest.raises(PermissionError, match="not bound to this session"):
        await resources.verify_ready_reference(
            resource_id="reference-binding-race",
            session_id="original-session",
            purpose="chat_turn",
        )


async def test_object_resource_rejects_unknown_retention_before_persisting_or_uploading(
    pg_session_store_factory, business_actors,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    with pytest.raises(ValueError, match="resource retention is unknown"):
        await resources.put(
            resource_kind="workspace_output",
            resource_id="invalid-retention",
            filename="body.txt",
            data=b"body",
            retention="future-retention",
        )
    assert object_store.puts == []
    assert await resources.list(resource_kind="workspace_output", resource_id="invalid-retention") == []


@pytest.mark.parametrize(
    ("constraint", "corruption", "message"),
    [
        ("resource_objects_state_check", "state='future-state'", "resource state is unknown"),
        ("resource_objects_retention_check", "retention='future-retention'", "resource retention is unknown"),
    ],
)
async def test_unknown_persisted_resource_cannot_be_listed_or_deleted(
    pg_session_store_factory,
    business_actors,
    migrated_pg,
    constraint,
    corruption,
    message,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    handle = await resources.put(
        resource_kind="workspace_output",
        resource_id="invalid-stored-resource",
        filename="body.txt",
        data=b"body",
    )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                f"ALTER TABLE enterprise.resource_objects DROP CONSTRAINT IF EXISTS {constraint}"
            )
            await connection.execute(
                f"UPDATE enterprise.resource_objects SET {corruption} "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (actor.tenant_id, actor.user_id, handle.object_id),
            )
    with pytest.raises(ValueError, match=message):
        await resources.list(
            resource_kind="workspace_output", resource_id="invalid-stored-resource"
        )
    with pytest.raises(ValueError, match=message):
        await resources.read(handle, filename="body.txt")
    with pytest.raises(ValueError, match=message):
        await resources.delete(handle)
    assert object_store.deletes == []
    assert list(object_store.objects.values()) == [b"body"]


async def test_unknown_cleanup_job_state_blocks_retry_before_objectstore_delete(
    pg_session_store_factory, business_actors, migrated_pg,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    handle = await resources.put(
        resource_kind="workspace_output",
        resource_id="invalid-cleanup-job",
        filename="body.txt",
        data=b"body",
    )
    object_store.fail_delete_once = True
    await resources.delete(handle)
    assert object_store.deletes and list(object_store.objects.values()) == [b"body"]
    before_deletes = list(object_store.deletes)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "ALTER TABLE enterprise.resource_cleanup_jobs "
                "DROP CONSTRAINT IF EXISTS resource_cleanup_jobs_state_check"
            )
            await connection.execute(
                "UPDATE enterprise.resource_cleanup_jobs SET state='future-state' "
                "WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                (actor.tenant_id, actor.user_id, handle.object_id),
            )
    with pytest.raises(ValueError, match="resource cleanup job state is unknown"):
        await resources.list_cleanup(resource_kind="workspace_output")
    with pytest.raises(ValueError, match="resource cleanup job state is unknown"):
        await resources.cleanup_pending(resource_kind="workspace_output")
    assert object_store.deletes == before_deletes
    assert list(object_store.objects.values()) == [b"body"]


async def test_cleanup_listing_rejects_unknown_resource_state_with_pending_job(
    pg_session_store_factory, business_actors, migrated_pg,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    handle = await resources.put(
        resource_kind="workspace_output",
        resource_id="unknown-state-pending-job",
        filename="body.txt",
        data=b"body",
    )
    object_store.fail_delete_once = True
    await resources.delete(handle)
    before_deletes = list(object_store.deletes)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            "ALTER TABLE enterprise.resource_objects "
            "DROP CONSTRAINT IF EXISTS resource_objects_state_check"
        )
        await connection.execute(
            "UPDATE enterprise.resource_objects SET state='future-state' "
            "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
            (actor.tenant_id, actor.user_id, handle.object_id),
        )

    with pytest.raises(ValueError, match="resource state is unknown"):
        await resources.list_cleanup(resource_kind="workspace_output")
    assert object_store.deletes == before_deletes


async def test_delete_request_cannot_overwrite_unknown_cleanup_job_state(
    pg_session_store_factory, business_actors, migrated_pg,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    handle = await resources.put(
        resource_kind="workspace_output",
        resource_id="delete-unknown-job",
        filename="body.txt",
        data=b"body",
    )
    object_store.fail_delete_once = True
    await resources.delete(handle)
    before_deletes = list(object_store.deletes)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "ALTER TABLE enterprise.resource_cleanup_jobs "
                "DROP CONSTRAINT IF EXISTS resource_cleanup_jobs_state_check"
            )
            await connection.execute(
                "UPDATE enterprise.resource_cleanup_jobs SET state='future-state' "
                "WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                (actor.tenant_id, actor.user_id, handle.object_id),
            )
    with pytest.raises(ValueError, match="resource cleanup job state is unknown"):
        await resources.delete(handle)
    assert object_store.deletes == before_deletes
    assert list(object_store.objects.values()) == [b"body"]


async def test_cleanup_rechecks_job_state_after_listing_before_side_effect(
    pg_session_store_factory, business_actors, migrated_pg, monkeypatch,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    handle = await resources.put(
        resource_kind="workspace_output",
        resource_id="cleanup-race",
        filename="body.txt",
        data=b"body",
    )
    object_store.fail_delete_once = True
    await resources.delete(handle)
    before_deletes = list(object_store.deletes)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            "ALTER TABLE enterprise.resource_cleanup_jobs "
            "DROP CONSTRAINT IF EXISTS resource_cleanup_jobs_state_check"
        )
    original_list = resources.list_cleanup

    async def corrupt_after_listing(*args, **kwargs):
        items = await original_list(*args, **kwargs)
        async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
            await connection.execute(
                "UPDATE enterprise.resource_cleanup_jobs SET state='future-state' "
                "WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                (actor.tenant_id, actor.user_id, handle.object_id),
            )
        return items

    monkeypatch.setattr(resources, "list_cleanup", corrupt_after_listing)
    with pytest.raises(ValueError, match="resource cleanup job state is unknown"):
        await resources.cleanup_pending(resource_kind="workspace_output")
    assert object_store.deletes == before_deletes
    assert list(object_store.objects.values()) == [b"body"]


@pytest.mark.parametrize(
    ("table", "constraint", "message"),
    [
        ("resource_objects", "resource_objects_state_check", "resource state is unknown"),
        (
            "resource_cleanup_jobs",
            "resource_cleanup_jobs_state_check",
            "resource cleanup job state is unknown",
        ),
    ],
)
async def test_cleanup_rechecks_business_state_after_objectstore_delete(
    pg_session_store_factory, business_actors, migrated_pg, table, constraint, message,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    handle = await resources.put(
        resource_kind="workspace_output",
        resource_id="cleanup-after-io-race",
        filename="body.txt",
        data=b"body",
    )
    object_store.fail_delete_once = True
    await resources.delete(handle)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            f"ALTER TABLE enterprise.{table} DROP CONSTRAINT IF EXISTS {constraint}"
        )

    def corrupt_after_delete(_key):
        with psycopg.connect(migrated_pg.admin_dsn) as connection:
            connection.execute(
                f"UPDATE enterprise.{table} SET state='future-state' "
                "WHERE tenant_id=%s AND owner_id=%s AND "
                + ("id=%s" if table == "resource_objects" else "object_id=%s"),
                (actor.tenant_id, actor.user_id, handle.object_id),
            )

    object_store.on_delete = corrupt_after_delete
    with pytest.raises(ValueError, match=message):
        await resources.cleanup_pending(resource_kind="workspace_output")
    async with resources.store.db.transaction(resources.store.scope) as connection:
        row = await (
            await connection.execute(
                "SELECT r.state AS resource_state,j.state AS job_state "
                "FROM enterprise.resource_objects r "
                "JOIN enterprise.resource_cleanup_jobs j "
                "ON (j.tenant_id,j.owner_id,j.object_id)=(r.tenant_id,r.owner_id,r.id) "
                "WHERE r.tenant_id=%s AND r.owner_id=%s AND r.id=%s",
                (*resources.store._owner, handle.object_id),
            )
        ).fetchone()
    assert row == {
        "resource_state": "future-state" if table == "resource_objects" else "delete-pending",
        "job_state": "future-state" if table == "resource_cleanup_jobs" else "running",
    }


@pytest.mark.parametrize(
    ("table", "constraint", "message"),
    [
        ("resource_objects", "resource_objects_state_check", "resource state is unknown"),
        (
            "resource_cleanup_jobs",
            "resource_cleanup_jobs_state_check",
            "resource cleanup job state is unknown",
        ),
    ],
)
async def test_cleanup_failure_does_not_overwrite_unknown_state_after_objectstore_error(
    pg_session_store_factory, business_actors, migrated_pg, table, constraint, message,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    handle = await resources.put(
        resource_kind="workspace_output",
        resource_id="cleanup-error-race",
        filename="body.txt",
        data=b"body",
    )
    object_store.fail_delete_once = True
    await resources.delete(handle)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            f"ALTER TABLE enterprise.{table} DROP CONSTRAINT IF EXISTS {constraint}"
        )

    def corrupt_on_delete_error(_key):
        with psycopg.connect(migrated_pg.admin_dsn) as connection:
            connection.execute(
                f"UPDATE enterprise.{table} SET state='future-state' "
                "WHERE tenant_id=%s AND owner_id=%s AND "
                + ("id=%s" if table == "resource_objects" else "object_id=%s"),
                (actor.tenant_id, actor.user_id, handle.object_id),
            )

    object_store.fail_delete_once = True
    object_store.on_delete_failure = corrupt_on_delete_error
    with pytest.raises(ValueError, match=message):
        await resources.cleanup_pending(resource_kind="workspace_output")
    async with resources.store.db.transaction(resources.store.scope) as connection:
        row = await (
            await connection.execute(
                "SELECT r.state AS resource_state,j.state AS job_state "
                "FROM enterprise.resource_objects r "
                "JOIN enterprise.resource_cleanup_jobs j "
                "ON (j.tenant_id,j.owner_id,j.object_id)=(r.tenant_id,r.owner_id,r.id) "
                "WHERE r.tenant_id=%s AND r.owner_id=%s AND r.id=%s",
                (*resources.store._owner, handle.object_id),
            )
        ).fetchone()
    assert row == {
        "resource_state": "future-state" if table == "resource_objects" else "delete-pending",
        "job_state": "future-state" if table == "resource_cleanup_jobs" else "running",
    }
    assert list(object_store.objects.values()) == [b"body"]


async def test_cleanup_rejects_unknown_resource_retention_before_delete(
    pg_session_store_factory, business_actors, migrated_pg,
):
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    handle = await resources.put(
        resource_kind="workspace_output",
        resource_id="cleanup-unknown-retention",
        filename="body.txt",
        data=b"body",
    )
    object_store.fail_delete_once = True
    await resources.delete(handle)
    before_deletes = list(object_store.deletes)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                "ALTER TABLE enterprise.resource_objects "
                "DROP CONSTRAINT IF EXISTS resource_objects_retention_check"
            )
            await connection.execute(
                "UPDATE enterprise.resource_objects SET retention='future-retention' "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (actor.tenant_id, actor.user_id, handle.object_id),
            )
    with pytest.raises(ValueError, match="resource retention is unknown"):
        await resources.list_cleanup(resource_kind="workspace_output")
    with pytest.raises(ValueError, match="resource retention is unknown"):
        await resources.cleanup_pending(resource_kind="workspace_output")
    assert object_store.deletes == before_deletes
    assert list(object_store.objects.values()) == [b"body"]


async def test_object_resource_store_round_trips_required_a2_file_kinds(
    pg_session_store_factory, business_actors
):
    """若 reading/workspace/artifact/export 等持久文件未写入 PG 元数据 + ObjectStore，本测试应失败。"""

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(store, object_store)

    samples = [
        ("reading_material", "reading-1", "chapter.txt", b"reading bytes"),
        ("workspace_output", "session-1/turn-1", "plot.svg", b"<svg />"),
        ("generated_artifact", "artifact-1", "answer.html", b"<html></html>"),
        ("export_file", "export-1", "annotated.md", b"# annotated"),
        ("persistent_intermediate", "job-1", "manifest.json", b"{}"),
    ]

    for kind, resource_id, filename, payload in samples:
        handle = await resources.put(
            resource_kind=kind,
            resource_id=resource_id,
            filename=filename,
            data=payload,
            mime_type="text/plain",
        )
        assert handle.resource_kind == kind
        assert handle.resource_id == resource_id
        assert handle.state == "ready"
        assert handle.size_bytes == len(payload)
        assert resources.proxy_url(handle, filename=filename).startswith(
            f"/files/resources/{kind}/{quote(resource_id, safe='')}/"
        )
        assert await resources.read(handle, filename=filename) == payload
        rebuilt_store = pg_session_store_factory(actor)
        rebuilt_resources = PostgresObjectResourceStore(rebuilt_store, object_store)
        assert await rebuilt_resources.read(handle, filename=filename) == payload

        listed = await resources.list(resource_kind=kind, resource_id=resource_id)
        assert [item.object_id for item in listed] == [handle.object_id]

    assert len(object_store.puts) == len(samples)
    assert len(object_store.gets) == len(samples) * 2


async def test_object_resource_delete_failure_is_queryable_and_retried(
    pg_session_store_factory, business_actors
):
    """若 ObjectStore 删除失败不进入可重试 cleanup job，本测试应失败。"""

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(store, object_store)

    handle = await resources.put(
        resource_kind="workspace_output",
        resource_id="session-1/turn-1",
        filename="plot.svg",
        data=b"<svg />",
        mime_type="image/svg+xml",
    )
    object_key = next(iter(object_store.objects))

    object_store.fail_delete_once = True
    first = await resources.delete(handle)
    assert first["pending"] == 1
    assert first["errors"] == [{"object_id": handle.object_id, "error": "objectstore_unavailable"}]
    assert object_store.objects[object_key] == b"<svg />"

    cleanup = await resources.list_cleanup(resource_kind="workspace_output")
    assert cleanup[0]["object_id"] == handle.object_id
    assert cleanup[0]["state"] == "failed"
    assert cleanup[0]["last_error"] == "objectstore_unavailable"

    second = await resources.cleanup_pending(resource_kind="workspace_output")
    assert second["pending"] == 0
    assert object_store.objects == {}
    assert object_store.deletes == [object_key, object_key]
    with pytest.raises(FileNotFoundError):
        await resources.read(handle, filename="plot.svg")


async def test_object_resource_create_and_delete_are_audited_without_private_body(
    pg_session_store_factory, business_actors
):
    """若资源创建/删除没有 PG 审计或审计暴露正文，本测试应失败。"""

    from deeptutor.persistence.postgres.governance import RuntimeGovernanceStore
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(store, object_store)

    handle = await resources.put(
        resource_kind="workspace_output",
        resource_id="session-1/turn-1",
        filename="private.txt",
        data=b"private_body_must_not_appear",
        mime_type="text/plain",
    )
    await resources.delete(handle)

    audit = await RuntimeGovernanceStore(store).list_audit(limit=20)
    kinds = {row["event_kind"] for row in audit}
    assert {"object.created", "object.delete_requested"} <= kinds
    assert "private_body_must_not_appear" not in str(audit)


async def test_object_resource_http_proxy_authorizes_before_objectstore_read(
    pg_session_store_factory, business_actors
):
    """若通用资源下载仅凭 object key/bucket 存在授权，本测试应失败。"""

    from fastapi import FastAPI
    import httpx

    from deeptutor.api.routers.resources import router
    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(store, object_store)
    handle = await resources.put(
        resource_kind="reading_material",
        resource_id="book-1",
        filename="chapter.txt",
        data=b"chapter",
        mime_type="text/plain",
    )
    object_key = next(iter(object_store.objects))
    url = resources.proxy_url(handle, filename="chapter.txt")

    app = FastAPI()
    app.include_router(router, prefix="/files/resources")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        foreign = pg_session_store_factory(business_actors.tenants[0].owners[1])
        with provider_context(ApplicationProviders(store=foreign, object_store=object_store)):
            response = await client.get(url)
        assert response.status_code in (403, 404)
        assert object_store.gets == []

        with provider_context(ApplicationProviders(store=store, object_store=object_store)):
            response = await client.get(url)
        assert response.status_code == 200
        assert response.content == b"chapter"
        assert response.headers["cache-control"] == "private, no-store"
        assert object_store.gets == [object_key]


async def test_object_resource_upload_publish_failure_records_cleanup_job(
    pg_session_store_factory, business_actors, migrated_pg
):
    """若对象已写入但 PG ready 发布失败后没有补偿记录，本测试应失败。"""

    import psycopg

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    class PublishFailingObjectStore(RecordingObjectStore):
        def put_bytes(self, key, data, **kwargs):
            ref = super().put_bytes(key, data, **kwargs)
            with psycopg.connect(migrated_pg.admin_dsn) as connection:
                connection.execute(
                    "UPDATE enterprise.resource_objects "
                    "SET state='delete-pending' WHERE object_key=%s",
                    (key,),
                )
            return ref

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = PublishFailingObjectStore()
    resources = PostgresObjectResourceStore(store, object_store)

    with pytest.raises(RuntimeError, match="resource object candidate") as failure:
        await resources.put(
            resource_kind="export_file",
            resource_id="export-1",
            filename="export.md",
            data=b"export body",
            mime_type="text/markdown",
        )

    object_id = failure.value.resource_operation_id
    object_key = next(iter(object_store.objects))
    cleanup = await resources.list_cleanup(resource_kind="export_file")
    assert cleanup[0]["object_id"] == object_id
    assert cleanup[0]["state"] == "pending"
    assert cleanup[0]["last_error"] == "upload_publish_failed"

    report = await resources.cleanup_pending(resource_kind="export_file")
    assert report["pending"] == 0
    assert object_store.objects == {}
    assert object_store.deletes == [object_key]


async def test_object_resource_rejects_forged_local_path_and_wrong_resource_binding(
    pg_session_store_factory, business_actors
):
    """若旧本地路径或伪造 resource_id 能绕过 PG metadata，本测试应失败。"""

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore
    from deeptutor.runtime.externalized_providers import ResourceHandle

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(store, object_store)
    handle = await resources.put(
        resource_kind="reading_material",
        resource_id="book-1",
        filename="chapter.txt",
        data=b"chapter",
        mime_type="text/plain",
    )

    forged = ResourceHandle(
        tenant_id=handle.tenant_id,
        owner_id=handle.owner_id,
        resource_kind=handle.resource_kind,
        resource_id="../data/user/workspace/book-1",
        object_id=handle.object_id,
        version=handle.version,
        state=handle.state,
        size_bytes=handle.size_bytes,
        sha256=handle.sha256,
        mime_type=handle.mime_type,
    )
    with pytest.raises(FileNotFoundError):
        await resources.read(forged, filename="chapter.txt")
    assert object_store.gets == []
    with pytest.raises(ValueError):
        resources.proxy_url(handle, filename="../secret.txt")


async def test_object_resource_store_covers_kb_persona_skill_and_notebook_kinds(
    pg_session_store_factory, business_actors
):
    """若 KB/persona/skill/notebook 仍只能靠本地路径归属，本测试应失败。"""

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(store, object_store)
    samples = [
        ("kb_source", "kb-1", "source.pdf", b"kb original"),
        ("dynamic_persona", "persona:socratic", "persona.md", b"persona body"),
        ("dynamic_skill", "skill:proof-helper", "skill.zip", b"skill package"),
        ("notebook_file", "notebook-1", "index.json", b"{\"entries\":[]}"),
    ]

    for kind, resource_id, filename, payload in samples:
        handle = await resources.put(
            resource_kind=kind,
            resource_id=resource_id,
            filename=filename,
            data=payload,
            mime_type="application/octet-stream",
        )
        assert await resources.read(handle, filename=filename) == payload

        foreign = PostgresObjectResourceStore(
            pg_session_store_factory(business_actors.tenants[0].owners[1]), object_store
        )
        with pytest.raises(FileNotFoundError):
            await foreign.read(handle, filename=filename)

    assert len(object_store.puts) == len(samples)


async def test_object_resource_cleanup_never_deletes_ready_or_foreign_owner_objects(
    pg_session_store_factory, business_actors
):
    """若 cleanup 按 bucket/prefix 扫描而误删仍被 PG 引用或其他 owner 对象，本测试应失败。"""

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    owner_a = business_actors.tenants[0].admin
    owner_b = business_actors.tenants[0].owners[1]
    object_store = RecordingObjectStore()
    resources_a = PostgresObjectResourceStore(pg_session_store_factory(owner_a), object_store)
    resources_b = PostgresObjectResourceStore(pg_session_store_factory(owner_b), object_store)
    keep_a = await resources_a.put(
        resource_kind="workspace_output",
        resource_id="same-suffix",
        filename="keep.txt",
        data=b"keep-a",
        mime_type="text/plain",
    )
    delete_b = await resources_b.put(
        resource_kind="workspace_output",
        resource_id="same-suffix",
        filename="delete.txt",
        data=b"delete-b",
        mime_type="text/plain",
    )

    report_a = await resources_a.cleanup_pending(resource_kind="workspace_output")
    assert report_a["pending"] == 0
    assert object_store.deletes == []
    assert await resources_a.read(keep_a, filename="keep.txt") == b"keep-a"

    report_b = await resources_b.delete(delete_b)
    assert report_b["pending"] == 0
    assert await resources_a.read(keep_a, filename="keep.txt") == b"keep-a"
    with pytest.raises(FileNotFoundError):
        await resources_b.read(delete_b, filename="delete.txt")


async def test_object_resource_bulk_and_large_payload_lifecycle(
    pg_session_store_factory, business_actors
):
    """若大附件/批量输出/删除风暴只在本地文件路径可用，本测试应失败。"""

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    resources = PostgresObjectResourceStore(pg_session_store_factory(actor), object_store)
    large = await resources.put(
        resource_kind="workspace_output",
        resource_id="bulk-run",
        filename="large.bin",
        data=b"x" * (1024 * 1024),
        mime_type="application/octet-stream",
    )
    batch = [
        await resources.put(
            resource_kind="generated_artifact",
            resource_id="bulk-run",
            filename=f"artifact-{i}.txt",
            data=f"artifact {i}".encode(),
            mime_type="text/plain",
        )
        for i in range(25)
    ]

    assert await resources.read(large, filename="large.bin") == b"x" * (1024 * 1024)
    assert len(await resources.list(resource_kind="generated_artifact", resource_id="bulk-run")) == 25

    for handle in batch:
        report = await resources.delete(handle)
        assert report["errors"] == []
    assert (await resources.cleanup_pending(resource_kind="generated_artifact"))["pending"] == 0
    with pytest.raises(FileNotFoundError):
        await resources.read(batch[0], filename="artifact-0.txt")


async def test_local_minio_presigned_upload_complete_read_and_delete(
    pg_session_store_factory, business_actors, monkeypatch
):
    """本地 MinIO 可用时，验证真实 pre-signed PUT → complete → read → delete 链路。"""

    import hashlib
    import os
    from pathlib import Path

    import httpx

    if os.environ.get("DEEPTUTOR_RUN_LOCAL_MINIO_TESTS") != "1":
        pytest.skip("set DEEPTUTOR_RUN_LOCAL_MINIO_TESTS=1 to run local MinIO integration")

    env_path = Path("/opt/data/minio/config/minio.env")
    if not env_path.exists():
        pytest.skip("local MinIO env file is unavailable")

    local_env: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        local_env[name.strip()] = value.strip().strip('"').strip("'")
    access = local_env.get("MINIO_ROOT_USER", "")
    secret = local_env.get("MINIO_ROOT_PASSWORD", "")
    region = local_env.get("MINIO_REGION_NAME", "us-east-1")
    if not access or not secret:
        pytest.skip("local MinIO credentials are unavailable")

    monkeypatch.setenv("DEEPLT_LOCAL_MINIO_ACCESS", access)
    monkeypatch.setenv("DEEPLT_LOCAL_MINIO_SECRET", secret)

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore
    from deeptutor.runtime.externalized_providers import (
        EnvSecretResolver,
        ObjectStoreError,
        S3CompatibleObjectStore,
        S3ObjectStoreConfig,
        SecretRef,
    )

    object_store = S3CompatibleObjectStore(
        S3ObjectStoreConfig(
            endpoint="http://127.0.0.1:9000",
            region=region,
            bucket="local-debug",
            access_key_ref=SecretRef.parse("env:DEEPLT_LOCAL_MINIO_ACCESS"),
            secret_key_ref=SecretRef.parse("env:DEEPLT_LOCAL_MINIO_SECRET"),
            path_style=True,
            verify_tls=False,
        ),
        secret_resolver=EnvSecretResolver(),
    )
    status = object_store.check_bucket()
    if not status.available:
        pytest.skip(f"local MinIO bucket local-debug unavailable: {status.code}")

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    resources = PostgresObjectResourceStore(store, object_store)
    payload = b"local-minio-presigned-upload-smoke"
    digest = hashlib.sha256(payload).hexdigest()
    session = await store.create_session(title="local minio resource smoke")
    intent = await resources.create_upload_intent(
        modality="image",
        mime_type="image/png",
        size_bytes=len(payload),
        sha256=digest,
        purpose="chat_turn",
        session_id=session["id"],
        filename="diagram.png",
        resource_kind="turn_input",
        expires_seconds=300,
    )
    assert intent["resource_id"].startswith("res_")
    assert "object_key" not in intent

    upload = httpx.put(
        intent["upload_url"],
        content=payload,
        headers=intent["headers"],
        timeout=10,
    )
    assert upload.status_code in (200, 204), upload.text

    handle = await resources.complete_upload_intent(resource_id=intent["resource_id"])
    assert handle.state == "ready"
    assert handle.sha256 == digest
    assert await resources.read(handle, filename="diagram.png") == payload
    await resources.verify_ready_reference(
        resource_id=intent["resource_id"],
        session_id=session["id"],
        purpose="chat_turn",
    )

    foreign = PostgresObjectResourceStore(
        pg_session_store_factory(business_actors.tenants[0].owners[1]),
        object_store,
    )
    with pytest.raises(FileNotFoundError):
        await foreign.verify_ready_reference(
            resource_id=intent["resource_id"],
            session_id=session["id"],
            purpose="chat_turn",
        )

    cleanup = await resources.delete(handle)
    assert cleanup["pending"] == 0
    with pytest.raises((FileNotFoundError, ObjectStoreError)):
        await resources.read(handle, filename="diagram.png")
