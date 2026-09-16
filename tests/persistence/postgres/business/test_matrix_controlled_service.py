from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any
import uuid

import httpx
import pytest

pytest.importorskip("mistune")
pytest.importorskip("nh3")
pytest.importorskip("nio")
pytest.importorskip("vodozemac")

from nio import (  # noqa: E402
    AsyncClient,
    AsyncClientConfig,
    InviteEvent,
    JoinResponse,
    LoginResponse,
    MatrixRoom,
    RoomCreateResponse,
    RoomMessageText,
    RoomSendResponse,
)
from nio.crypto import TrustState  # noqa: E402

from deeptutor.partners.bus.events import OutboundMessage  # noqa: E402
from deeptutor.partners.bus.queue import MessageBus  # noqa: E402
from deeptutor.partners.channels.matrix import MatrixChannel  # noqa: E402
from deeptutor.persistence.postgres.matrix import (  # noqa: E402
    MatrixPostgresStoreConfig,
    postgres_matrix_store_factory,
)

pytestmark = pytest.mark.asyncio

IMAGE = os.environ.get("DT_MATRIX_SYNAPSE_IMAGE", "ghcr.io/element-hq/synapse:v1.160.0")


def _require_enabled() -> None:
    if os.environ.get("DT_MATRIX_CONTROLLED_SERVICE") != "1":
        pytest.skip("set DT_MATRIX_CONTROLLED_SERVICE=1 to run controlled Synapse smoke")
    if not shutil.which("docker"):
        pytest.skip("docker is required for controlled Synapse smoke")
    images = subprocess.run(
        ["docker", "image", "inspect", IMAGE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if images.returncode != 0:
        pytest.skip(f"Synapse image {IMAGE!r} is not present locally")


class _Synapse:
    def __init__(self, root: Path, name: str, base_url: str) -> None:
        self.root = root
        self.name = name
        self.base_url = base_url

    def register(self, username: str, password: str, *, admin: bool = False) -> None:
        args = [
            "docker",
            "exec",
            self.name,
            "register_new_matrix_user",
            "-c",
            "/data/homeserver.yaml",
            "-u",
            username,
            "-p",
            password,
            "--admin" if admin else "--no-admin",
            "http://127.0.0.1:8008",
        ]
        subprocess.run(args, check=True, capture_output=True, text=True)

    def stop(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], check=False, capture_output=True)
        shutil.rmtree(self.root, ignore_errors=True)


def _start_synapse() -> _Synapse:
    root = Path(tempfile.mkdtemp(prefix="dt-matrix-synapse-"))
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            "SYNAPSE_SERVER_NAME=localhost",
            "-e",
            "SYNAPSE_REPORT_STATS=no",
            "-v",
            f"{root}:/data",
            IMAGE,
            "generate",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    name = f"dt-matrix-{uuid.uuid4().hex[:12]}"
    subprocess.run(
        ["docker", "run", "-d", "--name", name, "-p", "0:8008", "-v", f"{root}:/data", IMAGE],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        port = ""
        for _ in range(90):
            port = subprocess.check_output(
                ["docker", "port", name, "8008/tcp"], text=True
            ).strip().rsplit(":", 1)[-1]
            if port:
                url = f"http://127.0.0.1:{port}"
                try:
                    with httpx.Client(timeout=1.0) as client:
                        response = client.get(f"{url}/_matrix/client/versions")
                    if response.status_code == 200:
                        return _Synapse(root, name, url)
                except httpx.HTTPError:
                    pass
            subprocess.run(["sleep", "1"], check=True)
        raise RuntimeError("Synapse did not become ready")
    except BaseException:
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
        shutil.rmtree(root, ignore_errors=True)
        raise


def _store_factory(database, actor, *, partner_id: str, secret_suffix: str):
    return postgres_matrix_store_factory(
        MatrixPostgresStoreConfig(
            database=database,
            scope=actor.scope,
            partner_id=partner_id,
            encryption_secret=f"matrix-e2e-envelope-secret-{secret_suffix:0>16}",
            secret_id=f"matrix-controlled:{partner_id}",
            secret_version=1,
        )
    )


async def _login_pg_client(
    homeserver: str,
    user: str,
    password: str,
    *,
    device_id: str,
    store_factory,
    pickle_secret: str,
) -> AsyncClient:
    client = AsyncClient(
        homeserver,
        user=user,
        device_id=device_id,
        store_path="postgresql-matrix-store",
        config=AsyncClientConfig(
            store=store_factory,
            encryption_enabled=True,
            store_sync_tokens=True,
            pickle_key=pickle_secret,
        ),
    )
    response = await client.login(password, device_name=device_id)
    assert isinstance(response, LoginResponse), response
    client.load_store()
    assert not hasattr(client.store, "database_path")
    upload = await client.keys_upload()
    assert "Error" not in type(upload).__name__, upload
    return client


async def _sync_until(client: AsyncClient, predicate, *, timeout: float = 15.0):
    deadline = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < deadline:
        last = await client.sync(timeout=1000, full_state=True)
        if predicate(last):
            return last
    raise AssertionError(f"condition not reached; last sync={last!r}")


async def _join_invited(client: AsyncClient, room_id: str) -> None:
    async def _maybe_join(sync):
        room = client.invited_rooms.get(room_id)
        if room is not None:
            response = await client.join(room_id)
            assert isinstance(response, JoinResponse), response
            return True
        return room_id in client.rooms

    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        if await _maybe_join(await client.sync(timeout=1000, full_state=True)):
            return
    raise AssertionError("invite was not joined")


async def _keys_query_if_required(client: AsyncClient) -> None:
    try:
        response = await client.keys_query()
    except Exception as exc:  # nio raises LocalProtocolError when nothing is pending.
        if "No key query required" not in str(exc):
            raise
        return
    assert "Error" not in type(response).__name__, response


def _sync_texts(sync: Any, room_id: str) -> list[str]:
    joined = getattr(getattr(sync, "rooms", None), "join", {}) or {}
    room = joined.get(room_id)
    timeline = getattr(room, "timeline", None)
    events = getattr(timeline, "events", []) if timeline is not None else []
    return [
        event.body
        for event in events
        if isinstance(event, RoomMessageText) and isinstance(getattr(event, "body", None), str)
    ]


async def test_matrix_pg_store_against_controlled_synapse_plain_and_e2ee(
    monkeypatch, business_sync_database, business_actors
):
    _require_enabled()
    synapse = _start_synapse()
    bot_user = "@bot:localhost"
    alice_user = "@alice:localhost"
    clients: list[AsyncClient] = []
    channels: list[MatrixChannel] = []
    try:
        synapse.register("bot", "botpass", admin=True)
        synapse.register("alice", "alicepass", admin=False)
        bot_actor = business_actors.tenants[0].owners[0]
        alice_actor = business_actors.tenants[0].owners[1]

        bot_client = await _login_pg_client(
            synapse.base_url,
            bot_user,
            "botpass",
            device_id="BOTPLAIN",
            store_factory=_store_factory(
                business_sync_database, bot_actor, partner_id="matrix-bot-plain", secret_suffix="1"
            ),
            pickle_secret="matrix-plain-bot-pickle-secret-0000000001",
        )
        clients.append(bot_client)
        alice_client = await _login_pg_client(
            synapse.base_url,
            alice_user,
            "alicepass",
            device_id="ALICEPLAIN",
            store_factory=_store_factory(
                business_sync_database,
                alice_actor,
                partner_id="matrix-alice-plain",
                secret_suffix="2",
            ),
            pickle_secret="matrix-plain-alice-pickle-secret-0000001",
        )
        clients.append(alice_client)

        class _Config:
            tenant_id = bot_actor.tenant_id

        class _Runtime:
            config = _Config()
            sync_db = business_sync_database

        class _Container:
            worker_id = "matrix-controlled-worker"
            postgres_runtime = _Runtime()

        monkeypatch.setattr(
            "deeptutor.app.container.get_application_container", lambda: _Container()
        )
        bus = MessageBus()
        channel = MatrixChannel(
            {
                "enabled": True,
                "homeserver": synapse.base_url,
                "access_token": bot_client.access_token,
                "user_id": bot_user,
                "device_id": "BOTPLAIN",
                "allow_from": [alice_user],
                "store_pickle_secret": "matrix-plain-bot-pickle-secret-0000000001",
                "store_encryption_secret": "matrix-e2e-envelope-secret-0000000000000001",
                "store_secret_id": "matrix-controlled:matrix-bot-plain",
            },
            bus,
        )
        channel.partner_id = "matrix-bot-plain"
        channel.owner_id = bot_actor.user_id
        await channel.start()
        channels.append(channel)
        assert not hasattr(channel.client.store, "database_path")

        plain_room = await alice_client.room_create(invite=[bot_user], is_direct=True)
        assert isinstance(plain_room, RoomCreateResponse), plain_room
        await _sync_until(alice_client, lambda _sync: plain_room.room_id in alice_client.rooms)
        sent = await alice_client.room_send(
            plain_room.room_id,
            "m.room.message",
            {"msgtype": "m.text", "body": "plain-one"},
        )
        assert isinstance(sent, RoomSendResponse), sent
        inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=20)
        assert inbound.content == "plain-one"
        assert channel.client.store.load_sync_token()

        await channel.stop()
        channels.remove(channel)
        # Restart with the same PG Matrix store.  The old message must not replay.
        restarted_bus = MessageBus()
        restarted = MatrixChannel(channel.config, restarted_bus)
        restarted.partner_id = channel.partner_id
        restarted.owner_id = channel.owner_id
        await restarted.start()
        channels.append(restarted)
        assert not hasattr(restarted.client.store, "database_path")
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(restarted_bus.consume_inbound(), timeout=2)
        sent = await alice_client.room_send(
            plain_room.room_id,
            "m.room.message",
            {"msgtype": "m.text", "body": "plain-two"},
        )
        assert isinstance(sent, RoomSendResponse), sent
        inbound = await asyncio.wait_for(restarted_bus.consume_inbound(), timeout=20)
        assert inbound.content == "plain-two"
        await restarted.send(
            OutboundMessage(
                channel="matrix",
                chat_id=plain_room.room_id,
                content="bot-plain-reply",
            )
        )
        await _sync_until(
            alice_client,
            lambda sync: "bot-plain-reply" in _sync_texts(sync, plain_room.room_id),
            timeout=20,
        )
        await restarted.stop()
        channels.remove(restarted)

        # E2EE path with both clients using DeepTutor PG Matrix stores.
        bot_e2e = await _login_pg_client(
            synapse.base_url,
            bot_user,
            "botpass",
            device_id="BOTE2E",
            store_factory=_store_factory(
                business_sync_database, bot_actor, partner_id="matrix-bot-e2e", secret_suffix="3"
            ),
            pickle_secret="matrix-e2e-bot-pickle-secret-00000000001",
        )
        clients.append(bot_e2e)
        alice_e2e = await _login_pg_client(
            synapse.base_url,
            alice_user,
            "alicepass",
            device_id="ALICEE2E",
            store_factory=_store_factory(
                business_sync_database,
                alice_actor,
                partner_id="matrix-alice-e2e",
                secret_suffix="4",
            ),
            pickle_secret="matrix-e2e-alice-pickle-secret-0000001",
        )
        clients.append(alice_e2e)

        encrypted_room = await bot_e2e.room_create(
            invite=[alice_user],
            is_direct=True,
            initial_state=[
                {
                    "type": "m.room.encryption",
                    "state_key": "",
                    "content": {"algorithm": "m.megolm.v1.aes-sha2"},
                }
            ],
        )
        assert isinstance(encrypted_room, RoomCreateResponse), encrypted_room
        await _join_invited(alice_e2e, encrypted_room.room_id)
        await _sync_until(bot_e2e, lambda _sync: encrypted_room.room_id in bot_e2e.rooms)
        await _keys_query_if_required(bot_e2e)
        await _keys_query_if_required(alice_e2e)

        for _user_id, devices in bot_e2e.device_store.items():
            for device in devices.values():
                bot_e2e.store.verify_device(device)
        alice_device = bot_e2e.device_store[alice_user]["ALICEE2E"]
        assert bot_e2e.store.load_device_keys()[alice_user]["ALICEE2E"].trust_state is (
            TrustState.verified
        )

        encrypted_send = await bot_e2e.room_send(
            encrypted_room.room_id,
            "m.room.message",
            {"msgtype": "m.text", "body": "encrypted-one"},
            ignore_unverified_devices=False,
        )
        assert isinstance(encrypted_send, RoomSendResponse), encrypted_send
        await _sync_until(
            alice_e2e,
            lambda sync: "encrypted-one" in _sync_texts(sync, encrypted_room.room_id),
            timeout=25,
        )
        await _keys_query_if_required(alice_e2e)
        for _user_id, devices in alice_e2e.device_store.items():
            for device in devices.values():
                alice_e2e.store.verify_device(device)
        encrypted_reply = await alice_e2e.room_send(
            encrypted_room.room_id,
            "m.room.message",
            {"msgtype": "m.text", "body": "encrypted-two"},
            ignore_unverified_devices=False,
        )
        assert isinstance(encrypted_reply, RoomSendResponse), encrypted_reply
        await _sync_until(
            bot_e2e,
            lambda sync: "encrypted-two" in _sync_texts(sync, encrypted_room.room_id),
            timeout=25,
        )

        alice_e2e_token = alice_e2e.access_token
        await alice_e2e.close()
        clients.remove(alice_e2e)
        alice_restart = AsyncClient(
            synapse.base_url,
            user=alice_user,
            device_id="ALICEE2E",
            store_path="postgresql-matrix-store",
            config=AsyncClientConfig(
                store=_store_factory(
                    business_sync_database,
                    alice_actor,
                    partner_id="matrix-alice-e2e",
                    secret_suffix="4",
                ),
                encryption_enabled=True,
                store_sync_tokens=True,
                pickle_key="matrix-e2e-alice-pickle-secret-0000001",
            ),
        )
        clients.append(alice_restart)
        alice_restart.user_id = alice_user
        alice_restart.device_id = "ALICEE2E"
        alice_restart.access_token = alice_e2e_token
        alice_restart.load_store()
        messages = await alice_restart.room_messages(encrypted_room.room_id, limit=10)
        assert "Error" not in type(messages).__name__, messages
        assert any(
            isinstance(event, RoomMessageText) and event.body == "encrypted-one"
            for event in getattr(messages, "chunk", [])
        )

    finally:
        for channel in list(channels):
            with suppress(Exception):
                await channel.stop()
        for client in list(clients):
            with suppress(Exception):
                await client.close()
        synapse.stop()
