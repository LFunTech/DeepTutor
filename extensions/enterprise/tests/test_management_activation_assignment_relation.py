"""首管理员写入 assignment 前，程序复核角色目录而非依赖旧触发器。"""

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
SCHOOL = UUID("10000000-0000-0000-0000-000000000001")
OWNER = UUID("20000000-0000-0000-0000-000000000001")


class _Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, role_scope):
        self.role_scope = role_scope
        self.statements = []

    async def execute(self, statement, _params=None):
        self.statements.append(statement)
        if statement.startswith("SELECT b.eduplus_tenant_id,b.version"):
            return _Cursor(
                {
                    "eduplus_tenant_id": 10001,
                    "version": 1,
                    "bootstrap_completed": False,
                    "external_eligibility": "allowed",
                    "provisioning_status": "pending",
                    "recovery_state": "normal",
                }
            )
        if "FROM eduplus2.webhook_school_state" in statement:
            return _Cursor({
                "generation": 1,
                "eligibility": "allowed",
                "binding_version": 1,
                "database_initialized": True,
            })
        if "FROM eduplus2.lifecycle_actor_candidates" in statement:
            return _Cursor(
                {
                    "school_id": SCHOOL,
                    "external_tenant_id": 10001,
                    "external_app_id": 51,
                    "binding_version": 1,
                    "actor_issuer": "https://synthetic-issuer.example",
                    "actor_subject": "synthetic-admin",
                    "status": "pending_verification",
                }
            )
        if "FROM management.role_versions" in statement:
            return _Cursor({"scope_kind": self.role_scope} if self.role_scope else None)
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
        subject="synthetic-admin",
        school_id=SCHOOL,
        policy_version=1,
        school_binding_version=1,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
        webhook_app_id=51,
    )


@pytest.mark.parametrize("role_scope", [None, "platform", "future-scope"])
async def test_activation_rejects_missing_or_wrong_role_scope_before_assignment_write(role_scope):
    connection = _Connection(role_scope)
    enterprise = SimpleNamespace(
        db=_Database(connection),
        deployment=SimpleNamespace(tenant_id=OWNER),
        eduplus2_lifecycle_receiver_enabled=True,
        eduplus2_issuer="https://synthetic-issuer.example",
    )
    with pytest.raises(ManagementAuthorizationDenied, match="assignment relation"):
        await activate_first_school_administrator(
            enterprise, _identity(), event_id="signed-event", request_id="activate-1"
        )
    assert not any(
        sql.startswith("INSERT INTO management.assignments") for sql in connection.statements
    )
