from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

pytest.importorskip("mistune")
pytest.importorskip("nh3")
pytest.importorskip("nio")

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import matrix as matrix_module
from deeptutor.partners.channels.matrix import MatrixChannel

pytestmark = pytest.mark.asyncio


class _FakeRoom:
    room_id = "!room:example.org"
    display_name = "Test Room"
    member_count = 2
    encrypted = False


class _FakeTextEvent:
    sender = "@alice:example.org"
    body = "hello from matrix"
    event_id = "$event-1"
    source = {"content": {"body": body, "msgtype": "m.text"}}


class _BaseFakeClient:
    instances: list["_BaseFakeClient"] = []

    def __init__(self, homeserver: str, user: str, store_path: str, config: Any):
        self.homeserver = homeserver
        self.user_id = user
        self.device_id = ""
        self.access_token = ""
        self.store_path = store_path
        self.config = config
        self.store = None
        self.loaded_sync_token = None
        self.event_callbacks: list[tuple[Any, Any]] = []
        self.response_callbacks: list[tuple[Any, Any]] = []
        self.stop_requested = False
        self.closed = False
        self.load_store_thread_id: int | None = None
        self.sync_thread_id: int | None = None
        self.sync_started = threading.Event()
        self.cursor_saved = threading.Event()
        self.sync_calls = 0
        type(self).instances.append(self)

    def add_event_callback(self, callback, event_type) -> None:
        self.event_callbacks.append((callback, event_type))

    def add_response_callback(self, callback, response_type) -> None:
        self.response_callbacks.append((callback, response_type))

    def load_store(self) -> None:
        from nio.crypto import OlmAccount

        self.load_store_thread_id = threading.get_ident()
        self.store = self.config.store(
            self.user_id,
            self.device_id,
            self.store_path,
            self.config.pickle_key,
            self.config.store_name,
        )
        self.store.save_account(OlmAccount())
        self.loaded_sync_token = self.store.load_sync_token()

    def stop_sync_forever(self) -> None:
        self.stop_requested = True

    async def close(self) -> None:
        self.closed = True

    async def room_typing(self, **_kwargs):
        return object()


class _BlockingFakeClient(_BaseFakeClient):
    async def sync_forever(self, *, timeout: int, full_state: bool) -> None:
        self.sync_calls += 1
        self.sync_thread_id = threading.get_ident()
        self.sync_started.set()
        for callback, event_type in self.event_callbacks:
            if event_type is matrix_module.RoomMessageText:
                await callback(_FakeRoom(), _FakeTextEvent())
        self.store.save_sync_token("cursor-after-callback")
        self.cursor_saved.set()
        while not self.stop_requested:
            await asyncio.sleep(0.01)


class _FailingFakeClient(_BaseFakeClient):
    failed = threading.Event()

    async def sync_forever(self, *, timeout: int, full_state: bool) -> None:
        self.sync_calls += 1
        self.sync_thread_id = threading.get_ident()
        self.sync_started.set()
        type(self).failed.set()
        raise RuntimeError("simulated PG store failure")


def _matrix_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "homeserver": "https://matrix.invalid",
        "access_token": "syt_test",
        "user_id": "@bot:example.org",
        "device_id": "DEVICE-A",
        "allow_from": ["@alice:example.org"],
        "store_pickle_secret": "matrix-pickle-secret-000000000000000001",
        "store_encryption_secret": "matrix-store-envelope-secret-000000000001",
        "store_secret_id": "matrix-store:test",
        "store_secret_version": 7,
    }


def _install_pg_container(monkeypatch, database, actor):
    class _Config:
        tenant_id = actor.tenant_id

    class _Runtime:
        config = _Config()
        sync_db = database

    class _Container:
        worker_id = "matrix-test-worker"
        postgres_runtime = _Runtime()

    monkeypatch.setattr("deeptutor.app.container.get_application_container", lambda: _Container())


def _channel(actor) -> MatrixChannel:
    channel = MatrixChannel(_matrix_config(), MessageBus())
    channel.partner_id = "ada"
    channel.owner_id = actor.user_id
    return channel


async def test_matrix_channel_uses_pg_store_on_dedicated_worker_and_cursor_after_handoff(
    monkeypatch, business_sync_database, business_actors
):
    actor = business_actors.tenants[0].owners[0]
    _install_pg_container(monkeypatch, business_sync_database, actor)
    monkeypatch.setattr(matrix_module, "AsyncClient", _BlockingFakeClient)
    _BlockingFakeClient.instances.clear()
    main_thread = threading.get_ident()
    channel = _channel(actor)

    await asyncio.wait_for(channel.start(), timeout=1)
    client = _BlockingFakeClient.instances[-1]
    assert client.config.encryption_enabled is True
    assert client.config.store_sync_tokens is True
    assert client.load_store_thread_id != main_thread
    assert await asyncio.to_thread(client.sync_started.wait, 1)
    assert client.sync_thread_id != main_thread
    assert await asyncio.to_thread(client.cursor_saved.wait, 2)

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1)
    assert inbound.content == "hello from matrix"
    assert inbound.metadata["event_id"] == "$event-1"
    assert client.store.load_sync_token() == "cursor-after-callback"
    assert not hasattr(client.store, "database_path")

    await channel.stop()
    assert client.closed is True
    assert channel._matrix_worker is None


async def test_matrix_channel_stops_sync_on_pg_store_failure_without_retry(
    monkeypatch, business_sync_database, business_actors
):
    actor = business_actors.tenants[0].owners[0]
    _install_pg_container(monkeypatch, business_sync_database, actor)
    monkeypatch.setattr(matrix_module, "AsyncClient", _FailingFakeClient)
    _FailingFakeClient.instances.clear()
    _FailingFakeClient.failed.clear()
    channel = _channel(actor)

    await channel.start()
    client = _FailingFakeClient.instances[-1]
    assert await asyncio.to_thread(client.sync_started.wait, 1)
    assert await asyncio.to_thread(_FailingFakeClient.failed.wait, 1)
    await asyncio.sleep(0.1)

    assert client.sync_calls == 1
    assert channel.is_running is False
    assert channel.setup_state["status"] == "error"
    assert "RuntimeError" in channel.setup_state["message"]

    await channel.stop()
