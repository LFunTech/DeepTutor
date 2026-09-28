"""首位学校管理员激活不能忽略租户历史未知状态。"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

from deeptutor_enterprise.management.actor_activation import activate_first_school_administrator
from deeptutor_enterprise.management.authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
)
import pytest

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, school):
        self.school = school
        self.statements = []

    async def execute(self, statement, _params=None):
        self.statements.append(statement)
        if statement.startswith("SELECT b.eduplus_tenant_id,b.version"):
            if "t.recovery_state='normal'" in statement and self.school["recovery_state"] != "normal":
                return _Cursor()
            row = {
                "eduplus_tenant_id": 10001,
                "version": 1,
                "bootstrap_completed": False,
            }
            if "t.external_eligibility" in statement:
                row.update(self.school)
            return _Cursor(row)
        return _Cursor()


class _Database:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def transaction(self, _scope):
        yield self.connection


def _identity():
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="tms",
        issuer="https://synthetic-issuer.example",
        subject="synthetic-user",
        school_id=UUID("10000000-0000-0000-0000-000000000001"),
        policy_version=1,
        school_binding_version=1,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
        webhook_app_id=51,
    )


def _enterprise(connection):
    return SimpleNamespace(
        db=_Database(connection),
        deployment=SimpleNamespace(tenant_id=UUID("20000000-0000-0000-0000-000000000001")),
        eduplus2_lifecycle_receiver_enabled=True,
        eduplus2_issuer="https://synthetic-issuer.example",
    )


@pytest.mark.parametrize(
    ("field", "unknown"),
    [
        ("external_eligibility", "future-eligibility"),
        ("provisioning_status", "future-provisioning"),
        ("recovery_state", "future-recovery"),
    ],
)
async def test_first_admin_activation_rejects_unknown_school_values_before_projection(
    field, unknown
):
    school = {
        "external_eligibility": "allowed",
        "provisioning_status": "pending",
        "recovery_state": "normal",
    }
    school[field] = unknown
    connection = _Connection(school)

    with pytest.raises(ManagementAuthorizationDenied, match="school lifecycle or state"):
        await activate_first_school_administrator(
            _enterprise(connection), _identity(), event_id="synthetic-event", request_id="request-1"
        )
    assert not any("FROM eduplus2.webhook_school_state" in sql for sql in connection.statements)


@pytest.mark.parametrize(
    ("field", "value"),
    [("external_eligibility", "denied"), ("recovery_state", "quarantined")],
)
async def test_first_admin_activation_rejects_ineligible_school_before_projection(field, value):
    school = {
        "external_eligibility": "allowed",
        "provisioning_status": "pending",
        "recovery_state": "normal",
    }
    school[field] = value
    connection = _Connection(school)

    with pytest.raises(ManagementAuthorizationDenied, match="school lifecycle or state"):
        await activate_first_school_administrator(
            _enterprise(connection), _identity(), event_id="synthetic-event", request_id="request-1"
        )
    assert not any("FROM eduplus2.webhook_school_state" in sql for sql in connection.statements)


@pytest.mark.parametrize("provisioning_status", ["pending", "ready", "failed"])
async def test_first_admin_activation_does_not_require_ai_resource_readiness(provisioning_status):
    connection = _Connection(
        {
            "external_eligibility": "allowed",
            "provisioning_status": provisioning_status,
            "recovery_state": "normal",
        }
    )

    with pytest.raises(ManagementAuthorizationDenied, match="school webhook projection is unavailable"):
        await activate_first_school_administrator(
            _enterprise(connection), _identity(), event_id="synthetic-event", request_id="request-1"
        )
    assert any("FROM eduplus2.webhook_school_state" in sql for sql in connection.statements)
