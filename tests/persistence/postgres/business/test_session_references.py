"""允许的机器引用必须由 PG FK 保持，不能仅先查存在再存任意 JSON。"""

import pytest

from deeptutor.reading.catalog_contracts import ReadingReferenceError
from tests.persistence.postgres.business.test_reading_catalog import factory

pytestmark = pytest.mark.asyncio


async def test_reading_preference_reference_blocks_material_delete_until_detached(
    business_sync_database, pg_scope_factory, pg_session_store_factory, business_actors
):
    actor = business_actors.tenants[0].owners[0]
    store = pg_session_store_factory(actor)
    reading = factory(business_sync_database, pg_scope_factory, actor)
    await reading.run(
        lambda u: u.upsert_material(content_id="m", filename="m", title="m", source_kind="file")
    )
    await store.create_session(session_id="s")
    await store.update_session_preferences("s", {"reading_material_id": "m"})
    with pytest.raises(ReadingReferenceError):
        await reading.run(lambda u: u.delete_material("m"))
    await store.update_session_preferences("s", {"reading_material_id": ""})
    assert await reading.run(lambda u: u.delete_material("m"))


async def test_message_reference_is_removed_with_message(
    business_sync_database, pg_scope_factory, pg_session_store_factory, business_actors
):
    actor = business_actors.tenants[0].owners[0]
    store = pg_session_store_factory(actor)
    reading = factory(business_sync_database, pg_scope_factory, actor)
    await reading.run(
        lambda u: u.upsert_material(content_id="m", filename="m", title="m", source_kind="file")
    )
    await store.create_session(session_id="s")
    mid = await store.add_message("s", "user", "ref", metadata={"reading_material_id": "m"})
    with pytest.raises(ReadingReferenceError):
        await reading.run(lambda u: u.delete_material("m"))
    await store.delete_message(mid)
    assert await reading.run(lambda u: u.delete_material("m"))
