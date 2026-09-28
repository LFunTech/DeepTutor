"""恢复命令不能把旧租户未知业务状态覆盖为合法值。"""

from contextlib import asynccontextmanager

from deeptutor_enterprise.recovery import RecoveryOperations
import pytest

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self, row):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, tenant):
        self.tenant = tenant
        self.writes = []

    async def execute(self, statement, _params=None):
        if statement.startswith("SELECT pg_try_advisory_xact_lock"):
            return _Cursor({"acquired": True})
        if statement.startswith("SELECT * FROM enterprise.tenants"):
            return _Cursor(self.tenant)
        if statement.startswith("SELECT 1 FROM enterprise.tenants"):
            if (
                self.tenant["auth_epoch"] == _params[1]
                and self.tenant["recovery_state"] == "quarantined"
                and not self.tenant["local_enabled"]
            ):
                return _Cursor({"?column?": 1})
            return _Cursor(None)
        if statement.startswith("SELECT external_eligibility,provisioning_status"):
            return _Cursor(self.tenant)
        self.writes.append(statement)
        return _Cursor(None)


class _Database:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def transaction(self, _scope):
        yield self.connection


@pytest.mark.parametrize(
    ("field", "unknown"),
    [
        ("external_eligibility", "future-eligibility"),
        ("provisioning_status", "future-provisioning"),
        ("recovery_state", "future-recovery"),
    ],
)
async def test_recovery_quarantine_rejects_unknown_tenant_values_before_side_effects(field, unknown):
    tenant = {
        "auth_epoch": "old-epoch",
        "external_eligibility": "allowed",
        "provisioning_status": "ready",
        "recovery_state": "normal",
    }
    tenant[field] = unknown
    connection = _Connection(tenant)
    recovery = RecoveryOperations(
        _Database(connection),
        tenant_id="10000000-0000-0000-0000-000000000001",
        resource="synthetic-recovery",
        auth_epoch="new-epoch",
        maintenance=True,
    )

    with pytest.raises(ValueError, match=field):
        await recovery.quarantine(old_process_confirmed_stopped=True)
    assert connection.writes == []


@pytest.mark.parametrize(
    ("field", "unknown"),
    [
        ("external_eligibility", "future-eligibility"),
        ("provisioning_status", "future-provisioning"),
        ("recovery_state", "future-recovery"),
    ],
)
async def test_recovery_reset_and_release_gate_reject_unknown_tenant_values(field, unknown):
    tenant = {
        "auth_epoch": "new-epoch",
        "local_enabled": False,
        "external_eligibility": "allowed",
        "provisioning_status": "ready",
        "recovery_state": "quarantined",
    }
    tenant[field] = unknown
    connection = _Connection(tenant)
    recovery = RecoveryOperations(
        _Database(connection),
        tenant_id="10000000-0000-0000-0000-000000000001",
        resource="synthetic-recovery",
        auth_epoch="new-epoch",
        maintenance=True,
    )

    with pytest.raises(ValueError, match=field):
        await recovery._quarantined(connection)
    assert connection.writes == []


async def test_recovery_known_quarantine_state_remains_idempotent():
    tenant = {
        "auth_epoch": "new-epoch",
        "external_eligibility": "allowed",
        "provisioning_status": "ready",
        "recovery_state": "quarantined",
    }
    connection = _Connection(tenant)
    recovery = RecoveryOperations(
        _Database(connection),
        tenant_id="10000000-0000-0000-0000-000000000001",
        resource="synthetic-recovery",
        auth_epoch="new-epoch",
        maintenance=True,
    )

    await recovery.quarantine(old_process_confirmed_stopped=True)
    assert connection.writes == []


async def test_recovery_known_quarantine_state_allows_reset_and_release_gate():
    tenant = {
        "auth_epoch": "new-epoch",
        "local_enabled": False,
        "external_eligibility": "allowed",
        "provisioning_status": "ready",
        "recovery_state": "quarantined",
    }
    connection = _Connection(tenant)
    recovery = RecoveryOperations(
        _Database(connection),
        tenant_id="10000000-0000-0000-0000-000000000001",
        resource="synthetic-recovery",
        auth_epoch="new-epoch",
        maintenance=True,
    )

    await recovery._quarantined(connection)
    assert connection.writes == []
