"""真实 PG + SDK/HTTP 分支竞争；只对真实 ContextBuilder 增加调度门。"""

import asyncio

import httpx
import pytest
from test_application import app as app
from test_flows import model as model

from deeptutor.services.session import get_session_store
from deeptutor.services.session.context_builder import ContextBuilder


async def seed_branches(store):
    session = await store.create_session(title="Branch consistency")
    sid = session["id"]
    root = await store.add_message(sid, "user", "Shared question", parent_message_id=None)
    shared = await store.add_message(sid, "assistant", "Shared answer", parent_message_id=root)
    prompt = await store.add_message(sid, "user", "Branch prompt", parent_message_id=shared)
    branch_a = await store.add_message(
        sid, "assistant", "Branch A answer", parent_message_id=prompt
    )
    branch_b = await store.add_message(
        sid, "assistant", "Branch B answer", parent_message_id=prompt
    )
    await store.select_active_leaf(sid, branch_a)
    return sid, shared, prompt, branch_a, branch_b


async def collect(sdk, turn_id):
    return [event async for event in sdk.stream_turn(turn_id)]


@pytest.mark.parametrize("mode", ["implicit_parent", "explicit_parent", "regenerate"])
async def test_concurrent_branch_selection_keeps_context_and_parent_on_same_path(
    app, model, monkeypatch, mode
):
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="branch-race")
    history_ready = asyncio.Event()
    allow_user_write = asyncio.Event()
    built_leaves = []
    original_build = ContextBuilder.build

    async def pause_after_real_build(self, **kwargs):
        result = await original_build(self, **kwargs)
        built_leaves.append(kwargs["leaf_message_id"])
        history_ready.set()
        await allow_user_write.wait()
        return result

    monkeypatch.setattr(ContextBuilder, "build", pause_after_real_build)
    async with enterprise.sdk(token) as sdk:
        store = get_session_store()
        sid, shared, prompt, branch_a, branch_b = await seed_branches(store)
        if mode == "regenerate":
            _, turn = await sdk.regenerate_last_turn(sid)
        else:
            payload = {"session_id": sid, "content": "Continue selected branch"}
            if mode == "explicit_parent":
                payload["parent_message_id"] = branch_a
            _, turn = await sdk.start_turn(payload)
        stream = asyncio.create_task(collect(sdk, turn["id"]))
        try:
            await asyncio.wait_for(history_ready.wait(), 10)
            assert not model.requests
            assert built_leaves == [shared if mode == "regenerate" else branch_a]
            # ContextBuilder 已读取 A；在真正写 user 之前，经另一个 HTTP 请求切到 B。
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://school.example",
                headers={"Authorization": "Bearer " + token},
            ) as client:
                changed = await client.put(
                    f"/api/sessions/{sid}/branch-selection",
                    json={"selected_branches": {str(prompt): branch_b}},
                )
                assert changed.status_code == 200, changed.text
            assert (await store.get_session(sid))["preferences"]["active_leaf_id"] == branch_b
        finally:
            allow_user_write.set()
        events = await asyncio.wait_for(stream, 10)
        assert events[-1]["metadata"]["status"] == "completed"
        assert len(model.requests) == 1
        supplied = [message.get("content") for message in model.requests[0]["messages"]]
        assert "Shared answer" in supplied
        assert "Branch B answer" not in supplied
        detail = await sdk.get_session(sid)
        messages = detail["messages"]
        final = messages[-1]
        restored = await store.get_messages_for_context(sid, leaf_message_id=final["id"])
        if mode == "regenerate":
            assert len(messages) == 6
            assert final["parent_message_id"] == prompt
            assert "Branch A answer" not in supplied
            assert [row["content"] for row in restored][-2:] == ["Branch prompt", "First answer"]
            assert (
                sum(row["role"] == "user" and row["content"] == "Branch prompt" for row in messages)
                == 1
            )
        else:
            assert "Branch A answer" in supplied
            user = messages[-2]
            assert user["content"] == "Continue selected branch"
            assert user["parent_message_id"] == branch_a
            assert final["parent_message_id"] == user["id"]
            assert "Branch A answer" in [row["content"] for row in restored]
            assert "Branch B answer" not in [row["content"] for row in restored]


@pytest.mark.parametrize("existing_history", [False, True])
async def test_explicit_root_and_empty_session_keep_none_parent(app, model, existing_history):
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="root-branch")
    async with enterprise.sdk(token) as sdk:
        store = get_session_store()
        if existing_history:
            sid, *_ = await seed_branches(store)
        else:
            sid = (await store.create_session(title="Empty branch"))["id"]
        payload = {"session_id": sid, "content": "Start a separate root"}
        if existing_history:
            payload["parent_message_id"] = None
        _, turn = await sdk.start_turn(payload)
        events = await asyncio.wait_for(collect(sdk, turn["id"]), 10)
        assert events[-1]["metadata"]["status"] == "completed"
        supplied = [message.get("content") for message in model.requests[0]["messages"]]
        assert not {
            "Shared question",
            "Shared answer",
            "Branch A answer",
            "Branch B answer",
        }.intersection(supplied)
        messages = (await sdk.get_session(sid))["messages"]
        assert messages[-2]["parent_message_id"] is None
        assert messages[-1]["parent_message_id"] == messages[-2]["id"]
        assert (
            len(await store.get_messages_for_context(sid, leaf_message_id=messages[-1]["id"])) == 2
        )
