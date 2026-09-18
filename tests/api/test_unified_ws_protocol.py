from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth, unified_ws


class _Turns:
    def __init__(self) -> None:
        self.cancelled: list[tuple[str, str]] = []
        self.subscriptions: list[tuple[str, int]] = []

    async def cancel_turn(self, turn_id: str, *, command_id: str) -> bool:
        self.cancelled.append((turn_id, command_id))
        return True

    async def check_active_turn(self, _session_id: str) -> dict[str, str]:
        return {"turn_id": "turn-1", "status": "recovering", "owner_id": "worker-b"}

    async def subscribe_turn(self, turn_id: str, after_seq: int = 0):
        self.subscriptions.append((turn_id, after_seq))
        yield {"type": "done", "turn_id": turn_id, "seq": after_seq + 1, "timestamp": 1.0}


@pytest.fixture
def protocol_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _Turns]:
    turns = _Turns()

    async def allow(_ws):
        return None

    monkeypatch.setattr(auth, "ws_require_auth", allow)
    app = FastAPI()
    app.state.application_container = SimpleNamespace(turns=turns)
    app.include_router(unified_ws.router)
    return TestClient(app), turns


def test_ws_rejects_missing_and_future_protocol_versions(protocol_client) -> None:
    client, _turns = protocol_client
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "ping"})
        missing = socket.receive_json()
        socket.send_json({"type": "ping", "protocol_version": "3.0"})
        future = socket.receive_json()

    for frame in (missing, future):
        assert frame == {
            "type": "protocol_error",
            "error_code": "unsupported_protocol_version",
            "message": "Unsupported or missing protocol_version; expected 2.0.",
            "retryable": False,
            "session_id": "",
            "turn_id": "",
            "protocol_version": "2.0",
        }


def test_ws_versions_heartbeats_active_state_and_command_ack(protocol_client) -> None:
    client, turns = protocol_client
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "ping", "protocol_version": "2.0"})
        assert socket.receive_json() == {"type": "pong", "protocol_version": "2.0"}

        socket.send_json(
            {
                "type": "check_active_turn",
                "session_id": "session-1",
                "protocol_version": "2.0",
            }
        )
        assert socket.receive_json() == {
            "type": "active_turn_info",
            "turn_id": "turn-1",
            "status": "recovering",
            "owner_id": "worker-b",
            "protocol_version": "2.0",
        }

        socket.send_json(
            {
                "type": "cancel_turn",
                "turn_id": "turn-1",
                "command_id": "cancel-1",
                "protocol_version": "2.0",
            }
        )
        assert socket.receive_json() == {
            "type": "command_ack",
            "command_id": "cancel-1",
            "command_type": "cancel_turn",
            "accepted": True,
            "turn_id": "turn-1",
            "error_code": "",
            "message": "",
            "protocol_version": "2.0",
        }

    assert turns.cancelled == [("turn-1", "cancel-1")]


def test_ws_echoes_token_carrier_subprotocol_for_browser_handshake(protocol_client) -> None:
    """浏览器提供子协议时，服务端必须回选一个子协议，否则 Chrome 会判定握手失败。"""

    client, _turns = protocol_client
    with client.websocket_connect(
        "/ws",
        subprotocols=["deeptutor-token", "header.payload.signature"],
    ) as socket:
        assert socket.accepted_subprotocol == "deeptutor-token"
        socket.send_json({"type": "ping", "protocol_version": "2.0"})
        assert socket.receive_json() == {"type": "pong", "protocol_version": "2.0"}


def test_ws_requires_command_ids_for_retryable_mutations(protocol_client) -> None:
    client, turns = protocol_client
    with client.websocket_connect("/ws") as socket:
        socket.send_json(
            {
                "type": "cancel_turn",
                "turn_id": "turn-1",
                "protocol_version": "2.0",
            }
        )
        frame = socket.receive_json()

    assert frame["type"] == "protocol_error"
    assert frame["error_code"] == "invalid_command"
    assert frame["protocol_version"] == "2.0"
    assert turns.cancelled == []


def test_ws_auth_refresh_command_uses_auth_provider_without_old_revalidate() -> None:
    """防止短期 token 过期后，客户端无法先 refresh 再继续 WS 命令。"""

    class RefreshingAuthProvider:
        def __init__(self) -> None:
            self.token = "old-token"
            self.revalidated: list[str] = []
            self.refreshed: list[str] = []

        async def authenticate(self, ws):
            ws.state.auth_token = self.token
            return None

        async def revalidate(self, ws):
            token = getattr(ws.state, "auth_token", "")
            if token == "old-token":
                raise PermissionError("expired")
            self.revalidated.append(token)

        async def refresh(self, ws, payload):
            self.refreshed.append(payload["dt_token"])
            ws.state.auth_token = payload["dt_token"]
            return {"expires_at": 123, "refresh_deadline": 120}

        @staticmethod
        def error_message(error):
            return str(error)

    auth_provider = RefreshingAuthProvider()
    app = FastAPI()
    app.state.auth_provider = auth_provider
    app.state.application_container = SimpleNamespace(turns=_Turns())
    app.include_router(unified_ws.router)

    with TestClient(app).websocket_connect("/ws") as socket:
        socket.send_json(
            {
                "type": "auth_refresh",
                "command_id": "refresh-1",
                "dt_token": "new-token",
                "protocol_version": "2.0",
            }
        )
        assert socket.receive_json() == {
            "type": "auth_ack",
            "command_id": "refresh-1",
            "accepted": True,
            "expires_at": 123,
            "refresh_deadline": 120,
            "protocol_version": "2.0",
        }
        socket.send_json({"type": "ping", "protocol_version": "2.0"})
        assert socket.receive_json() == {"type": "pong", "protocol_version": "2.0"}

    assert auth_provider.refreshed == ["new-token"]
    assert auth_provider.revalidated == ["new-token", "new-token", "new-token"]


def test_ws_reconnect_resume_from_uses_new_authenticated_connection(protocol_client) -> None:
    client, turns = protocol_client
    with client.websocket_connect("/ws") as socket:
        socket.send_json(
            {
                "type": "resume_from",
                "turn_id": "turn-resume",
                "seq": 7,
                "protocol_version": "2.0",
            }
        )
        assert socket.receive_json() == {
            "type": "done",
            "turn_id": "turn-resume",
            "seq": 8,
            "timestamp": 1.0,
            "protocol_version": "2.0",
        }

    assert turns.subscriptions == [("turn-resume", 7)]


def test_ws_rejects_new_command_after_auth_expires() -> None:
    class ExpiringAuthProvider:
        async def authenticate(self, _ws):
            return None

        async def revalidate(self, _ws):
            raise PermissionError("expired")

    app = FastAPI()
    app.state.auth_provider = ExpiringAuthProvider()
    app.state.application_container = SimpleNamespace(turns=_Turns())
    app.include_router(unified_ws.router)

    with pytest.raises(Exception):
        with TestClient(app).websocket_connect("/ws") as socket:
            socket.send_json({"type": "ping", "protocol_version": "2.0"})
            socket.receive_json()


def test_ws_duplicate_auth_refresh_is_idempotent() -> None:
    class IdempotentAuthProvider:
        async def authenticate(self, ws):
            ws.state.auth_token = "old"
            return None

        async def revalidate(self, ws):
            if getattr(ws.state, "auth_token", "") != "new-token":
                raise PermissionError("expired")

        async def refresh(self, ws, payload):
            ws.state.auth_token = payload["dt_token"]
            return {"expires_at": 200, "refresh_deadline": 190}

    app = FastAPI()
    app.state.auth_provider = IdempotentAuthProvider()
    app.state.application_container = SimpleNamespace(turns=_Turns())
    app.include_router(unified_ws.router)

    with TestClient(app).websocket_connect("/ws") as socket:
        for command_id in ("refresh-1", "refresh-2"):
            socket.send_json(
                {
                    "type": "auth_refresh",
                    "command_id": command_id,
                    "dt_token": "new-token",
                    "protocol_version": "2.0",
                }
            )
            frame = socket.receive_json()
            assert frame["type"] == "auth_ack"
            assert frame["accepted"] is True
            assert frame["command_id"] == command_id
            assert frame["expires_at"] == 200


def test_ws_revoked_connection_closes_on_next_command() -> None:
    class RevokedAuthProvider:
        async def authenticate(self, _ws):
            return None

        async def revalidate(self, _ws):
            raise PermissionError("revoked")

    app = FastAPI()
    app.state.auth_provider = RevokedAuthProvider()
    app.state.application_container = SimpleNamespace(turns=_Turns())
    app.include_router(unified_ws.router)

    with pytest.raises(Exception):
        with TestClient(app).websocket_connect("/ws") as socket:
            socket.send_json({"type": "ping", "protocol_version": "2.0"})
            socket.receive_json()
