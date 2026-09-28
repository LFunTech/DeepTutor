"""global Skill 完整包的不可变持久化；仅隔离合成 PG/ObjectStore。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
import zipfile

from deeptutor_enterprise.management.authorization import ManagementIdentity
from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.stores.postgres.connection import Database
import httpx
import psycopg
import pytest
from test_application import app as app

from deeptutor.runtime.externalized_providers import ObjectBlobRef
from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


def _zip() -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "socratic/SKILL.md",
            "---\nname: socratic\ndescription: 引导式提问\nalways: true\n---\n\n只提问题。\n",
        )
        archive.writestr("socratic/references/example.md", "# 示例\n")
    return out.getvalue()


def _zip_with_code() -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "socratic/SKILL.md",
            "---\nname: socratic\ndescription: 脚本型提问\n---\n\n先提问。\n",
        )
        archive.writestr("socratic/scripts/run.py", "print('synthetic')\n")
    return out.getvalue()


class MemoryObjectStore:
    def __init__(self):
        self.objects = {}

    def put_bytes(self, key, data, *, expected_sha256=None, content_type="application/octet-stream"):
        digest = hashlib.sha256(data).hexdigest()
        assert digest == expected_sha256
        assert key not in self.objects
        self.objects[key] = data
        return ObjectBlobRef(key, len(data), digest, content_type)

    def get_bytes(self, ref):
        return self.objects[ref.key]


async def _actor(pg_dsn):
    principal_id = uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal_id, "https://issuer.example", "skill-admin"),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_config_admin',2,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid4(), principal_id, uuid4()),
        )
        await c.execute(
            "UPDATE management.principals SET policy_version=policy_version+1 WHERE id=%s",
            (principal_id,),
        )
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="oms", issuer="https://issuer.example", subject="skill-admin",
        school_id=None, policy_version=2, school_binding_version=None,
        external_active=True, external_checked_at=now,
        external_verified_until=now + timedelta(seconds=5),
    )


async def _reviewer(pg_dsn):
    principal_id = uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal_id, "https://issuer.example", "skill-reviewer"),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_security_admin',2,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid4(), principal_id, uuid4()),
        )
        await c.execute(
            "UPDATE management.principals SET policy_version=policy_version+1 WHERE id=%s",
            (principal_id,),
        )
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="oms", issuer="https://issuer.example", subject="skill-reviewer",
        school_id=None, policy_version=2, school_binding_version=None,
        external_active=True, external_checked_at=now,
        external_verified_until=now + timedelta(seconds=5),
    )


async def _school_operator(pg_dsn, school_id):
    principal_id = uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants"
            "(id,external_eligibility,auth_epoch,bootstrap_completed,local_enabled,"
            "provisioning_status) VALUES(%s,'allowed','synthetic',true,true,'ready')",
            (school_id,),
        )
        await c.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic','synthetic://school')",
            (school_id,),
        )
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) VALUES(%s,'oms',%s,%s,'active')",
            (principal_id, "https://issuer.example", "skill-operator"),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
            "school_binding_version,valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_operator',2,'school',%s,1,"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
            (uuid4(), principal_id, school_id, uuid4()),
        )
        await c.execute(
            "UPDATE management.principals SET policy_version=policy_version+1 WHERE id=%s",
            (principal_id,),
        )
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="oms", issuer="https://issuer.example", subject="skill-operator",
        school_id=None, policy_version=2, school_binding_version=None,
        external_active=True, external_checked_at=now,
        external_verified_until=now + timedelta(seconds=5),
    )


async def test_global_skill_zip_draft_is_immutable_and_not_published(pg_dsn):
    from deeptutor_enterprise.oms.skill_store import SkillDraftConflict, upload_global_skill

    await MigrationRunner(pg_dsn).apply()
    actor = await _actor(pg_dsn)
    db = Database(single_database_user_dsn(pg_dsn), resource="skill-store-test")
    store = MemoryObjectStore()
    enterprise = SimpleNamespace(db=db, object_store=store)
    payload = _zip()
    await db.__aenter__()
    try:
        result = await upload_global_skill(
            enterprise, actor, payload, expected_version=0,
            reason="首个 Agent Skill", request_id="synthetic-skill-1",
        )
        assert result.name == "socratic"
        assert result.version == 1
        assert result.status == "draft"
        assert store.objects[result.object_key] == payload
        with pytest.raises(SkillDraftConflict):
            await upload_global_skill(
                enterprise, actor, payload, expected_version=0,
                reason="旧版本重试", request_id="synthetic-skill-2",
            )
        assert len(store.objects) == 1
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            row = await (
                await c.execute(
                    "SELECT owner_kind,name,version,content_sha256,metadata "
                    "FROM oms.skill_revisions WHERE id=%s",
                    (result.revision_id,),
                )
            ).fetchone()
            assert row[0:4] == ("global", "socratic", 1, result.sha256)
            assert row[4]["description"] == "引导式提问"
            assert row[4]["always"] is True
            published = await (
                await c.execute("SELECT count(*) FROM oms.skill_publications")
            ).fetchone()
            granted = await (
                await c.execute("SELECT count(*) FROM oms.skill_grants")
            ).fetchone()
            assert published == (0,)
            assert granted == (0,)
    finally:
        await db.__aexit__(None, None, None)


async def test_skill_review_and_publication_fences_are_versioned(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        rows = await (
            await c.execute(
                "SELECT table_name,column_name FROM information_schema.columns "
                "WHERE table_schema='oms' AND "
                "((table_name='skill_reviews' AND column_name='revision_id') OR "
                "(table_name='skill_revisions' AND column_name='created_issuer') OR "
                "(table_name='skill_publications' AND column_name='review_id') OR "
                "(table_name='skill_grants' AND column_name='publication_version')) "
                "ORDER BY table_name,column_name"
            )
        ).fetchall()
    assert rows == [
        ("skill_grants", "publication_version"),
        ("skill_publications", "review_id"),
        ("skill_reviews", "revision_id"),
        ("skill_revisions", "created_issuer"),
    ]


async def test_skill_review_reads_exact_object_and_requires_independent_reviewer(pg_dsn):
    from deeptutor_enterprise.management.authorization import ManagementAuthorizationDenied
    from deeptutor_enterprise.oms.skill_store import (
        review_global_skill,
        upload_global_skill,
    )

    await MigrationRunner(pg_dsn).apply()
    uploader, reviewer = await _actor(pg_dsn), await _reviewer(pg_dsn)
    db = Database(single_database_user_dsn(pg_dsn), resource="skill-review-test")
    store = MemoryObjectStore()
    enterprise = SimpleNamespace(db=db, object_store=store)
    await db.__aenter__()
    try:
        draft = await upload_global_skill(
            enterprise, uploader, _zip(), expected_version=0,
            reason="合成包", request_id="upload-1",
        )
        with pytest.raises(ManagementAuthorizationDenied):
            await review_global_skill(
                enterprise, uploader, draft.revision_id, expected_sha256=draft.sha256,
                approved=True, reason="自审", request_id="review-self",
            )
        exact = store.objects[draft.object_key]
        store.objects[draft.object_key] = b"tampered"
        with pytest.raises(RuntimeError, match="digest|content"):
            await review_global_skill(
                enterprise, reviewer, draft.revision_id, expected_sha256=draft.sha256,
                approved=True, reason="篡改包", request_id="review-tampered",
            )
        store.objects[draft.object_key] = exact
        review = await review_global_skill(
            enterprise, reviewer, draft.revision_id, expected_sha256=draft.sha256,
            approved=True, reason="已核对内容与依赖", request_id="review-ok",
        )
        assert review.approved is True
        assert review.code_file_count == 0
        assert not review.replayed
        replay = await review_global_skill(
            enterprise, reviewer, draft.revision_id, expected_sha256=draft.sha256,
            approved=True, reason="已核对内容与依赖", request_id="review-ok",
        )
        assert replay.review_id == review.review_id and replay.replayed
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            row = await (
                await c.execute(
                    "SELECT approved,content_sha256,code_file_digests FROM oms.skill_reviews "
                    "WHERE id=%s", (review.review_id,)
                )
            ).fetchone()
            assert row == (True, draft.sha256, {})
            assert (
                await (await c.execute("SELECT count(*) FROM oms.skill_publications")).fetchone()
            ) == (0,)
    finally:
        await db.__aexit__(None, None, None)


async def test_skill_creator_cannot_self_review_even_with_review_role(pg_dsn):
    from deeptutor_enterprise.oms.skill_store import (
        SkillReviewConflict,
        review_global_skill,
        upload_global_skill,
    )

    await MigrationRunner(pg_dsn).apply()
    creator = await _actor(pg_dsn)
    db = Database(single_database_user_dsn(pg_dsn), resource="skill-self-review")
    enterprise = SimpleNamespace(db=db, object_store=MemoryObjectStore())
    await db.__aenter__()
    try:
        draft = await upload_global_skill(
            enterprise, creator, _zip(), expected_version=0,
            reason="合成包", request_id="self-upload",
        )
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            principal = await (
                await c.execute(
                    "SELECT id FROM management.principals WHERE subject='skill-admin'"
                )
            ).fetchone()
            await c.execute(
                "INSERT INTO management.assignments"
                "(id,application,principal_id,role_key,role_version,scope_kind,"
                "valid_from,expires_at,command_id,created_by) "
                "VALUES(%s,'oms',%s,'platform_security_admin',2,'platform',"
                "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic-approval')",
                (uuid4(), principal[0], uuid4()),
            )
            await c.execute(
                "UPDATE management.principals SET policy_version=policy_version+1 WHERE id=%s",
                (principal[0],),
            )
        now = datetime.now(timezone.utc)
        dual_role_creator = replace(
            creator, policy_version=3, external_checked_at=now,
            external_verified_until=now + timedelta(seconds=5),
        )
        with pytest.raises(SkillReviewConflict, match="creator cannot"):
            await review_global_skill(
                enterprise, dual_role_creator, draft.revision_id,
                expected_sha256=draft.sha256, approved=True,
                reason="自审", request_id="self-review",
            )
    finally:
        await db.__aexit__(None, None, None)


async def test_skill_code_requires_review_evidence_and_school_scope_cannot_read_reviews(pg_dsn):
    from deeptutor_enterprise.oms.skill_store import (
        SkillReviewConflict,
        review_global_skill,
        upload_global_skill,
    )

    from deeptutor.persistence.postgres.scope import TenantScope

    await MigrationRunner(pg_dsn).apply()
    creator, reviewer = await _actor(pg_dsn), await _reviewer(pg_dsn)
    db = Database(single_database_user_dsn(pg_dsn), resource="skill-code-review")
    enterprise = SimpleNamespace(db=db, object_store=MemoryObjectStore())
    await db.__aenter__()
    try:
        draft = await upload_global_skill(
            enterprise, creator, _zip_with_code(), expected_version=0,
            reason="脚本包", request_id="code-upload",
        )
        with pytest.raises(SkillReviewConflict, match="require independent review evidence"):
            await review_global_skill(
                enterprise, reviewer, draft.revision_id, expected_sha256=draft.sha256,
                approved=True, reason="审核", request_id="code-review-no-evidence",
            )
        reviewed = await review_global_skill(
            enterprise, reviewer, draft.revision_id, expected_sha256=draft.sha256,
            approved=True, reason="已复核脚本", request_id="code-review-ok",
            code_review_evidence="已逐文件复核 scripts/run.py 与摘要，隔离环境未执行",
        )
        assert reviewed.code_file_count == 1
        async with db.transaction(TenantScope(str(uuid4()), "@school-reader")) as c:
            rows = await (
                await c.execute("SELECT id FROM oms.skill_reviews WHERE id=%s", (reviewed.review_id,))
            ).fetchall()
            assert rows == []
    finally:
        await db.__aexit__(None, None, None)


async def test_skill_publication_requires_approved_independent_review_and_cas(pg_dsn):
    from deeptutor_enterprise.oms.skill_store import (
        SkillReviewConflict,
        publish_global_skill,
        review_global_skill,
        upload_global_skill,
    )

    await MigrationRunner(pg_dsn).apply()
    uploader, reviewer = await _actor(pg_dsn), await _reviewer(pg_dsn)
    db = Database(single_database_user_dsn(pg_dsn), resource="skill-publish-test")
    enterprise = SimpleNamespace(db=db, object_store=MemoryObjectStore())
    await db.__aenter__()
    try:
        draft = await upload_global_skill(
            enterprise, uploader, _zip(), expected_version=0,
            reason="草稿", request_id="publish-upload-1",
        )
        with pytest.raises(SkillReviewConflict):
            await publish_global_skill(
                enterprise, uploader, draft.revision_id, expected_version=0,
                reason="无审查", request_id="publish-denied",
            )
        review = await review_global_skill(
            enterprise, reviewer, draft.revision_id, expected_sha256=draft.sha256,
            approved=True, reason="审核通过", request_id="publish-review-1",
        )
        published = await publish_global_skill(
            enterprise, uploader, draft.revision_id, expected_version=0,
            reason="发布测试包", request_id="publish-ok",
        )
        assert published.version == 1
        assert published.review_id == review.review_id
        with pytest.raises(SkillReviewConflict):
            await publish_global_skill(
                enterprise, uploader, draft.revision_id, expected_version=0,
                reason="旧版本", request_id="publish-stale",
            )
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            row = await (
                await c.execute(
                    "SELECT revision_id,version,review_id,published_issuer "
                    "FROM oms.skill_publications WHERE name='socratic'"
                )
            ).fetchone()
            assert row == (draft.revision_id, 1, review.review_id, uploader.issuer)
    finally:
        await db.__aexit__(None, None, None)


async def test_skill_grant_is_fenced_to_exact_publication_version(pg_dsn):
    from deeptutor_enterprise.oms.skill_store import (
        grant_global_skill,
        publish_global_skill,
        resolve_authorized_global_skill,
        review_global_skill,
        revoke_global_skill,
        upload_global_skill,
    )

    await MigrationRunner(pg_dsn).apply()
    school_id = uuid4()
    uploader, reviewer = await _actor(pg_dsn), await _reviewer(pg_dsn)
    operator = await _school_operator(pg_dsn, school_id)
    db = Database(single_database_user_dsn(pg_dsn), resource="skill-grant-test")
    enterprise = SimpleNamespace(db=db, object_store=MemoryObjectStore())
    await db.__aenter__()
    try:
        first = await upload_global_skill(
            enterprise, uploader, _zip(), expected_version=0,
            reason="首版", request_id="grant-upload-1",
        )
        await review_global_skill(
            enterprise, reviewer, first.revision_id, expected_sha256=first.sha256,
            approved=True, reason="首版审核", request_id="grant-review-1",
        )
        await publish_global_skill(
            enterprise, uploader, first.revision_id, expected_version=0,
            reason="首版发布", request_id="grant-publish-1",
        )
        granted = await grant_global_skill(
            enterprise, operator, school_id, "socratic", expected_grant_version=0,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            reason="测试学校授权", request_id="grant-1",
        )
        assert granted.grant_version == 1 and granted.publication_version == 1
        resolved = await resolve_authorized_global_skill(enterprise, school_id, "socratic")
        assert resolved is not None and resolved.revision_id == first.revision_id

        second = await upload_global_skill(
            enterprise, uploader, _zip(), expected_version=1,
            reason="新版", request_id="grant-upload-2",
        )
        await review_global_skill(
            enterprise, reviewer, second.revision_id, expected_sha256=second.sha256,
            approved=True, reason="新版审核", request_id="grant-review-2",
        )
        await publish_global_skill(
            enterprise, uploader, second.revision_id, expected_version=1,
            reason="新版发布", request_id="grant-publish-2",
        )
        assert await resolve_authorized_global_skill(enterprise, school_id, "socratic") is None
        await publish_global_skill(
            enterprise, uploader, first.revision_id, expected_version=2,
            reason="回退首版", request_id="grant-publish-3",
        )
        assert await resolve_authorized_global_skill(enterprise, school_id, "socratic") is None
        renewed = await grant_global_skill(
            enterprise, operator, school_id, "socratic", expected_grant_version=1,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            reason="按回退版本重新授权", request_id="grant-2",
        )
        assert renewed.grant_version == 2 and renewed.publication_version == 3
        assert await resolve_authorized_global_skill(enterprise, school_id, "socratic")
        revoked = await revoke_global_skill(
            enterprise, operator, school_id, "socratic", expected_grant_version=2,
            reason="撤权", request_id="grant-revoke",
        )
        assert revoked.grant_version == 3
        assert await resolve_authorized_global_skill(enterprise, school_id, "socratic") is None
    finally:
        await db.__aexit__(None, None, None)


@pytest.mark.parametrize(
    ("field", "constraint"),
    [
        ("external_eligibility", "tenants_external_eligibility_check"),
        ("provisioning_status", "tenants_provisioning_status_check"),
        ("recovery_state", "tenants_recovery_state_check"),
    ],
)
async def test_skill_resolution_rejects_unknown_school_state_without_db_check(
    pg_dsn, field, constraint
):
    from deeptutor_enterprise.oms.skill_store import resolve_authorized_global_skill

    await MigrationRunner(pg_dsn).apply()
    school_id = uuid4()
    await _school_operator(pg_dsn, school_id)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(f"ALTER TABLE enterprise.tenants DROP CONSTRAINT IF EXISTS {constraint}")
        await c.execute(
            f"UPDATE enterprise.tenants SET {field}='future-value' WHERE id=%s",
            (school_id,),
        )
    db = Database(single_database_user_dsn(pg_dsn), resource="skill-school-state-test")
    enterprise = SimpleNamespace(db=db, object_store=MemoryObjectStore())
    await db.__aenter__()
    try:
        with pytest.raises(ValueError, match=f"tenant {field} has unknown persisted value"):
            await resolve_authorized_global_skill(enterprise, school_id, "socratic")
    finally:
        await db.__aexit__(None, None, None)


async def test_later_rejected_review_invalidates_publication_and_old_school_grant(pg_dsn):
    from deeptutor_enterprise.oms.skill_store import (
        SkillReviewConflict,
        grant_global_skill,
        publish_global_skill,
        resolve_authorized_global_skill,
        review_global_skill,
        upload_global_skill,
    )

    await MigrationRunner(pg_dsn).apply()
    school_id = uuid4()
    uploader, reviewer = await _actor(pg_dsn), await _reviewer(pg_dsn)
    operator = await _school_operator(pg_dsn, school_id)
    db = Database(single_database_user_dsn(pg_dsn), resource="skill-review-fence")
    enterprise = SimpleNamespace(db=db, object_store=MemoryObjectStore())
    await db.__aenter__()
    try:
        draft = await upload_global_skill(
            enterprise, uploader, _zip(), expected_version=0,
            reason="待审查", request_id="fence-upload",
        )
        approved = await review_global_skill(
            enterprise, reviewer, draft.revision_id, expected_sha256=draft.sha256,
            approved=True, reason="首轮通过", request_id="fence-review-approved",
        )
        first = await publish_global_skill(
            enterprise, uploader, draft.revision_id, expected_version=0,
            reason="首轮发布", request_id="fence-publish-first",
        )
        assert first.review_id == approved.review_id
        await grant_global_skill(
            enterprise, operator, school_id, "socratic", expected_grant_version=0,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            reason="首轮授权", request_id="fence-grant-first",
        )
        assert await resolve_authorized_global_skill(enterprise, school_id, "socratic")

        await review_global_skill(
            enterprise, reviewer, draft.revision_id, expected_sha256=draft.sha256,
            approved=False, reason="补充审查否决", request_id="fence-review-rejected",
        )
        assert await resolve_authorized_global_skill(enterprise, school_id, "socratic") is None
        with pytest.raises(SkillReviewConflict):
            await grant_global_skill(
                enterprise, operator, school_id, "socratic", expected_grant_version=1,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                reason="旧发布不得授权", request_id="fence-grant-denied",
            )
        fresh = await review_global_skill(
            enterprise, reviewer, draft.revision_id, expected_sha256=draft.sha256,
            approved=True, reason="复核通过", request_id="fence-review-again",
        )
        assert await resolve_authorized_global_skill(enterprise, school_id, "socratic") is None
        second = await publish_global_skill(
            enterprise, uploader, draft.revision_id, expected_version=1,
            reason="复核后重新发布", request_id="fence-publish-second",
        )
        assert second.version == 2 and second.review_id == fresh.review_id
        assert await resolve_authorized_global_skill(enterprise, school_id, "socratic") is None
        renewed = await grant_global_skill(
            enterprise, operator, school_id, "socratic", expected_grant_version=1,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            reason="绑定复核发布版本", request_id="fence-grant-renewed",
        )
        assert renewed.publication_version == 2
        assert await resolve_authorized_global_skill(enterprise, school_id, "socratic")
    finally:
        await db.__aexit__(None, None, None)


async def test_oms_skill_upload_route_requires_local_action_and_keeps_zip_unpublished(app, pg_dsn):
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    class Verifier:
        async def verify(self, token):
            if token != "skill-token":
                raise PermissionError("invalid")
            now = int(datetime.now(timezone.utc).timestamp())
            return PlatformIdentity(
                issuer="https://issuer.example", subject="skill-admin",
                client_id="eduplus-platform-admin", token_hash="digest",
                issued_at=now, expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return token == "skill-token" and subject == "skill-admin"

    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    store = MemoryObjectStore()
    enterprise.object_store = store
    headers = {
        "Authorization": "Bearer skill-token",
        "Origin": "https://school.example",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        denied = await client.post(
            "/api/v1/oms/skills/draft",
            files={"file": ("skill.zip", _zip(), "application/zip")},
            data={"expected_version": "0", "reason": "首个 Agent 的 global Skill 草稿"},
            headers=headers,
        )
        assert denied.status_code == 403
        await _actor(pg_dsn)
        created = await client.post(
            "/api/v1/oms/skills/draft",
            files={"file": ("skill.zip", _zip(), "application/zip")},
            data={"expected_version": "0", "reason": "首个 Agent 的 global Skill 草稿"},
            headers=headers,
        )
        assert created.status_code == 200, created.text
        assert created.json()["name"] == "socratic"
        assert created.json()["status"] == "draft"
        assert "object_key" not in created.text
    assert len(store.objects) == 1


async def test_oms_skill_review_publish_and_school_grant_routes_enforce_distinct_actions(
    app, pg_dsn,
):
    from deeptutor_enterprise.oms.identity import PlatformIdentity

    subjects = {
        "upload-token": "skill-admin",
        "review-token": "skill-reviewer",
        "grant-token": "skill-operator",
    }

    class Verifier:
        async def verify(self, token):
            if token not in subjects:
                raise PermissionError("invalid")
            now = int(datetime.now(timezone.utc).timestamp())
            return PlatformIdentity(
                issuer="https://issuer.example", subject=subjects[token],
                client_id="eduplus-platform-admin", token_hash="digest",
                issued_at=now, expires_at=now + 60,
            )

    class AccountStatus:
        async def check(self, token, *, issuer, subject):
            return subjects.get(token) == subject and issuer == "https://issuer.example"

    enterprise = app.state.enterprise
    enterprise.oms_platform_verifier = Verifier()
    enterprise.oms_account_status = AccountStatus()
    enterprise.object_store = MemoryObjectStore()
    school_id, other_school_id = uuid4(), uuid4()
    await _actor(pg_dsn)
    await _reviewer(pg_dsn)
    await _school_operator(pg_dsn, school_id)

    def headers(token):
        return {"Authorization": f"Bearer {token}", "Origin": "https://school.example"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        created = await client.post(
            "/api/v1/oms/skills/draft",
            files={"file": ("skill.zip", _zip(), "application/zip")},
            data={"expected_version": "0", "reason": "待审查"},
            headers=headers("upload-token"),
        )
        assert created.status_code == 200, created.text
        revision_id = created.json()["revision_id"]
        review_path = f"/api/v1/oms/skills/revisions/{revision_id}/review"
        review_command = {
            "expected_sha256": created.json()["sha256"],
            "approved": True, "reason": "独立审核通过",
        }
        unauthenticated = await client.post(review_path, json=review_command)
        assert unauthenticated.status_code == 401
        self_review = await client.post(
            review_path, json=review_command, headers=headers("upload-token")
        )
        assert self_review.status_code == 403
        reviewed = await client.post(
            review_path, json=review_command, headers=headers("review-token")
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["approved"] is True

        publish_path = f"/api/v1/oms/skills/revisions/{revision_id}/publish"
        publish_command = {"expected_version": 0, "reason": "发布经审核版本"}
        wrong_role = await client.post(
            publish_path, json=publish_command, headers=headers("review-token")
        )
        assert wrong_role.status_code == 403
        published = await client.post(
            publish_path, json=publish_command, headers=headers("upload-token")
        )
        assert published.status_code == 200, published.text
        assert published.json()["version"] == 1

        grant_command = {
            "expected_grant_version": 0,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "reason": "学校显式授权",
        }
        wrong_school = await client.post(
            f"/api/v1/oms/skills/socratic/schools/{other_school_id}/grant",
            json=grant_command, headers=headers("grant-token"),
        )
        assert wrong_school.status_code == 403
        grant_path = f"/api/v1/oms/skills/socratic/schools/{school_id}/grant"
        granted = await client.post(
            grant_path, json=grant_command, headers=headers("grant-token")
        )
        assert granted.status_code == 200, granted.text
        assert granted.json()["status"] == "active"
        assert granted.json()["publication_version"] == 1

        revoked = await client.request(
            "DELETE", grant_path,
            json={"expected_grant_version": 1, "reason": "显式撤权"},
            headers=headers("grant-token"),
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["status"] == "revoked"
