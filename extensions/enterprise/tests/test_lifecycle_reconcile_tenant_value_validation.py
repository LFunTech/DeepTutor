"""历史在线对账兼容入口也不得覆盖租户历史未知状态。"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from deeptutor_enterprise.eduplus2.lifecycle import (
    LifecycleEvent,
    _reconcile_lifecycle_target_locked,
    ingest_lifecycle_event,
)
import pytest

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self, row=None, rows=()):
        self.row = row
        self.rows = list(rows)

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, tenant):
        self.tenant = tenant
        self.statements = []
        self.now = datetime.now(timezone.utc)

    async def execute(self, statement, _params=None):
        self.statements.append(statement)
        if statement.startswith("SELECT generation,eligibility"):
            return _Cursor(
                {
                    "generation": 1,
                    "eligibility": "unknown",
                    "verified_client_id": "",
                    "proof_checked_at": None,
                    "proof_expires_at": None,
                    "binding_version": 0,
                }
            )
        if statement.startswith("SELECT b.tenant_id,b.version FROM oms.school_bindings"):
            return _Cursor(
                {"tenant_id": UUID("10000000-0000-0000-0000-000000000001"), "version": 1}
            )
        if statement.startswith("SELECT DISTINCT client_id FROM"):
            return _Cursor(rows=[])
        if statement.startswith("SELECT clock_timestamp() AS checked_at"):
            return _Cursor({"checked_at": self.now})
        if statement.startswith("SELECT clock_timestamp() AS current_time"):
            return _Cursor({"current_time": self.now})
        if statement.startswith("SELECT generation,proof_checked_at"):
            return _Cursor(
                {
                    "generation": 1,
                    "proof_checked_at": None,
                    "eligibility": "unknown",
                    "verified_client_id": "",
                    "proof_expires_at": None,
                    "binding_version": 0,
                }
            )
        if statement.startswith("SELECT version FROM oms.school_bindings"):
            return _Cursor({"version": 1})
        if statement.startswith("SELECT external_eligibility,provisioning_status"):
            return _Cursor(self.tenant)
        return _Cursor()


class _Database:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def transaction(self, _scope):
        yield self.connection


def _enterprise(connection):
    return SimpleNamespace(
        db=_Database(connection),
        deployment=SimpleNamespace(tenant_id=UUID("20000000-0000-0000-0000-000000000001")),
        eduplus2_resolver=None,
        eduplus2_issuer="",
    )


@pytest.mark.parametrize(
    ("field", "unknown"),
    [
        ("external_eligibility", "future-eligibility"),
        ("provisioning_status", "future-provisioning"),
        ("recovery_state", "future-recovery"),
    ],
)
async def test_legacy_reconcile_rejects_unknown_tenant_values_before_update(field, unknown):
    tenant = {
        "external_eligibility": "allowed",
        "provisioning_status": "ready",
        "recovery_state": "normal",
    }
    tenant[field] = unknown
    connection = _Connection(tenant)

    with pytest.raises(ValueError, match=field):
        await _reconcile_lifecycle_target_locked(
            _enterprise(connection), external_tenant_id=10001, external_app_id=51
        )
    assert not any(
        statement.startswith("UPDATE enterprise.tenants") for statement in connection.statements
    )


async def test_legacy_reconcile_keeps_known_tenant_update_path():
    connection = _Connection(
        {
            "external_eligibility": "allowed",
            "provisioning_status": "ready",
            "recovery_state": "normal",
        }
    )

    assert await _reconcile_lifecycle_target_locked(
        _enterprise(connection), external_tenant_id=10001, external_app_id=51
    ) == "unknown"
    assert any(
        statement.startswith("UPDATE enterprise.tenants") for statement in connection.statements
    )


async def test_legacy_reconcile_missing_locked_tenant_is_stale_without_update():
    connection = _Connection(None)

    assert await _reconcile_lifecycle_target_locked(
        _enterprise(connection), external_tenant_id=10001, external_app_id=51
    ) == "stale"
    assert not any(
        statement.startswith("UPDATE enterprise.tenants") for statement in connection.statements
    )


class _NotificationConnection:
    def __init__(self, tenant):
        self.tenant = tenant
        self.statements = []

    async def execute(self, statement, _params=None):
        statement = statement.strip()
        self.statements.append(statement)
        if statement.startswith("INSERT INTO eduplus2.lifecycle_inbox"):
            return _Cursor({"event_id": "synthetic-legacy-event"})
        if statement.startswith("SELECT 1 FROM oms.school_bindings"):
            return _Cursor({"?column?": 1} if self.tenant is not None else None)
        if statement.startswith("SELECT t.id,t.external_eligibility"):
            return _Cursor(self.tenant)
        return _Cursor()


def _notification_event():
    return LifecycleEvent(
        event_id="synthetic-legacy-event",
        event_type="subscription.suspended",
        external_tenant_id=10001,
        external_app_id=51,
        external_subscription_id=20001,
        subscription_status="suspended",
        client_id="",
        actor_type="",
        actor_subject="",
        tenant_type="school",
        school_code="synthetic-school",
        semantic_digest="d" * 64,
    )


def _notification_enterprise(connection):
    enterprise = _enterprise(connection)
    enterprise.eduplus2_webhook_inbox_digest_key = "k" * 48
    enterprise.eduplus2_webhook_secret = "s" * 48
    enterprise.eduplus2_webhook_previous_secret = ""
    return enterprise


@pytest.mark.parametrize(
    ("field", "unknown"),
    [
        ("external_eligibility", "future-eligibility"),
        ("provisioning_status", "future-provisioning"),
        ("recovery_state", "future-recovery"),
    ],
)
async def test_legacy_notification_rejects_unknown_bound_tenant_before_projection(field, unknown):
    tenant = {
        "id": UUID("10000000-0000-0000-0000-000000000001"),
        "external_eligibility": "allowed",
        "provisioning_status": "ready",
        "recovery_state": "normal",
    }
    tenant[field] = unknown
    connection = _NotificationConnection(tenant)

    with pytest.raises(ValueError, match=field):
        await ingest_lifecycle_event(
            _notification_enterprise(connection), _notification_event(), delivery_timestamp=1
        )
    assert not any(
        statement.startswith("INSERT INTO eduplus2.lifecycle_targets")
        for statement in connection.statements
    )


@pytest.mark.parametrize(
    ("eligibility", "expected_update"),
    [("allowed", True), ("denied", False), ("not_required", False)],
)
async def test_legacy_notification_updates_only_known_allowed_school(eligibility, expected_update):
    connection = _NotificationConnection(
        {
            "id": UUID("10000000-0000-0000-0000-000000000001"),
            "external_eligibility": eligibility,
            "provisioning_status": "ready",
            "recovery_state": "normal",
        }
    )

    assert await ingest_lifecycle_event(
        _notification_enterprise(connection), _notification_event(), delivery_timestamp=1
    ) == "pending_reconcile"
    assert any(
        statement.startswith("UPDATE enterprise.tenants") for statement in connection.statements
    ) is expected_update


async def test_legacy_notification_unbound_school_remains_pending_binding():
    connection = _NotificationConnection(None)

    assert await ingest_lifecycle_event(
        _notification_enterprise(connection), _notification_event(), delivery_timestamp=1
    ) == "pending_binding"
    assert not any(
        statement.startswith("UPDATE enterprise.tenants") for statement in connection.statements
    )
