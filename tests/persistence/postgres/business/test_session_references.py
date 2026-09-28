"""允许的机器引用必须由 PG FK 保持，不能仅先查存在再存任意 JSON。"""

import psycopg
import pytest

from deeptutor.reading.catalog_contracts import ReadingReferenceError
from tests.persistence.postgres.business.test_reading_catalog import factory

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("constraint", "corruption", "message"),
    [
        ("session_references_kind_check", "kind='future-kind'", "session reference kind is unknown"),
        ("session_references_source_kind_check", "source_kind='future-source'", "session reference source kind is unknown"),
    ],
)
async def test_unknown_persisted_reference_blocks_read_update_and_delete_claim(
    business_sync_database,
    pg_scope_factory,
    pg_session_store_factory,
    business_actors,
    migrated_pg,
    constraint,
    corruption,
    message,
):
    actor = business_actors.tenants[0].owners[0]
    store = pg_session_store_factory(actor)
    reading = factory(business_sync_database, pg_scope_factory, actor)
    await reading.run(
        lambda unit: unit.upsert_material(
            content_id="m", filename="m", title="m", source_kind="file"
        )
    )
    await store.create_session(session_id="s")
    await store.update_session_preferences("s", {"reading_material_id": "m"})
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                f"ALTER TABLE enterprise.session_references DROP CONSTRAINT IF EXISTS {constraint}"
            )
            await connection.execute(
                f"UPDATE enterprise.session_references SET {corruption} "
                "WHERE tenant_id=%s AND owner_id=%s AND session_id='s'",
                (actor.tenant_id, actor.user_id),
            )
    async with store.db.transaction(store.scope) as connection:
        scoped_rows = await (
            await connection.execute(
                "SELECT kind,source_kind FROM enterprise.session_references "
                "WHERE tenant_id=%s AND owner_id=%s AND session_id='s'",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchall()
    assert scoped_rows and any(
        row["kind"] == "future-kind" or row["source_kind"] == "future-source"
        for row in scoped_rows
    ), scoped_rows
    with pytest.raises(ValueError, match=message):
        await store.get_session("s")
    with pytest.raises(ValueError, match=message):
        await store.update_session_preferences("s", {"reading_material_id": ""})
    with pytest.raises(ValueError, match=message):
        await store.claim_deletion("s")
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        result = await connection.execute(
            "SELECT deleting,preferences->>'reading_material_id' FROM enterprise.sessions "
            "WHERE tenant_id=%s AND owner_id=%s AND id='s'",
            (actor.tenant_id, actor.user_id),
        )
        assert await result.fetchone() == (False, "m")


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
