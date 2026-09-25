# ruff: noqa: F811
"""默认 Python SDK 的 PostgreSQL-only 身份与生命周期契约。"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import types
import uuid

import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn, single_database_user_dsn  # noqa: F401


def _reset_runtime_singletons(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(home))
    for name in (
        "DEEPTUTOR_POSTGRES_CONFIG",
        "DEEPTUTOR_DATABASE_URL",
        "DEEPTUTOR_MIGRATION_DATABASE_URL",
        "TEST_SIGNING_SECRET",
        "TEST_AUTH_EPOCH_SECRET",
        "TEST_BOOTSTRAP_SECRET",
        "SDK_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    from deeptutor.app.container import set_application_container
    from deeptutor.runtime.launcher import _reset_runtime_singletons as reset_runtime_paths

    set_application_container(None)
    reset_runtime_paths()


def _write_postgres_config(path: Path, tenant_id: str, *, resource: str = "default-sdk") -> Path:
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


async def _prepare_default_sdk_environment(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, dict, str]:
    """建立隔离 PG schema、默认 SDK 配置和一条已提交会话。"""

    _reset_runtime_singletons(monkeypatch, tmp_path / "home")
    tenant_id = str(uuid.uuid4())
    config = _write_postgres_config(tmp_path / "postgres.json", tenant_id)
    runtime_dsn = single_database_user_dsn(pg_dsn)
    monkeypatch.setenv("DEEPTUTOR_POSTGRES_CONFIG", str(config))
    monkeypatch.setenv("DEEPTUTOR_DATABASE_URL", runtime_dsn)
    monkeypatch.setenv("TEST_SIGNING_SECRET", "s" * 48)
    monkeypatch.setenv("TEST_AUTH_EPOCH_SECRET", "epoch-default-sdk")
    monkeypatch.setenv("TEST_BOOTSTRAP_SECRET", "b" * 48)

    from deeptutor.persistence.postgres.connection import Database
    from deeptutor.persistence.postgres.identity.service import IdentityService
    from deeptutor.persistence.postgres.migrations.runner import MigrationRunner
    from deeptutor.persistence.postgres.scope import TenantScope
    from deeptutor.persistence.postgres.session import PostgresSessionStore

    await MigrationRunner(runtime_dsn).apply()
    async with Database(runtime_dsn, resource="default-sdk-bootstrap") as db:
        identity = IdentityService(
            db,
            tenant_id=tenant_id,
            signing_key="s" * 48,
            auth_epoch="epoch-default-sdk",
            bootstrap_secret="b" * 48,
        )
        await identity.bootstrap("admin", "administrator-123", secret="b" * 48)
        token = await identity.login("admin", "administrator-123", client="sdk-test")
        actor = await identity.authenticate(token)
        store = PostgresSessionStore(db, TenantScope(tenant_id, actor.user_id))
        session = await store.create_session(title="SDK PG session")
    return token, session, runtime_dsn


@pytest.mark.asyncio
async def test_sdk_token_env_reads_same_pg_sessions_and_revalidates_revocation(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """若 SDK 不用 PG auth token 或不重验撤权，会读不到同一会话或继续放行。"""

    token, session, _runtime_dsn = await _prepare_default_sdk_environment(
        pg_dsn, tmp_path, monkeypatch
    )
    monkeypatch.setenv("SDK_TOKEN", token)

    from deeptutor.app import DeepTutorApp
    from deeptutor.multi_user.context import get_current_user_or_none

    async with DeepTutorApp(auth_token_env="SDK_TOKEN") as app:
        sessions = await app.list_sessions()
        assert [item["session_id"] for item in sessions] == [session["id"]]
        assert get_current_user_or_none() is None

        provider = app.container.auth_provider
        actor = await provider.identity.authenticate(token)
        await provider.identity.revoke_sessions(token, actor.user_id)
        with pytest.raises(PermissionError):
            await app.list_sessions()

    assert get_current_user_or_none() is None


@pytest.mark.asyncio
async def test_sdk_default_pg_business_requires_identity_without_sqlite_fallback(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认 SDK 有 PG 配置但无可信主体时必须拒绝，而不是回落本地 SQLite。"""

    _token, _session, _runtime_dsn = await _prepare_default_sdk_environment(
        pg_dsn, tmp_path, monkeypatch
    )

    from deeptutor.app import DeepTutorApp

    app = DeepTutorApp()
    try:
        with pytest.raises(PermissionError):
            await app.list_sessions()
    finally:
        await app.close()

    assert not list((tmp_path / "home").rglob("*.sqlite*"))
    assert not list((tmp_path / "home").rglob("*.db"))


@pytest.mark.asyncio
async def test_sdk_operation_context_binds_default_pg_resource_provider(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """租户身份解析模型访问时必须能绑定 owner 资源目录。"""

    token, _session, _runtime_dsn = await _prepare_default_sdk_environment(
        pg_dsn, tmp_path, monkeypatch
    )
    monkeypatch.setenv("SDK_TOKEN", token)

    from deeptutor.app import DeepTutorApp
    from deeptutor.multi_user.model_access import redacted_model_access

    async with DeepTutorApp(auth_token_env="SDK_TOKEN") as app:
        async with app._operation_context():
            assert redacted_model_access() == {"llm": []}


@pytest.mark.asyncio
async def test_sdk_explicit_provider_object_after_context_exit_does_not_fallback(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """provider 上下文退出后的残留 SDK 对象必须拒绝身份，而非构造默认本地容器。"""

    token, session, _runtime_dsn = await _prepare_default_sdk_environment(
        pg_dsn, tmp_path, monkeypatch
    )

    from deeptutor.app import DeepTutorApp
    from deeptutor.app.container import ApplicationContainer
    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )

    container = ApplicationContainer.build()
    app = None
    context_token = None
    try:
        await container.start()
        payload = await container.auth_provider.decode(token)
        with provider_context(
            ApplicationProviders(
                container=container,
                store=container.store_provider,
                auth=container.auth_provider,
                resources=container.resources_provider,
                learning=container.learning_provider,
                reading=container.reading_provider,
            )
        ):
            context_token = set_current_user(user_from_token_payload(payload))
            app = DeepTutorApp()
            sessions = await app.list_sessions()
            assert [item["session_id"] for item in sessions] == [session["id"]]
            reset_current_user(context_token)
            context_token = None

        with pytest.raises(PermissionError):
            await app.list_sessions()
    finally:
        if context_token is not None:
            reset_current_user(context_token)
        if app is not None:
            await app.close()
        else:
            await container.close()


@pytest.mark.asyncio
async def test_sdk_remote_session_methods_use_bearer_without_local_pg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SDK 远程会话 API 只连显式 HTTPS 服务，不需要也不能启动本地 PG runtime。"""

    _reset_runtime_singletons(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("SDK_TOKEN", "token-value")

    import httpx

    import deeptutor.app.container as container_module

    def forbidden_local_container():
        raise AssertionError("remote SDK must not start a local application container")

    monkeypatch.setattr(container_module, "get_application_container", forbidden_local_container)

    captured_clients: list[dict] = []
    calls: list[tuple[str, str, dict | None, dict | None]] = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict) -> None:
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise AssertionError(f"unexpected HTTP error {self.status_code}")

        def json(self) -> dict:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            captured_clients.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            pass

        async def get(self, path: str, *, params: dict | None = None):
            calls.append(("GET", path, params, None))
            if path == "/api/sessions":
                return FakeResponse(
                    200,
                    {
                        "sessions": [
                            {"session_id": "session-remote", "title": "Remote PG session"}
                        ]
                    },
                )
            return FakeResponse(
                200,
                {"session_id": "session-remote", "title": "Remote PG session", "messages": []},
            )

        async def patch(self, path: str, *, json: dict):
            calls.append(("PATCH", path, None, json))
            return FakeResponse(200, {"session": {"session_id": "session-remote"}})

        async def delete(self, path: str):
            calls.append(("DELETE", path, None, None))
            return FakeResponse(200, {"deleted": True, "session_id": "session-remote"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    from deeptutor.app import DeepTutorApp

    async with DeepTutorApp(
        server="https://school.example/",
        auth_token_env="SDK_TOKEN",
    ) as app:
        assert await app.list_sessions(limit=2, offset=1) == [
            {"session_id": "session-remote", "title": "Remote PG session"}
        ]
        assert await app.get_session("session-remote") == {
            "session_id": "session-remote",
            "title": "Remote PG session",
            "messages": [],
        }
        assert await app.rename_session("session-remote", "New title") is True
        assert await app.delete_session("session-remote") is True

    assert captured_clients
    assert all(item["base_url"] == "https://school.example" for item in captured_clients)
    assert all(
        item["headers"] == {"Authorization": "Bearer token-value"} for item in captured_clients
    )
    assert all(item["follow_redirects"] is False for item in captured_clients)
    assert all(item["trust_env"] is False for item in captured_clients)
    assert calls == [
        ("GET", "/api/sessions", {"limit": 2, "offset": 1}, None),
        ("GET", "/api/sessions/session-remote", None, None),
        ("PATCH", "/api/sessions/session-remote", None, {"title": "New title"}),
        ("DELETE", "/api/sessions/session-remote", None, None),
    ]


def test_sdk_remote_rejects_unsafe_origin_before_pg_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """远程 SDK 校验 unsafe origin 时不能先读取本地 PG 配置或泄露 token。"""

    _reset_runtime_singletons(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("SDK_TOKEN", "token-value")

    from deeptutor.app import DeepTutorApp

    with pytest.raises(ValueError) as exc_info:
        DeepTutorApp(server="http://school.example", auth_token_env="SDK_TOKEN")

    message = str(exc_info.value)
    assert "HTTPS required" in message
    assert "token-value" not in message
    assert "postgres" not in message.lower()


@pytest.mark.asyncio
async def test_sdk_remote_turn_stream_and_commands_use_ws_bearer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """远程 SDK 通过 WS 命令复用服务端执行者，并只携带 bearer token。"""

    _reset_runtime_singletons(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("SDK_TOKEN", "token-value")

    class FakeWebSocket:
        def __init__(self, frames: list[dict | object]) -> None:
            self.frames = frames
            self.sent: list[dict] = []

        async def send(self, raw: str) -> None:
            self.sent.append(json.loads(raw))

        def __aiter__(self):
            return self

        async def __anext__(self) -> str:
            if not self.frames:
                raise StopAsyncIteration
            frame = self.frames.pop(0)
            if callable(frame):
                frame = frame(self)
            return json.dumps(frame, ensure_ascii=False)

    def ack(command_type: str):
        return lambda ws: {
            "type": "command_ack",
            "command_id": ws.sent[0]["command_id"],
            "command_type": command_type,
            "accepted": True,
        }

    frames_by_connection: list[list[dict | object]] = [
        [
            {
                "type": "session",
                "metadata": {"session_id": "session-remote", "turn_id": "turn-remote"},
            }
        ],
        [
            {"type": "content", "turn_id": "turn-remote", "content": "hello", "seq": 4},
            {
                "type": "done",
                "session_id": "session-remote",
                "turn_id": "turn-remote",
                "metadata": {"status": "completed"},
            },
        ],
        [ack("submit_user_reply")],
        [ack("cancel_turn")],
        [
            {
                "type": "session",
                "metadata": {"session_id": "session-remote", "turn_id": "turn-regenerated"},
            }
        ],
        [
            {
                "type": "active_turn_info",
                "turn_id": "turn-regenerated",
                "status": "running",
                "owner_id": "user-1",
            }
        ],
    ]
    connections: list[dict] = []

    class FakeConnect:
        def __init__(self, uri: str, **kwargs) -> None:
            self.websocket = FakeWebSocket(frames_by_connection.pop(0))
            connections.append({"uri": uri, "kwargs": kwargs, "websocket": self.websocket})

        async def __aenter__(self):
            return self.websocket

        async def __aexit__(self, exc_type, exc, tb) -> None:
            pass

    websockets_mod = types.ModuleType("websockets")
    legacy_mod = types.ModuleType("websockets.legacy")
    client_mod = types.ModuleType("websockets.legacy.client")
    client_mod.connect = FakeConnect
    legacy_mod.client = client_mod
    websockets_mod.legacy = legacy_mod
    monkeypatch.setitem(sys.modules, "websockets", websockets_mod)
    monkeypatch.setitem(sys.modules, "websockets.legacy", legacy_mod)
    monkeypatch.setitem(sys.modules, "websockets.legacy.client", client_mod)

    from deeptutor.app import DeepTutorApp, TurnRequest

    async with DeepTutorApp(server="https://school.example", auth_token_env="SDK_TOKEN") as app:
        session, turn = await app.start_turn(TurnRequest(content="hello", capability="chat"))
        streamed = [event async for event in app.stream_turn("turn-remote", after_seq=3)]
        assert await app.submit_user_reply("turn-remote", text="ok") is True
        assert await app.cancel_turn("turn-remote") is True
        regenerated_session, regenerated_turn = await app.regenerate_last_turn(
            "session-remote", overrides={"capability": "chat"}
        )
        active = await app.get_active_turn("session-remote")

    assert session == {"id": "session-remote"}
    assert turn == {"id": "turn-remote"}
    assert streamed[-1]["type"] == "done"
    assert regenerated_session == {"id": "session-remote"}
    assert regenerated_turn == {"id": "turn-regenerated"}
    assert active == {
        "turn_id": "turn-regenerated",
        "status": "running",
        "owner_id": "user-1",
    }
    assert all(item["uri"] == "wss://school.example/ws" for item in connections)
    assert all(
        item["kwargs"]["extra_headers"] == {"Authorization": "Bearer token-value"}
        for item in connections
    )
    assert [connection["websocket"].sent[0]["type"] for connection in connections] == [
        "start_turn",
        "subscribe_turn",
        "submit_user_reply",
        "cancel_turn",
        "regenerate",
        "check_active_turn",
    ]
    assert connections[0]["websocket"].sent[0]["content"] == "hello"
    assert connections[1]["websocket"].sent[0]["after_seq"] == 3
    assert connections[2]["websocket"].sent[0]["text"] == "ok"
    assert connections[3]["websocket"].sent[0]["turn_id"] == "turn-remote"
    assert connections[4]["websocket"].sent[0]["overrides"] == {"capability": "chat"}
    assert connections[5]["websocket"].sent[0]["session_id"] == "session-remote"
    assert not frames_by_connection
