"""Turn/SDK 入口对 ObjectStore-backed 聊天附件的真实上传契约。"""

from __future__ import annotations

import base64
import json
import os
from types import SimpleNamespace

import pytest

from deeptutor.core.providers import ApplicationProviders, provider_context
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.multi_user.context import (
    reset_current_user,
    set_current_user,
    user_from_token_payload,
)
from deeptutor.runtime.externalized_providers import ObjectStoreError
from deeptutor.services.session.turn_runtime import TurnRuntimeManager

pytestmark = pytest.mark.asyncio


async def _noop_async(*_args, **_kwargs):
    return None


class FailingObjectStore:
    def __init__(self) -> None:
        self.config = SimpleNamespace(bucket="turn-bucket")
        self.puts: list[str] = []

    def put_bytes(self, key, data, *, expected_sha256=None, content_type="application/octet-stream"):
        del data, expected_sha256, content_type
        self.puts.append(key)
        raise ObjectStoreError("objectstore_unavailable", retryable=True)


class FakeContextBuilder:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def build(self, **_kwargs):
        return SimpleNamespace(
            conversation_history=[],
            conversation_summary="",
            context_text="",
            token_count=0,
            budget=0,
        )


class FakeOrchestrator:
    async def handle(self, _context):
        yield StreamEvent(
            type=StreamEventType.CONTENT,
            source="chat",
            stage="responding",
            content="should not be reached after upload failure",
            metadata={"call_kind": "llm_final_response"},
        )
        yield StreamEvent(type=StreamEventType.DONE, source="chat")


def _patch_turn_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_l3_concat=lambda: "", emit=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "deeptutor.services.skill.get_skill_service",
        lambda: SimpleNamespace(
            summary_entries=lambda: [],
            load_always_for_context=lambda: "",
            load_for_context=lambda _skills: "",
            list_skills=lambda: [],
        ),
    )
    monkeypatch.setattr(
        "deeptutor.services.persona.get_persona_service",
        lambda: SimpleNamespace(load_for_context=lambda _name: ""),
    )
    monkeypatch.setattr(
        "deeptutor.services.workspace.get_content_workspace_service",
        lambda: SimpleNamespace(
            create_runtime_context=lambda **_kwargs: SimpleNamespace(
                workspace_id="test-workspace",
                root=None,
                output_dir=None,
            )
        ),
    )


async def test_turn_upload_failure_in_objectstore_attachment_store_fails_turn_without_llm(
    pg_session_store_factory, business_actors, monkeypatch: pytest.MonkeyPatch
) -> None:
    """若 ObjectStore-backed 上传失败被吞掉并继续跑 LLM，本测试应失败。"""

    _patch_turn_dependencies(monkeypatch)
    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = FailingObjectStore()
    runtime = TurnRuntimeManager(store=store)
    token = set_current_user(user_from_token_payload(actor.identity))
    try:
        with provider_context(ApplicationProviders(store=store, object_store=object_store)):
            session, turn = await runtime.start_turn(
                {
                    "type": "start_turn",
                    "content": "please read the file",
                    "session_id": None,
                    "capability": "chat",
                    "tools": [],
                    "knowledge_bases": [],
                    "attachments": [
                        {
                            "type": "file",
                            "filename": "a.txt",
                            "mime_type": "text/plain",
                            "base64": base64.b64encode(b"actual bytes").decode(),
                        }
                    ],
                    "language": "en",
                    "config": {},
                }
            )
            events = [event async for event in runtime.subscribe_turn(turn["id"], after_seq=0)]
    finally:
        reset_current_user(token)
        await runtime.close()

    assert object_store.puts, "turn should attempt the ObjectStore upload"
    terminal_errors = [str(event.get("content") or "") for event in events if event["type"] == "error"]
    assert terminal_errors
    assert "objectstore_unavailable" in terminal_errors[-1]
    assert events[-1]["type"] == "done"
    assert events[-1]["metadata"]["status"] == "failed"
    assert "should not be reached" not in "\n".join(str(event.get("content") or "") for event in events)
    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    assert detail["messages"] == []


class RecordingObjectStore:
    def __init__(self) -> None:
        self.config = SimpleNamespace(bucket="turn-bucket")
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []

    def put_bytes(self, key, data, *, expected_sha256=None, content_type="application/octet-stream"):
        import hashlib

        from deeptutor.runtime.externalized_providers import ObjectBlobRef

        digest = hashlib.sha256(data).hexdigest()
        assert expected_sha256 == digest
        self.puts.append(key)
        self.objects[key] = bytes(data)
        return ObjectBlobRef(
            key=key,
            size_bytes=len(data),
            sha256=digest,
            content_type=content_type,
        )

    def get_bytes(self, ref):
        return self.objects[ref.key]

    def delete(self, ref) -> None:
        self.objects.pop(ref.key, None)


async def test_turn_upload_success_persists_objectstore_url_and_reads_via_pg_metadata(
    pg_session_store_factory, business_actors, monkeypatch: pytest.MonkeyPatch
) -> None:
    """若真实 turn 上传绕过 ObjectStore/PG metadata 或只保存 base64，本测试应失败。"""

    _patch_turn_dependencies(monkeypatch)
    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    runtime = TurnRuntimeManager(store=store)
    token = set_current_user(user_from_token_payload(actor.identity))
    try:
        with provider_context(ApplicationProviders(store=store, object_store=object_store)):
            session, turn = await runtime.start_turn(
                {
                    "type": "start_turn",
                    "content": "please read the file",
                    "session_id": None,
                    "capability": "chat",
                    "tools": [],
                    "knowledge_bases": [],
                    "attachments": [
                        {
                            "type": "file",
                            "filename": "a.txt",
                            "mime_type": "text/plain",
                            "base64": base64.b64encode(b"actual bytes").decode(),
                        }
                    ],
                    "language": "en",
                    "config": {},
                }
            )
            events = [event async for event in runtime.subscribe_turn(turn["id"], after_seq=0)]
    finally:
        reset_current_user(token)
        await runtime.close()

    assert events[-1]["type"] == "done"
    assert events[-1]["metadata"]["status"] == "completed"
    assert len(object_store.puts) == 1
    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    user_message = next(message for message in detail["messages"] if message["role"] == "user")
    attachment = user_message["attachments"][0]
    assert attachment["base64"] == ""
    assert attachment["url"].startswith(f"/files/attachments/{session['id']}/")

    from deeptutor.persistence.postgres.session_resources import PostgresObjectAttachmentStore

    object_id = attachment["url"].split("/")[-2]
    rebuilt_store = pg_session_store_factory(actor)
    assert (
        await PostgresObjectAttachmentStore(rebuilt_store, object_store).read_attachment(
            session_id=session["id"], attachment_id=object_id, filename="a.txt"
        )
        == b"actual bytes"
    )


class _StoreProvider:
    def __init__(self, store) -> None:
        self._store = store

    def get(self):
        return self._store


class _RuntimeRegistry:
    def __init__(self, runtime) -> None:
        self._runtime = runtime

    def get(self, _store):
        return self._runtime


async def test_sdk_start_turn_uses_container_objectstore_for_attachment_upload(
    pg_session_store_factory, business_actors, monkeypatch: pytest.MonkeyPatch
) -> None:
    """若 SDK operation_context 未传播 ObjectStore provider，附件会回落本地或失败。"""

    _patch_turn_dependencies(monkeypatch)
    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    runtime = TurnRuntimeManager(store=store)

    from deeptutor.app import DeepTutorApp
    from deeptutor.app.service import TurnApplicationService
    from deeptutor.runtime.coordination import MemoryCoordinator

    coordinator = MemoryCoordinator()
    store_provider = _StoreProvider(store)
    container = SimpleNamespace()
    container.capability_registry = SimpleNamespace(
        get_manifests=lambda: [{"name": "chat", "cli_aliases": []}]
    )
    container.providers = ApplicationProviders(
        store=store,
        container=container,
        object_store=object_store,
    )
    container.turns = TurnApplicationService(store_provider, _RuntimeRegistry(runtime), coordinator)
    container.start = lambda: _noop_async()
    container.close = lambda: _noop_async()

    token = set_current_user(user_from_token_payload(actor.identity))
    app = DeepTutorApp(container=container)
    try:
        session, turn = await app.start_turn(
            {
                "content": "please read the file",
                "session_id": None,
                "capability": "chat",
                "tools": [],
                "knowledge_bases": [],
                "attachments": [
                    {
                        "type": "file",
                        "filename": "sdk.txt",
                        "mime_type": "text/plain",
                        "base64": base64.b64encode(b"sdk bytes").decode(),
                    }
                ],
                "language": "en",
                "config": {},
            }
        )
        events = [event async for event in app.stream_turn(turn["id"], after_seq=0)]
    finally:
        reset_current_user(token)
        await app.close()

    assert events[-1]["metadata"]["status"] == "completed"
    assert len(object_store.puts) == 1
    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    user_message = next(message for message in detail["messages"] if message["role"] == "user")
    attachment = user_message["attachments"][0]
    assert attachment["url"].startswith(f"/files/attachments/{session['id']}/")
    object_id = attachment["url"].split("/")[-2]
    from deeptutor.persistence.postgres.session_resources import PostgresObjectAttachmentStore

    rebuilt_store = pg_session_store_factory(actor)
    assert (
        await PostgresObjectAttachmentStore(rebuilt_store, object_store).read_attachment(
            session_id=session["id"], attachment_id=object_id, filename="sdk.txt"
        )
        == b"sdk bytes"
    )


async def test_ws_start_turn_uploads_attachment_through_container_objectstore(
    pg_session_store_factory, business_actors, monkeypatch: pytest.MonkeyPatch
) -> None:
    """若真实 `/ws` start_turn 没有把附件上传接入容器 ObjectStore，本测试应失败。"""

    import asyncio

    from fastapi import WebSocketDisconnect

    from deeptutor.api.contracts.turn_protocol import PROTOCOL_VERSION
    from deeptutor.api.routers import unified_ws
    from deeptutor.app.service import TurnApplicationService
    from deeptutor.runtime.coordination import MemoryCoordinator

    _patch_turn_dependencies(monkeypatch)
    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    runtime = TurnRuntimeManager(store=store)

    coordinator = MemoryCoordinator()
    store_provider = _StoreProvider(store)
    container = SimpleNamespace()
    container.providers = ApplicationProviders(
        store=store,
        container=container,
        object_store=object_store,
    )
    container.turns = TurnApplicationService(store_provider, _RuntimeRegistry(runtime), coordinator)

    class FakeAuthProvider:
        async def authenticate(self, _ws):
            return set_current_user(user_from_token_payload(actor.identity))

        async def revalidate(self, _ws):
            return None

        @staticmethod
        def error_message(error):
            return str(error)

    class FakeWebSocket:
        def __init__(self) -> None:
            self.app = SimpleNamespace(
                state=SimpleNamespace(
                    auth_provider=FakeAuthProvider(),
                    application_container=container,
                )
            )
            self.sent: list[dict] = []
            self._sent_start = False
            self._done = asyncio.Event()

        async def accept(self) -> None:
            return None

        async def receive_text(self) -> str:
            if not self._sent_start:
                self._sent_start = True
                return json.dumps(
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        "type": "start_turn",
                        "content": "please read the websocket file",
                        "session_id": None,
                        "capability": "chat",
                        "tools": [],
                        "knowledge_bases": [],
                        "attachments": [
                            {
                                "type": "file",
                                "filename": "ws.txt",
                                "mime_type": "text/plain",
                                "base64": base64.b64encode(b"ws bytes").decode(),
                            }
                        ],
                        "language": "en",
                        "config": {},
                    }
                )
            await asyncio.wait_for(self._done.wait(), timeout=3)
            raise WebSocketDisconnect()

        async def send_text(self, value: str) -> None:
            payload = json.loads(value)
            self.sent.append(payload)
            if payload.get("type") == "done":
                self._done.set()

        async def close(self, *args, **kwargs) -> None:
            return None

    ws = FakeWebSocket()
    try:
        await unified_ws.unified_websocket(ws)
    finally:
        await runtime.close()

    done = next(event for event in ws.sent if event["type"] == "done")
    assert done["metadata"]["status"] == "completed"
    assert len(object_store.puts) == 1
    session_id = done["session_id"]
    detail = await store.get_session_with_messages(session_id)
    assert detail is not None
    user_message = next(message for message in detail["messages"] if message["role"] == "user")
    attachment = user_message["attachments"][0]
    assert attachment["base64"] == ""
    assert attachment["url"].startswith(f"/files/attachments/{session_id}/")

    from deeptutor.persistence.postgres.session_resources import PostgresObjectAttachmentStore

    object_id = attachment["url"].split("/")[-2]
    rebuilt_store = pg_session_store_factory(actor)
    assert (
        await PostgresObjectAttachmentStore(rebuilt_store, object_store).read_attachment(
            session_id=session_id, attachment_id=object_id, filename="ws.txt"
        )
        == b"ws bytes"
    )


@pytest.mark.integration
async def test_turn_attachment_round_trips_against_s3_compatible_endpoint(
    pg_session_store_factory, business_actors, monkeypatch: pytest.MonkeyPatch
) -> None:
    """若真实 S3-compatible provider 无法承载聊天附件，本测试应失败。"""

    if os.environ.get("DEEPTUTOR_RUN_S3_COMPATIBLE_TESTS") != "1":
        pytest.skip("set DEEPTUTOR_RUN_S3_COMPATIBLE_TESTS=1 to run S3-compatible smoke")
    if not os.environ.get("DEEPTUTOR_TEST_S3_ACCESS_KEY") or not os.environ.get(
        "DEEPTUTOR_TEST_S3_SECRET_KEY"
    ):
        pytest.skip("S3-compatible smoke credential references are not configured")

    from deeptutor.persistence.postgres.session_resources import PostgresObjectAttachmentStore
    from deeptutor.runtime.externalized_providers import (
        EnvSecretResolver,
        S3CompatibleObjectStore,
        S3ObjectStoreConfig,
    )

    _patch_turn_dependencies(monkeypatch)
    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = S3CompatibleObjectStore(
        S3ObjectStoreConfig.from_environment(
            {
                "DEEPTUTOR_OBJECTSTORE_ENDPOINT": os.environ.get(
                    "DEEPTUTOR_TEST_S3_ENDPOINT", "http://127.0.0.1:9000"
                ),
                "DEEPTUTOR_OBJECTSTORE_REGION": os.environ.get(
                    "DEEPTUTOR_TEST_S3_REGION", "us-east-1"
                ),
                "DEEPTUTOR_OBJECTSTORE_BUCKET": os.environ.get(
                    "DEEPTUTOR_TEST_S3_BUCKET", "local-debug"
                ),
                "DEEPTUTOR_OBJECTSTORE_ACCESS_KEY_REF": "env:DEEPTUTOR_TEST_S3_ACCESS_KEY",
                "DEEPTUTOR_OBJECTSTORE_SECRET_KEY_REF": "env:DEEPTUTOR_TEST_S3_SECRET_KEY",
                "DEEPTUTOR_OBJECTSTORE_PATH_STYLE": os.environ.get(
                    "DEEPTUTOR_TEST_S3_PATH_STYLE", "true"
                ),
                "DEEPTUTOR_OBJECTSTORE_TIMEOUT_SECONDS": "3.0",
                "DEEPTUTOR_OBJECTSTORE_MAX_RETRIES": "1",
            }
        ),
        secret_resolver=EnvSecretResolver(),
    )
    assert object_store.check_bucket().available is True

    runtime = TurnRuntimeManager(store=store)
    attachment_store = PostgresObjectAttachmentStore(store, object_store)
    token = set_current_user(user_from_token_payload(actor.identity))
    session_id = ""
    user_message_id: int | None = None
    object_id = ""
    try:
        with provider_context(ApplicationProviders(store=store, object_store=object_store)):
            session, turn = await runtime.start_turn(
                {
                    "type": "start_turn",
                    "content": "please read the real object store file",
                    "session_id": None,
                    "capability": "chat",
                    "tools": [],
                    "knowledge_bases": [],
                    "attachments": [
                        {
                            "type": "file",
                            "filename": "s3.txt",
                            "mime_type": "text/plain",
                            "base64": base64.b64encode(b"s3-compatible bytes").decode(),
                        }
                    ],
                    "language": "en",
                    "config": {},
                }
            )
            session_id = session["id"]
            events = [event async for event in runtime.subscribe_turn(turn["id"], after_seq=0)]
        assert events[-1]["metadata"]["status"] == "completed"

        detail = await store.get_session_with_messages(session_id)
        assert detail is not None
        user_message = next(message for message in detail["messages"] if message["role"] == "user")
        user_message_id = int(user_message["id"])
        attachment = user_message["attachments"][0]
        object_id = attachment["url"].split("/")[-2]
        assert (
            await attachment_store.read_attachment(
                session_id=session_id, attachment_id=object_id, filename="s3.txt"
            )
            == b"s3-compatible bytes"
        )
    finally:
        reset_current_user(token)
        if user_message_id is not None:
            await store.delete_message(user_message_id)
            await attachment_store.cleanup_pending()
        elif object_id:
            await attachment_store.withdraw_operation(object_id)
        await runtime.close()
