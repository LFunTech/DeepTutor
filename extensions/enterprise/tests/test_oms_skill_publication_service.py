"""global Skill 发布/回退的程序 CAS 与独立审查栅栏。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from deeptutor_enterprise.management.authorization import ManagementIdentity
from deeptutor_enterprise.oms.skill_store import SkillReviewConflict, publish_global_skill
import pytest

pytestmark = pytest.mark.asyncio


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
    def __init__(self):
        self.name = "socratic"
        self.first = uuid4()
        self.second = uuid4()
        self.revisions = {
            self.first: self._revision(self.first, 1, "a" * 64),
            self.second: self._revision(self.second, 2, "b" * 64),
        }
        self.reviews = {}
        self.publication = None
        self.audit = []

    def _revision(self, revision_id, version, digest):
        return {
            "id": revision_id,
            "name": self.name,
            "version": version,
            "content_sha256": digest,
            "created_issuer": "https://synthetic-issuer.example",
            "created_by": "uploader",
        }

    def approve(self, revision_id, *, reviewer="reviewer", approved=True):
        review_id = uuid4()
        self.reviews[revision_id] = {
            "id": review_id,
            "approved": approved,
            "content_sha256": self.revisions[revision_id]["content_sha256"],
            "code_file_digests": {},
            "code_review_evidence": "",
            "reviewer_issuer": "https://synthetic-issuer.example",
            "reviewer_subject": reviewer,
            "scanner_version": "skill-archive-v1",
        }
        return review_id

    async def execute(self, statement, params=None):
        if "FROM oms.skill_revisions WHERE id=" in statement:
            return _Cursor(self.revisions.get(params[0]))
        if "FROM oms.skill_reviews WHERE revision_id=" in statement:
            return _Cursor(self.reviews.get(params[0]))
        if "FROM oms.skill_publications" in statement:
            return _Cursor(self.publication.copy() if self.publication else None)
        if statement.startswith("UPDATE oms.skill_publications"):
            if (
                self.publication is None
                or self.publication["id"] != params[5]
                or self.publication["version"] != params[6]
            ):
                return _Cursor()
            self.publication.update(
                revision_id=params[0],
                review_id=params[1],
                version=params[2],
                published_by=params[3],
                published_issuer=params[4],
            )
            return _Cursor({"id": self.publication["id"]})
        if statement.startswith("INSERT INTO oms.skill_publications"):
            if self.publication is not None:
                raise AssertionError("publication already exists")
            self.publication = {
                "id": params[0],
                "revision_id": params[2],
                "review_id": params[3],
                "version": 1,
                "published_by": params[4],
                "published_issuer": params[5],
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


def _enterprise():
    connection = _Connection()
    return SimpleNamespace(db=_Database(connection)), connection


async def test_publication_requires_latest_approved_independent_review(allowed):
    enterprise, connection = _enterprise()
    for review in (None, "uploader", "publisher"):
        if review is not None:
            connection.approve(connection.first, reviewer=review)
        with pytest.raises(SkillReviewConflict, match="independent approved"):
            await publish_global_skill(
                enterprise,
                _identity("publisher"),
                connection.first,
                expected_version=0,
                reason="合成发布",
                request_id="attempt",
            )
    connection.approve(connection.first, approved=False)
    with pytest.raises(SkillReviewConflict, match="independent approved"):
        await publish_global_skill(
            enterprise,
            _identity("publisher"),
            connection.first,
            expected_version=0,
            reason="否决后尝试",
            request_id="denied",
        )
    assert connection.publication is None and not connection.audit
    assert all(action == "ops.skills.publish" and write for _, action, write in allowed)


async def test_publication_upgrade_and_rollback_are_cas_and_append_audit(allowed):
    enterprise, connection = _enterprise()
    first_review = connection.approve(connection.first)
    second_review = connection.approve(connection.second)
    publisher = _identity("publisher")
    first = await publish_global_skill(
        enterprise,
        publisher,
        connection.first,
        expected_version=0,
        reason="首版",
        request_id="publish-1",
    )
    assert (first.version, first.review_id) == (1, first_review)
    with pytest.raises(SkillReviewConflict, match="version changed"):
        await publish_global_skill(
            enterprise,
            publisher,
            connection.second,
            expected_version=0,
            reason="过期版本",
            request_id="stale",
        )
    second = await publish_global_skill(
        enterprise,
        publisher,
        connection.second,
        expected_version=1,
        reason="新版",
        request_id="publish-2",
    )
    assert (second.version, second.review_id) == (2, second_review)
    rolled_back = await publish_global_skill(
        enterprise,
        publisher,
        connection.first,
        expected_version=2,
        reason="回退首版",
        request_id="publish-3",
    )
    assert (rolled_back.version, rolled_back.review_id) == (3, first_review)
    assert connection.publication["revision_id"] == connection.first
    assert connection.publication["version"] == 3
    assert [(row[6], row[7]) for row in connection.audit] == [(0, 1), (1, 2), (2, 3)]
    assert len(allowed) == 4


async def test_later_rejected_review_blocks_republication(allowed):
    enterprise, connection = _enterprise()
    connection.approve(connection.first)
    publisher = _identity("publisher")
    await publish_global_skill(
        enterprise,
        publisher,
        connection.first,
        expected_version=0,
        reason="首版",
        request_id="publish-1",
    )
    connection.approve(connection.first, approved=False)
    with pytest.raises(SkillReviewConflict, match="independent approved"):
        await publish_global_skill(
            enterprise,
            publisher,
            connection.first,
            expected_version=1,
            reason="已否决仍发布",
            request_id="publish-denied",
        )
    assert connection.publication["version"] == 1
    assert len(connection.audit) == 1
