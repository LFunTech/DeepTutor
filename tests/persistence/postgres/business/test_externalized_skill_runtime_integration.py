"""Runtime entry points must use externalized skill/persona providers when PG/ObjectStore is bound."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.asyncio


class RecordingObjectStore:
    def __init__(self) -> None:
        self.config = SimpleNamespace(bucket="runtime-skill-bucket")
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, key, data, *, expected_sha256=None, content_type="application/octet-stream"):
        import hashlib

        from deeptutor.runtime.externalized_providers import ObjectBlobRef

        digest = hashlib.sha256(data).hexdigest()
        assert expected_sha256 == digest
        self.objects[key] = bytes(data)
        return ObjectBlobRef(key=key, size_bytes=len(data), sha256=digest, content_type=content_type)

    def get_bytes(self, ref):
        return self.objects[ref.key]

    def delete(self, ref) -> None:
        self.objects.pop(ref.key, None)


async def test_runtime_skill_service_and_read_skill_tool_use_pg_objectstore_provider(
    pg_session_store_factory, business_actors
):
    """若 read_skill 仍读取本地 data/user/workspace/skills，本测试应失败。"""

    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.services.skill.externalized import ExternalizedSkillService
    from deeptutor.services.skill.runtime import get_runtime_skill_service
    from deeptutor.tools.builtin import ReadSkillTool

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    service = ExternalizedSkillService(store, object_store, builtin_root=None)
    await service.create("pod-safe", "Pod safe", "Externalized body")

    with provider_context(ApplicationProviders(store=store, object_store=object_store)):
        runtime_service = get_runtime_skill_service(builtin_root=None)
        assert isinstance(runtime_service, ExternalizedSkillService)
        result = await ReadSkillTool().execute(name="pod-safe")

    assert result.success is True
    assert "Externalized body" in result.content


async def test_runtime_persona_service_uses_pg_objectstore_provider(
    pg_session_store_factory, business_actors
):
    """若 turn persona context 仍读取本地 data/user/workspace/personas，本测试应失败。"""

    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.services.persona.externalized import ExternalizedPersonaService
    from deeptutor.services.persona.runtime import get_runtime_persona_service

    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    object_store = RecordingObjectStore()
    service = ExternalizedPersonaService(store, object_store)
    await service.create("mentor", "Mentor", "Externalized voice")

    with provider_context(ApplicationProviders(store=store, object_store=object_store)):
        runtime_service = get_runtime_persona_service()
        assert isinstance(runtime_service, ExternalizedPersonaService)
        context = await runtime_service.load_for_context("mentor")

    assert "Externalized voice" in context
