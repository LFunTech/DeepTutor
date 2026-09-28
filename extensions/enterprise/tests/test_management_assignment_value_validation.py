"""移除管理 assignment 的枚举 CHECK 前，PEP 必须自己判定旧行。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

from deeptutor_enterprise.management.authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
    require_management_permission,
)
import pytest

pytestmark = pytest.mark.asyncio
_SCHOOL = UUID("10000000-0000-0000-0000-000000000001")
_PRINCIPAL = UUID("20000000-0000-0000-0000-000000000001")
_ASSIGNMENT = UUID("30000000-0000-0000-0000-000000000001")


class _Cursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        return self.rows


class _Connection:
    autocommit = False
    info = SimpleNamespace(transaction_status=None)

    def __init__(self, assignments):
        self.assignments = assignments
        self.assignment_sql = ""

    async def execute(self, statement, _params=None):
        if statement.startswith("SELECT current_setting('app.tenant_id'"):
            return _Cursor((str(_SCHOOL),))
        if "FROM management.principals" in statement:
            return _Cursor((_PRINCIPAL, _SCHOOL, "active", 1))
        if "FROM oms.school_bindings" in statement:
            return _Cursor((1, True, True, "ready", "normal", 101, None, "allowed"))
        if "FROM management.assignments a" in statement:
            self.assignment_sql = statement
            return _Cursor(rows=self.assignments)
        return _Cursor()


def _identity():
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="tms",
        issuer="https://synthetic-issuer.example",
        subject="synthetic-admin",
        school_id=_SCHOOL,
        policy_version=1,
        school_binding_version=1,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )


def _assignment(**overrides):
    now = datetime.now(timezone.utc)
    row = {
        "id": _ASSIGNMENT,
        "version": 1,
        "is_template": True,
        "owner_school_id": None,
        "role_key": "school_auditor",
        "action_owner_school_id": None,
        "status": "active",
        "valid_from": now - timedelta(minutes=1),
        "expires_at": now + timedelta(hours=1),
        "school_binding_version": 1,
        "action_status": "active",
        "allowed_scope": "school",
        "scope_kind": "school",
        "school_id": _SCHOOL,
        "revoked_at": None,
        "application": "tms",
        "role_scope_kind": "school",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    "change",
    [
        {"status": "future"},
        {"scope_kind": "future"},
        {"version": 0},
        {"action_status": "future"},
        {"allowed_scope": "future"},
        {"school_binding_version": None},
        {"valid_from": datetime.now(timezone.utc) + timedelta(hours=2)},
        {"revoked_at": datetime.now(timezone.utc)},
        {"role_scope_kind": "platform"},
    ],
)
async def test_permission_rejects_malformed_assignment_fact(change):
    connection = _Connection([_assignment(**change)])
    with pytest.raises(ManagementAuthorizationDenied, match="assignment fact"):
        await require_management_permission(
            connection,
            _identity(),
            "tenant.members.read",
            target_school_id=_SCHOOL,
            write=True,
        )


async def test_permission_selects_only_current_active_matching_assignment():
    connection = _Connection(
        [
            _assignment(
                id=UUID("30000000-0000-0000-0000-000000000002"),
                status="revoked",
                revoked_at=datetime.now(timezone.utc),
            ),
            _assignment(
                id=UUID("30000000-0000-0000-0000-000000000003"),
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            ),
            _assignment(),
        ]
    )
    decision = await require_management_permission(
        connection,
        _identity(),
        "tenant.members.read",
        target_school_id=_SCHOOL,
        write=True,
    )
    assert decision.assignment_id == _ASSIGNMENT
    assert "a.status='active'" not in connection.assignment_sql
    assert "ac.status='active'" not in connection.assignment_sql


async def test_permission_retired_action_does_not_grant():
    connection = _Connection([_assignment(action_status="retired")])
    with pytest.raises(ManagementAuthorizationDenied, match="not granted"):
        await require_management_permission(
            connection,
            _identity(),
            "tenant.members.read",
            target_school_id=_SCHOOL,
            write=True,
        )
