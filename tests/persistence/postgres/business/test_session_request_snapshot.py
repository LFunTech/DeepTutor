"""I115-01/02：实际请求快照 helper 与真实 PG Store 的合同回归。"""

import pytest

from deeptutor.persistence.postgres.session_resources import PostgresAttachmentStore
from deeptutor.persistence.resources import OwnerResourceProvider
from deeptutor.services.session._turn_runtime_shared import _request_snapshot_metadata
from tests.persistence.postgres.business.test_reading_catalog import factory

pytestmark = pytest.mark.asyncio


def snapshot(*, attachments=None, payload=None):
    return _request_snapshot_metadata(
        payload=payload or {},
        content="Q",
        capability="chat",
        config={},
        attachments=attachments or [],
        notebook_references=[],
        history_references=[],
        partner_group_references=[],
        question_notebook_references=[],
        book_references=[],
        persona="",
        memory_references=[],
        llm_selection=None,
    )


@pytest.mark.parametrize("top_level", [True, False])
@pytest.mark.parametrize("delete", ["message", "session"])
async def test_real_snapshot_attachment_is_authorized_registered_and_cleaned(
    top_level, delete, pg_session_store_factory, business_actors, tmp_path
):
    store = pg_session_store_factory(business_actors.tenants[0].owners[0])
    files = PostgresAttachmentStore(store, OwnerResourceProvider(tmp_path.absolute()))
    await store.create_session(session_id="s")
    url = await files.put(
        session_id="s", attachment_id="logical", filename="a.txt", data=b"snapshot bytes"
    )
    attachment = {"id": "logical", "url": url, "filename": "a.txt"}
    metadata = snapshot(attachments=[attachment])
    mid = await store.add_message(
        "s", "user", "Q", attachments=[attachment] if top_level else None, metadata=metadata
    )
    row = (await store.get_messages("s"))[0]
    assert row["metadata"] == metadata
    assert (
        await files.read_attachment(
            session_id="s", attachment_id=url.split("/")[-2], filename="a.txt"
        )
        == b"snapshot bytes"
    )
    physical = list(tmp_path.rglob("*.blob"))[0]
    if delete == "message":
        assert await store.delete_message(mid)
    else:
        assert await store.delete_session("s")
    assert (await files.cleanup_pending())["pending"] == 0
    assert not physical.exists()


@pytest.mark.parametrize("invalid", ["foreign", "old_generation", "unsupported"])
async def test_snapshot_attachment_cannot_bypass_object_authority(
    invalid, pg_session_store_factory, business_actors, tmp_path
):
    actor, other = business_actors.tenants[0].owners[:2]
    store = pg_session_store_factory(actor)
    await store.create_session(session_id="s")
    source = pg_session_store_factory(other) if invalid == "foreign" else store
    if invalid == "foreign":
        await source.create_session(session_id="foreign")
    files = PostgresAttachmentStore(source, OwnerResourceProvider(tmp_path.absolute()))
    url = await files.put(
        session_id="foreign" if invalid == "foreign" else "s",
        attachment_id="a",
        filename="a",
        data=b"x",
    )
    if invalid == "foreign":
        url = url.replace("/attachments/foreign/", "/attachments/s/")
    if invalid == "old_generation":
        await store.delete_session("s")
        await store.create_session(session_id="s")
    if invalid == "unsupported":
        url = "/files/outputs/no-authority"
    with pytest.raises(ValueError):
        await store.add_message("s", "user", "Q", metadata=snapshot(attachments=[{"url": url}]))
    assert await store.get_messages("s") == []


async def test_real_camelcase_snapshot_retains_all_typed_targets_after_preferences_detach(
    pg_session_store_factory,
    pg_learning_store_factory,
    business_sync_database,
    pg_scope_factory,
    business_actors,
):
    from deeptutor.learning.contracts import LearningReferenceError
    from deeptutor.learning.models import LearningProgress
    from deeptutor.persistence.postgres.session_references import references
    from deeptutor.persistence.postgres.session_validation import validate_reference_shape
    from deeptutor.reading.catalog_contracts import ReadingReferenceError

    actor = business_actors.tenants[0].owners[0]
    store, learning = pg_session_store_factory(actor), pg_learning_store_factory(actor)
    reading = factory(business_sync_database, pg_scope_factory, actor)
    await reading.run(
        lambda u: u.upsert_material(
            content_id="abcdef12", filename="m", title="m", source_kind="file"
        )
    )
    await reading.run(lambda u: u.create_workspace("w", [], workspace_id="w"))
    await learning.run(lambda u: u.save(LearningProgress(book_id="p")))
    payload = {
        "mastery_path_id": "p",
        "reading_workspace_id": "w",
        "reading_material_id": "abcdef12",
    }
    await store.create_session(session_id="s")
    await store.update_session_preferences("s", payload)
    metadata = snapshot(payload=payload)
    validate_reference_shape(metadata)
    assert set(references(metadata)) == set(payload.items())
    mid = await store.add_message("s", "user", "Q", metadata=metadata)
    await store.update_session_preferences("s", {key: "" for key in payload})
    with pytest.raises(ReadingReferenceError):
        await reading.run(lambda u: u.delete_material("abcdef12"))
    with pytest.raises(ReadingReferenceError):
        await reading.run(lambda u: u.delete_workspace("w"))
    with pytest.raises(LearningReferenceError):
        await learning.run(lambda u: u.delete("p"))
    assert (await store.get_messages("s"))[0]["metadata"] == metadata
    await store.delete_message(mid)
    assert await reading.run(lambda u: u.delete_material("abcdef12"))
    assert await reading.run(lambda u: u.delete_workspace("w"))
    await learning.run(lambda u: u.delete("p"))
    assert await learning.run(lambda u: u.load("p")) is None


@pytest.mark.parametrize("key", ["masteryPathId", "readingMaterialId", "readingWorkspaceId"])
async def test_snapshot_typed_reference_rejects_missing_or_wrong_shape(
    key, pg_session_store_factory, business_actors
):
    store = pg_session_store_factory(business_actors.tenants[0].owners[0])
    await store.create_session(session_id="s")
    for value in ("foreign", {"id": "foreign"}):
        with pytest.raises(ValueError):
            await store.add_message("s", "user", "Q", metadata={"request_snapshot": {key: value}})
    assert await store.get_messages("s") == []


@pytest.mark.parametrize("path", ["metadata_root", "nested_snapshot", "unsupported_provider"])
async def test_snapshot_allowance_does_not_open_other_attachment_or_provider_paths(
    path, pg_session_store_factory, business_actors, tmp_path
):
    store = pg_session_store_factory(business_actors.tenants[0].owners[0])
    files = PostgresAttachmentStore(store, OwnerResourceProvider(tmp_path.absolute()))
    await store.create_session(session_id="s")
    url = await files.put(session_id="s", attachment_id="a", filename="a", data=b"x")
    attachment = {"url": url}
    metadata = (
        {"attachments": [attachment]}
        if path == "metadata_root"
        else {"nested": snapshot(attachments=[attachment])}
    )
    if path == "unsupported_provider":
        metadata = snapshot(attachments=[attachment])
        metadata["request_snapshot"]["config"] = {"course_id": "no-provider"}
    with pytest.raises(ValueError):
        await store.add_message("s", "user", "Q", metadata=metadata)
    assert await store.get_messages("s") == []

def test_rag_sources_metadata_kb_name_is_not_treated_as_unscoped_dependency():
    from deeptutor.persistence.postgres.session_validation import validate_reference_shape

    validate_reference_shape(
        [
            {
                "type": "tool_call",
                "metadata": {
                    "args": {"query": "二次函数", "kb_name": "user:kb:test"}
                },
            },
            {
                "type": "sources",
                "metadata": {
                    "sources": [
                        {
                            "type": "rag",
                            "kb_name": "user:kb:test",
                            "title": "课堂资料",
                            "metadata": {"kb_name": "user:kb:test"},
                        }
                    ]
                },
            },
        ]
    )
    with pytest.raises(ValueError):
        validate_reference_shape({"metadata": {"kb_name": "user:kb:foreign"}})
