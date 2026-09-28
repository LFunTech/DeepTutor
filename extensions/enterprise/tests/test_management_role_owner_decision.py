"""管理 PEP 不得把另一学校自定义角色的 assignment 当作当前学校权限。"""

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
_SCHOOL_A = UUID("10000000-0000-0000-0000-000000000001")
_SCHOOL_B = UUID("10000000-0000-0000-0000-000000000002")
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

    def __init__(self, assignment):
        now = datetime.now(timezone.utc)
        self.assignment = {
            "id": assignment[0],
            "version": assignment[1],
            "is_template": assignment[2],
            "owner_school_id": assignment[3],
            "role_key": assignment[4],
            "action_owner_school_id": assignment[5],
            "status": "active",
            "valid_from": now - timedelta(minutes=1),
            "expires_at": now + timedelta(hours=1),
            "school_binding_version": 1,
            "action_status": "active",
            "allowed_scope": "school",
            "scope_kind": "school",
            "school_id": _SCHOOL_B,
            "revoked_at": None,
            "application": "tms",
            "role_scope_kind": "school",
        }

    async def execute(self, statement, _params=None):
        if statement.startswith("SELECT current_setting('app.tenant_id'"):
            return _Cursor((str(_SCHOOL_B),))
        if "FROM management.principals" in statement:
            return _Cursor((_PRINCIPAL, _SCHOOL_B, "active", 1))
        if "FROM oms.school_bindings" in statement:
            return _Cursor((1, True, True, "ready", "normal", 101, None, "allowed"))
        if "FROM management.assignments a" in statement:
            return _Cursor(self.assignment, [self.assignment])
        return _Cursor()


def _identity():
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="tms",
        issuer="https://synthetic-issuer.example",
        subject="school-admin",
        school_id=_SCHOOL_B,
        policy_version=1,
        school_binding_version=1,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )


async def test_tms_permission_denies_other_schools_custom_role_assignment():
    assignment = (_ASSIGNMENT, 1, False, _SCHOOL_A, f"custom_{_SCHOOL_A.hex}_readers", _SCHOOL_A)
    with pytest.raises(ManagementAuthorizationDenied, match="role owner"):
        await require_management_permission(
            _Connection(assignment),
            _identity(),
            "tenant.members.read",
            target_school_id=_SCHOOL_B,
            write=True,
        )


async def test_tms_permission_accepts_school_template_assignment():
    assignment = (_ASSIGNMENT, 1, True, None, "school_auditor", None)
    result = await require_management_permission(
        _Connection(assignment),
        _identity(),
        "tenant.members.read",
        target_school_id=_SCHOOL_B,
        write=True,
    )
    assert result.assignment_id == _ASSIGNMENT


async def test_tms_permission_accepts_own_schools_custom_role_assignment():
    assignment = (
        _ASSIGNMENT,
        1,
        False,
        _SCHOOL_B,
        f"custom_{_SCHOOL_B.hex}_readers",
        _SCHOOL_B,
    )
    result = await require_management_permission(
        _Connection(assignment),
        _identity(),
        "tenant.members.read",
        target_school_id=_SCHOOL_B,
        write=True,
    )
    assert result.assignment_id == _ASSIGNMENT


async def test_tms_permission_denies_role_action_owner_drift():
    assignment = (
        _ASSIGNMENT,
        1,
        False,
        _SCHOOL_B,
        f"custom_{_SCHOOL_B.hex}_readers",
        _SCHOOL_A,
    )
    with pytest.raises(ManagementAuthorizationDenied, match="role owner"):
        await require_management_permission(
            _Connection(assignment),
            _identity(),
            "tenant.members.read",
            target_school_id=_SCHOOL_B,
            write=True,
        )
