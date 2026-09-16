# ruff: noqa: F811
"""默认 CLI 的 PostgreSQL-only 运行契约。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import types
import uuid

from fastapi import Depends, FastAPI
import pytest
from typer.testing import CliRunner
import uvicorn

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401

runner = CliRunner()


def _invoke(args: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "deeptutor_cli", *args],
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
    )


def _write_postgres_config(path: Path, tenant_id: str, *, resource: str = "default-cli") -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "tenant_id": tenant_id,
                "resource": resource,
                "signing_secret": "env:TEST_SIGNING_SECRET",
                "auth_epoch_secret": "env:TEST_AUTH_EPOCH_SECRET",
                "bootstrap_secret": "env:TEST_BOOTSTRAP_SECRET",
            }
        ),
        encoding="utf-8",
    )
    return path


def _install_environment(monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]) -> None:
    for name in (
        "DEEPTUTOR_HOME",
        "DEEPTUTOR_POSTGRES_CONFIG",
        "DEEPTUTOR_DATABASE_URL",
        "TEST_SIGNING_SECRET",
        "TEST_AUTH_EPOCH_SECRET",
        "TEST_BOOTSTRAP_SECRET",
    ):
        monkeypatch.setenv(name, environment[name])


async def _prepare_default_cli_environment(pg_dsn: str, tmp_path: Path):
    from deeptutor.persistence.postgres.connection import Database
    from deeptutor.persistence.postgres.identity.service import IdentityService
    from deeptutor.persistence.postgres.migrations.runner import MigrationRunner
    from deeptutor.persistence.postgres.scope import TenantScope
    from deeptutor.persistence.postgres.session import PostgresSessionStore

    await MigrationRunner(pg_dsn).apply()
    tenant_id = str(uuid.uuid4())
    config = _write_postgres_config(tmp_path / "postgres.json", tenant_id)
    runtime_dsn = pg_dsn.replace("user=postgres", "user=dt_enterprise_app")
    environment = {
        **os.environ,
        "DEEPTUTOR_HOME": str(tmp_path / "home"),
        "DEEPTUTOR_POSTGRES_CONFIG": str(config),
        "DEEPTUTOR_DATABASE_URL": runtime_dsn,
        "TEST_SIGNING_SECRET": "s" * 48,
        "TEST_AUTH_EPOCH_SECRET": "epoch-default-cli",
        "TEST_BOOTSTRAP_SECRET": "b" * 48,
    }
    environment.pop("DT_RUN_REAL_MODEL", None)
    async with Database(runtime_dsn, resource="default-cli-bootstrap") as db:
        identity = IdentityService(
            db,
            tenant_id=tenant_id,
            signing_key="s" * 48,
            auth_epoch="epoch-default-cli",
            bootstrap_secret="b" * 48,
        )
        await identity.bootstrap("admin", "administrator-123", secret="b" * 48)
        token = await identity.login("admin", "administrator-123", client="cli-test")
        actor = await identity.authenticate(token)
        store = PostgresSessionStore(db, TenantScope(tenant_id, actor.user_id))
        session = await store.create_session(title="CLI PG session")
    environment["CLI_TOKEN"] = token
    return environment, session


def test_cli_help_and_version_do_not_require_postgres(tmp_path: Path) -> None:
    """帮助/版本若回归为构造默认 PG runtime，本测试会失败。"""

    environment = {**os.environ, "DEEPTUTOR_HOME": str(tmp_path / "home")}
    environment.pop("DEEPTUTOR_POSTGRES_CONFIG", None)
    environment.pop("DEEPTUTOR_DATABASE_URL", None)
    environment.pop("DT_RUN_REAL_MODEL", None)

    for args in (["--help"], ["run", "--help"], ["session", "list", "--help"]):
        result = _invoke(args, environment)
        assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "home" / "user" / "settings" / "postgres.json").exists()


def test_run_server_mode_delegates_without_local_pg_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`run --server` 只能走远程客户端；若构造本地 PG runtime，本测试会失败。"""

    captured: dict[str, object] = {}

    async def fake_remote_run_and_render(**kwargs):
        captured.update(kwargs)

    monkeypatch.setenv("CLI_TOKEN", "token-value")
    monkeypatch.delenv("DEEPTUTOR_POSTGRES_CONFIG", raising=False)
    monkeypatch.delenv("DEEPTUTOR_DATABASE_URL", raising=False)
    monkeypatch.setattr("deeptutor_cli.main.remote_run_and_render", fake_remote_run_and_render)

    result = runner.invoke(
        __import__("deeptutor_cli.main", fromlist=["app"]).app,
        [
            "run",
            "chat",
            "hello",
            "--server",
            "https://school.example",
            "--auth-token-env",
            "CLI_TOKEN",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["server"] == "https://school.example"
    assert captured["auth_token_env"] == "CLI_TOKEN"
    assert captured["request"].content == "hello"


def test_run_server_mode_rejects_unsafe_origin_without_local_pg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """远程 CLI 只向安全 origin 发送 token，且校验前不需要本地 PG 配置。"""

    monkeypatch.setenv("CLI_TOKEN", "token-value")
    monkeypatch.delenv("DEEPTUTOR_POSTGRES_CONFIG", raising=False)
    monkeypatch.delenv("DEEPTUTOR_DATABASE_URL", raising=False)

    result = runner.invoke(
        __import__("deeptutor_cli.main", fromlist=["app"]).app,
        [
            "run",
            "chat",
            "hello",
            "--server",
            "http://school.example",
            "--auth-token-env",
            "CLI_TOKEN",
        ],
    )

    assert result.exit_code != 0
    assert "HTTPS required" in result.output
    assert "token-value" not in result.output
    assert "postgres" not in result.output.lower()


async def test_remote_run_websocket_json_uses_bearer_and_auto_replies(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """远程单 turn 通过 WS 控制服务端执行者，客户端只持有 bearer token。"""

    from deeptutor.app import TurnRequest
    from deeptutor_cli.remote import remote_run_and_render

    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict] = []
            self.frames = [
                json.dumps(
                    {
                        "type": "session",
                        "metadata": {"session_id": "session-remote", "turn_id": "turn-remote"},
                    }
                ),
                json.dumps(
                    {
                        "type": "tool_result",
                        "session_id": "session-remote",
                        "turn_id": "turn-remote",
                        "content": "",
                        "metadata": {
                            "tool_metadata": {
                                "ask_user": {
                                    "questions": [{"id": "q1", "prompt": "Continue?"}]
                                }
                            }
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "command_ack",
                        "command_id": "reply-1",
                        "command_type": "submit_user_reply",
                        "accepted": True,
                    }
                ),
                json.dumps(
                    {
                        "type": "done",
                        "session_id": "session-remote",
                        "turn_id": "turn-remote",
                        "metadata": {"status": "completed"},
                    }
                ),
            ]

        async def send(self, raw: str) -> None:
            self.sent.append(json.loads(raw))

        def __aiter__(self):
            return self

        async def __anext__(self) -> str:
            if not self.frames:
                raise StopAsyncIteration
            return self.frames.pop(0)

    fake_ws = FakeWebSocket()
    captured: dict[str, object] = {}

    class FakeConnect:
        def __init__(self, uri: str, **kwargs) -> None:
            captured["uri"] = uri
            captured["kwargs"] = kwargs

        async def __aenter__(self):
            return fake_ws

        async def __aexit__(self, exc_type, exc, tb) -> None:
            captured["closed"] = True

    websockets_mod = types.ModuleType("websockets")
    legacy_mod = types.ModuleType("websockets.legacy")
    client_mod = types.ModuleType("websockets.legacy.client")
    client_mod.connect = FakeConnect
    legacy_mod.client = client_mod
    websockets_mod.legacy = legacy_mod
    monkeypatch.setitem(sys.modules, "websockets", websockets_mod)
    monkeypatch.setitem(sys.modules, "websockets.legacy", legacy_mod)
    monkeypatch.setitem(sys.modules, "websockets.legacy.client", client_mod)
    monkeypatch.setenv("CLI_TOKEN", "token-value")
    monkeypatch.delenv("DEEPTUTOR_POSTGRES_CONFIG", raising=False)
    monkeypatch.delenv("DEEPTUTOR_DATABASE_URL", raising=False)

    session, turn = await remote_run_and_render(
        request=TurnRequest(content="hello", capability="chat"),
        fmt="json",
        server="https://school.example",
        auth_token_env="CLI_TOKEN",
    )

    output = capsys.readouterr().out
    assert session == {"id": "session-remote"}
    assert turn == {"id": "turn-remote"}
    assert captured["uri"] == "wss://school.example/ws"
    assert captured["kwargs"]["extra_headers"] == {"Authorization": "Bearer token-value"}
    assert fake_ws.sent[0]["type"] == "start_turn"
    assert fake_ws.sent[0]["content"] == "hello"
    assert fake_ws.sent[1]["type"] == "submit_user_reply"
    assert fake_ws.sent[1]["turn_id"] == "turn-remote"
    assert fake_ws.sent[1]["text"] == ""
    assert "command_ack" not in output
    assert "token-value" not in output


def test_default_business_cli_requires_auth_token_env(tmp_path: Path) -> None:
    """业务 CLI 不能在缺少可信主体时退回本地管理员或 SQLite。"""

    environment = {**os.environ, "DEEPTUTOR_HOME": str(tmp_path / "home")}
    environment.pop("DEEPTUTOR_POSTGRES_CONFIG", None)
    environment.pop("DEEPTUTOR_DATABASE_URL", None)
    environment.pop("DT_RUN_REAL_MODEL", None)

    result = _invoke(["session", "list"], environment)

    assert result.returncode != 0
    assert "CLI authentication token environment reference is required" in result.stderr
    assert "sqlite" not in (result.stdout + result.stderr).lower()
    assert not (tmp_path / "home" / "chat_sessions.db").exists()


async def test_default_session_cli_uses_pg_identity_and_releases_executor(
    pg_dsn: str, tmp_path: Path
) -> None:
    """删除 CLI token 绑定或退出 close 都会让本测试失败。"""

    environment, session = await _prepare_default_cli_environment(pg_dsn, tmp_path)

    first = _invoke(
        ["session", "list", "--auth-token-env", "CLI_TOKEN", "--format", "json"],
        environment,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    payload = json.loads(first.stdout)
    assert payload["sessions"][0]["session_id"] == session["id"]
    assert payload["sessions"][0]["title"] == "CLI PG session"
    assert environment["CLI_TOKEN"] not in first.stdout + first.stderr

    # 第二个全新 CLI 进程应能重新取得执行权；若第一个进程未关闭 PG runtime，
    # executor_state/advisory lock 会挡住这里。
    second = _invoke(["session", "show", session["id"], "--auth-token-env", "CLI_TOKEN"], environment)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "CLI PG session" in second.stdout
    assert environment["CLI_TOKEN"] not in second.stdout + second.stderr


async def test_default_session_cli_rejects_revoked_token(pg_dsn: str, tmp_path: Path) -> None:
    """CLI 每次命令都必须按 PG 当前世代认证，不能信任缓存主体。"""

    environment, _session = await _prepare_default_cli_environment(pg_dsn, tmp_path)
    from deeptutor.persistence.postgres.connection import Database
    from deeptutor.persistence.postgres.identity.service import IdentityService

    async with Database(environment["DEEPTUTOR_DATABASE_URL"], resource="default-cli-revoke") as db:
        identity = IdentityService(
            db,
            tenant_id=json.loads(Path(environment["DEEPTUTOR_POSTGRES_CONFIG"]).read_text())[
                "tenant_id"
            ],
            signing_key="s" * 48,
            auth_epoch="epoch-default-cli",
            bootstrap_secret=None,
        )
        actor = await identity.authenticate(environment["CLI_TOKEN"])
        await identity.revoke_sessions(environment["CLI_TOKEN"], actor.user_id)

    result = _invoke(["session", "list", "--auth-token-env", "CLI_TOKEN"], environment)

    assert result.returncode != 0
    assert environment["CLI_TOKEN"] not in result.stdout + result.stderr
    assert "CLI authentication failed" in result.stderr


async def test_remote_session_cli_uses_existing_executor_without_client_database_secret(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已有服务持有执行权时，CLI 必须走受控远程控制而不是启动第二 writer。"""

    environment, session = await _prepare_default_cli_environment(pg_dsn, tmp_path)
    _install_environment(monkeypatch, environment)

    from deeptutor.api.routers import auth, sessions
    from deeptutor.app.container import ApplicationContainer, set_application_container

    container = ApplicationContainer.build()
    await container.start()
    set_application_container(container)
    api = FastAPI()
    api.state.application_container = container
    api.state.auth_provider = container.auth_provider
    api.include_router(
        sessions.router,
        prefix="/api/sessions",
        dependencies=[Depends(auth.require_learning_surface)],
    )

    import asyncio
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(api, log_level="error", lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.01)
        direct = await asyncio.to_thread(
            _invoke, ["session", "list", "--auth-token-env", "CLI_TOKEN"], environment
        )
        assert direct.returncode != 0
        assert "executor is already active" in direct.stderr

        client_environment = {
            key: value
            for key, value in environment.items()
            if key
            not in {
                "DEEPTUTOR_POSTGRES_CONFIG",
                "DEEPTUTOR_DATABASE_URL",
                "TEST_SIGNING_SECRET",
                "TEST_AUTH_EPOCH_SECRET",
                "TEST_BOOTSTRAP_SECRET",
            }
        }
        remote = await asyncio.to_thread(
            _invoke,
            [
                "session",
                "list",
                "--server",
                f"http://127.0.0.1:{listener.getsockname()[1]}",
                "--allow-loopback-http",
                "--auth-token-env",
                "CLI_TOKEN",
                "--format",
                "json",
            ],
            client_environment,
        )
        assert remote.returncode == 0, remote.stdout + remote.stderr
        payload = json.loads(remote.stdout)
        assert payload["sessions"][0]["session_id"] == session["id"]
        assert environment["CLI_TOKEN"] not in remote.stdout + remote.stderr
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        listener.close()
        set_application_container(None)
        await container.close()
