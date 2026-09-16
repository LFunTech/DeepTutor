"""浏览器手动历史导入的真实 PG 合同；不是旧 SQLite 离线搬迁。"""

import asyncio
import math

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
def store(pg_session_store_factory, business_actors):
    return pg_session_store_factory(business_actors.tenants[0].owners[0])


async def upload(store, **overrides):
    args = dict(
        session_id="imported_codex_abc",
        title=" Imported ",
        created_at=1000.0,
        updated_at=1001.0,
        preferences={"import": {"source": "codex", "external_id": "abc"}},
        messages=[
            {"role": "user", "content": "hi", "created_at": 1000.0},
            {"role": "assistant", "content": "hello", "created_at": 1001.0},
        ],
    )
    return await store.import_session(**(args | overrides))


async def test_import_reopen_continue_and_history_groups(store):
    await store.create_session(session_id="native")
    result = await upload(store)
    assert result == {"session_id": "imported_codex_abc", "imported": True, "message_count": 2}
    imported = await store.list_imported_sessions()
    assert [s["id"] for s in imported] == ["imported_codex_abc"]
    assert [s["id"] for s in await store.list_sessions()] == ["native"]
    row = await store.get_session_with_messages("imported_codex_abc")
    assert (row["title"], row["created_at"], row["updated_at"]) == ("Imported", 1000, 1001)
    msgs = row["messages"]
    assert [(m["role"], m["content"], m["created_at"]) for m in msgs] == [
        ("user", "hi", 1000),
        ("assistant", "hello", 1001),
    ]
    assert msgs[0]["parent_message_id"] is None
    assert msgs[1]["parent_message_id"] == msgs[0]["id"]
    await store.add_message(row["id"], "user", "continue")
    assert (await store.get_messages(row["id"]))[-1]["parent_message_id"] == msgs[-1]["id"]


async def test_reimport_backfills_only_attribution_and_concurrent_dedup(store):
    first, second = await asyncio.gather(upload(store), upload(store))
    assert sorted([first["imported"], second["imported"]]) == [False, True]
    sid = "imported_codex_abc"
    await store.update_session_title(sid, "Edited")
    await store.update_session_preferences(sid, {"pinned": True})
    await store.add_message(sid, "user", "edited branch")
    before = await store.get_session_with_messages(sid)
    result = await upload(
        store,
        preferences={
            "import": {
                "source": "spoof",
                "external_id": "different",
                "agent_name": "Agent",
                "source_cwd": "/synthetic",
            },
            "pinned": False,
        },
    )
    assert result == {"session_id": sid, "imported": False, "updated": True, "message_count": 0}
    after = await store.get_session_with_messages(sid)
    assert after["messages"] == before["messages"]
    assert after["title"] == "Edited" and after["preferences"]["pinned"]
    assert after["updated_at"] == before["updated_at"]
    assert after["preferences"]["import"] == {
        "source": "codex",
        "external_id": "abc",
        "agent_name": "Agent",
        "source_cwd": "/synthetic",
    }
    assert not (await upload(store))["updated"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"session_id": "native"},
        {"created_at": math.nan},
        {"updated_at": math.inf},
        {"messages": [{"role": "administrator", "content": "x"}]},
        {"messages": [{"role": "user", "created_at": math.nan}]},
        {"messages": [{"role": "user", "metadata": {"kb_name": "foreign"}}]},
        {"preferences": {"course_id": "foreign"}},
        {"messages": [{"role": "user", "attachments": [{"url": "/files/outputs/foreign"}]}]},
        {"messages": [{"role": "user", "content": "x"}] * 10001},
        {"messages": [{"role": "user", "content": "x" * (4 * 1024 * 1024 + 1)}]},
    ],
)
async def test_import_validation_is_atomic(store, overrides):
    with pytest.raises((ValueError, RuntimeError)):
        await upload(store, **overrides)
    assert await store.list_imported_sessions() == []
    assert await store.list_sessions() == []


async def test_import_scope_and_parent_preferences(
    store, business_actors, pg_session_store_factory
):
    other = pg_session_store_factory(business_actors.tenants[1].owners[0])
    await upload(store)
    await upload(other, title="Other")
    assert (await other.list_imported_sessions())[0]["title"] == "Other"
    assert (await store.list_imported_sessions())[0]["title"] == "Imported"
