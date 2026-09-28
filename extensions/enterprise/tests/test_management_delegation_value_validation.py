"""撤销数据库状态约束前，委托读取须由程序拒绝未知或畸形存量事实。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

from deeptutor_enterprise.management.authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
    require_management_delegation,
)
import pytest

pytestmark = pytest.mark.asyncio
_SCHOOL = UUID("10000000-0000-0000-0000-000000000001")
_PRINCIPAL = UUID("20000000-0000-0000-0000-000000000001")
_DELEGATION = UUID("30000000-0000-0000-0000-000000000001")


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    async def execute(self, statement, _params=None):
        self.statements.append(statement)
        return _Cursor(self.rows)


def _identity(application="tms"):
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application=application,
        issuer="https://synthetic-issuer.example",
        subject="synthetic-admin",
        school_id=_SCHOOL if application == "tms" else None,
        policy_version=1,
        school_binding_version=1 if application == "tms" else None,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )


def _row(**overrides):
    now = datetime.now(timezone.utc)
    values = {
        "id": _DELEGATION,
        "version": 1,
        "status": "active",
        "valid_from": now - timedelta(minutes=1),
        "expires_at": now + timedelta(hours=1),
        "scope_kind": "school",
        "school_id": _SCHOOL,
        "action_status": "active",
        "allowed_scope": "school",
    }
    values.update(overrides)
    return values


@pytest.fixture
def authorized(monkeypatch):
    async def permission(*_args, **_kwargs):
        return SimpleNamespace(principal_id=_PRINCIPAL, school_binding_version=1)

    monkeypatch.setattr(
        "deeptutor_enterprise.management.authorization.require_management_permission", permission
    )


@pytest.mark.parametrize(
    "change",
    [
        {"status": "future-status"},
        {"scope_kind": "future-scope"},
        {"version": 0},
        {"school_id": None},
        {"action_status": "future-action-status"},
        {"allowed_scope": "future-action-scope"},
    ],
)
async def test_delegation_denies_unknown_old_fact_before_authorization(authorized, change):
    connection = _Connection([_row(**change)])
    with pytest.raises(ManagementAuthorizationDenied, match="delegation fact"):
        await require_management_delegation(
            connection,
            _identity(),
            "tenant.members.read",
            target_school_id=_SCHOOL,
            grant_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )


async def test_delegation_allows_current_active_fact_and_denies_retired_action(authorized):
    valid = _Connection([_row()])
    decision = await require_management_delegation(
        valid,
        _identity(),
        "tenant.members.read",
        target_school_id=_SCHOOL,
        grant_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    assert decision.delegation_id == _DELEGATION
    retired = _Connection([_row(action_status="retired")])
    with pytest.raises(ManagementAuthorizationDenied, match="delegation is not granted"):
        await require_management_delegation(
            retired,
            _identity(),
            "tenant.members.read",
            target_school_id=_SCHOOL,
            grant_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )


async def test_oms_delegation_rejects_known_but_mismatched_action_scope(authorized):
    connection = _Connection([_row(allowed_scope="platform")])
    with pytest.raises(ManagementAuthorizationDenied, match="delegation fact"):
        await require_management_delegation(
            connection,
            _identity("oms"),
            "ops.tenants.read",
            target_school_id=_SCHOOL,
            grant_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
