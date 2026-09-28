"""撤销写入口不能依赖 validate_assignment 触发器清理异常旧关联。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from deeptutor_enterprise.management.authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
)
from deeptutor_enterprise.management.grants import RevokeRoleCommand, revoke_management_role
import pytest

pytestmark = pytest.mark.asyncio
SCHOOL_A = UUID("10000000-0000-0000-0000-000000000001")
SCHOOL_B = UUID("10000000-0000-0000-0000-000000000002")
PRINCIPAL = UUID("20000000-0000-0000-0000-000000000001")
ASSIGNMENT = UUID("30000000-0000-0000-0000-000000000001")


class _Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, *, principal_school=SCHOOL_B, role_scope="school"):
        self.principal_school = principal_school
        self.role_scope = role_scope
        self.statements = []

    async def execute(self, statement, _params=None):
        self.statements.append(statement)
        if "SELECT principal_id FROM management.assignments" in statement:
            return _Cursor((PRINCIPAL,))
        if "FROM management.principals" in statement:
            return _Cursor((PRINCIPAL, 1, self.principal_school))
        if "FROM management.assignments" in statement and "FOR UPDATE" in statement:
            now = datetime.now(timezone.utc)
            return _Cursor(
                (
                    PRINCIPAL,
                    1,
                    "active",
                    "school_admin",
                    1,
                    now - timedelta(minutes=1),
                    now + timedelta(hours=1),
                )
            )
        if "FROM management.role_versions" in statement:
            return _Cursor((self.role_scope,))
        return _Cursor()


def _identity():
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="tms",
        issuer="https://synthetic-issuer.example",
        subject="synthetic-admin",
        school_id=SCHOOL_A,
        policy_version=1,
        school_binding_version=1,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )


def _command():
    return RevokeRoleCommand(
        assignment_id=ASSIGNMENT,
        target_school_id=SCHOOL_A,
        expected_assignment_version=1,
        expected_target_policy_version=1,
        command_id=uuid4(),
        reason="合成撤销",
        request_id="revoke-assignment-relation",
    )


@pytest.mark.parametrize(
    ("principal_school", "role_scope"),
    [(SCHOOL_B, "school"), (SCHOOL_A, "platform")],
)
async def test_revoke_rejects_invalid_relation_before_assignment_update(
    monkeypatch, principal_school, role_scope
):
    async def authorized(*_args, **_kwargs):
        return SimpleNamespace()

    monkeypatch.setattr(
        "deeptutor_enterprise.management.grants.require_management_permission", authorized
    )
    connection = _Connection(principal_school=principal_school, role_scope=role_scope)
    with pytest.raises(ManagementAuthorizationDenied, match="assignment relation"):
        await revoke_management_role(connection, _identity(), _command())
    assert not any(sql.startswith("UPDATE management.assignments") for sql in connection.statements)
