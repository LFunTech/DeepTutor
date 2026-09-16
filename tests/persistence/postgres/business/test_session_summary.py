"""列表不逐会话读取 turn/trace，全量正文只由显式 history/context 消费。"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_list_summary_is_single_batch_without_per_row_loader(
    pg_session_store_factory, business_actors, monkeypatch
):
    store = pg_session_store_factory(business_actors.tenants[0].owners[0])
    for sid in ("a", "b", "c"):
        await store.create_session(session_id=sid)
        await store.add_message(sid, "user", sid)
        turn = await store.begin_turn(sid, capability="chat")
        await store.transition_turn(turn["id"], "failed")
    expected = {sid: await store.get_session(sid) for sid in ("a", "b", "c")}

    async def no_per_row(*args):
        raise AssertionError("list must not call per-row summary/turn loader")

    monkeypatch.setattr(type(store), "_session_payload", no_per_row)
    rows = await store.list_sessions()
    assert {row["id"]: row for row in rows} == expected
    assert {
        row["id"]: row for row in await store.get_session_summaries(["a", "b", "c"])
    } == expected
    assert [row["id"] for row in rows] == ["c", "b", "a"]
