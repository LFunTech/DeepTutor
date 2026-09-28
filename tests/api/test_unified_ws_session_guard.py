"""WebSocket turn 入口必须对会话域持久化异常 fail closed。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from deeptutor.api.contracts.turn_protocol import PROTOCOL_VERSION
from deeptutor.api.routers.unified_ws import unified_websocket

pytestmark = pytest.mark.asyncio


class _AuthProvider:
    async def authenticate(self, _ws):
        return None

    async def revalidate(self, _ws) -> None:
        return None

    def error_message(self, error: Exception) -> str:
        return str(error)


class _Turns:
    async def check_active_turn(self, _session_id: str):
        raise RuntimeError("unknown turn status in PostgreSQL")


class _WebSocket:
    headers: dict[str, str] = {}

    def __init__(self) -> None:
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                auth_provider=_AuthProvider(),
                application_container=SimpleNamespace(turns=_Turns(), providers=None),
            )
        )
        self.sent: list[dict] = []
        self.accepted = False
        self._received = False

    async def accept(self, subprotocol=None) -> None:
        self.accepted = True
        self.subprotocol = subprotocol

    async def receive_text(self) -> str:
        if self._received:
            raise WebSocketDisconnect()
        self._received = True
        return json.dumps(
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "check_active_turn",
                "session_id": "polluted-session",
            }
        )

    async def send_text(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def close(self, **_kwargs) -> None:
        self.closed = True


async def test_ws_check_active_turn_reports_protocol_error_on_unknown_persisted_state():
    ws = _WebSocket()

    await unified_websocket(ws)

    assert ws.accepted
    assert ws.sent
    assert ws.sent[-1]["type"] == "protocol_error"
    assert ws.sent[-1]["error_code"] == "internal_error"
    assert "unknown turn status" in ws.sent[-1]["message"]
    assert not any(item["type"] == "active_turn_info" for item in ws.sent)
