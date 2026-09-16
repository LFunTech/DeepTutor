from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.core.providers import ApplicationProviders, get_providers


@pytest.mark.asyncio
async def test_http_provider_context_binds_application_container_providers() -> None:
    from deeptutor.api import main as api_main

    providers = ApplicationProviders(reading=object(), resources=object())
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                application_container=SimpleNamespace(providers=providers),
            )
        )
    )

    async def call_next(received):
        assert received is request
        assert get_providers() is providers
        return "response"

    assert get_providers() is None
    assert await api_main.application_provider_context(request, call_next) == "response"
    assert get_providers() is None

@pytest.mark.asyncio
async def test_unified_ws_binds_application_objectstore_provider_during_start_turn() -> None:
    import json

    from fastapi import WebSocketDisconnect

    from deeptutor.api.routers import unified_ws

    object_store = object()
    seen: dict[str, object] = {}

    class FakeAuthProvider:
        async def authenticate(self, _ws):
            return None

        async def revalidate(self, _ws):
            return None

        @staticmethod
        def error_message(error):
            return str(error)

    class FakeTurns:
        async def start_turn(self, payload):
            assert payload["content"] == "hello"
            seen["object_store"] = get_providers().object_store
            return {"id": "s"}, {"id": "t"}

        async def subscribe_turn(self, _turn_id, after_seq=0):
            if False:
                yield {"type": "done", "metadata": {"status": "completed"}}

    class FakeWebSocket:
        def __init__(self) -> None:
            self.app = SimpleNamespace(
                state=SimpleNamespace(
                    auth_provider=FakeAuthProvider(),
                    application_container=SimpleNamespace(
                        providers=ApplicationProviders(object_store=object_store),
                        turns=FakeTurns(),
                    ),
                )
            )
            self._messages = [
                json.dumps(
                    {
                        "protocol_version": unified_ws.PROTOCOL_VERSION,
                        "type": "start_turn",
                        "content": "hello",
                        "capability": "chat",
                        "tools": [],
                        "knowledge_bases": [],
                        "attachments": [],
                        "language": "en",
                        "config": {},
                    }
                )
            ]
            self.sent: list[str] = []

        async def accept(self) -> None:
            return None

        async def receive_text(self) -> str:
            if self._messages:
                return self._messages.pop(0)
            raise WebSocketDisconnect()

        async def send_text(self, value: str) -> None:
            self.sent.append(value)

        async def close(self, *args, **kwargs) -> None:
            return None

    await unified_ws.unified_websocket(FakeWebSocket())

    assert seen["object_store"] is object_store
    assert get_providers() is None
