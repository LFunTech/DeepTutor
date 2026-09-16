from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.asyncio


class RecordingObjectStore:
    def __init__(self) -> None:
        self.config = SimpleNamespace(bucket="smoke-bucket")
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, key, data, *, expected_sha256=None, content_type="application/octet-stream"):
        import hashlib

        from deeptutor.runtime.externalized_providers import ObjectBlobRef

        digest = hashlib.sha256(data).hexdigest()
        assert expected_sha256 == digest
        self.objects[key] = bytes(data)
        return ObjectBlobRef(key=key, size_bytes=len(data), sha256=digest, content_type=content_type)

    def get_bytes(self, ref):
        return self.objects[ref.key]

    def delete(self, ref) -> None:
        self.objects.pop(ref.key, None)


async def test_empty_local_data_rebuild_and_dual_pod_share_pg_objectstore_state(
    pg_session_store_factory, business_actors, tmp_path
):
    """若已提交状态依赖旧 Pod 本地 data 或双 Pod 需要共享 PVC，本测试应失败。"""

    from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore
    from deeptutor.persistence.postgres.session_resources import PostgresObjectAttachmentStore

    actor = business_actors.tenants[0].admin
    pod_a_store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    attachments_a = PostgresObjectAttachmentStore(pod_a_store, object_store)
    resources_a = PostgresObjectResourceStore(pod_a_store, object_store)

    local_data = tmp_path / "data"
    (local_data / "user" / "workspace").mkdir(parents=True)
    (local_data / "user" / "workspace" / "scratch.txt").write_text("scratch", encoding="utf-8")

    await pod_a_store.create_session(session_id="s")
    attachment_url = await attachments_a.put(
        session_id="s",
        attachment_id="upload-1",
        filename="a.txt",
        data=b"attachment",
        mime_type="text/plain",
    )
    attachment_id = attachment_url.split("/")[-2]
    await pod_a_store.add_message(
        "s",
        "user",
        "with attachment",
        attachments=[{"id": "upload-1", "url": attachment_url, "filename": "a.txt"}],
    )

    handles = []
    for kind in [
        "reading_material",
        "workspace_output",
        "dynamic_persona",
        "dynamic_skill",
        "notebook_file",
        "kb_source",
    ]:
        handles.append(
            (
                kind,
                await resources_a.put(
                    resource_kind=kind,
                    resource_id="stateless-smoke",
                    filename=f"{kind}.bin",
                    data=kind.encode(),
                    mime_type="application/octet-stream",
                ),
            )
        )

    async with pod_a_store.db.transaction(pod_a_store.scope) as c:
        await c.execute(
            "INSERT INTO enterprise.runtime_settings(tenant_id,scope_kind,scope_id,key,desired,active,status,updated_by) VALUES(%s,'owner',%s,'model.default',%s,%s,'active',%s)",
            (
                pod_a_store._owner[0],
                pod_a_store._owner[1],
                '{"model":"gpt"}',
                '{"model":"gpt"}',
                pod_a_store._owner[1],
            ),
        )
        await c.execute(
            "INSERT INTO enterprise.runtime_policies(tenant_id,policy_kind,subject_kind,subject_id,document,status,updated_by) VALUES(%s,'tool-grants','owner',%s,%s,'active',%s)",
            (pod_a_store._owner[0], pod_a_store._owner[1], '{"tools":["web_search"]}', pod_a_store._owner[1]),
        )

    shutil.rmtree(local_data)

    pod_b_store = pg_session_store_factory(actor)
    attachments_b = PostgresObjectAttachmentStore(pod_b_store, object_store)
    resources_b = PostgresObjectResourceStore(pod_b_store, object_store)
    detail = await pod_b_store.get_session_with_messages("s")
    assert detail is not None
    assert await attachments_b.read_attachment(
        session_id="s", attachment_id=attachment_id, filename="a.txt"
    ) == b"attachment"
    for kind, handle in handles:
        assert await resources_b.read(handle, filename=f"{kind}.bin") == kind.encode()

    async with pod_b_store.db.transaction(pod_b_store.scope) as c:
        settings = await (await c.execute("SELECT active FROM enterprise.runtime_settings WHERE key='model.default'")).fetchone()
        policy = await (await c.execute("SELECT document FROM enterprise.runtime_policies WHERE policy_kind='tool-grants'")).fetchone()
    assert settings["active"]["model"] == "gpt"
    assert policy["document"]["tools"] == ["web_search"]
