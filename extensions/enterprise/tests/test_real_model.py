"""需显式启用的真实模型验收；仅发送合成教学问题，绝不回退替身。"""

import asyncio
import json
import os
from pathlib import Path
import re
import time
import uuid

from deeptutor_enterprise.configuration import DeploymentConfig
from deeptutor_enterprise.identity.service import IdentityService
from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.stores.postgres.connection import Database
import httpx
import pytest
from test_flows import Socket

pytestmark = pytest.mark.skipif(
    os.environ.get("DT_RUN_REAL_MODEL") != "1", reason="真实计费验收须显式启用"
)


async def test_real_model_ws_sdk_continue_regenerate_and_ask_user(pg_dsn, monkeypatch):
    from deeptutor_enterprise.bootstrap import create_application
    from openai.resources.chat.completions.completions import AsyncCompletions

    original_create = AsyncCompletions.create
    actual_calls = []

    class RecordedStream:
        def __init__(self, stream, record):
            self.stream, self.record = stream, record

        def __getattr__(self, name):
            return getattr(self.stream, name)

        async def __aenter__(self):
            await self.stream.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self.stream.__aexit__(*args)

        async def __aiter__(self):
            try:
                async for chunk in self.stream:
                    if chunk.usage is not None:
                        self.record["usage"] = chunk.usage.model_dump()
                    yield chunk
                self.record["stream_finished"] = True
            finally:
                self.record["elapsed_seconds"] = round(time.monotonic() - self.record["started"], 2)

    async def record_create(client, *args, **kwargs):
        assert len(actual_calls) < 14, "exceeded synthetic smoke call budget"
        limit = kwargs.get("max_tokens", kwargs.get("max_completion_tokens"))
        assert isinstance(limit, int) and limit <= 512, "exceeded per-call output budget"
        record = {
            "messages": kwargs.get("messages", []),
            "max_output_tokens": limit,
            "usage": None,
            "stream_finished": False,
            "include_usage": kwargs.get("stream_options", {}).get("include_usage", False),
            "started": time.monotonic(),
        }
        actual_calls.append(record)
        stream = await original_create(client, *args, **kwargs)
        return RecordedStream(stream, record)

    monkeypatch.setattr(AsyncCompletions, "create", record_create)
    source = Path(".secrets/.test-secrets").read_text()
    key = next(
        re.split(r"[:=]", line, maxsplit=1)[1].strip().strip('" ,')
        for line in source.splitlines()
        if '"API KEY"' in line
    )
    host = re.search(r'"API Host"\s*=\s*"([^\"]+)"', source).group(1)
    env = {
        "SMOKE_DB": pg_dsn.replace("user=postgres", "user=dt_enterprise_app"),
        "SMOKE_KEY": key,
        "SMOKE_SIGN": uuid.uuid4().hex + uuid.uuid4().hex,
        "SMOKE_EPOCH": str(uuid.uuid4()),
        "SMOKE_BOOT": uuid.uuid4().hex + uuid.uuid4().hex,
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    model = os.environ.get("DT_SMOKE_MODEL", "qwen-plus")
    deployment = DeploymentConfig(
        version=1,
        tenant_id=uuid.uuid4(),
        resource="real-model-smoke",
        database_secret="env:SMOKE_DB",
        signing_secret="env:SMOKE_SIGN",
        auth_epoch_secret="env:SMOKE_EPOCH",
        bootstrap_secret="env:SMOKE_BOOT",
        origins=("https://school.example",),
        max_rounds=3,
        models=(
            {
                "profile_id": "chat",
                "model_id": "primary",
                "model": model,
                "base_url": f"https://{host}/compatible-mode/v1",
                "secret": "env:SMOKE_KEY",
                "allowed_roles": ("user", "tenant_admin"),
                "max_tokens": 512,
            },
        ),
    )
    await MigrationRunner(pg_dsn).apply()
    application = create_application(deployment)
    async with application.state.enterprise.db:
        await application.state.enterprise.identity.bootstrap(
            "smoke-admin", "synthetic-smoke-password-2026", secret=env["SMOKE_BOOT"]
        )
    application = create_application(deployment)
    records = []
    started = time.monotonic()
    async with application.router.lifespan_context(application):
        enterprise = application.state.enterprise
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="https://school.example"
        ) as client:
            login = await client.post(
                "/api/auth/login",
                headers={"Origin": "https://school.example"},
                json={"username": "smoke-admin", "password": "synthetic-smoke-password-2026"},
            )
            assert login.status_code == 200
            token = client.cookies["dt_token"]
            async with Socket(application, token) as ws:
                await ws.send(
                    {
                        "type": "start_turn",
                        "content": "这是集成验收。用两句话解释分数 1/2，不调用工具。",
                        "operation_id": "real-1",
                    }
                )
                first = await ws.until("done")
                assert first[-1]["metadata"]["status"] == "completed", first[-1]
                records.append(first)
                sid = first[-1]["session_id"]
                detail = (await client.get("/api/sessions/" + sid)).json()
                original_answer = detail["messages"][-1]["content"]
                before_continue = len(actual_calls)
                await ws.send(
                    {
                        "type": "start_turn",
                        "content": "继续给一个生活中的例子，用一句话回答。",
                        "session_id": sid,
                        "operation_id": "real-2",
                    }
                )
                continued = await ws.until("done")
                assert continued[-1]["metadata"]["status"] == "completed", continued[-1]
                records.append(continued)
                assert any(
                    m.get("content") == original_answer
                    for m in actual_calls[before_continue]["messages"]
                ), "actual model continuation lost original answer"
                await ws.send({"type": "regenerate", "session_id": sid})
                regenerated = await ws.until("done")
                assert regenerated[-1]["metadata"]["status"] == "completed", regenerated[-1]
                records.append(regenerated)
            detail = await client.get("/api/sessions/" + sid)
            assert detail.status_code == 200 and len(detail.json()["messages"]) == 5
            async with enterprise.sdk(token) as sdk:
                session, turn = await sdk.start_turn(
                    {
                        "content": "在回答前必须先调用 ask_user 工具，询问我想学代数还是几何；收到我的工具回复后，用一句中文介绍我选择的科目。",
                        "operation_id": "real-ask",
                    }
                )
                events = []
                replied = False
                async with asyncio.timeout(120):
                    async for event in sdk.stream_turn(turn["id"]):
                        events.append(event)
                        # 原 ask_user 协议通过 tool_result 发出卡片，PG 持久状态用于确定等待边界。
                        if not replied:
                            from deeptutor.services.session import get_session_store

                            state = await get_session_store().get_turn(turn["id"])
                            if state["status"] == "waiting_input":
                                assert await sdk.submit_user_reply(turn["id"], text="代数")
                                replied = True
                assert replied, "真实模型未触发 ask_user，不能把纯文本回答冒充交互验收"
                assert events[-1]["metadata"]["status"] == "completed"
                records.append(events)
                assert (await sdk.get_session(session["id"]))["messages"]
    evidence = {
        "model": model,
        "secret_source": ".secrets/.test-secrets（仅进程内读取）",
        "endpoint_host": host,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "turns": [],
        "budget_limits": {
            "max_rounds_per_turn": 3,
            "max_output_tokens_per_chat_call": 512,
            "turns": 4,
            "title_max_tokens": 80,
        },
        "actual_model_calls": [
            {
                "max_output_tokens": c["max_output_tokens"],
                "message_count": len(c["messages"]),
                "usage": c["usage"],
                "stream_finished": c["stream_finished"],
                "include_usage": c["include_usage"],
                "elapsed_seconds": c.get("elapsed_seconds"),
            }
            for c in actual_calls
        ],
        "note": "真实调用，不含凭证/正文；cost_summary仅core聊天用量估算，actual_model_calls记录已观察到的服务端用量。usage=null表示未获得usage末帧，不能按0费用计算；标题受20秒超时/80输出tokens约束。均非供应商账单。",
    }
    for events in records:
        costs = [
            e.get("metadata", {}).get("metadata", {}).get("cost_summary")
            for e in events
            if e.get("metadata", {}).get("metadata", {}).get("cost_summary")
        ]
        assert costs, "真实turn缺少用量信封"
        evidence["turns"].append(
            {
                "turn_id": events[-1]["turn_id"],
                "events": len(events),
                "status": events[-1]["metadata"]["status"],
                "cost_summary": costs,
            }
        )
    target = Path("openspec/changes/add-enterprise-pg-identity-session-slice/evidence")
    target.mkdir(exist_ok=True)
    (target / "real-model-smoke.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    )
    assert all(c["usage"] is not None for c in actual_calls if c["max_output_tokens"] > 80), (
        evidence["actual_model_calls"]
    )
