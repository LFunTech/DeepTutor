"""完整 Session 领域服务组合，不把 CREATE_ROW 当 create_session。"""

import pytest

from tests.persistence.postgres.business.test_reading_catalog import factory

pytestmark = pytest.mark.asyncio


async def test_complete_create_preferences_rename_and_reading_membership_atomic(
    business_sync_database, pg_scope_factory, business_actors, pg_session_store_factory
):
    actor = business_actors.tenants[0].owners[0]
    reading = factory(business_sync_database, pg_scope_factory, actor)
    store = pg_session_store_factory(actor)

    def write(u):
        u.upsert_material(content_id="m", filename="m", title="m", source_kind="file")
        u.create_workspace("w", ["m"], workspace_id="w")

        def composed(unit, e):
            row = e.create_session(
                title="  Title  ",
                session_id="s",
                preferences={
                    "reading_workspace_id": "w",
                    "reading_material_id": "m",
                    "pinned": True,
                },
            )
            assert row["title"] == "Title" and row["message_count"] == 0
            unit.attach_session("w", "s", title="Title", active_material_id="m")
            assert e.update_session_title("s", "Renamed", expected_version=row["version"])
            unit.rename_session("w", "s", "Renamed")
            return row

        return u.compose(composed)

    await reading.run(write)
    row = await store.get_session("s")
    assert row["title"] == "Renamed" and row["preferences"]["pinned"]
    assert (await reading.run(lambda u: u.list_sessions("w")))[0].title == "Renamed"
    async with store.db.transaction(store.scope) as c:
        count = await (
            await c.execute(
                "SELECT count(*) AS n FROM enterprise.audit WHERE tenant_id=%s AND actor_id=%s AND target_id='s' AND action='session.create'",
                store._owner,
            )
        ).fetchone()
        assert count["n"] == 1

    def rollback(u):
        def composed(unit, e):
            e.create_session(session_id="rolled", preferences={"reading_workspace_id": "w"})
            unit.attach_session("w", "rolled")
            raise ValueError("synthetic failure")

        u.compose(composed)

    with pytest.raises(ValueError):
        await reading.run(rollback)
    assert await store.get_session("rolled") is None
    assert len(await reading.run(lambda u: u.list_sessions("w"))) == 1


async def test_complete_create_invalid_reference_poison_even_if_swallowed(
    business_sync_database, pg_scope_factory, business_actors, pg_session_store_factory
):
    actor = business_actors.tenants[0].owners[0]
    reading = factory(business_sync_database, pg_scope_factory, actor)
    store = pg_session_store_factory(actor)

    def write(u):
        u.upsert_material(content_id="m", filename="m", title="m", source_kind="file")

        def compose(unit, e):
            try:
                e.create_session(session_id="s", preferences={"reading_material_id": "foreign"})
            except (ValueError, RuntimeError):
                pass

        u.compose(compose)

    from deeptutor.reading.catalog_contracts import ReadingError

    with pytest.raises(ReadingError, match="poisoned"):
        await reading.run(write)
    assert await reading.run(lambda u: u.get_material("m")) is None
    assert await store.get_session("s") is None


async def test_detach_and_complete_session_delete_rollback_as_one_unit(
    business_sync_database, pg_scope_factory, business_actors, pg_session_store_factory
):
    actor = business_actors.tenants[0].owners[0]
    reading = factory(business_sync_database, pg_scope_factory, actor)
    store = pg_session_store_factory(actor)

    def seed(u):
        u.create_workspace("w", [], workspace_id="w")
        u.compose(lambda unit, e: e.create_session(session_id="s"))
        u.attach_session("w", "s")

    await reading.run(seed)

    def remove(u, fail):
        def compose(unit, e):
            unit.detach_session("w", "s")
            assert e.delete_session("s")
            if fail:
                raise ValueError("after detach/delete")

        u.compose(compose)

    with pytest.raises(ValueError, match="after detach"):
        await reading.run(lambda u: remove(u, True))
    assert await store.get_session("s")
    assert len(await reading.run(lambda u: u.list_sessions("w"))) == 1
    await reading.run(lambda u: remove(u, False))
    assert await store.get_session("s") is None
    assert await reading.run(lambda u: u.list_sessions("w")) == []


async def test_internal_lifecycle_steps_not_public_row_operations(
    business_sync_database, pg_scope_factory, business_actors, pg_session_store_factory
):
    from deeptutor.persistence.postgres.session_statements import SessionStatement
    from deeptutor.reading.catalog_contracts import ReadingError

    actor = business_actors.tenants[0].owners[0]
    reading = factory(business_sync_database, pg_scope_factory, actor)
    store = pg_session_store_factory(actor)
    await store.create_session(session_id="s")

    def write(u):
        def compose(unit, e):
            try:
                e.execute(SessionStatement.DELETE_ROW, ("s",))
            except ReadingError:
                pass

        u.compose(compose)

    with pytest.raises(ReadingError, match="poisoned"):
        await reading.run(write)
    assert await store.get_session("s")
