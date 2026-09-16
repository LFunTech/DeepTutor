"""真实 PG + 原 ASGI/WS/SDK；仅外部模型使用确定性测试替身。"""

import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from test_application import app as app


class Socket:
    def __init__(self, application, token, origin="https://school.example"):
        self.app = application
        self.token = token
        self.origin = origin
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()

    async def __aenter__(self):
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "wss",
            "path": "/api/v1/ws",
            "raw_path": b"/api/v1/ws",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"origin", self.origin.encode()),
                (b"authorization", ("Bearer " + self.token).encode()),
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("school.example", 443),
            "subprotocols": [],
            "state": {},
        }
        self.task = asyncio.create_task(self.app(scope, self.incoming.get, self.outgoing.put))
        await self.incoming.put({"type": "websocket.connect"})
        assert (await asyncio.wait_for(self.outgoing.get(), 10))["type"] == "websocket.accept"
        return self

    async def send(self, value):
        await self.incoming.put(
            {"type": "websocket.receive", "text": json.dumps({"protocol_version": "2.0", **value})}
        )

    async def receive(self):
        message = await asyncio.wait_for(self.outgoing.get(), 30)
        if message["type"] == "websocket.close":
            return {"type": "closed", "code": message.get("code")}
        return json.loads(message["text"])

    async def until(self, kind):
        result = []
        while True:
            event = await self.receive()
            result.append(event)
            if event["type"] == kind:
                return result
            assert event["type"] not in ("closed", "protocol_error"), event

    async def __aexit__(self, *args):
        await self.incoming.put({"type": "websocket.disconnect", "code": 1000})
        try:
            await asyncio.wait_for(self.task, 5)
        except (TimeoutError, asyncio.CancelledError):
            self.task.cancel()


class ScriptedModel:
    """Deterministic OpenAI-compatible test double for enterprise WS flows."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.requests = []
        self.started = asyncio.Event()
        self.gate = None
        self.cancelled = asyncio.Event()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        self.started.set()
        try:
            if self.gate is not None:
                await self.gate.wait()
            chunks = self.scripts.pop(0)
            if isinstance(chunks, Exception):
                raise chunks
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


def chunk(content=None, *, tools=None, finish="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=tools),
                finish_reason=finish,
            )
        ],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
    )


@pytest.fixture
async def model(monkeypatch):
    from deeptutor.agents.loop import pipeline
    from deeptutor.services import llm

    model = ScriptedModel([[chunk("First answer")], [chunk("Continued")], [chunk("Regenerated")]])
    monkeypatch.setattr(pipeline, "build_openai_client", lambda config: model)

    async def title(**kwargs):
        yield "Generated title"

    monkeypatch.setattr(llm, "stream", title)
    return model


async def test_ws_continue_regenerate_replay_delete_and_operation_tombstone(app, model):
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="ws-test")
    async with Socket(app, token) as ws:
        await ws.send({"type": "start_turn", "content": "First question", "operation_id": "one"})
        first = await ws.until("done")
        assert first[-1]["metadata"]["status"] == "completed", first
        sid, tid = first[-1]["session_id"], first[-1]["turn_id"]
        assert any(e.get("metadata", {}).get("metadata", {}).get("cost_summary") for e in first)
        await ws.send({"type": "start_turn", "content": "First question", "operation_id": "one"})
        replay = await ws.until("done")
        assert replay[-1]["turn_id"] == tid and len(model.requests) == 1
        await ws.send({"type": "start_turn", "content": "Continue", "session_id": sid})
        await ws.until("done")
        assert any(m.get("content") == "First answer" for m in model.requests[1]["messages"]), (
            "WS continuation discarded selected history"
        )
        await ws.send({"type": "regenerate", "session_id": sid})
        await ws.until("done")
        assert len(model.requests) == 3
        await ws.send({"type": "resume_from", "turn_id": tid, "seq": first[-2]["seq"]})
        tail = await ws.until("done")
        assert len(tail) == 1
        async with enterprise.sdk(token) as sdk:
            record = await sdk.get_session(sid)
            assert [m["content"] for m in record["messages"]] == [
                "First question",
                "First answer",
                "Continue",
                "Continued",
                "Regenerated",
            ]
            assert await sdk.delete_session(sid)
        await ws.send({"type": "start_turn", "content": "First question", "operation_id": "one"})
        result = await ws.until("protocol_error")
        assert result[-1]["error_code"] == "operation_deleted"
        assert len(model.requests) == 3


async def test_ws_ask_user_reconnect_reply_and_revoked_output(app, model):
    model.scripts = [
        [
            chunk(
                tools=[
                    SimpleNamespace(
                        index=0,
                        id="ask-1",
                        function=SimpleNamespace(
                            name="ask_user",
                            arguments='{"questions":[{"id":"q1","question":"Which subject?"}]}',
                        ),
                    )
                ],
                finish="tool_calls",
            )
        ],
        [chunk("Algebra selected")],
    ]
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="ws-reply")
    async with Socket(app, token) as ws:
        await ws.send({"type": "start_turn", "content": "Help me learn"})
        events = await ws.until("tool_result")
        tid = events[-1]["turn_id"]
    async with Socket(app, token) as ws:
        await ws.send(
            {
                "type": "submit_user_reply",
                "turn_id": tid,
                "text": "algebra",
                "command_id": "reply-1",
            }
        )
        ack = (await ws.until("command_ack"))[-1]
        assert ack["accepted"], ack
        await ws.send({"type": "subscribe_turn", "turn_id": tid})
        assert (await ws.until("done"))[-1]["metadata"]["status"] == "completed"
        await enterprise.identity.logout(token)
        await ws.send({"type": "subscribe_turn", "turn_id": tid})
        assert (await ws.receive())["type"] == "closed"


async def test_reply_command_retry_cannot_answer_a_later_question(app, model):
    def ask(number):
        return chunk(
            tools=[
                SimpleNamespace(
                    index=0,
                    id=f"ask-{number}",
                    function=SimpleNamespace(
                        name="ask_user",
                        arguments=json.dumps(
                            {"questions": [{"id": f"q{number}", "question": f"Question {number}?"}]}
                        ),
                    ),
                )
            ],
            finish="tool_calls",
        )

    model.scripts = [[ask(1)], [ask(2)], [chunk("Two fresh answers received")]]
    enterprise = app.state.enterprise
    token = await enterprise.identity.login("admin", "long-password-1", client="two-asks")
    async with Socket(app, token) as ws:
        await ws.send({"type": "start_turn", "content": "Ask two separate questions"})
        first = await ws.until("tool_result")
        tid = first[-1]["turn_id"]
        await ws.send(
            {
                "type": "submit_user_reply",
                "turn_id": tid,
                "text": "first answer",
                "command_id": "stable-reply-1",
            }
        )
        assert (await ws.until("command_ack"))[-1]["accepted"]
        await ws.until("tool_result")
        await ws.send(
            {
                "type": "submit_user_reply",
                "turn_id": tid,
                "text": "first answer",
                "command_id": "stable-reply-1",
            }
        )
        assert (await ws.until("command_ack"))[-1]["accepted"]
        async with enterprise.sdk(token):
            from deeptutor.services.session import get_session_store

            # ACK 之前的处理已经完成，重放不能消耗第二次 waiting_input。
            state = await get_session_store().get_turn(tid)
            assert state["status"] == "waiting_input"
        assert len(model.requests) == 2
        await ws.send(
            {
                "type": "submit_user_reply",
                "turn_id": tid,
                "text": "second answer",
                "command_id": "stable-reply-2",
            }
        )
        assert (await ws.until("command_ack"))[-1]["accepted"]
        assert (await ws.until("done"))[-1]["metadata"]["status"] == "completed"
