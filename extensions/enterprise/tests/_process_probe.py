"""新解释器内的真实入口探针。仅模型 HTTP 是协议替身，不替换配置/SDK/存储。"""

import asyncio
import json
import os
from pathlib import Path
import sys

HOME = Path.cwd()
ROOT = Path(os.environ["PROBE_ROOT"])
violations = []
blocked = [str(ROOT / "data"), str(HOME / "data"), str(ROOT / ".secrets"), str(HOME / "multi-user")]


def audit(event, args):
    if event == "sqlite3.connect":
        violations.append("sqlite3.connect")
        raise AssertionError("local SQLite accessed")
    if event in {
        "open",
        "os.mkdir",
        "os.listdir",
        "os.scandir",
        "os.rename",
        "os.remove",
        "os.rmdir",
    }:
        for value in args[:2]:
            if isinstance(value, (str, bytes)):
                path = os.path.abspath(os.fsdecode(value))
                if any(path == root or path.startswith(root + os.sep) for root in blocked):
                    violations.append(event + ":" + path)
                    raise AssertionError("local authority accessed")


sys.addaudithook(audit)
from deeptutor_enterprise.bootstrap import create_application
from deeptutor_enterprise.configuration import DeploymentConfig
from deeptutor_enterprise.executor import ExecutorLease
import httpx
from test_flows import Socket

from deeptutor.services.session import get_session_store

requests = []
scripts = [
    "First answer",
    "Continued answer",
    "Regenerated answer",
    "Edited answer",
    "ASK",
    "Answered",
    "ASK",
    "ASK",
    "HOLD",
]
original_client = httpx.AsyncClient.__init__


async def model_http(request):
    assert request.url.host == "model.example", "unexpected external request"
    body = json.loads(request.content)
    requests.append(body)
    system = str(body["messages"][0].get("content", ""))
    is_title = "为一段对话生成一个简洁的标题" in system or "You generate a concise" in system
    is_summary = "滚动摘要" in system or "rolling" in system
    if is_title:
        text = "Probe conversation title"
    elif is_summary:
        text = "Earlier we discussed algebra and variables."
    else:
        text = scripts.pop(0)
    if text == "HOLD":
        await asyncio.Event().wait()
    delta = {"role": "assistant", "content": text}
    reason = "stop"
    if text == "ASK":
        delta = {
            "role": "assistant",
            "tool_calls": [
                {
                    "index": 0,
                    "id": "probe-ask",
                    "type": "function",
                    "function": {
                        "name": "ask_user",
                        "arguments": json.dumps(
                            {"questions": [{"id": "q", "question": "Choose algebra or geometry?"}]}
                        ),
                    },
                }
            ],
        }
        reason = "tool_calls"
    event = {
        "id": "probe-completion",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "probe-model",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }
    tail = {
        **event,
        "choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    wire = "data: " + json.dumps(event) + "\n\ndata: " + json.dumps(tail) + "\n\ndata: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire.encode())


def model_client(self, *args, **kwargs):
    # 仅替换网络传输；真实 OpenAI SDK、工厂及显式 transport 参数仍运行。
    if not isinstance(kwargs.get("transport"), httpx.ASGITransport):
        kwargs["transport"] = httpx.MockTransport(model_http)
    original_client(self, *args, **kwargs)


httpx.AsyncClient.__init__ = model_client
config = DeploymentConfig.model_validate_json(os.environ["PROBE_CONFIG"])


async def consume(sdk, turn):
    events = [e async for e in sdk.stream_turn(turn["id"])]
    assert events[-1]["metadata"]["status"] == "completed", events[-1]
    return events


async def first():
    application = create_application(config)
    async with application.state.enterprise.db:
        await application.state.enterprise.identity.bootstrap(
            "admin", "synthetic-password-1", secret=os.environ["PROBE_BOOT"]
        )
    application = create_application(config)
    await application.state.enterprise.start()
    enterprise = application.state.enterprise
    application.state.application_container = enterprise.container
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="https://school.example"
    ) as client:
        login = await client.post(
            "/api/auth/login",
            headers={"Origin": "https://school.example"},
            json={"username": "admin", "password": "synthetic-password-1"},
        )
        assert login.status_code == 200
        token = client.cookies["dt_token"]
        async with Socket(application, token) as ws:
            await ws.send(
                {"type": "start_turn", "content": "Initial question", "operation_id": "probe-first"}
            )
            initial = await ws.until("done")
            assert initial[-1]["metadata"]["status"] == "completed", initial
            sid = initial[-1]["session_id"]
            async with enterprise.sdk(token) as sdk:
                store = get_session_store()
                assert (await sdk.get_session(sid))["title"] == "Probe conversation title"
                for i in range(12):
                    await store.add_message(
                        sid, "user" if i % 2 == 0 else "assistant", "algebra variables " * 250
                    )
            await ws.send({"type": "start_turn", "content": "Continue", "session_id": sid})
            assert (await ws.until("done"))[-1]["metadata"]["status"] == "completed"
            async with enterprise.sdk(token) as sdk:
                assert (await sdk.get_session(sid))[
                    "compressed_summary"
                ] == "Earlier we discussed algebra and variables.", (
                    (await sdk.get_session(sid))["compressed_summary"],
                    [str(b["messages"][0].get("content"))[:90] for b in requests],
                )
            await ws.send({"type": "regenerate", "session_id": sid})
            assert (await ws.until("done"))[-1]["metadata"]["status"] == "completed"
            await ws.send(
                {
                    "type": "start_turn",
                    "content": "Edited root",
                    "session_id": sid,
                    "parent_message_id": None,
                }
            )
            assert (await ws.until("done"))[-1]["metadata"]["status"] == "completed"
        assert (await client.get("/api/sessions/" + sid)).status_code == 200
        async with enterprise.sdk(token) as sdk:
            question, turn = await sdk.start_turn({"content": "Ask for choice"})
            async for event in sdk.stream_turn(turn["id"]):
                if event["type"] == "tool_result":
                    assert await sdk.submit_user_reply(turn["id"], "algebra")
            assert (await get_session_store().get_turn(turn["id"]))["status"] == "completed"
            cancelled, turn = await sdk.start_turn({"content": "Ask then cancel"})
            async for event in sdk.stream_turn(turn["id"]):
                if event["type"] == "tool_result":
                    assert await sdk.cancel_turn(turn["id"])
            assert (await get_session_store().get_turn(turn["id"]))["status"] == "cancelled"
            assert await sdk.cancel_turn(turn["id"])
            assert await sdk.delete_session(cancelled["id"])
            assert await sdk.delete_session(question["id"])
            _, waiting = await sdk.start_turn(
                {"content": "Waiting at process crash", "operation_id": "orphan-waiting"}
            )
            async for event in sdk.stream_turn(waiting["id"]):
                if event["type"] == "tool_result":
                    break
            count = len(requests)
            _, running = await sdk.start_turn(
                {"content": "Running at process crash", "operation_id": "orphan-running"}
            )
            async with asyncio.timeout(5):
                while len(requests) == count:
                    await asyncio.sleep(0.01)
            assert not scripts
    assert not violations, violations
    print(
        json.dumps(
            {
                "executor_id": enterprise.lease.execution_id,
                "history": sid,
                "waiting": waiting["id"],
                "running": running["id"],
                "model_http_calls": len(requests),
                "local_authority_io": 0,
            }
        ),
        flush=True,
    )
    # 模拟没有机会写 stopped 的真实进程退出，父测试确认 PID 结束再允许接管。
    os._exit(42)


async def second():
    state = json.loads(os.environ["PROBE_STATE"])
    application = create_application(config)
    enterprise = application.state.enterprise
    try:
        await enterprise.start()
        raise AssertionError("unconfirmed executor automatically taken over")
    except RuntimeError as error:
        assert "confirmed" in str(error)
    await ExecutorLease.confirm_stopped(
        os.environ["PROBE_DB"], resource=config.resource, execution_id=state["executor_id"]
    )
    application = create_application(config)
    async with application.router.lifespan_context(application):
        enterprise = application.state.enterprise
        token = await enterprise.identity.login(
            "admin", "synthetic-password-1", client="fresh-process"
        )
        async with enterprise.sdk(token) as sdk:
            record = await sdk.get_session(state["history"])
            assert record["messages"] and record["title"] == "Probe conversation title"
            store = get_session_store()
            for tid in (state["running"], state["waiting"]):
                turn = await store.get_turn(tid)
                assert turn["status"] == "failed" and turn["failure_code"] == "worker_lost"
                events = await store.get_turn_events(tid)
                assert events[-1]["type"] == "done" and events[-1]["metadata"]["status"] == "failed"
                assert not await sdk.submit_user_reply(tid, "old queued reply")
            _, replayed = await sdk.start_turn(
                {"content": "Waiting at process crash", "operation_id": "orphan-waiting"}
            )
            assert replayed["id"] == state["waiting"] and replayed["status"] == "failed"
            assert await sdk.delete_session(state["history"])
    assert not requests, "process recovery must not replay models"
    assert not violations, violations
    print(json.dumps({"recovered_turns": 2, "model_http_calls": 0, "local_authority_io": 0}))


asyncio.run(first() if sys.argv[1] == "first" else second())
