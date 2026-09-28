"""已验签 Webhook 不得将已绑定学校的旧未知租户状态覆盖。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

from deeptutor_enterprise.eduplus2.lifecycle import LifecycleEvent
from deeptutor_enterprise.eduplus2.webhook_authority import ingest_authoritative_webhook
import pytest

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, states):
        self.states = states
        self.statements = []

    async def execute(self, statement, _params=None):
        self.statements.append(statement)
        if statement.startswith("INSERT INTO eduplus2.lifecycle_inbox"):
            return _Cursor({"event_id": "synthetic-state-event"})
        if statement.startswith("SELECT b.tenant_id,b.status,b.version"):
            binding = {
                "tenant_id": UUID("10000000-0000-0000-0000-000000000001"),
                "status": "verified",
                "version": 1,
                "external_tid": "10001",
            }
            if "t.external_eligibility" in statement:
                binding.update(self.states)
            return _Cursor(binding)
        if statement.startswith("INSERT INTO eduplus2.webhook_school_state"):
            return _Cursor({"generation": 1})
        if statement.startswith("SELECT eligibility,binding_version,onboarding_event_id"):
            return _Cursor(
                rows=[
                    {
                        "eligibility": "denied",
                        "binding_version": 1,
                        "onboarding_event_id": None,
                        "onboarding_completed_at": None,
                    }
                ]
            )
        return _Cursor()


class _Database:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def transaction(self, _scope):
        yield self.connection


def _event():
    return LifecycleEvent(
        event_id="synthetic-state-event",
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


def _enterprise(connection):
    return SimpleNamespace(
        db=_Database(connection),
        deployment=SimpleNamespace(tenant_id=UUID("20000000-0000-0000-0000-000000000001")),
        eduplus2_webhook_inbox_digest_key="k" * 48,
        eduplus2_webhook_secret="s" * 48,
        eduplus2_webhook_previous_secret="",
    )


@pytest.mark.parametrize(
    ("field", "unknown"),
    [
        ("external_eligibility", "future-eligibility"),
        ("provisioning_status", "future-provisioning"),
        ("recovery_state", "future-recovery"),
    ],
)
async def test_signed_webhook_rejects_unknown_bound_school_values_before_projection(field, unknown):
    states = {
        "external_eligibility": "allowed",
        "provisioning_status": "ready",
        "recovery_state": "normal",
    }
    states[field] = unknown
    connection = _Connection(states)

    with pytest.raises(RuntimeError, match="tenant business state") as error:
        await ingest_authoritative_webhook(
            _enterprise(connection), _event(), delivery_timestamp=1
        )
    assert field in str(error.value.__cause__)
    assert not any(
        statement.startswith("INSERT INTO eduplus2.webhook_school_state")
        for statement in connection.statements
    )


async def test_signed_webhook_preserves_known_bound_school_projection():
    connection = _Connection(
        {
            "external_eligibility": "allowed",
            "provisioning_status": "ready",
            "recovery_state": "normal",
        }
    )

    assert await ingest_authoritative_webhook(
        _enterprise(connection), _event(), delivery_timestamp=1
    ) == "denied"
    assert any(
        statement.startswith("INSERT INTO eduplus2.webhook_school_state")
        for statement in connection.statements
    )
