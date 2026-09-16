"""并发会话编辑的显式版本冲突，不能静默覆盖已提交的新版本。"""

import asyncio

import httpx
from test_application import app as app

from deeptutor.services.session import get_session_store


async def test_if_match_compare_and_swap_for_session_mutations(app):
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="versions")
    async with enterprise.sdk(token):
        session = await get_session_store().create_session()
    headers = {"Authorization": "Bearer " + token, "If-Match": str(session["version"])}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example", headers=headers
    ) as client:
        prefix = "/api/sessions/" + session["id"]
        first, second = await asyncio.gather(
            client.patch(prefix, json={"title": "One"}), client.patch(prefix, json={"title": "Two"})
        )
        assert sorted([first.status_code, second.status_code]) == [200, 409]
        assert (
            await client.patch(prefix + "/organization", json={"pinned": True})
        ).status_code == 409
        assert (
            await client.put(prefix + "/branch-selection", json={"selected_branches": {}})
        ).status_code == 409
        current = (await client.get(prefix)).json()
        response = await client.patch(
            prefix + "/organization",
            json={"pinned": True},
            headers={"If-Match": str(current["version"])},
        )
        assert response.status_code == 200, response.text
        assert response.json()["session"]["version"] > current["version"]


async def test_generated_title_cannot_overwrite_a_concurrent_manual_rename(app, monkeypatch):
    from test_flows import ScriptedModel, chunk

    from deeptutor.agents.loop import pipeline
    from deeptutor.services import llm

    model = ScriptedModel([[chunk("Answer")]])
    monkeypatch.setattr(pipeline, "build_openai_client", lambda config: model)
    entered, resume = asyncio.Event(), asyncio.Event()

    async def title(**kwargs):
        entered.set()
        await resume.wait()
        yield "Generated title"

    monkeypatch.setattr(llm, "stream", title)
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="title-race")
    async with enterprise.sdk(token) as sdk:
        session, turn = await sdk.start_turn({"content": "Question"})
        await asyncio.wait_for(entered.wait(), 5)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://school.example",
                headers={"Authorization": "Bearer " + token},
            ) as client:
                assert (
                    await client.patch(
                        "/api/sessions/" + session["id"], json={"title": "My chosen title"}
                    )
                ).status_code == 200
        finally:
            resume.set()
        events = [e async for e in sdk.stream_turn(turn["id"])]
        assert events[-1]["metadata"]["status"] == "completed"
        assert (await sdk.get_session(session["id"]))["title"] == "My chosen title"
        assert not any(
            e["type"] == "session_meta" and e["content"] == "Generated title" for e in events
        )
