"""CLI 连接真实 TCP 服务；仅外部模型使用确定性替身，身份与持久化均为真实 PG。"""

import asyncio
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import pytest
from test_application import app as app
from test_flows import chunk
from test_flows import model as model
import uvicorn


@pytest.fixture
async def remote(app, tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        path = tmp_path / "deployment.json"
        path.write_text(app.state.enterprise.deployment.model_dump_json())
        yield app.state.enterprise, path, f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        listener.close()


async def invoke(
    remote, token, *args, allow_http=True, input_text=None, server_override=None, input_gate=None
):
    _, config, server = remote
    server = server_override or server
    env = dict(os.environ, CLI_AUTH=token)
    env["PYTHONPATH"] = (
        str(Path(__file__).parents[1] / "src") + os.pathsep + env.get("PYTHONPATH", "")
    )
    # 客户端根本不需要数据库、签名或模型 Secret，更不能另起执行者。
    for name in ("DT_TEST_DB", "DT_TEST_SIGN", "DT_TEST_EPOCH", "DT_TEST_BOOT", "DT_TEST_MODEL"):
        env.pop(name, None)
    command = [
        sys.executable,
        "-m",
        "deeptutor_enterprise.cli",
        "--config",
        str(config),
        "session",
        *args,
        "--server",
        server,
        "--auth-token-env",
        "CLI_AUTH",
    ]
    if allow_http:
        command.append("--allow-loopback-http")
    process = await asyncio.create_subprocess_exec(
        *command,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        if input_gate is not None:
            await input_gate.wait()
        stdout, stderr = await asyncio.wait_for(
            process.communicate((input_text or "").encode()), 30
        )
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    return process.returncode, stdout.decode(), stderr.decode()


async def test_remote_cli_starts_reads_and_cancels_existing_executor(remote, model):
    enterprise, _, _ = remote
    token = await enterprise.identity.login("admin", "long-password-1", client="remote-cli")
    model.gate = asyncio.Event()
    running = asyncio.create_task(
        invoke(remote, token, "run", "--text", "CLI question", "--operation-id", "remote-op")
    )
    try:
        async with asyncio.timeout(15):
            while not model.started.is_set():
                if running.done():
                    result = await running
                    pytest.fail(f"远程 start 未到达模型：{result}")
                await asyncio.sleep(0.02)
        async with enterprise.sdk(token) as sdk:
            records = await sdk.list_sessions()
            sid = records[0]["session_id"]
            turn = await sdk.get_active_turn(sid)
        code, output, error = await invoke(remote, token, "list")
        assert code == 0, error
        assert json.loads(output)["sessions"][0]["session_id"] == sid
        code, output, error = await invoke(remote, token, "show", "--session-id", sid)
        assert code == 0, error
        assert json.loads(output)["messages"][0]["content"] == "CLI question"
        code, output, error = await invoke(remote, token, "cancel", "--turn-id", turn["turn_id"])
        assert code == 0, error
        assert json.loads(output)["cancelled"] is True
        code, output, error = await running
        assert code == 0, error
        lines = [json.loads(line) for line in output.splitlines()]
        assert any(
            row.get("type") == "done" and row["metadata"]["status"] == "cancelled" for row in lines
        )
        assert len(model.requests) == 1
        assert enterprise.lease.active
    finally:
        model.gate.set()
        if not running.done():
            await running


async def test_remote_cli_owner_token_and_transport_fail_closed(remote):
    enterprise, _, _ = remote
    admin = await enterprise.identity.login("admin", "long-password-1", client="remote-owner")
    await enterprise.identity.create_user(admin, "ordinary", "long-password-2")
    ordinary = await enterprise.identity.login("ordinary", "long-password-2", client="remote-owner")
    async with enterprise.sdk(ordinary):
        from deeptutor.services.session import get_session_store

        store = get_session_store()
        session = await store.create_session("private CLI session")
        turn = await store.begin_turn(session["id"])
    for command in (
        ("show", "--session-id", session["id"]),
        ("cancel", "--turn-id", turn["id"]),
        ("delete", "--session-id", session["id"]),
        ("rename", "--session-id", session["id"], "--text", "stolen"),
    ):
        code, output, error = await invoke(remote, admin, *command)
        assert code != 0
        assert "private CLI session" not in output + error
    code, output, error = await invoke(remote, "invalid-token", "list")
    assert code != 0 and "invalid-token" not in output + error
    code, _, _ = await invoke(remote, ordinary, "list", allow_http=False)
    assert code != 0
    await enterprise.identity.logout(ordinary)
    code, output, error = await invoke(remote, ordinary, "list")
    assert code != 0 and ordinary not in output + error


async def test_remote_cli_ask_user_replay_rename_and_delete(remote, model):
    enterprise, _, _ = remote
    token = await enterprise.identity.login("admin", "long-password-1", client="cli-ask")
    model.scripts = [
        [
            chunk(
                tools=[
                    SimpleNamespace(
                        index=0,
                        id="ask-cli",
                        function=SimpleNamespace(
                            name="ask_user",
                            arguments='{"questions":[{"id":"q1","question":"Which subject?"}]}',
                        ),
                    )
                ],
                finish="tool_calls",
            )
        ],
        [chunk("Clarified answer")],
    ]
    command = ("run", "--text", "Help me", "--operation-id", "ask-operation")
    code, output, error = await invoke(remote, token, *command, input_text="algebra\n")
    assert code == 0, error
    result = json.loads(output.splitlines()[-1])
    assert result["status"] == "completed"
    sid = result["session_id"]
    code, output, error = await invoke(remote, token, *command)
    assert code == 0, error
    assert "回复:" not in error
    assert len(model.requests) == 2
    code, output, error = await invoke(
        remote, token, "rename", "--session-id", sid, "--text", "CLI title"
    )
    assert code == 0, error
    assert json.loads(output)["session"]["title"] == "CLI title"
    code, output, error = await invoke(remote, token, "delete", "--session-id", sid)
    assert code == 0 and json.loads(output)["deleted"], error
    code, output, error = await invoke(remote, token, *command)
    assert code == 0 and json.loads(output)["status"] == "deleted", error


async def test_remote_cancel_stops_cli_while_stdin_is_waiting(remote, model):
    enterprise, _, _ = remote
    token = await enterprise.identity.login("admin", "long-password-1", client="cli-input")
    model.scripts = [
        [
            chunk(
                tools=[
                    SimpleNamespace(
                        index=0,
                        id="ask-cancel",
                        function=SimpleNamespace(
                            name="ask_user",
                            arguments='{"questions":[{"id":"q1","question":"Subject?"}]}',
                        ),
                    )
                ],
                finish="tool_calls",
            )
        ]
    ]
    gate = asyncio.Event()
    running = asyncio.create_task(invoke(remote, token, "run", "--text", "Ask me", input_gate=gate))
    try:
        async with asyncio.timeout(15):
            while True:
                async with enterprise.sdk(token) as sdk:
                    sessions = await sdk.list_sessions()
                    turn = (
                        await sdk.get_active_turn(sessions[0]["session_id"]) if sessions else None
                    )
                if turn and turn["status"] == "waiting_input":
                    break
                await asyncio.sleep(0.03)
        await asyncio.sleep(0.1)
        code, _, error = await invoke(remote, token, "cancel", "--turn-id", turn["turn_id"])
        assert code == 0, error
        await asyncio.sleep(0.1)
        gate.set()
        code, output, error = await running
        assert code == 0, error
        assert json.loads(output.splitlines()[-1])["status"] == "cancelled"
    finally:
        gate.set()
        if not running.done():
            await running


def test_cli_rejects_remote_http_credentials_and_inline_identity():
    from deeptutor_enterprise.cli import _server_url, parser

    for server in (
        "http://school.example",
        "http://localhost",
        "http://192.168.1.2",
        "https://user:password@school.example",
        "https://school.example/?token=secret",
        "https://school.example/api",
        "file:///etc/passwd",
        "ftp://127.0.0.1",
    ):
        with pytest.raises(ValueError):
            _server_url(server, allow_loopback_http=True)
    assert _server_url("https://school.example/") == "https://school.example"
    prefix = ["--config", "unused", "session", "list", "--auth-token-env", "AUTH"]
    for extra in (("--auth-token", "inline-token"), ("--tenant-id", "other")):
        with pytest.raises(SystemExit):
            parser().parse_args(prefix + ["--server", "https://school.example", *extra])


async def test_cli_never_forwards_bearer_through_websocket_redirect(remote):
    """真实 TCP 恶意重定向响应，验证第二地址不会收到认证握手。"""
    destination_called = asyncio.Event()

    async def destination(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        destination_called.set()
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with await asyncio.start_server(destination, "127.0.0.1", 0) as target:
        location = f"ws://127.0.0.1:{target.sockets[0].getsockname()[1]}/api/v1/ws"

        async def redirect(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(
                f"HTTP/1.1 302 Found\r\nLocation: {location}\r\nContent-Length: 0\r\n\r\n".encode()
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        async with await asyncio.start_server(redirect, "127.0.0.1", 0) as source:
            origin = f"http://127.0.0.1:{source.sockets[0].getsockname()[1]}"
            code, output, error = await invoke(
                remote, "must-not-forward", "cancel", "--turn-id", "turn", server_override=origin
            )
            assert code != 0 and "must-not-forward" not in output + error
            assert not destination_called.is_set()
