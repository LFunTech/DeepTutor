"""学校 Skill 授权事实在失去数据库枚举 CHECK 后仍须程序判定。"""

from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4
import zipfile

from deeptutor_enterprise.management.authorization import ManagementIdentity
from deeptutor_enterprise.oms.skill_store import (
    SkillReviewConflict,
    grant_global_skill,
    resolve_authorized_global_skill,
    revoke_global_skill,
)
import pytest

from deeptutor.runtime.externalized_providers import ObjectBlobRef

pytestmark = pytest.mark.asyncio
_SCHOOL = UUID("10000000-0000-0000-0000-000000000001")
_REVISION = UUID("20000000-0000-0000-0000-000000000001")


def _identity():
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


def _payload():
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "socratic/SKILL.md",
            "---\nname: socratic\ndescription: 合成提问\n---\n\n先提问。\n",
        )
    return output.getvalue()


class _Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, payload):
        self.payload = payload
        self.digest = hashlib.sha256(payload).hexdigest()
        self.tenant_row = {
            "external_tid": None,
            "external_eligibility": "allowed",
            "bootstrap_completed": True,
            "local_enabled": True,
            "provisioning_status": "ready",
            "recovery_state": "normal",
            "eduplus_tenant_id": 101,
            "version": 1,
        }
        self.grant = None
        self.publication = {"revision_id": _REVISION, "version": 1}
        self.audit = []
        self.statements = []
        self.revoke_update_missing = False

    async def execute(self, statement, params=None):
        self.statements.append((statement, params))
        if statement.startswith("SELECT set_config") or statement.startswith(
            "SELECT pg_advisory_xact_lock"
        ):
            return _Cursor()
        if "FROM enterprise.tenants t JOIN oms.school_bindings" in statement:
            return _Cursor(self.tenant_row.copy())
        if "FROM oms.skill_grants g" in statement:
            assert "p.revision_id=g.revision_id" in statement
            assert "p.version=g.publication_version" in statement
            if (
                self.grant is None
                or self.grant["revision_id"] != self.publication["revision_id"]
                or self.grant["publication_version"] != self.publication["version"]
            ):
                return _Cursor()
            return _Cursor(
                {
                    "revision_id": _REVISION,
                    "publication_version": self.publication["version"],
                    "content_sha256": self.digest,
                    "object_key": "synthetic/socratic.zip",
                    "content_bytes": len(self.payload),
                    "metadata": {"description": "合成提问"},
                }
            )
        if "FROM oms.skill_grants" in statement:
            return _Cursor(self.grant.copy() if self.grant else None)
        if statement.startswith("INSERT INTO oms.skill_grants"):
            self.grant = {
                "revision_id": params[2],
                "publication_version": params[3],
                "status": "active",
                "version": 1,
                "expires_at": params[4],
            }
            return _Cursor()
        if statement.startswith("UPDATE oms.skill_grants SET revision_id"):
            if self.grant is None or self.grant["version"] != params[8]:
                return _Cursor()
            self.grant.update(
                revision_id=params[0],
                publication_version=params[1],
                status="active",
                version=params[2],
                expires_at=params[3],
            )
            return _Cursor({"version": self.grant["version"]})
        if statement.startswith("UPDATE oms.skill_grants SET status='revoked'"):
            if (
                self.revoke_update_missing
                or self.grant is None
                or self.grant["version"] != params[3]
            ):
                return _Cursor()
            self.grant.update(status="revoked", version=params[0])
            return _Cursor({"version": self.grant["version"]})
        if statement.startswith("INSERT INTO management.audit_events"):
            self.audit.append(params)
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

    def get_bytes(self, _ref: ObjectBlobRef):
        self.reads += 1
        return self.payload


@pytest.fixture
def authorized(monkeypatch):
    calls = []

    async def permission(_connection, _actor, action, *, target_school_id, write):
        calls.append((action, target_school_id, write))
        return SimpleNamespace()

    async def publication(connection, _name):
        return connection.publication

    monkeypatch.setattr(
        "deeptutor_enterprise.oms.skill_store.require_management_permission", permission
    )
    monkeypatch.setattr(
        "deeptutor_enterprise.oms.skill_store._current_global_publication", publication
    )
    return calls


def _enterprise():
    payload = _payload()
    connection = _Connection(payload)
    store = _ObjectStore(payload)
    return SimpleNamespace(db=_Database(connection), object_store=store), connection, store


async def test_grant_does_not_overwrite_unknown_old_status(authorized):
    enterprise, connection, _ = _enterprise()
    connection.grant = {
        "revision_id": _REVISION,
        "publication_version": 1,
        "status": "future_status",
        "version": 4,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    with pytest.raises(SkillReviewConflict, match="grant fact"):
        await grant_global_skill(
            enterprise,
            _identity(),
            _SCHOOL,
            "socratic",
            expected_grant_version=4,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            reason="不得覆盖未知状态",
            request_id="invalid-old-status",
        )
    assert connection.grant["status"] == "future_status"
    assert not connection.audit


async def test_revoke_rejects_malformed_old_grant_fact(authorized):
    enterprise, connection, _ = _enterprise()
    connection.grant = {
        "revision_id": _REVISION,
        "publication_version": 0,
        "status": "active",
        "version": 1,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    with pytest.raises(SkillReviewConflict, match="grant fact"):
        await revoke_global_skill(
            enterprise,
            _identity(),
            _SCHOOL,
            "socratic",
            expected_grant_version=1,
            reason="畸形旧事实",
            request_id="invalid-old-version",
        )
    assert connection.grant["status"] == "active"
    assert not connection.audit


async def test_runtime_rejects_unknown_grant_fact_before_loading_object(authorized):
    enterprise, connection, store = _enterprise()
    connection.grant = {
        "revision_id": _REVISION,
        "publication_version": 1,
        "status": "future_status",
        "version": 1,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    with pytest.raises(SkillReviewConflict, match="grant fact"):
        await resolve_authorized_global_skill(enterprise, _SCHOOL, "socratic")
    assert store.reads == 0


@pytest.mark.parametrize(
    "field", ("external_eligibility", "provisioning_status", "recovery_state")
)
async def test_runtime_rejects_unknown_school_business_value_before_grant_lookup(
    authorized, field
):
    enterprise, connection, store = _enterprise()
    connection.tenant_row[field] = "future-value"
    with pytest.raises(ValueError, match=f"tenant {field} has unknown persisted value"):
        await resolve_authorized_global_skill(enterprise, _SCHOOL, "socratic")
    assert store.reads == 0
    assert not any("FROM oms.skill_grants g" in sql for sql, _ in connection.statements)


async def test_revoke_requires_update_cas_confirmation_before_audit(authorized):
    enterprise, connection, _ = _enterprise()
    connection.grant = {
        "revision_id": _REVISION,
        "publication_version": 1,
        "status": "active",
        "version": 1,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    connection.revoke_update_missing = True
    with pytest.raises(SkillReviewConflict, match="version changed"):
        await revoke_global_skill(
            enterprise,
            _identity(),
            _SCHOOL,
            "socratic",
            expected_grant_version=1,
            reason="CAS 必须确认",
            request_id="revoke-missing-row",
        )
    assert connection.grant["status"] == "active"
    assert not connection.audit


async def test_school_grant_revoke_and_expiry_use_explicit_versions(authorized):
    enterprise, connection, store = _enterprise()
    actor = _identity()
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    first = await grant_global_skill(
        enterprise,
        actor,
        _SCHOOL,
        "socratic",
        expected_grant_version=0,
        expires_at=expiry,
        reason="首轮学校授权",
        request_id="grant-1",
    )
    assert (first.grant_version, first.publication_version) == (1, 1)
    assert await resolve_authorized_global_skill(enterprise, _SCHOOL, "socratic")
    assert store.reads == 1
    connection.publication["version"] = 2
    assert await resolve_authorized_global_skill(enterprise, _SCHOOL, "socratic") is None
    connection.publication["version"] = 1
    assert store.reads == 1
    connection.grant["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await resolve_authorized_global_skill(enterprise, _SCHOOL, "socratic") is None
    assert store.reads == 1
    revoked = await revoke_global_skill(
        enterprise,
        actor,
        _SCHOOL,
        "socratic",
        expected_grant_version=1,
        reason="撤销学校授权",
        request_id="revoke-1",
    )
    assert revoked.grant_version == 2
    assert await resolve_authorized_global_skill(enterprise, _SCHOOL, "socratic") is None
    assert store.reads == 1
    connection.publication["version"] = 3
    renewed = await grant_global_skill(
        enterprise,
        actor,
        _SCHOOL,
        "socratic",
        expected_grant_version=2,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        reason="按新发布版本重新授权",
        request_id="grant-2",
    )
    assert (renewed.grant_version, renewed.publication_version) == (3, 3)
    assert len(connection.audit) == 3
    assert all(
        action == "ops.skills.grant" and school == _SCHOOL and write
        for action, school, write in authorized
    )
