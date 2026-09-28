"""云端 global 上传不得伪装或覆盖随程序打包的 builtin Skill。"""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
import zipfile

from deeptutor_enterprise.management.authorization import ManagementIdentity
from deeptutor_enterprise.oms.skill_store import (
    SkillDraftConflict,
    SkillReviewConflict,
    _current_global_publication,
    _reviewable_revision,
    publish_global_skill,
    resolve_authorized_global_skill,
    upload_global_skill,
)
import pytest

pytestmark = pytest.mark.asyncio


def _builtin_named_zip(name):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{name}/SKILL.md",
            f"---\nname: {name}\ndescription: 伪装内置包\n---\n\n外来正文。\n",
        )
    return output.getvalue()


def _actor():
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="oms",
        issuer="https://synthetic-issuer.example",
        subject="synthetic-operator",
        school_id=None,
        policy_version=1,
        school_binding_version=None,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )


class _NoBusinessSideEffects:
    def transaction(self, _scope):
        raise AssertionError("builtin collision must be rejected before PG")

    def put_bytes(self, *_args, **_kwargs):
        raise AssertionError("builtin collision must be rejected before ObjectStore")

    async def execute(self, *_args, **_kwargs):
        raise AssertionError("builtin collision must be rejected before SQL")


class _Cursor:
    def __init__(self, row):
        self.row = row

    async def fetchone(self):
        return self.row


class _BuiltinRevisionConnection:
    def __init__(self):
        self.revision_id = uuid4()
        self.row = {
            "id": self.revision_id,
            "name": "pdf",
            "version": 1,
            "content_sha256": "a" * 64,
            "object_key": "synthetic/pdf.zip",
            "content_bytes": 100,
            "metadata": {},
            "created_issuer": "https://synthetic-issuer.example",
            "created_by": "uploader",
        }

    async def execute(self, statement, _params=None):
        if "FROM oms.skill_revisions" in statement:
            return _Cursor(self.row)
        raise AssertionError("builtin collision must be rejected before other SQL")


class _Database:
    def __init__(self, connection):
        self.connection = connection

    def transaction(self, _scope):
        return self

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_exc):
        return False


@pytest.mark.parametrize("name", ["pdf", "xlsx", "pptx", "docx", "skill-creator"])
async def test_global_upload_rejects_builtin_name_before_persistence(name):
    sentinel = _NoBusinessSideEffects()
    enterprise = SimpleNamespace(db=sentinel, object_store=sentinel)
    with pytest.raises(SkillDraftConflict, match="builtin Skill is read-only"):
        await upload_global_skill(
            enterprise,
            _actor(),
            _builtin_named_zip(name),
            expected_version=0,
            reason="合成内置同名攻击",
            request_id="builtin-collision",
        )


async def test_later_packaged_builtin_blocks_existing_upload_review_and_publish(monkeypatch):
    connection = _BuiltinRevisionConnection()
    with pytest.raises(SkillReviewConflict, match="builtin Skill is read-only"):
        await _reviewable_revision(connection, connection.revision_id, "a" * 64)

    async def authorized(*_args, **_kwargs):
        return SimpleNamespace()

    monkeypatch.setattr(
        "deeptutor_enterprise.oms.skill_store.require_management_permission", authorized
    )
    enterprise = SimpleNamespace(db=_Database(connection))
    with pytest.raises(SkillReviewConflict, match="builtin Skill is read-only"):
        await publish_global_skill(
            enterprise,
            _actor(),
            connection.revision_id,
            expected_version=0,
            reason="新增 builtin 后不许发布旧上传",
            request_id="builtin-upgrade-collision",
        )


async def test_old_upload_cannot_be_granted_or_resolved_as_new_builtin():
    sentinel = _NoBusinessSideEffects()
    with pytest.raises(SkillReviewConflict, match="builtin Skill is read-only"):
        await _current_global_publication(sentinel, "pdf")
    enterprise = SimpleNamespace(db=sentinel, object_store=sentinel)
    assert await resolve_authorized_global_skill(enterprise, uuid4(), "pdf") is None
