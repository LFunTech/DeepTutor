"""自定义角色版本只能由同应用授权服务追加。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from deeptutor_enterprise.management.authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
)
from deeptutor_enterprise.management.roles import (
    CustomRoleConflict,
    PublishCustomRoleCommand,
    publish_custom_role,
)
import pytest

pytestmark = pytest.mark.asyncio
_SCHOOL = UUID("10000000-0000-0000-0000-000000000001")


class _Cursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self):
        self.latest = None
        self.actions = {
            "tenant.members.read": ("school", "active", False),
            "tenant.clients.manage": ("school", "active", True),
            "tenant.usage.read": ("school", "retired", False),
            "ops.providers.read": ("platform", "active", False),
            "ops.oms.access": ("both", "active", False),
            "ops.credentials.manage": ("platform", "active", True),
            "ops.cost.read": ("platform", "retired", True),
        }
        self.role_actions = []
        self.action_owner = None
        self.audit = {}
        self.statements = []

    async def execute(self, statement, params=None):
        self.statements.append((statement, params))
        if statement.startswith("SELECT pg_advisory_xact_lock"):
            return _Cursor()
        if "FROM management.audit_events WHERE id=%s" in statement:
            return _Cursor(self.audit.get(params[0]))
        if "FROM management.role_versions" in statement and "ORDER BY version DESC" in statement:
            return _Cursor(self.latest)
        if "FROM management.role_versions" in statement and "AND version=%s" in statement:
            return _Cursor(self.latest if self.latest and self.latest[0] == params[2] else None)
        if "FROM management.action_catalog" in statement:
            value = self.actions.get(params[1])
            return _Cursor(value)
        if "FROM management.role_actions" in statement:
            return _Cursor(
                rows=[(action, self.action_owner) for action in sorted(self.role_actions)]
            )
        if statement.startswith("INSERT INTO management.role_versions"):
            self.latest = (params[2], params[3], False, params[4])
            return _Cursor()
        if statement.startswith("INSERT INTO management.role_actions"):
            self.role_actions.append(params[3])
            self.action_owner = params[4]
            return _Cursor()
        if statement.startswith("INSERT INTO management.audit_events"):
            self.audit[params[0]] = (
                params[1],
                params[2],
                params[3],
                params[4],
                params[5],
                "role_version",
                params[6],
                params[7],
                "success",
                params[8],
                params[9],
                params[10],
                params[11].obj,
            )
            return _Cursor()
        raise AssertionError(statement)


def _identity(application="tms"):
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application=application,
        issuer="https://synthetic-issuer.example",
        subject="synthetic-admin",
        school_id=_SCHOOL if application == "tms" else None,
        policy_version=3,
        school_binding_version=1 if application == "tms" else None,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )


def _command(**overrides):
    values = {
        "role_key": "custom_readers",
        "scope_kind": "platform",
        "target_school_id": None,
        "action_keys": ("ops.providers.read",),
        "expected_version": 0,
        "command_id": uuid4(),
        "reason": "合成测试角色",
        "request_id": "request-1",
    }
    values.update(overrides)
    return PublishCustomRoleCommand(**values)


@pytest.fixture
def authorized(monkeypatch):
    calls = []

    async def permission(_connection, actor, action, **kwargs):
        calls.append(("permission", actor.application, action, kwargs))
        return SimpleNamespace(principal_id=UUID("20000000-0000-0000-0000-000000000001"))

    async def delegation(_connection, actor, action, **kwargs):
        calls.append(("delegation", actor.application, action, kwargs))
        return SimpleNamespace()

    monkeypatch.setattr(
        "deeptutor_enterprise.management.roles.require_management_permission", permission
    )
    monkeypatch.setattr(
        "deeptutor_enterprise.management.roles.require_management_delegation", delegation
    )
    return calls


async def test_publish_custom_role_uses_cas_audit_and_exact_replay(authorized):
    connection = _Connection()
    command = _command()

    result = await publish_custom_role(connection, _identity("oms"), command)
    assert result.version == 1 and not result.replayed
    assert connection.latest == (1, "platform", False, None)
    assert connection.role_actions == ["ops.providers.read"]
    assert len(connection.audit) == 1
    assert any(call[0] == "delegation" for call in authorized)

    replay = await publish_custom_role(connection, _identity("oms"), command)
    assert replay.version == 1 and replay.replayed
    assert connection.role_actions == ["ops.providers.read"]
    with pytest.raises(CustomRoleConflict, match="idempotency"):
        await publish_custom_role(
            connection, _identity("oms"), _command(command_id=command.command_id, reason="changed")
        )

    second = await publish_custom_role(
        connection,
        _identity("oms"),
        _command(
            expected_version=1,
            action_keys=("ops.providers.read", "ops.oms.access"),
        ),
    )
    assert second.version == 2
    assert second.action_keys == ("ops.oms.access", "ops.providers.read")
    assert not any(
        sql.startswith("UPDATE management.assignments") for sql, _ in connection.statements
    )


@pytest.mark.parametrize(
    ("action_keys", "error"),
    [
        (("tenant.members.read",), "application"),
        (("ops.cost.read",), "retired"),
    ],
)
async def test_custom_role_rejects_cross_application_and_retired_actions(
    authorized, action_keys, error
):
    connection = _Connection()
    with pytest.raises(ManagementAuthorizationDenied, match=error):
        await publish_custom_role(connection, _identity("oms"), _command(action_keys=action_keys))
    assert connection.latest is None


async def test_custom_role_sensitive_action_requires_independent_approval(authorized):
    connection = _Connection()
    with pytest.raises(ManagementAuthorizationDenied, match="sensitive"):
        await publish_custom_role(
            connection, _identity("oms"), _command(action_keys=("ops.credentials.manage",))
        )
    assert connection.latest is None


async def test_custom_role_cannot_overwrite_template_or_skip_expected_version(authorized):
    connection = _Connection()
    connection.latest = (1, "platform", True, None)
    with pytest.raises(CustomRoleConflict, match="template"):
        await publish_custom_role(connection, _identity("oms"), _command(expected_version=1))
    connection.latest = (1, "platform", False, None)
    with pytest.raises(CustomRoleConflict, match="version"):
        await publish_custom_role(connection, _identity("oms"), _command(expected_version=0))


async def test_school_custom_role_uses_school_owned_physical_key(authorized):
    connection = _Connection()
    result = await publish_custom_role(
        connection,
        _identity(),
        _command(
            scope_kind="school",
            target_school_id=_SCHOOL,
            action_keys=("tenant.members.read",),
        ),
    )
    assert result.role_key == f"custom_{_SCHOOL.hex}_readers"
    assert connection.role_actions == ["tenant.members.read"]


async def test_school_custom_role_replay_rejects_action_owner_drift(authorized):
    connection = _Connection()
    command = _command(
        scope_kind="school", target_school_id=_SCHOOL, action_keys=("tenant.members.read",)
    )
    await publish_custom_role(connection, _identity(), command)
    connection.action_owner = UUID("10000000-0000-0000-0000-000000000002")
    with pytest.raises(CustomRoleConflict, match="drifted"):
        await publish_custom_role(connection, _identity(), command)
