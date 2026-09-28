"""OMS global Skill 完整包、独立审查、版本化发布及按学校授权。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import PurePosixPath
import re
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.scope import GlobalScope, TenantScope
from deeptutor.persistence.postgres.tenant_state import validate_tenant_business_values
from deeptutor.runtime.externalized_providers import ObjectBlobRef
from deeptutor.services.skill.service import BUILTIN_SKILLS_ROOT

from ..management.authorization import ManagementIdentity, require_management_permission
from .skill_package import validate_skill_archive

_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _is_packaged_builtin(name: str) -> bool:
    """打包目录是 builtin 身份权威，不允许普通 global 上传抢占名称。"""

    return (BUILTIN_SKILLS_ROOT / name / "SKILL.md").is_file()


class SkillDraftConflict(ValueError):
    """同名版本被别的命令占用。"""


class SkillReviewConflict(ValueError):
    """内容、审核人或幂等命令与不可变修订不一致。"""


@dataclass(frozen=True, slots=True)
class SkillDraftResult:
    revision_id: UUID
    name: str
    version: int
    sha256: str
    object_key: str
    status: str = "draft"


@dataclass(frozen=True, slots=True)
class SkillReviewResult:
    review_id: UUID
    revision_id: UUID
    approved: bool
    code_file_count: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class SkillPublicationResult:
    publication_id: UUID
    revision_id: UUID
    review_id: UUID
    version: int


@dataclass(frozen=True, slots=True)
class SkillGrantResult:
    school_id: UUID
    name: str
    revision_id: UUID
    grant_version: int
    publication_version: int
    status: str


@dataclass(frozen=True, slots=True)
class AuthorizedGlobalSkill:
    school_id: UUID
    name: str
    revision_id: UUID
    publication_version: int
    sha256: str
    archive: object


_CODE_SUFFIXES = frozenset({
    ".py", ".js", ".mjs", ".ts", ".sh", ".rb", ".lua", ".r", ".sql",
    ".html", ".htm", ".jinja", ".j2", ".tmpl", ".template",
})


async def upload_global_skill(
    enterprise,
    actor: ManagementIdentity,
    payload: bytes,
    *,
    expected_version: int,
    reason: str,
    request_id: str,
) -> SkillDraftResult:
    """验证 ZIP → S3 不可变对象 → PG 版本事实；绝不执行包内代码。"""

    if (
        not isinstance(actor, ManagementIdentity)
        or actor.application != "oms"
        or type(expected_version) is not int
        or expected_version < 0
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ValueError("invalid OMS Skill upload command")
    archive = validate_skill_archive(payload)
    if _is_packaged_builtin(archive.name):
        raise SkillDraftConflict("builtin Skill is read-only")
    scope = GlobalScope("@oms-skill-upload")
    # 先检查权限和版本，避免无权请求写入对象存储。网络 I/O 不持 PG 事务。
    async with enterprise.db.transaction(scope) as c:
        await require_management_permission(c, actor, "ops.skills.manage", write=True)
        latest = await (
            await c.execute(
                "SELECT coalesce(max(version),0) AS version FROM oms.skill_revisions "
                "WHERE owner_kind='global' AND name=%s",
                (archive.name,),
            )
        ).fetchone()
        if latest["version"] != expected_version:
            raise SkillDraftConflict("global Skill version changed")

    revision_id = uuid4()
    object_key = f"oms/skills/global/{archive.name}/{revision_id}/{archive.sha256}.zip"
    ref = await asyncio.to_thread(
        enterprise.object_store.put_bytes,
        object_key,
        payload,
        expected_sha256=archive.sha256,
        content_type="application/zip",
    )
    if ref.key != object_key or ref.sha256 != archive.sha256 or ref.size_bytes != len(payload):
        raise RuntimeError("Skill object store did not confirm exact ZIP bytes")

    # 上传后再次锁定/检查主体及版本；若此处失败，对象是不可访问的孤儿，
    # 必须由后续 ObjectStore 对账清理，不能在不确定提交状态下盲删。
    async with enterprise.db.transaction(scope) as c:
        await require_management_permission(c, actor, "ops.skills.manage", write=True)
        await c.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"oms-skill:global:{archive.name}",),
        )
        latest = await (
            await c.execute(
                "SELECT coalesce(max(version),0) AS version FROM oms.skill_revisions "
                "WHERE owner_kind='global' AND name=%s",
                (archive.name,),
            )
        ).fetchone()
        if latest["version"] != expected_version:
            raise SkillDraftConflict("global Skill version changed")
        version = expected_version + 1
        metadata = {
            "description": archive.description,
            "tags": list(archive.tags),
            "always": archive.always,
            "requires": {
                "bins": list(archive.requires.bins),
                "env": list(archive.requires.env),
                "sandbox": archive.requires.sandbox,
            },
        }
        await c.execute(
            "INSERT INTO oms.skill_revisions"
            "(id,owner_kind,name,version,source,content_sha256,object_key,"
            "content_bytes,metadata,created_by,created_issuer) "
            "VALUES(%s,'global',%s,%s,'upload',%s,%s,%s,%s,%s,%s)",
            (
                revision_id, archive.name, version, archive.sha256, object_key,
                len(payload), Jsonb(metadata), actor.subject, actor.issuer,
            ),
        )
        await c.execute(
            "INSERT INTO management.audit_events"
            "(id,application,actor_issuer,actor_subject,action_key,target_kind,target_id,"
            "request_id,result,reason,before_version,after_version,safe_summary) "
            "VALUES(%s,'oms',%s,%s,'ops.skills.manage','skill_revision',%s,"
            "%s,'success',%s,%s,%s,%s)",
            (
                uuid4(), actor.issuer, actor.subject, str(revision_id),
                request_id.strip(), reason.strip(), expected_version, version,
                Jsonb({"name": archive.name, "sha256": archive.sha256, "status": "draft"}),
            ),
        )
    return SkillDraftResult(revision_id, archive.name, version, archive.sha256, object_key)


def _review_input(
    actor: ManagementIdentity,
    revision_id: UUID,
    expected_sha256: str,
    approved: bool,
    reason: str,
    request_id: str,
    code_review_evidence: str,
) -> None:
    if (
        not isinstance(actor, ManagementIdentity)
        or actor.application != "oms"
        or not isinstance(revision_id, UUID)
        or not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_sha256)
        or type(approved) is not bool
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
        or not isinstance(code_review_evidence, str)
        or len(code_review_evidence.strip()) > 2000
    ):
        raise ValueError("invalid OMS Skill review command")


async def _reviewable_revision(c, revision_id: UUID, expected_sha256: str):
    row = await (
        await c.execute(
            "SELECT id,name,version,content_sha256,object_key,content_bytes,metadata,"
            "created_issuer,created_by FROM oms.skill_revisions "
            "WHERE id=%s AND owner_kind='global' AND owner_school_id IS NULL "
            "AND source='upload' FOR SHARE",
            (revision_id,),
        )
    ).fetchone()
    if row is None or row["content_sha256"] != expected_sha256:
        raise SkillReviewConflict("Skill revision or digest changed")
    if _is_packaged_builtin(row["name"]):
        raise SkillReviewConflict("builtin Skill is read-only")
    if not row["created_issuer"] or not row["created_by"]:
        raise SkillReviewConflict("Skill revision creator is unverified")
    return row


async def review_global_skill(
    enterprise,
    actor: ManagementIdentity,
    revision_id: UUID,
    *,
    expected_sha256: str,
    approved: bool,
    reason: str,
    request_id: str,
    code_review_evidence: str = "",
) -> SkillReviewResult:
    """服务端复读完整 ZIP 与元数据；审查事实只追加，脚本需人工证据。"""

    _review_input(
        actor, revision_id, expected_sha256, approved, reason,
        request_id, code_review_evidence,
    )
    scope = GlobalScope("@oms-skill-review")
    async with enterprise.db.transaction(scope) as c:
        await require_management_permission(c, actor, "ops.skills.review", write=True)
        revision = await _reviewable_revision(c, revision_id, expected_sha256)
        if (actor.issuer, actor.subject) == (
            revision["created_issuer"], revision["created_by"]
        ):
            raise SkillReviewConflict("Skill creator cannot review own revision")

    ref = ObjectBlobRef(
        revision["object_key"], revision["content_bytes"], expected_sha256,
        "application/zip",
    )
    payload = await asyncio.to_thread(enterprise.object_store.get_bytes, ref)
    if (
        not isinstance(payload, bytes)
        or len(payload) != ref.size_bytes
        or hashlib.sha256(payload).hexdigest() != expected_sha256
    ):
        raise RuntimeError("Skill object content digest differs from immutable revision")
    archive = validate_skill_archive(payload)
    metadata = revision["metadata"]
    expected_metadata = {
        "description": archive.description,
        "tags": list(archive.tags),
        "always": archive.always,
        "requires": {
            "bins": list(archive.requires.bins),
            "env": list(archive.requires.env),
            "sandbox": archive.requires.sandbox,
        },
    }
    if archive.name != revision["name"] or metadata != expected_metadata:
        raise SkillReviewConflict("Skill content metadata differs from immutable revision")
    code_files = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in archive.files
        if PurePosixPath(name).suffix.lower() in _CODE_SUFFIXES
    }
    if approved and code_files and not code_review_evidence.strip():
        raise SkillReviewConflict("executable Skill files require independent review evidence")

    async with enterprise.db.transaction(scope) as c:
        await require_management_permission(c, actor, "ops.skills.review", write=True)
        await c.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"oms-skill-review:{revision_id}:{actor.issuer}:{actor.subject}:{request_id}",),
        )
        current = await _reviewable_revision(c, revision_id, expected_sha256)
        if any(current[key] != revision[key] for key in revision):
            raise SkillReviewConflict("Skill revision changed during review")
        previous = await (
            await c.execute(
                "SELECT id,approved,content_sha256,code_file_digests,"
                "code_review_evidence,reason FROM oms.skill_reviews "
                "WHERE revision_id=%s AND reviewer_issuer=%s AND reviewer_subject=%s "
                "AND request_id=%s FOR SHARE",
                (revision_id, actor.issuer, actor.subject, request_id.strip()),
            )
        ).fetchone()
        if previous:
            if (
                previous["approved"] != approved
                or previous["content_sha256"] != expected_sha256
                or previous["code_file_digests"] != code_files
                or previous["code_review_evidence"] != code_review_evidence.strip()
                or previous["reason"] != reason.strip()
            ):
                raise SkillReviewConflict("Skill review idempotency key was reused")
            return SkillReviewResult(previous["id"], revision_id, approved, len(code_files), True)
        review_id = uuid4()
        await c.execute(
            "INSERT INTO oms.skill_reviews"
            "(id,revision_id,content_sha256,approved,scanner_version,code_file_digests,"
            "code_review_evidence,reviewer_issuer,reviewer_subject,reason,request_id) "
            "VALUES(%s,%s,%s,%s,'skill-archive-v1',%s,%s,%s,%s,%s,%s)",
            (
                review_id, revision_id, expected_sha256, approved, Jsonb(code_files),
                code_review_evidence.strip(), actor.issuer, actor.subject,
                reason.strip(), request_id.strip(),
            ),
        )
        await c.execute(
            "INSERT INTO management.audit_events"
            "(id,application,actor_issuer,actor_subject,action_key,target_kind,target_id,"
            "request_id,result,reason,before_version,after_version,safe_summary) "
            "VALUES(%s,'oms',%s,%s,'ops.skills.review','skill_review',%s,"
            "%s,'success',%s,%s,%s,%s)",
            (
                uuid4(), actor.issuer, actor.subject, str(review_id), request_id.strip(),
                reason.strip(), revision["version"], revision["version"],
                Jsonb({"revision_id": str(revision_id), "sha256": expected_sha256,
                       "approved": approved, "code_file_count": len(code_files)}),
            ),
        )
        return SkillReviewResult(review_id, revision_id, approved, len(code_files), False)


async def publish_global_skill(
    enterprise,
    actor: ManagementIdentity,
    revision_id: UUID,
    *,
    expected_version: int,
    reason: str,
    request_id: str,
) -> SkillPublicationResult:
    """发布已独立审查的 global 修订；切换指针不会继承旧学校授权。"""

    if (
        not isinstance(actor, ManagementIdentity)
        or actor.application != "oms"
        or not isinstance(revision_id, UUID)
        or type(expected_version) is not int
        or expected_version < 0
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ValueError("invalid OMS Skill publication command")
    scope = GlobalScope("@oms-skill-publish")
    async with enterprise.db.transaction(scope) as c:
        await require_management_permission(c, actor, "ops.skills.publish", write=True)
        revision = await (
            await c.execute(
                "SELECT id,name,version,content_sha256,created_issuer,created_by "
                "FROM oms.skill_revisions WHERE id=%s AND owner_kind='global' "
                "AND owner_school_id IS NULL AND source='upload' FOR SHARE",
                (revision_id,),
            )
        ).fetchone()
        if revision is None or not revision["created_issuer"]:
            raise SkillReviewConflict("global Skill revision is unavailable")
        if _is_packaged_builtin(revision["name"]):
            raise SkillReviewConflict("builtin Skill is read-only")
        await c.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"oms-skill:global:{revision['name']}",),
        )
        review = await (
            await c.execute(
                "SELECT id,approved,content_sha256,code_file_digests,"
                "code_review_evidence,reviewer_issuer,reviewer_subject,scanner_version "
                "FROM oms.skill_reviews WHERE revision_id=%s "
                "ORDER BY reviewed_at DESC,id DESC LIMIT 1 FOR SHARE",
                (revision_id,),
            )
        ).fetchone()
        if (
            review is None
            or review["approved"] is not True
            or review["content_sha256"] != revision["content_sha256"]
            or review["scanner_version"] != "skill-archive-v1"
            or not isinstance(review["code_file_digests"], dict)
            or (
                review["code_file_digests"]
                and not review["code_review_evidence"].strip()
            )
            or (review["reviewer_issuer"], review["reviewer_subject"])
            in {
                (actor.issuer, actor.subject),
                (revision["created_issuer"], revision["created_by"]),
            }
        ):
            raise SkillReviewConflict("independent approved Skill review is unavailable")
        current = await (
            await c.execute(
                "SELECT id,revision_id,review_id,version FROM oms.skill_publications "
                "WHERE owner_kind='global' AND owner_school_id IS NULL AND name=%s FOR UPDATE",
                (revision["name"],),
            )
        ).fetchone()
        version = current["version"] if current else 0
        if version != expected_version or (
            current
            and current["revision_id"] == revision_id
            and current["review_id"] == review["id"]
        ):
            raise SkillReviewConflict("global Skill publication version changed")
        publication_id = current["id"] if current else uuid4()
        next_version = version + 1
        if current:
            updated = await (
                await c.execute(
                    "UPDATE oms.skill_publications SET revision_id=%s,review_id=%s,"
                    "version=%s,published_by=%s,published_issuer=%s,"
                    "published_at=clock_timestamp() WHERE id=%s AND version=%s RETURNING id",
                    (
                        revision_id, review["id"], next_version, actor.subject, actor.issuer,
                        publication_id, expected_version,
                    ),
                )
            ).fetchone()
            if not updated:
                raise SkillReviewConflict("global Skill publication version changed")
        else:
            await c.execute(
                "INSERT INTO oms.skill_publications"
                "(id,owner_kind,name,revision_id,review_id,version,published_by,"
                "published_issuer) VALUES(%s,'global',%s,%s,%s,1,%s,%s)",
                (
                    publication_id, revision["name"], revision_id, review["id"],
                    actor.subject, actor.issuer,
                ),
            )
        await c.execute(
            "INSERT INTO management.audit_events"
            "(id,application,actor_issuer,actor_subject,action_key,target_kind,target_id,"
            "request_id,result,reason,before_version,after_version,safe_summary) "
            "VALUES(%s,'oms',%s,%s,'ops.skills.publish','skill_publication',%s,"
            "%s,'success',%s,%s,%s,%s)",
            (
                uuid4(), actor.issuer, actor.subject, str(publication_id), request_id.strip(),
                reason.strip(), version, next_version,
                Jsonb({"revision_id": str(revision_id), "review_id": str(review["id"]),
                       "sha256": revision["content_sha256"]}),
            ),
        )
        return SkillPublicationResult(
            publication_id, revision_id, review["id"], next_version
        )


def _grant_input(
    actor: ManagementIdentity,
    school_id: UUID,
    name: str,
    expected_grant_version: int,
    reason: str,
    request_id: str,
) -> None:
    if (
        not isinstance(actor, ManagementIdentity)
        or actor.application != "oms"
        or not isinstance(school_id, UUID)
        or not isinstance(name, str)
        or not _SKILL_NAME.fullmatch(name)
        or type(expected_grant_version) is not int
        or expected_grant_version < 0
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ValueError("invalid OMS Skill grant command")


def _validate_grant_fact(row) -> None:
    """拒绝旧未知授权事实，不能用一次新写入把它静默改成合法状态。"""

    if (
        not isinstance(row["revision_id"], UUID)
        or type(row["publication_version"]) is not int
        or row["publication_version"] < 1
        or row["status"] not in {"active", "revoked"}
        or type(row["version"]) is not int
        or row["version"] < 1
        or not isinstance(row["expires_at"], datetime)
        or row["expires_at"].tzinfo is None
    ):
        raise SkillReviewConflict("global Skill grant fact is invalid")


async def _current_global_publication(c, name: str):
    if _is_packaged_builtin(name):
        raise SkillReviewConflict("builtin Skill is read-only")
    row = await (
        await c.execute(
            "SELECT p.id,p.revision_id,p.version,p.review_id,r.content_sha256 "
            "FROM oms.skill_publications p "
            "JOIN oms.skill_revisions r ON r.id=p.revision_id "
            "AND r.owner_kind='global' AND r.owner_school_id IS NULL AND r.name=p.name "
            "JOIN oms.skill_reviews rv ON rv.id=p.review_id "
            "AND rv.revision_id=r.id AND rv.content_sha256=r.content_sha256 "
            "WHERE p.owner_kind='global' AND p.owner_school_id IS NULL "
            "AND p.name=%s AND rv.approved=true "
            "AND rv.scanner_version='skill-archive-v1' "
            "AND rv.id=(SELECT latest.id FROM oms.skill_reviews latest "
            "WHERE latest.revision_id=r.id "
            "ORDER BY latest.reviewed_at DESC,latest.id DESC LIMIT 1) "
            "FOR SHARE OF p,r,rv",
            (name,),
        )
    ).fetchone()
    if row is None:
        raise SkillReviewConflict("approved global Skill publication is unavailable")
    return row


async def grant_global_skill(
    enterprise,
    actor: ManagementIdentity,
    school_id: UUID,
    name: str,
    *,
    expected_grant_version: int,
    expires_at: datetime,
    reason: str,
    request_id: str,
) -> SkillGrantResult:
    """学校授权绑定当前发布序号；换包与回退均须重新授权。"""

    _grant_input(actor, school_id, name, expected_grant_version, reason, request_id)
    if (
        not isinstance(expires_at, datetime)
        or expires_at.tzinfo is None
        or expires_at <= datetime.now(timezone.utc)
    ):
        raise ValueError("Skill grant expiry is invalid")
    scope = TenantScope(str(school_id), "@oms-skill-grant")
    async with enterprise.db.transaction(scope) as c:
        await require_management_permission(
            c, actor, "ops.skills.grant", target_school_id=school_id, write=True
        )
        await c.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"oms-skill-grant:{school_id}:{name}",),
        )
        publication = await _current_global_publication(c, name)
        current = await (
            await c.execute(
                "SELECT revision_id,publication_version,status,version,expires_at "
                "FROM oms.skill_grants "
                "WHERE tenant_id=%s AND name=%s FOR UPDATE",
                (school_id, name),
            )
        ).fetchone()
        if current is not None:
            _validate_grant_fact(current)
        current_version = current["version"] if current else 0
        if current_version != expected_grant_version:
            raise SkillReviewConflict("Skill grant version changed")
        next_version = current_version + 1
        if current:
            updated = await (
                await c.execute(
                    "UPDATE oms.skill_grants SET revision_id=%s,publication_version=%s,"
                    "status='active',version=%s,expires_at=%s,granted_by=%s,"
                    "granted_issuer=%s,updated_at=clock_timestamp() "
                    "WHERE tenant_id=%s AND name=%s AND version=%s RETURNING version",
                    (
                        publication["revision_id"], publication["version"], next_version,
                        expires_at, actor.subject, actor.issuer, school_id, name,
                        current_version,
                    ),
                )
            ).fetchone()
            if updated is None:
                raise SkillReviewConflict("Skill grant version changed")
        else:
            await c.execute(
                "INSERT INTO oms.skill_grants"
                "(tenant_id,name,revision_id,publication_version,status,version,"
                "expires_at,granted_by,granted_issuer) "
                "VALUES(%s,%s,%s,%s,'active',1,%s,%s,%s)",
                (
                    school_id, name, publication["revision_id"], publication["version"],
                    expires_at, actor.subject, actor.issuer,
                ),
            )
        await c.execute(
            "INSERT INTO management.audit_events"
            "(id,application,school_id,actor_issuer,actor_subject,action_key,target_kind,"
            "target_id,request_id,result,reason,before_version,after_version,safe_summary) "
            "VALUES(%s,'oms',%s,%s,%s,'ops.skills.grant','skill_grant',%s,"
            "%s,'success',%s,%s,%s,%s)",
            (
                uuid4(), school_id, actor.issuer, actor.subject, f"{school_id}:{name}",
                request_id.strip(), reason.strip(), current_version, next_version,
                Jsonb({"revision_id": str(publication["revision_id"]),
                       "publication_version": publication["version"], "status": "active"}),
            ),
        )
        return SkillGrantResult(
            school_id, name, publication["revision_id"], next_version,
            publication["version"], "active",
        )


async def revoke_global_skill(
    enterprise,
    actor: ManagementIdentity,
    school_id: UUID,
    name: str,
    *,
    expected_grant_version: int,
    reason: str,
    request_id: str,
) -> SkillGrantResult:
    """撤销当前学校授权；不删除历史行或已发布修订。"""

    _grant_input(actor, school_id, name, expected_grant_version, reason, request_id)
    if expected_grant_version < 1:
        raise ValueError("Skill grant version is invalid")
    scope = TenantScope(str(school_id), "@oms-skill-grant")
    async with enterprise.db.transaction(scope) as c:
        await require_management_permission(
            c, actor, "ops.skills.grant", target_school_id=school_id, write=True
        )
        await c.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"oms-skill-grant:{school_id}:{name}",),
        )
        current = await (
            await c.execute(
                "SELECT revision_id,publication_version,status,version,expires_at "
                "FROM oms.skill_grants WHERE tenant_id=%s AND name=%s FOR UPDATE",
                (school_id, name),
            )
        ).fetchone()
        if current is not None:
            _validate_grant_fact(current)
        if (
            current is None
            or current["status"] != "active"
            or current["version"] != expected_grant_version
        ):
            raise SkillReviewConflict("Skill grant is inactive or version changed")
        next_version = expected_grant_version + 1
        updated = await (
            await c.execute(
                "UPDATE oms.skill_grants SET status='revoked',version=%s,"
                "updated_at=clock_timestamp() WHERE tenant_id=%s AND name=%s AND version=%s "
                "RETURNING version",
                (next_version, school_id, name, expected_grant_version),
            )
        ).fetchone()
        if updated is None or updated["version"] != next_version:
            raise SkillReviewConflict("Skill grant version changed")
        await c.execute(
            "INSERT INTO management.audit_events"
            "(id,application,school_id,actor_issuer,actor_subject,action_key,target_kind,"
            "target_id,request_id,result,reason,before_version,after_version,safe_summary) "
            "VALUES(%s,'oms',%s,%s,%s,'ops.skills.grant','skill_grant',%s,"
            "%s,'success',%s,%s,%s,%s)",
            (
                uuid4(), school_id, actor.issuer, actor.subject, f"{school_id}:{name}",
                request_id.strip(), reason.strip(), expected_grant_version, next_version,
                Jsonb({"revision_id": str(current["revision_id"]),
                       "publication_version": current["publication_version"],
                       "status": "revoked"}),
            ),
        )
        return SkillGrantResult(
            school_id, name, current["revision_id"], next_version,
            current["publication_version"], "revoked",
        )


async def resolve_authorized_global_skill(
    enterprise, school_id: UUID, name: str, *, webhook_app_id: int | None = None
) -> AuthorizedGlobalSkill | None:
    """仅供可信学校运行时调用；无资格、授权或精确版本不符即不可见。"""

    if not isinstance(school_id, UUID) or not isinstance(name, str) or not _SKILL_NAME.fullmatch(name):
        raise ValueError("invalid Skill resolution scope")
    if _is_packaged_builtin(name):
        # builtin 须走独立的打包摘要/授权目录，不能借旧 upload grant 生效。
        return None
    scope = TenantScope(str(school_id), "@oms-skill-resolve")
    async with enterprise.db.transaction(scope) as c:
        # 仅应用内部解析可读取平台审查事实；学校主体不能直接取得审查表。
        await c.execute("SELECT set_config('app.management_app','oms',true)")
        school = await (
            await c.execute(
                "SELECT t.external_tid,t.external_eligibility,t.bootstrap_completed,"
                "t.local_enabled,t.provisioning_status,t.recovery_state,"
                "b.eduplus_tenant_id,b.version "
                "FROM enterprise.tenants t JOIN oms.school_bindings b ON b.tenant_id=t.id "
                "WHERE t.id=%s AND b.status='verified' FOR SHARE OF t,b",
                (school_id,),
            )
        ).fetchone()
        if school:
            validate_tenant_business_values(school)
        if not school or (
            school["external_eligibility"] != "allowed"
            or not school["bootstrap_completed"]
            or not school["local_enabled"]
            or school["provisioning_status"] != "ready"
            or school["recovery_state"] != "normal"
        ):
            return None
        if school["external_tid"] is not None:
            if (
                school["external_tid"] != str(school["eduplus_tenant_id"])
                or type(webhook_app_id) is not int
                or webhook_app_id <= 0
            ):
                return None
            projected = await (
                await c.execute(
                    "SELECT 1 FROM eduplus2.webhook_school_state p "
                    "JOIN eduplus2.webhook_school_controls k "
                    "ON (k.tenant_id,k.school_id,k.external_app_id)="
                    "(p.tenant_id,p.school_id,p.external_app_id) "
                    "WHERE p.school_id=%s AND p.external_tenant_id=%s "
                    "AND p.external_app_id=%s AND p.binding_version=%s "
                    "AND p.eligibility='allowed' AND NOT k.frozen "
                    "AND p.onboarding_completed_at IS NOT NULL FOR SHARE OF p,k",
                    (
                        school_id, school["eduplus_tenant_id"], webhook_app_id,
                        school["version"],
                    ),
                )
            ).fetchone()
            if not projected:
                return None
        grant = await (
            await c.execute(
                "SELECT revision_id,publication_version,status,version,expires_at "
                "FROM oms.skill_grants WHERE tenant_id=%s AND name=%s FOR SHARE",
                (school_id, name),
            )
        ).fetchone()
        if grant is None:
            return None
        _validate_grant_fact(grant)
        if grant["status"] != "active" or grant["expires_at"] <= datetime.now(timezone.utc):
            return None
        row = await (
            await c.execute(
                "SELECT g.revision_id,g.publication_version,r.content_sha256,"
                "r.object_key,r.content_bytes,r.metadata "
                "FROM oms.skill_grants g "
                "JOIN oms.skill_publications p ON p.owner_kind='global' "
                "AND p.owner_school_id IS NULL AND p.name=g.name "
                "AND p.revision_id=g.revision_id AND p.version=g.publication_version "
                "JOIN oms.skill_revisions r ON r.id=g.revision_id "
                "AND r.owner_kind='global' AND r.owner_school_id IS NULL "
                "AND r.name=g.name "
                "JOIN oms.skill_reviews rv ON rv.id=p.review_id "
                "AND rv.revision_id=r.id AND rv.approved=true "
                "AND rv.content_sha256=r.content_sha256 "
                "AND rv.id=(SELECT latest.id FROM oms.skill_reviews latest "
                "WHERE latest.revision_id=r.id "
                "ORDER BY latest.reviewed_at DESC,latest.id DESC LIMIT 1) "
                "WHERE g.tenant_id=%s AND g.name=%s AND g.status='active' "
                "AND g.expires_at>clock_timestamp() FOR SHARE OF g,p,r,rv",
                (school_id, name),
            )
        ).fetchone()
        if not row:
            return None
    ref = ObjectBlobRef(
        row["object_key"], row["content_bytes"], row["content_sha256"], "application/zip"
    )
    payload = await asyncio.to_thread(enterprise.object_store.get_bytes, ref)
    if (
        not isinstance(payload, bytes)
        or len(payload) != ref.size_bytes
        or hashlib.sha256(payload).hexdigest() != ref.sha256
    ):
        raise RuntimeError("authorized Skill content digest changed")
    archive = validate_skill_archive(payload)
    if archive.name != name:
        raise RuntimeError("authorized Skill package name changed")
    return AuthorizedGlobalSkill(
        school_id, name, row["revision_id"], row["publication_version"], ref.sha256,
        archive,
    )
