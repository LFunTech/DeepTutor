"""Reading 目录完整 PG unit：真实低权连接与认证 actor。"""

import importlib.util

import pytest

pytestmark = pytest.mark.asyncio


def factory(database, scopes, actor):
    assert importlib.util.find_spec("deeptutor.persistence.postgres.reading") is not None, (
        "PG reading catalog 尚未实现"
    )
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore

    return AsyncReadingCatalogStore(database, scopes(actor))


async def test_material_and_workspace_contract(
    business_sync_database, business_actors, pg_scope_factory
):
    store = factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])

    def exercise(u):
        a = u.upsert_material(
            content_id="content",
            material_id="a",
            filename="one.pdf",
            title="一",
            source_kind="file",
            status="ready",
            cover_url="cover",
            duration_seconds=8,
        )
        b = u.upsert_material(
            content_id="content",
            material_id="b",
            filename="two.pdf",
            title="二",
            source_kind="file",
        )
        assert a.progress == 100 and a.version == 1
        assert u.count_materials_for_content("content") == 2
        assert u.find_material_by_content("content").material_id == "a"
        a2 = u.upsert_material(
            content_id="content",
            material_id="a",
            filename="one.pdf",
            title="更新",
            source_kind="file",
            status="ready",
            expected_version=a.version,
        )
        assert (
            a2.cover_url == "cover" and a2.duration_seconds == 8 and a2.created_at == a.created_at
        )
        assert a2.version == 2 and a2.to_dict()["version"] == 2
        w = u.create_workspace("阅读", ["a", "b", "a"], workspace_id="w")
        assert [t.material.material_id for t in w.tabs] == ["a", "b"]
        assert w.active_material_id == "a" and w.version == 1
        w = u.reorder_materials("w", ["b", "a"], expected_version=w.version)
        assert [t.tab_order for t in w.tabs] == [0, 1]
        assert w.to_dict()["version"] == 2
        assert u.library_counts()["all"] == 2
        assert u.collections_for_material("a") == [{"workspace_id": "w", "title": "阅读"}]
        assert u.list_workspaces()[0] == w
        assert u.update_material_status("b", "failed", progress=120).progress == 99
        return w

    await store.run(exercise)


async def test_all_material_queries_and_workspace_mutations(
    business_sync_database, business_actors, pg_scope_factory
):
    from types import SimpleNamespace

    store = factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])

    def exercise(u):
        u.register_manifest(
            SimpleNamespace(
                material_id="manifest",
                filename="Example.PDF",
                title="100%_图",
                mime="application/pdf",
                render_mode="text",
            )
        )
        u.upsert_material(
            content_id="c", material_id="other", filename="other", title="other", source_kind="web"
        )
        assert [x.material_id for x in u.list_materials(search="%_")] == ["manifest"]
        assert (
            u.find_ready_material_by_filename("/tmp/example.pdf", mime="different").material_id
            == "manifest"
        )
        assert u.find_ready_material_by_filename("example.pdf").material_id == "manifest"
        assert u.find_ready_material_by_filename("missing") is None
        assert u.list_materials(status="failed") == []
        assert len(u.list_materials(library_filter="processing")) == 1
        assert u.library_counts([])["all"] == 0
        assert u.library_counts(["manifest"])["by_kind"]["document"] == 1
        w = u.create_workspace("empty", workspace_id="w")
        w = u.add_material("w", "manifest", expected_version=w.version)
        w = u.add_material("w", "manifest", expected_version=w.version)
        assert len(w.tabs) == 1
        w = u.add_material("w", "other", make_active=True, expected_version=w.version)
        assert w.active_material_id == "other"
        w = u.set_active_material("w", "manifest", expected_version=w.version)
        assert u.get_material("manifest").last_opened_at > 0
        w = u.update_workspace("w", title="新", description="说明", expected_version=w.version)
        assert w.title == "新" and w.description == "说明"
        assert u.collections_for_materials(["manifest", "missing"]) == {
            "manifest": [{"workspace_id": "w", "title": "新"}],
            "missing": [],
        }
        w = u.remove_material("w", "manifest", expected_version=w.version)
        assert w.active_material_id == "other" and w.tabs[0].tab_order == 0
        assert [x.material_id for x in u.list_materials(library_filter="unassigned")] == [
            "manifest"
        ]
        with u.locked_content("manifest") as plan:
            assert (
                plan.last_reference and plan.material_version == u.get_material("manifest").version
            )
            assert u.delete_material("manifest", expected_version=plan.material_version)
        assert not u.delete_material("manifest")
        assert u.delete_workspace("w", expected_version=w.version)
        assert not u.delete_workspace("w")
        assert u.get_workspace("w") is None

    await store.run(exercise)


async def test_sessions_links_same_real_session_and_scope(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    actor = business_actors.tenants[0].owners[0]
    store = factory(business_sync_database, pg_scope_factory, actor)
    chat = pg_session_store_factory(actor)
    await chat.create_session("one", session_id="s1")
    await chat.create_session("two", session_id="s2")

    def exercise(u):
        u.upsert_material(content_id="a", filename="a", title="a", source_kind="file")
        w = u.create_workspace("w", ["a"], workspace_id="w")
        s1 = u.attach_session("w", "s1", active_material_id="a")
        assert s1.to_dict()["version"] == 1
        s2 = u.attach_session("w", "s2")
        assert s2.active_material_id is None
        assert {s.session_id for s in u.list_sessions("w")} == {"s1", "s2"}
        s1 = u.rename_session("w", "s1", "new", expected_version=s1.version)
        assert s1.title == "new" and s1.version == 2
        u.link_session("w", "s1", "s2")
        u.link_session("w", "s1", "s2")
        assert u.list_session_links("w", "s1") == ["s2"]
        assert u.unlink_session("w", "s1", "s2") and not u.unlink_session("w", "s1", "s2")
        u.link_session("w", "s1", "s2")
        u.remove_material("w", "a", expected_version=w.version)
        s1 = next(s for s in u.list_sessions("w") if s.session_id == "s1")
        assert s1.active_material_id is None and s1.version == 3
        assert u.detach_session("w", "s2", expected_version=s2.version)
        assert u.list_session_links("w", "s1") == []
        assert not u.detach_session("w", "s2")

    await store.run(exercise)


async def test_stable_keyset_pages_and_explicit_legacy_limit(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    from deeptutor.reading.catalog_contracts import ReadingPageRequired

    actor = business_actors.tenants[0].owners[0]
    store = factory(business_sync_database, pg_scope_factory, actor)
    chats = pg_session_store_factory(actor)
    for sid in ["s1", "s2", "s3"]:
        await chats.create_session(session_id=sid)

    def seed(u):
        for i in range(503):
            u.upsert_material(
                content_id=f"m{i:04d}",
                filename=f"{i}.pdf",
                title=f"{i}%",
                source_kind="file",
                status="ready",
            )
        # 同 timestamp 的排序必须使用唯一 ID；只用 test 控制时间，而不虚构身份。
        u._execute(
            "UPDATE enterprise.reading_materials SET updated_at=1 WHERE tenant_id=%s AND owner_id=%s",
            u._owner,
        )
        summary = u.create_workspace(
            "大集合", [f"m{i:04d}" for i in range(503)], workspace_id="w", return_summary=True
        )
        assert summary.tab_count == 503 and summary.version == 1
        for sid in ["s1", "s2", "s3"]:
            u.attach_session("w", sid)
        u.link_session("w", "s1", "s2")
        u.link_session("w", "s1", "s3")

    await store.run(seed)
    with pytest.raises(ReadingPageRequired):
        await store.run(lambda u: u.get_workspace("w"))
    with pytest.raises(ReadingPageRequired):
        await store.run(lambda u: u.list_workspaces())

    async def collect(method, **kwargs):
        cursor = None
        items = []
        while True:
            page = await store.run(lambda u: getattr(u, method)(cursor=cursor, limit=37, **kwargs))
            assert len(page.items) <= 37
            items.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                return items

    materials = await collect("list_materials_page", search="%")
    assert [m.material_id for m in materials] == [f"m{i:04d}" for i in range(502, -1, -1)]
    tabs = await collect("list_tabs_page", workspace_id="w")
    assert [t.tab_order for t in tabs] == list(range(503))
    summaries = await collect("list_workspaces_page")
    assert len(summaries) == 1 and summaries[0].tab_count == 503
    assert {s.session_id for s in await collect("list_sessions_page", workspace_id="w")} == {
        "s1",
        "s2",
        "s3",
    }
    assert set(
        await collect("list_session_links_page", workspace_id="w", source_session_id="s1")
    ) == {"s2", "s3"}
    memberships = await collect("list_collections_page", material_ids=["m0000", "m0001"])
    assert {(m.material_id, m.workspace_id) for m in memberships} == {
        ("m0000", "w"),
        ("m0001", "w"),
    }
    summary = await store.run(
        lambda u: u.add_material("w", "m0000", return_summary=True, expected_version=1)
    )
    assert summary.tab_count == 503 and summary.version == 2


async def test_notebook_reading_requires_current_ready_typed_material(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    from deeptutor.reading.catalog_contracts import ReadingReferenceError
    from deeptutor.services.session.question_bank import QuestionBankReferenceConflict

    actor = business_actors.tenants[0].owners[0]
    store = factory(business_sync_database, pg_scope_factory, actor)
    chat = pg_session_store_factory(actor)
    await chat.create_session(session_id="s")
    # immersive_reading 的空 turn 合同保留；section 是文件 unit，不伪造 PG parent。
    item = {
        "question_id": "q",
        "question": "问题",
        "source": "immersive_reading",
        "material_id": "m",
        "section_id": "1",
    }
    await store.run(
        lambda u: u.upsert_material(content_id="m", filename="m", title="m", source_kind="file")
    )
    with pytest.raises(QuestionBankReferenceConflict, match="ready"):
        await chat.upsert_notebook_entries("s", [item])
    await store.run(lambda u: u.update_material_status("m", "ready"))
    assert await chat.upsert_notebook_entries("s", [item]) == 1
    await store.run(lambda u: u.create_workspace("w", ["m"], workspace_id="w"))
    before = await store.run(lambda u: u.get_workspace("w"))
    with pytest.raises(ReadingReferenceError):
        await store.run(lambda u: u.delete_material("m"))
    assert await store.run(lambda u: u.get_workspace("w")) == before


async def test_protected_session_composition_lifetime_poison_and_atomicity(
    business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.persistence.postgres.session_statements import SessionStatement as S
    from deeptutor.reading.models import ReadingError

    store = factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    escaped = []

    def collect(u):
        def compose(unit, c):
            escaped.extend([unit, c, c.execute(S.GET_ROW, ("missing",))])
            assert not hasattr(c, "connection") and not hasattr(c, "cursor")

        u.compose(compose)

    await store.run(collect)
    for action in [
        lambda: escaped[0].get_material("x"),
        lambda: escaped[1].execute(S.GET_ROW, ("x",)),
        lambda: escaped[2].fetchone(),
    ]:
        with pytest.raises(RuntimeError, match="inactive"):
            action()

    def swallowed(u):
        try:

            def duplicate(_, c):
                c.execute(S.CREATE_ROW, ("duplicate", "one"))
                c.execute(S.CREATE_ROW, ("duplicate", "two"))

            u.compose(duplicate)
        except Exception:
            pass
        return "cannot commit"

    with pytest.raises(ReadingError, match="poisoned"):
        await store.run(swallowed)
    assert (
        await store.run(
            lambda u: u.compose(lambda _, c: c.execute(S.GET_ROW, ("duplicate",)).fetchone())
        )
        is None
    )

    def rollback(u):
        u.upsert_material(content_id="m", filename="m", title="m", source_kind="file")
        u.compose(lambda _, c: c.execute(S.CREATE_ROW, ("s", "created")))
        u.create_workspace("w", ["m"], workspace_id="w")
        u.attach_session("w", "s")
        raise ValueError("rollback composed session")

    with pytest.raises(ValueError, match="rollback composed"):
        await store.run(rollback)
    assert await store.run(lambda u: u.get_material("m")) is None
    assert (
        await store.run(lambda u: u.compose(lambda _, c: c.execute(S.GET_ROW, ("s",)).fetchone()))
        is None
    )


async def test_batch_inputs_are_bounded_before_materializing_and_large_summary_writes(
    business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.reading.catalog_contracts import ReadingConflictError
    from deeptutor.reading.models import ReadingError

    store = factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    consumed = []

    def endless():
        for i in range(1000000):
            consumed.append(i)
            yield f"m{i}"

    with pytest.raises(ReadingError, match="10000"):
        await store.run(lambda u: u.create_workspace("w", endless(), return_summary=True))
    assert len(consumed) == 10001
    consumed.clear()
    with pytest.raises(ReadingError, match="500"):
        await store.run(lambda u: u.collections_for_materials(endless()))
    assert len(consumed) == 501

    def seed(u):
        for i in range(502):
            u.upsert_material(content_id=f"m{i}", filename="m", title="m", source_kind="file")
        return u.create_workspace(
            "w", [f"m{i}" for i in range(501)], workspace_id="w", return_summary=True
        )

    w = await store.run(seed)
    w = await store.run(
        lambda u: u.add_material("w", "m501", return_summary=True, expected_version=w.version)
    )
    assert w.tab_count == 502
    w = await store.run(
        lambda u: u.reorder_materials(
            "w",
            [f"m{i}" for i in range(501, -1, -1)],
            return_summary=True,
            expected_version=w.version,
        )
    )
    w = await store.run(
        lambda u: u.set_active_material(
            "w", "m500", return_summary=True, expected_version=w.version
        )
    )
    assert w.active_material_id == "m500"
    w = await store.run(
        lambda u: u.remove_material("w", "m500", return_summary=True, expected_version=w.version)
    )
    assert w.tab_count == 501 and w.active_material_id == "m501"
    with pytest.raises(ReadingConflictError):
        await store.run(
            lambda u: u.update_workspace(
                "w", title="stale", return_summary=True, expected_version=1
            )
        )


async def test_library_counts_preserves_empty_filter_semantics(
    business_sync_database, business_actors, pg_scope_factory
):
    store = factory(business_sync_database, pg_scope_factory, business_actors.tenants[0].owners[0])
    await store.run(
        lambda u: u.upsert_material(content_id="m", filename="m", title="m", source_kind="file")
    )
    assert (await store.run(lambda u: u.library_counts(["", "m"])))["all"] == 1
    assert (await store.run(lambda u: u.library_counts([""])))["all"] == 0
    assert (await store.run(lambda u: u.library_counts(None)))["all"] == 1


async def test_large_sessions_links_and_memberships_have_real_pages(
    business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    from deeptutor.reading.catalog_contracts import ReadingPageRequired

    actor = business_actors.tenants[0].owners[0]
    store = factory(business_sync_database, pg_scope_factory, actor)
    chats = pg_session_store_factory(actor)
    for i in range(502):
        await chats.create_session(session_id=f"s{i:04d}")

    def seed(u):
        u.upsert_material(content_id="m", filename="m", title="m", source_kind="file")
        for i in range(501):
            u.create_workspace("same title", ["m"], workspace_id=f"w{i:04d}")
        for i in range(502):
            u.attach_session("w0000", f"s{i:04d}")
        for i in range(1, 502):
            u.link_session("w0000", "s0000", f"s{i:04d}")
        # 相同时间时必须由 session/target ID 决定唯一顺序。
        u._execute(
            "UPDATE enterprise.reading_workspace_sessions SET updated_at=1 WHERE tenant_id=%s AND owner_id=%s",
            u._owner,
        )
        u._execute(
            "UPDATE enterprise.reading_session_links SET created_at=1 WHERE tenant_id=%s AND owner_id=%s",
            u._owner,
        )

    await store.run(seed)
    for read in [
        lambda u: u.list_sessions("w0000"),
        lambda u: u.list_session_links("w0000", "s0000"),
        lambda u: u.collections_for_material("m"),
    ]:
        with pytest.raises(ReadingPageRequired):
            await store.run(read)

    async def pages(method, *args):
        cursor = None
        out = []
        while True:
            page = await store.run(lambda u: getattr(u, method)(*args, limit=71, cursor=cursor))
            assert len(page.items) <= 71
            out.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                return out

    assert [s.session_id for s in await pages("list_sessions_page", "w0000")] == [
        f"s{i:04d}" for i in range(501, -1, -1)
    ]
    assert await pages("list_session_links_page", "w0000", "s0000") == [
        f"s{i:04d}" for i in range(1, 502)
    ]
    assert [m.workspace_id for m in await pages("list_collections_page", ["m"])] == [
        f"w{i:04d}" for i in range(501)
    ]
