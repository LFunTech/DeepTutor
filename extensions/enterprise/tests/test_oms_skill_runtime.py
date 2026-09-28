"""OMS global Skill 在学校运行时的授权装配；仅隔离合成 PG/ObjectStore。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.stores.postgres.connection import Database
import pytest
from test_oms_skill_store import (
    MemoryObjectStore,
    _actor,
    _reviewer,
    _school_operator,
    _zip,
)

from deeptutor.persistence.postgres.session import PostgresSessionStore
from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


async def test_enterprise_runtime_mounts_granted_global_skill_and_school_shadow_wins(pg_dsn):
    """防止：OMS 授权的 global Skill 已发布授权，但学校运行时 manifest/read/always 仍不可见。"""

    from deeptutor_enterprise.oms.runtime_skills import enterprise_skill_service_factory
    from deeptutor_enterprise.oms.skill_store import (
        grant_global_skill,
        publish_global_skill,
        review_global_skill,
        upload_global_skill,
    )
    from deeptutor_enterprise.scope import TenantScope

    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.services.skill.runtime import call_skill_service, get_runtime_skill_service

    await MigrationRunner(pg_dsn).apply()
    school_id = uuid4()
    user_id = uuid4()
    uploader, reviewer = await _actor(pg_dsn), await _reviewer(pg_dsn)
    operator = await _school_operator(pg_dsn, school_id)
    db = Database(single_database_user_dsn(pg_dsn), resource="skill-runtime-test")
    enterprise = type("EnterpriseStub", (), {})()
    enterprise.db = db
    enterprise.object_store = MemoryObjectStore()
    enterprise.object_store.config = SimpleNamespace(bucket="skill-runtime-bucket")
    await db.__aenter__()
    try:
        async with db.transaction(TenantScope(str(school_id), "@seed-runtime-user")) as c:
            await c.execute(
                "INSERT INTO enterprise.users(tenant_id,id,username,role) "
                "VALUES(%s,%s,'runtime-user','user')",
                (school_id, user_id),
            )
        store = PostgresSessionStore(db, TenantScope(str(school_id), str(user_id)))
        providers = ApplicationProviders(
            store=store,
            object_store=enterprise.object_store,
            skill_service_factory=enterprise_skill_service_factory(enterprise),
        )
        with provider_context(providers):
            service = get_runtime_skill_service()
            before = await call_skill_service(service, "summary_entries")
            visible_before = {entry.name for entry in before}
            assert "socratic" not in visible_before
            assert "skill-creator" not in visible_before
            assert await call_skill_service(service, "load_for_context", ["skill-creator"]) == ""
            from deeptutor.services.skill.service import SkillReadOnlyError

            with pytest.raises(SkillReadOnlyError):
                await call_skill_service(
                    service, "create", "skill-creator", "伪装 builtin", "不得覆盖打包 Skill"
                )

        draft = await upload_global_skill(
            enterprise,
            uploader,
            _zip(),
            expected_version=0,
            reason="上传运行时可用 Skill",
            request_id="runtime-upload-1",
        )
        await review_global_skill(
            enterprise,
            reviewer,
            draft.revision_id,
            expected_sha256=draft.sha256,
            approved=True,
            reason="运行时授权审查通过",
            request_id="runtime-review-1",
        )
        await publish_global_skill(
            enterprise,
            uploader,
            draft.revision_id,
            expected_version=0,
            reason="运行时发布",
            request_id="runtime-publish-1",
        )
        await grant_global_skill(
            enterprise,
            operator,
            school_id,
            "socratic",
            expected_grant_version=0,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            reason="授权学校运行首个 Agent",
            request_id="runtime-grant-1",
        )

        with provider_context(providers):
            service = get_runtime_skill_service()
            entries = await call_skill_service(service, "summary_entries")
            entry = next(item for item in entries if item.name == "socratic")
            assert entry.description == "引导式提问"
            assert entry.always is True
            assert entry.available is True
            assert entry.missing == []
            assert "只提问题" in await call_skill_service(
                service, "read_skill_file", "socratic", "SKILL.md"
            )
            assert "# 示例" in await call_skill_service(
                service, "read_skill_file", "socratic", "references/example.md"
            )
            always = await call_skill_service(service, "load_always_for_context")
            assert "### Skill: socratic" in always
            assert "只提问题" in always

            await call_skill_service(
                service,
                "create",
                "socratic",
                "本校覆盖",
                "本校策略优先，不加载平台 global 内容。",
                tags=["style"],
            )
            detail = await call_skill_service(service, "get_detail", "socratic")
            assert detail.source == "user"
            assert "本校策略优先" in detail.content
            shadowed_always = await call_skill_service(service, "load_always_for_context")
            assert "只提问题" not in shadowed_always
    finally:
        await db.__aexit__(None, None, None)
