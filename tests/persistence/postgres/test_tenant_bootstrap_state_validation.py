"""Core 首次管理员 bootstrap 不得覆盖或信任租户历史未知业务状态。"""

from contextlib import asynccontextmanager

import pytest

from deeptutor.persistence.postgres.identity.service import IdentityService

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, tenant):
        self.tenant = tenant
        self.statements = []

    async def execute(self, statement, _params=None):
        statement = statement.strip()
        self.statements.append(statement)
        if statement.startswith("SELECT * FROM enterprise.tenants"):
            return _Cursor(self.tenant)
        if statement.startswith("SELECT id,username,role FROM enterprise.users"):
            return _Cursor({"id": "known-admin", "username": "admin", "role": "tenant_admin"})
        return _Cursor()


class _Database:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def transaction(self, _scope):
        yield self.connection


def _service(connection):
    return IdentityService(
        _Database(connection),
        tenant_id="10000000-0000-0000-0000-000000000001",
        signing_key="s" * 48,
        auth_epoch="synthetic-epoch",
        bootstrap_secret="b" * 48,
    )


@pytest.mark.parametrize(
    ("field", "unknown"),
    [
        ("external_eligibility", "future-eligibility"),
        ("provisioning_status", "future-provisioning"),
        ("recovery_state", "future-recovery"),
    ],
)
@pytest.mark.parametrize("completed", [False, True])
async def test_bootstrap_rejects_unknown_existing_tenant_before_admin_creation(
    monkeypatch, field, unknown, completed
):
    async def _hash(_password):
        return "synthetic-password-hash"

    monkeypatch.setattr(IdentityService, "_hash", staticmethod(_hash))
    tenant = {
        "bootstrap_completed": completed,
        "external_eligibility": "not_required",
        "provisioning_status": "ready",
        "recovery_state": "normal",
    }
    tenant[field] = unknown
    connection = _Connection(tenant)

    with pytest.raises(ValueError, match=field):
        await _service(connection)._bootstrap_user(
            "admin", "synthetic-long-password", secret="b" * 48
        )
    assert not any(
        statement.startswith("INSERT INTO enterprise.users")
        or statement.startswith("UPDATE enterprise.tenants")
        for statement in connection.statements
    )


@pytest.mark.parametrize("completed", [False, True])
async def test_bootstrap_known_tenant_preserves_create_and_replay(monkeypatch, completed):
    async def _hash(_password):
        return "synthetic-password-hash"

    monkeypatch.setattr(IdentityService, "_hash", staticmethod(_hash))
    connection = _Connection(
        {
            "bootstrap_completed": completed,
            "external_eligibility": "not_required",
            "provisioning_status": "ready",
            "recovery_state": "normal",
        }
    )

    admin = await _service(connection)._bootstrap_user(
        "admin", "synthetic-long-password", secret="b" * 48
    )
    assert admin["role"] == "tenant_admin"
    assert any(
        statement.startswith("INSERT INTO enterprise.users") for statement in connection.statements
    ) is not completed
