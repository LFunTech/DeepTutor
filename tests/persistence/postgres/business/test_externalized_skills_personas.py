"""Externalized dynamic skills/personas must not use Pod-local data as authority."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.asyncio


class RecordingObjectStore:
    def __init__(self) -> None:
        self.config = SimpleNamespace(bucket="skill-persona-bucket")
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.gets: list[str] = []

    def put_bytes(self, key, data, *, expected_sha256=None, content_type="application/octet-stream"):
        import hashlib

        from deeptutor.runtime.externalized_providers import ObjectBlobRef

        digest = hashlib.sha256(data).hexdigest()
        assert expected_sha256 == digest
        self.puts.append(key)
        self.objects[key] = bytes(data)
        return ObjectBlobRef(key=key, size_bytes=len(data), sha256=digest, content_type=content_type)

    def get_bytes(self, ref):
        self.gets.append(ref.key)
        return self.objects[ref.key]

    def delete(self, ref) -> None:
        self.objects.pop(ref.key, None)


async def test_externalized_skill_package_survives_pod_rebuild_without_local_workspace(
    pg_session_store_factory, business_actors, tmp_path
):
    """若用户/导入 skill 仍以 data/user/workspace/skills 为权威，本测试应失败。"""

    from deeptutor.services.skill.externalized import ExternalizedSkillService
    from deeptutor.services.skill.service import SkillNotFoundError

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    service = ExternalizedSkillService(pg_session_store_factory(actor), object_store, builtin_root=None)

    source = tmp_path / "downloaded-skill"
    (source / "references").mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: Socratic Skill\ndescription: Ask good questions\ntags: [teaching]\nalways: true\n---\n\nAsk one question at a time.\n",
        encoding="utf-8",
    )
    (source / "references" / "guide.md").write_text("reference body", encoding="utf-8")

    installed = await service.install_tree(
        source,
        rename_to="socratic-skill",
        origin={"hub": "eduhub", "slug": "socratic-skill", "version": "1.0.0"},
        extra_tags=["eduhub"],
    )

    assert installed.info.to_dict() == {
        "name": "socratic-skill",
        "description": "Ask good questions",
        "tags": ["teaching", "eduhub"],
        "source": "user",
        "read_only": False,
    }
    assert "Ask one question" in await service.read_skill_file("socratic-skill")
    assert await service.read_skill_file("socratic-skill", "references/guide.md") == "reference body"
    assert await service.get_hub_origin("socratic-skill") == {
        "hub": "eduhub",
        "slug": "socratic-skill",
        "version": "1.0.0",
    }
    assert not (tmp_path / "data" / "user" / "workspace" / "skills").exists()

    rebuilt = ExternalizedSkillService(pg_session_store_factory(actor), object_store, builtin_root=None)
    assert await rebuilt.read_skill_file("socratic-skill", "references/guide.md") == "reference body"
    manifest = await rebuilt.summary_entries()
    assert [(entry.name, entry.always, entry.available) for entry in manifest] == [
        ("socratic-skill", False, True)
    ]
    assert "### Skill: socratic-skill" not in await rebuilt.load_always_for_context()

    foreign = ExternalizedSkillService(
        pg_session_store_factory(business_actors.tenants[1].admin), object_store, builtin_root=None
    )
    with pytest.raises(SkillNotFoundError):
        await foreign.read_skill_file("socratic-skill")


async def test_externalized_persona_survives_pod_rebuild_without_local_workspace(
    pg_session_store_factory, business_actors, tmp_path
):
    """若动态 persona 仍以 data/user/workspace/personas 为权威，本测试应失败。"""

    from deeptutor.services.persona.externalized import ExternalizedPersonaService
    from deeptutor.services.persona.service import PersonaNotFoundError

    actor = business_actors.tenants[0].admin
    object_store = RecordingObjectStore()
    service = ExternalizedPersonaService(pg_session_store_factory(actor), object_store)

    info = await service.create("mentor", "Warm mentor", "Use a supportive voice.")

    assert info.to_dict() == {
        "name": "mentor",
        "description": "Warm mentor",
        "source": "user",
        "read_only": False,
    }
    assert "Use a supportive voice" in await service.load_for_context("mentor")
    assert not (tmp_path / "data" / "user" / "workspace" / "personas").exists()

    rebuilt = ExternalizedPersonaService(pg_session_store_factory(actor), object_store)
    assert "### Persona: mentor" in await rebuilt.load_for_context("mentor")

    foreign = ExternalizedPersonaService(
        pg_session_store_factory(business_actors.tenants[1].admin), object_store
    )
    with pytest.raises(PersonaNotFoundError):
        await foreign.get_detail("mentor")
