"""不依赖 PG 进程的 Skill 审查服务合同；PG/RLS 另有隔离回归。"""

from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
import zipfile

from deeptutor_enterprise.management.authorization import ManagementIdentity
from deeptutor_enterprise.oms.skill_package import validate_skill_archive
from deeptutor_enterprise.oms.skill_store import SkillReviewConflict, review_global_skill
import pytest

pytestmark = pytest.mark.asyncio


def _zip(*, script=False):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "socratic/SKILL.md",
            "---\nname: socratic\ndescription: 合成提问\nalways: false\n---\n\n请先提问。\n",
        )
        if script:
            archive.writestr("socratic/scripts/run.py", "print('synthetic')\n")
    return output.getvalue()


def _identity(subject):
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="oms",
        issuer="https://synthetic-issuer.example",
        subject=subject,
        school_id=None,
        policy_version=1,
        school_binding_version=None,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )


class _Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, payload):
        archive = validate_skill_archive(payload)
        self.revision = {
            "id": uuid4(),
            "name": archive.name,
            "version": 1,
            "content_sha256": archive.sha256,
            "object_key": f"synthetic/{archive.sha256}.zip",
            "content_bytes": len(payload),
            "metadata": {
                "description": archive.description,
                "tags": list(archive.tags),
                "always": archive.always,
                "requires": {
                    "bins": list(archive.requires.bins),
                    "env": list(archive.requires.env),
                    "sandbox": archive.requires.sandbox,
                },
            },
            "created_issuer": "https://synthetic-issuer.example",
            "created_by": "uploader",
        }
        self.review = None
        self.audit = []
        self.statements = []

    async def execute(self, statement, params=None):
        self.statements.append((statement, params))
        if "FROM oms.skill_revisions" in statement:
            return _Cursor(self.revision.copy())
        if "FROM oms.skill_reviews" in statement:
            return _Cursor(self.review)
        if statement.startswith("INSERT INTO oms.skill_reviews"):
            assert "'skill-archive-v1'" in statement
            self.review = {
                "id": params[0],
                "approved": params[3],
                "content_sha256": params[2],
                "code_file_digests": params[4].obj,
                "code_review_evidence": params[5],
                "reason": params[8],
            }
            return _Cursor()
        if statement.startswith("INSERT INTO management.audit_events"):
            self.audit.append(params)
            return _Cursor()
        if statement.startswith("SELECT pg_advisory_xact_lock"):
            return _Cursor()
        raise AssertionError(statement)


class _Database:
    def __init__(self, connection):
        self.connection = connection

    def transaction(self, _scope):
        return self

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_exc):
        return False


class _ObjectStore:
    def __init__(self, payload):
        self.payload = payload
        self.reads = 0
        self.on_read = None

    def get_bytes(self, _ref):
        self.reads += 1
        if self.on_read:
            self.on_read()
        return self.payload


@pytest.fixture
def allowed(monkeypatch):
    calls = []

    async def permission(_connection, actor, action, *, write):
        calls.append((actor.subject, action, write))
        return SimpleNamespace()

    monkeypatch.setattr(
        "deeptutor_enterprise.oms.skill_store.require_management_permission", permission
    )
    return calls


def _enterprise(payload):
    connection = _Connection(payload)
    store = _ObjectStore(payload)
    return SimpleNamespace(db=_Database(connection), object_store=store), connection, store


async def test_review_rejects_self_review_before_object_read(allowed):
    payload = _zip()
    enterprise, connection, store = _enterprise(payload)
    with pytest.raises(SkillReviewConflict, match="creator cannot review"):
        await review_global_skill(
            enterprise,
            _identity("uploader"),
            connection.revision["id"],
            expected_sha256=connection.revision["content_sha256"],
            approved=True,
            reason="自审",
            request_id="self-review",
        )
    assert store.reads == 0
    assert connection.review is None
    assert allowed == [("uploader", "ops.skills.review", True)]


async def test_review_rejects_changed_object_and_changed_revision_without_audit(allowed):
    payload = _zip()
    enterprise, connection, store = _enterprise(payload)
    store.payload = b"changed"
    with pytest.raises(RuntimeError, match="digest"):
        await review_global_skill(
            enterprise,
            _identity("reviewer"),
            connection.revision["id"],
            expected_sha256=connection.revision["content_sha256"],
            approved=True,
            reason="核查",
            request_id="changed-object",
        )
    assert connection.review is None and not connection.audit

    store.payload = payload
    store.on_read = lambda: connection.revision.update(version=2)
    with pytest.raises(SkillReviewConflict, match="changed during review"):
        await review_global_skill(
            enterprise,
            _identity("reviewer"),
            connection.revision["id"],
            expected_sha256=connection.revision["content_sha256"],
            approved=True,
            reason="核查",
            request_id="changed-revision",
        )
    assert connection.review is None and not connection.audit


async def test_script_review_records_digest_evidence_and_exact_replay(allowed):
    payload = _zip(script=True)
    enterprise, connection, store = _enterprise(payload)
    revision_id = connection.revision["id"]
    digest = connection.revision["content_sha256"]
    actor = _identity("reviewer")
    with pytest.raises(SkillReviewConflict, match="review evidence"):
        await review_global_skill(
            enterprise,
            actor,
            revision_id,
            expected_sha256=digest,
            approved=True,
            reason="核查脚本",
            request_id="script-no-evidence",
        )
    assert connection.review is None
    evidence = "已逐文件复核 scripts/run.py 的摘要与命令行为"
    result = await review_global_skill(
        enterprise,
        actor,
        revision_id,
        expected_sha256=digest,
        approved=True,
        reason="核查脚本",
        request_id="script-reviewed",
        code_review_evidence=evidence,
    )
    assert result.code_file_count == 1 and not result.replayed
    assert connection.review == {
        "id": result.review_id,
        "approved": True,
        "content_sha256": digest,
        "code_file_digests": {
            "scripts/run.py": hashlib.sha256(b"print('synthetic')\n").hexdigest()
        },
        "code_review_evidence": evidence,
        "reason": "核查脚本",
    }
    assert len(connection.audit) == 1
    replay = await review_global_skill(
        enterprise,
        actor,
        revision_id,
        expected_sha256=digest,
        approved=True,
        reason="核查脚本",
        request_id="script-reviewed",
        code_review_evidence=evidence,
    )
    assert replay.review_id == result.review_id and replay.replayed
    assert len(connection.audit) == 1
    with pytest.raises(SkillReviewConflict, match="idempotency"):
        await review_global_skill(
            enterprise,
            actor,
            revision_id,
            expected_sha256=digest,
            approved=True,
            reason="改写原因",
            request_id="script-reviewed",
            code_review_evidence=evidence,
        )
    assert store.reads == 4
    assert all(call == ("reviewer", "ops.skills.review", True) for call in allowed[1:])
