"""真实 PG 的 HTTP / WebSocket / SDK 交错授权矩阵；外部模型采用确定性替身。"""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

from deeptutor_enterprise.context import current_identity, current_token
import httpx
import psycopg
import pytest
from test_application import app as app
from test_flows import ScriptedModel, Socket, chunk

from deeptutor.core.providers import get_providers
from deeptutor.multi_user.context import get_current_user_or_none
from deeptutor.services.session import get_session_store

ORIGIN = "https://school.example"
PASSWORD = "matrix-test-password-2026"


def assert_unbound():
    assert get_providers() is None
    assert get_current_user_or_none() is None
    with pytest.raises(PermissionError):
        current_identity()
    with pytest.raises(PermissionError):
        current_token()


def assert_private_to(value, owner, actors):
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    for name in actors:
        if name != owner:
            assert f"PRIVATE::{name}" not in encoded


@pytest.fixture
async def matrix(app, monkeypatch):
    enterprise = app.state.enterprise
    admin_token = await enterprise.identity.login("admin", "long-password-1", client="matrix")
    for name in ("alice", "bob"):
        await enterprise.identity.create_user(admin_token, name, PASSWORD)
    actors = {}
    for name in ("alice", "bob", "admin"):
        token = (
            admin_token
            if name == "admin"
            else await enterprise.identity.login(name, PASSWORD, client="matrix")
        )
        identity = await enterprise.identity.authenticate(token)
        async with enterprise.sdk(token):
            store = get_session_store()
            session = await store.create_session(f"PRIVATE::{name} title")
            user = await store.add_message(session["id"], "user", f"PRIVATE::{name} prompt")
            turn = await store.begin_turn(session["id"])
            await store.append_events(
                turn["id"], [{"type": "content", "content": f"PRIVATE::{name} trace"}]
            )
            result = await store.finalize_turn(
                turn["id"],
                status="completed",
                content=f"PRIVATE::{name} answer",
                user_message_id=user,
            )
            waiting_session = await store.create_session(f"PRIVATE::{name} waiting")
            waiting = await store.begin_turn(waiting_session["id"])
            await store.transition_turn(waiting["id"], "waiting_input")
            await store.append_events(
                waiting["id"], [{"type": "content", "content": f"PRIVATE::{name} waiting trace"}]
            )
        actors[name] = SimpleNamespace(
            token=token,
            identity=identity,
            session=session["id"],
            user=user,
            message=result["assistant_message_id"],
            turn=turn["id"],
            waiting_session=waiting_session["id"],
            waiting=waiting["id"],
        )
    models = {
        actor.identity.user_id: ScriptedModel(
            [[chunk(f"PRIVATE::{name} model answer")] for _ in range(10)]
        )
        for name, actor in actors.items()
    }
    from deeptutor.agents.loop import pipeline
    from deeptutor.services import llm

    monkeypatch.setattr(
        pipeline, "build_openai_client", lambda _config: models[current_identity().user_id]
    )

    async def title(**_kwargs):
        yield f"PRIVATE::{current_identity().username} generated title"

    monkeypatch.setattr(llm, "stream", title)
    assert_unbound()
    yield app, actors, models
    for actor in actors.values():
        async with enterprise.sdk(actor.token):
            store = get_session_store()
            if await store.get_turn(actor.waiting):
                await store.finalize_turn(actor.waiting, status="cancelled")
    assert_unbound()


def routes(actor):
    prefix = f"/api/sessions/{actor.session}"
    return [
        ("GET", prefix, None),
        ("GET", f"{prefix}/messages/{actor.message}/events", None),
        ("PATCH", prefix, {"title": "changed title"}),
        ("PATCH", f"{prefix}/organization", {"pinned": True, "archived": True}),
        (
            "PUT",
            f"{prefix}/branch-selection",
            {"selected_branches": {str(actor.user): actor.message}},
        ),
        ("DELETE", f"{prefix}/messages/{actor.message}", None),
        ("DELETE", prefix, None),
    ]


async def test_http_all_session_routes_enforce_owner_for_users_and_administrator(matrix):
    application, actors, models = matrix

    async def probe(name, actor):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url=ORIGIN,
            headers={"Authorization": "Bearer " + actor.token},
        ) as client:
            listed = await client.get("/api/sessions?limit=1&offset=0")
            assert listed.status_code == 200 and len(listed.json()["sessions"]) == 1
            assert_private_to(listed.json(), name, actors)
            for foreign_name, foreign in actors.items():
                if foreign_name == name:
                    continue
                for method, path, payload in routes(foreign):
                    response = await client.request(method, path, json=payload)
                    assert response.status_code == 404, (name, method, path, response.text)
                    assert_private_to(response.json(), name, actors)
            own = await client.get(f"/api/sessions/{actor.session}")
            assert own.status_code == 200 and f"PRIVATE::{name} answer" in own.text
            assert_private_to(own.json(), name, actors)
        assert_unbound()

    await asyncio.gather(*(probe(name, actor) for name, actor in actors.items()))
    assert all(not model.requests for model in models.values())
    assert_unbound()


async def test_http_owner_can_use_each_included_session_route(matrix):
    application, actors, _ = matrix

    async def own_routes(name, actor):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url=ORIGIN,
            headers={"Authorization": "Bearer " + actor.token},
        ) as client:
            for method, path, payload in routes(actor):
                response = await client.request(method, path, json=payload)
                assert response.status_code == 200, (name, method, path, response.text)
                assert_private_to(response.json(), name, actors)
            assert (await client.get(f"/api/sessions/{actor.session}")).status_code == 404
        assert_unbound()

    await asyncio.gather(*(own_routes(name, actor) for name, actor in actors.items()))


async def test_sdk_read_and_control_matrix_never_inherits_another_owner(matrix):
    application, actors, models = matrix
    enterprise = application.state.enterprise

    async def probe(name, actor):
        async with enterprise.sdk(actor.token) as sdk:
            assert current_identity().user_id == actor.identity.user_id
            listed = await sdk.list_sessions()
            assert len(listed) == 2
            assert_private_to(listed, name, actors)
            assert (await sdk.get_active_turn(actor.waiting_session))["turn_id"] == actor.waiting
            assert f"PRIVATE::{name} answer" in json.dumps(await sdk.get_session(actor.session))
            own_events = [event async for event in sdk.stream_turn(actor.turn)]
            assert own_events[-1]["type"] == "done"
            for foreign_name, foreign in actors.items():
                if foreign_name == name:
                    continue
                assert await sdk.get_session(foreign.session) is None
                assert await sdk.get_active_turn(foreign.waiting_session) is None
                assert await sdk.rename_session(foreign.session, "take over") is False
                assert await sdk.delete_session(foreign.session) is False
                for action in (
                    lambda: sdk.start_turn({"session_id": foreign.session, "content": "take over"}),
                    lambda: sdk.regenerate_last_turn(foreign.session),
                    lambda: sdk.cancel_turn(foreign.waiting),
                    lambda: sdk.submit_user_reply(foreign.waiting, text="foreign reply"),
                ):
                    with pytest.raises((LookupError, ValueError)):
                        await action()
                with pytest.raises(LookupError):
                    _ = [event async for event in sdk.stream_turn(foreign.turn)]
            with pytest.raises(ValueError):
                await sdk.start_turn({"content": "forged", "tenant_id": str(uuid4())})
        assert_unbound()
        with pytest.raises(PermissionError):
            await sdk.list_sessions()

    await asyncio.gather(*(probe(name, actor) for name, actor in actors.items()))
    assert all(not model.requests for model in models.values())
    assert_unbound()


async def test_ws_owner_negative_matrix_does_not_expose_or_control_foreign_turns(matrix):
    application, actors, models = matrix

    async def probe(name, actor):
        for foreign_name, foreign in actors.items():
            if foreign_name == name:
                continue
            async with Socket(application, actor.token) as ws:
                await ws.send({"type": "subscribe_session", "session_id": foreign.waiting_session})
                await ws.send({"type": "ping"})
                response = await ws.receive()
                assert response["type"] == "pong", response
                assert_private_to(response, name, actors)
            commands = [
                {"type": "start_turn", "session_id": foreign.session, "content": "take over"},
                {"type": "regenerate", "session_id": foreign.session},
                {"type": "check_active_turn", "session_id": foreign.waiting_session},
                {"type": "subscribe_turn", "turn_id": foreign.turn},
                {"type": "resume_from", "turn_id": foreign.turn, "seq": 0},
                {
                    "type": "submit_user_reply",
                    "turn_id": foreign.waiting,
                    "text": "take over",
                    "command_id": str(uuid4()),
                },
                {"type": "cancel_turn", "turn_id": foreign.waiting, "command_id": str(uuid4())},
            ]
            for command in commands:
                async with Socket(application, actor.token) as ws:
                    await ws.send(command)
                    response = await ws.receive()
                    assert_private_to(response, name, actors)
                    if command["type"] == "check_active_turn":
                        assert response["type"] == "active_turn_info"
                        assert response["status"] == "none" and not response["turn_id"]
                    else:
                        assert response["type"] == "protocol_error", response
        async with application.state.enterprise.sdk(actor.token):
            assert (await get_session_store().get_turn(actor.waiting))["status"] == "waiting_input"
        assert_unbound()

    await asyncio.gather(*(probe(name, actor) for name, actor in actors.items()))
    assert all(not model.requests for model in models.values())


async def test_ws_start_continue_regenerate_replay_are_interleaved_per_owner(matrix):
    application, actors, models = matrix

    async def exercise(name, actor):
        async with Socket(application, actor.token) as ws:
            await ws.send({"type": "check_active_turn", "session_id": actor.waiting_session})
            assert (await ws.receive())["turn_id"] == actor.waiting
            await ws.send({"type": "start_turn", "content": f"PRIVATE::{name} first question"})
            first = await ws.until("done")
            sid, tid = first[-1]["session_id"], first[-1]["turn_id"]
            assert first[-1]["metadata"]["status"] == "completed"
            assert_private_to(first, name, actors)
            await ws.send(
                {"type": "start_turn", "session_id": sid, "content": f"PRIVATE::{name} followup"}
            )
            continued = await ws.until("done")
            await ws.send({"type": "regenerate", "session_id": sid})
            regenerated = await ws.until("done")
            assert_private_to(continued + regenerated, name, actors)
            await ws.send({"type": "subscribe_turn", "turn_id": tid})
            replay = await ws.until("done")
            assert_private_to(replay, name, actors)
            await ws.send({"type": "resume_from", "turn_id": tid, "seq": first[-2]["seq"]})
            tail = await ws.until("done")
            assert len(tail) == 1 and tail[0]["turn_id"] == tid
        async with application.state.enterprise.sdk(actor.token) as sdk:
            detail = await sdk.get_session(sid)
            assert len(detail["messages"]) == 5
            assert_private_to(detail, name, actors)
        assert len(models[actor.identity.user_id].requests) == 3
        assert_private_to(models[actor.identity.user_id].requests, name, actors)
        assert_unbound()

    await asyncio.gather(*(exercise(name, actor) for name, actor in actors.items()))


async def test_ws_and_sdk_reply_cancel_act_only_on_current_owner_execution(matrix):
    application, actors, models = matrix
    for name, actor in actors.items():
        ask = chunk(
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
        models[actor.identity.user_id].scripts = [
            [ask],
            [chunk(f"PRIVATE::{name} answered")],
            [ask],
        ]

    async def exercise(name, actor):
        async with Socket(application, actor.token) as ws:
            await ws.send({"type": "start_turn", "content": f"PRIVATE::{name} ask"})
            first = await ws.until("tool_result")
            tid = first[-1]["turn_id"]
            await ws.send({"type": "unsubscribe", "turn_id": tid})
            await ws.send(
                {
                    "type": "subscribe_session",
                    "session_id": first[-1]["session_id"],
                    "after_seq": 0,
                }
            )
            # 收到已持久 ask 卡片后再回复，证明 session 订阅已经建立，避免时序侥幸。
            assert_private_to(await ws.until("tool_result"), name, actors)
            if name == "alice":
                async with application.state.enterprise.sdk(actor.token) as sdk:
                    assert await sdk.submit_user_reply(tid, text=f"PRIVATE::{name} reply")
            else:
                await ws.send(
                    {
                        "type": "submit_user_reply",
                        "turn_id": tid,
                        "text": f"PRIVATE::{name} reply",
                        "command_id": "own-reply",
                    }
                )
                assert (await ws.until("command_ack"))[-1]["accepted"]
            finished = await ws.until("done")
            assert finished[-1]["metadata"]["status"] == "completed"
            assert_private_to(finished, name, actors)
            await ws.send({"type": "start_turn", "content": f"PRIVATE::{name} cancel"})
            pending = await ws.until("tool_result")
            cancelled_id = pending[-1]["turn_id"]
            if name == "alice":
                await ws.send(
                    {"type": "cancel_turn", "turn_id": cancelled_id, "command_id": "own-cancel"}
                )
                received = []
                while not (
                    any(e["type"] == "done" for e in received)
                    and any(e["type"] == "command_ack" for e in received)
                ):
                    received.append(await ws.receive())
                assert next(e for e in received if e["type"] == "command_ack")["accepted"]
                assert (
                    next(e for e in received if e["type"] == "done")["metadata"]["status"]
                    == "cancelled"
                )
            else:
                async with application.state.enterprise.sdk(actor.token) as sdk:
                    assert await sdk.cancel_turn(cancelled_id)
                assert (await ws.until("done"))[-1]["metadata"]["status"] == "cancelled"
        assert_unbound()

    await asyncio.gather(*(exercise(name, actor) for name, actor in actors.items()))


async def rejected_handshake(application, token, *, headers=(), query=b""):
    received = asyncio.Queue()
    for message in ({"type": "websocket.connect"}, {"type": "websocket.disconnect", "code": 1000}):
        await received.put(message)
    sent = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "wss",
        "path": "/api/v1/ws",
        "raw_path": b"/api/v1/ws",
        "query_string": query,
        "root_path": "",
        "headers": [
            (b"origin", ORIGIN.encode()),
            (b"authorization", ("Bearer " + token).encode()),
            *headers,
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("school.example", 443),
        "subprotocols": [],
        "state": {},
    }
    await asyncio.wait_for(application(scope, received.get, send), 10)
    assert sent[0]["type"] == "websocket.close" and sent[0]["code"] == 1008
    return sent


async def test_http_ws_sdk_invalid_tokens_and_forged_tenants_fail_without_context_leaks(matrix):
    application, actors, _ = matrix
    for name, actor in actors.items():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url=ORIGIN
        ) as client:
            status = await client.get(
                "/api/auth/status", headers={"Authorization": "Bearer " + actor.token}
            )
            assert status.status_code == 200 and status.json()["user_id"] == actor.identity.user_id
            for method, path, payload in [
                ("GET", "/api/sessions", None),
                *routes(actor),
                ("POST", "/api/auth/logout", {}),
            ]:
                response = await client.request(
                    method, path, json=payload, headers={"Authorization": "Bearer invalid-token"}
                )
                assert response.status_code == 401
                assert "PRIVATE::" not in response.text
            for header in ("X-Tenant-Id", "X-Deeptutor-Tenant-Id"):
                response = await client.get(
                    "/api/sessions",
                    headers={"Authorization": "Bearer " + actor.token, header: "forged"},
                )
                assert response.status_code == 403
            for query in ("tenant", "tenant_id", "tenantId"):
                response = await client.get(
                    f"/api/sessions?{query}=forged",
                    headers={"Authorization": "Bearer " + actor.token},
                )
                assert response.status_code == 403
        await rejected_handshake(application, "invalid-token")
        await rejected_handshake(application, actor.token, headers=[(b"x-tenant-id", b"forged")])
        await rejected_handshake(application, actor.token, query=b"tenant_id=forged")
        async with Socket(application, actor.token) as ws:
            await ws.send({"type": "start_turn", "content": "forged", "tenant_id": "forged"})
            assert (await ws.receive())["type"] == "protocol_error"
        with pytest.raises(PermissionError):
            async with application.state.enterprise.sdk("invalid-token"):
                pytest.fail("Invalid token must not enter the SDK context")
        assert_unbound()


async def test_http_login_status_logout_are_consistent_for_each_role(matrix):
    application, actors, _ = matrix
    for name, actor in actors.items():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url=ORIGIN
        ) as client:
            anonymous = await client.get("/api/auth/status")
            assert anonymous.status_code == 200 and not anonymous.json()["authenticated"]
            invalid = await client.post(
                "/api/auth/login",
                headers={"Origin": ORIGIN},
                json={"username": name, "password": "incorrect-password"},
            )
            assert invalid.status_code == 401 and "PRIVATE::" not in invalid.text
            response = await client.post(
                "/api/auth/login",
                headers={"Origin": ORIGIN},
                json={
                    "username": name,
                    "password": "long-password-1" if name == "admin" else PASSWORD,
                },
            )
            assert (
                response.status_code == 200 and response.json()["user_id"] == actor.identity.user_id
            )
            token = client.cookies["dt_token"]
            assert (await client.get("/api/auth/status")).json()["authenticated"]
            logout = await client.post(
                "/api/auth/logout",
                headers={"Origin": ORIGIN, "X-CSRF-Token": client.cookies["dt_csrf"]},
            )
            assert logout.status_code == 200 and "dt_token" not in client.cookies
            assert not (
                await client.get("/api/auth/status", headers={"Authorization": "Bearer " + token})
            ).json()["authenticated"]
            assert (
                await client.get("/api/sessions", headers={"Authorization": "Bearer " + token})
            ).status_code == 401
        assert_unbound()


async def test_two_tenants_with_identical_user_session_turn_ids_cannot_replay_each_other(
    pg_dsn, monkeypatch
):
    from deeptutor_enterprise.bootstrap import create_application
    from deeptutor_enterprise.configuration import DeploymentConfig
    from deeptutor_enterprise.migrations.runner import MigrationRunner
    from deeptutor_enterprise.scope import TenantScope
    from deeptutor_enterprise.stores.postgres.session import PostgresSessionStore

    await MigrationRunner(pg_dsn).apply()
    env = {
        "DT_MATRIX_DB": pg_dsn.replace("user=postgres", "user=dt_enterprise_app"),
        "DT_MATRIX_SIGN": "s" * 48,
        "DT_MATRIX_EPOCH": "matrix-epoch",
        "DT_MATRIX_BOOT": "b" * 48,
        "DT_MATRIX_MODEL": "test-model-value",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    deployments, owners = {}, {}
    shared_user, sid, tid = "identical-internal-user", "identical-session", "identical-turn"
    for name in ("tenant-a", "tenant-b"):
        deployment = DeploymentConfig(
            version=1,
            tenant_id=uuid4(),
            resource=name,
            database_secret="env:DT_MATRIX_DB",
            signing_secret="env:DT_MATRIX_SIGN",
            auth_epoch_secret="env:DT_MATRIX_EPOCH",
            bootstrap_secret="env:DT_MATRIX_BOOT",
            origins=(ORIGIN,),
            models=(
                {
                    "profile_id": "chat",
                    "model_id": "primary",
                    "model": "test-model",
                    "base_url": "https://model.example/v1",
                    "secret": "env:DT_MATRIX_MODEL",
                    "allowed_roles": ("user", "tenant_admin"),
                },
            ),
        )
        deployments[name] = deployment
        application = create_application(deployment)
        enterprise = application.state.enterprise
        async with enterprise.db:
            bootstrap = await enterprise.identity.bootstrap("same-admin", PASSWORD, secret="b" * 48)
            # 仅在临时测试库插入刻意碰撞的内部标识；认证仍走真实密码/token验证。
            async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
                password_hash = (
                    await (
                        await c.execute(
                            "SELECT password_hash FROM enterprise.local_credentials WHERE tenant_id=%s AND user_id=%s",
                            (str(deployment.tenant_id), bootstrap["id"]),
                        )
                    ).fetchone()
                )[0]
                await c.execute(
                    "INSERT INTO enterprise.users(tenant_id,id,username,role) VALUES(%s,%s,'same-user','user')",
                    (str(deployment.tenant_id), shared_user),
                )
                await c.execute(
                    "INSERT INTO enterprise.local_credentials(tenant_id,user_id,password_hash) VALUES(%s,%s,%s)",
                    (str(deployment.tenant_id), shared_user, password_hash),
                )
            token = await enterprise.identity.login(
                "same-user", PASSWORD, client="collision-matrix"
            )
            store = PostgresSessionStore(
                enterprise.db, TenantScope(str(deployment.tenant_id), shared_user)
            )
            await store.create_session(f"PRIVATE::{name} title", session_id=sid)
            user_message = await store.add_message(sid, "user", f"PRIVATE::{name} question")
            await store.begin_turn(sid, turn_id=tid)
            await store.append_events(
                tid, [{"type": "content", "content": f"PRIVATE::{name} trace"}]
            )
            answer = await store.finalize_turn(
                tid,
                status="completed",
                content=f"PRIVATE::{name} answer",
                user_message_id=user_message,
            )
            owners[name] = SimpleNamespace(
                token=token,
                session=sid,
                turn=tid,
                user=user_message,
                message=answer["assistant_message_id"],
            )

    # 同一真实 DB 的固定 tenant 应用顺序启动，严格遵守单执行者约束。
    for name in ("tenant-a", "tenant-b", "tenant-a"):
        application = create_application(deployments[name])
        own = owners[name]
        foreign = owners["tenant-b" if name == "tenant-a" else "tenant-a"]
        async with application.router.lifespan_context(application):
            enterprise = application.state.enterprise
            async with enterprise.sdk(own.token) as sdk:
                assert current_identity().tenant_id == str(deployments[name].tenant_id)
                assert current_identity().user_id == shared_user
                detail = await sdk.get_session(sid)
                assert f"PRIVATE::{name} answer" in json.dumps(detail)
                assert_private_to(detail, name, owners)
                assert len(await sdk.list_sessions()) == 1
                events = [event async for event in sdk.stream_turn(tid)]
                assert_private_to(events, name, owners)
            with pytest.raises(PermissionError):
                async with enterprise.sdk(foreign.token):
                    pytest.fail("A token for a different tenant must not bind the SDK")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url=ORIGIN
            ) as client:
                detail = await client.get(
                    f"/api/sessions/{sid}", headers={"Authorization": "Bearer " + own.token}
                )
                assert detail.status_code == 200 and f"PRIVATE::{name} answer" in detail.text
                assert_private_to(detail.json(), name, owners)
                for method, path, payload in [("GET", "/api/sessions", None), *routes(own)]:
                    denied = await client.request(
                        method,
                        path,
                        json=payload,
                        headers={"Authorization": "Bearer " + foreign.token},
                    )
                    assert denied.status_code == 401
                    assert "PRIVATE::" not in denied.text
            await rejected_handshake(application, foreign.token)
            async with Socket(application, own.token) as ws:
                await ws.send({"type": "subscribe_turn", "turn_id": tid})
                replay = await ws.until("done")
                assert f"PRIVATE::{name} trace" in json.dumps(replay)
                assert_private_to(replay, name, owners)
            assert_unbound()
        assert_unbound()


async def test_sdk_owner_start_continue_regenerate_rename_delete_are_interleaved(matrix):
    application, actors, models = matrix

    async def exercise(name, actor):
        async with application.state.enterprise.sdk(actor.token) as sdk:
            session, first = await sdk.start_turn({"content": f"PRIVATE::{name} SDK question"})
            first_events = [event async for event in sdk.stream_turn(first["id"])]
            assert first_events[-1]["metadata"]["status"] == "completed"
            _, continued = await sdk.start_turn(
                {"session_id": session["id"], "content": f"PRIVATE::{name} SDK followup"}
            )
            continued_events = [event async for event in sdk.stream_turn(continued["id"])]
            _, regenerated = await sdk.regenerate_last_turn(session["id"])
            regenerated_events = [event async for event in sdk.stream_turn(regenerated["id"])]
            assert_private_to(first_events + continued_events + regenerated_events, name, actors)
            assert await sdk.rename_session(session["id"], f"PRIVATE::{name} renamed")
            detail = await sdk.get_session(session["id"])
            assert detail["title"] == f"PRIVATE::{name} renamed" and len(detail["messages"]) == 5
            assert_private_to(detail, name, actors)
            assert await sdk.delete_session(session["id"])
            assert await sdk.get_session(session["id"]) is None
        assert len(models[actor.identity.user_id].requests) == 3
        assert_private_to(models[actor.identity.user_id].requests, name, actors)
        assert_unbound()

    await asyncio.gather(*(exercise(name, actor) for name, actor in actors.items()))
