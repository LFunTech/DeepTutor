"""Core 登录与已有会话均须在程序内检查学校恢复状态。"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from deeptutor.persistence.postgres.identity import accounts as accounts_module
from deeptutor.persistence.postgres.identity import service as identity_module
from deeptutor.persistence.postgres.identity.service import IdentityService

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def execute(self, statement, _params=None):
        statement = statement.strip()
        self.statements.append(statement)
        if statement.startswith("SELECT u.*,lc.password_hash"):
            return _Cursor(self.row)
        if statement.startswith("SELECT u.id,u.username,u.role"):
            return _Cursor(self.row)
        if statement.startswith("SELECT d.*,u.username"):
            return _Cursor(self.row)
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


def _account_row(recovery_state):
    return {
        "id": "synthetic-user",
        "username": "admin",
        "role": "tenant_admin",
        "preset": "standard",
        "password_hash": "synthetic-hash",
        "disabled": False,
        "deleted_at": None,
        "local_enabled": True,
        "external_eligibility": "not_required",
        "provisioning_status": "ready",
        "recovery_state": recovery_state,
        "auth_epoch": "synthetic-epoch",
        "auth_version": 1,
        "session_id": "synthetic-session",
        "device_credential_id": None,
    }


def _device_row(recovery_state):
    return {
        **_account_row(recovery_state),
        "id": "synthetic-device",
        "user_id": "synthetic-user",
        "role": "user",
        "preset": "learner",
        "revoked_at": None,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "current_version": 1,
        "current_epoch": "synthetic-epoch",
        "pin_locked_until": None,
        "pin_hash": "synthetic-pin-hash",
        "generation": 1,
        "daily_limit_minutes": 5,
    }


@pytest.mark.parametrize("recovery_state", ["quarantined", "future-recovery"])
async def test_login_denies_non_normal_recovery_state_before_session_insert(
    monkeypatch, recovery_state
):
    connection = _Connection(_account_row(recovery_state))
    service = _service(connection)
    service._dummy_hash = "synthetic-hash"
    monkeypatch.setattr(identity_module.bcrypt, "checkpw", lambda _password, _hash: True)

    with pytest.raises(PermissionError, match="invalid credentials"):
        await service.login("admin", "synthetic-long-password", client="synthetic-client")
    assert not any(
        statement.startswith("INSERT INTO enterprise.auth_sessions")
        for statement in connection.statements
    )
    assert any("t.recovery_state" in statement for statement in connection.statements)


@pytest.mark.parametrize("recovery_state", ["quarantined", "future-recovery"])
async def test_existing_session_denies_non_normal_recovery_state(monkeypatch, recovery_state):
    connection = _Connection(_account_row(recovery_state))
    service = _service(connection)
    monkeypatch.setattr(
        service,
        "_claims",
        lambda _token: {"sid": "synthetic-session", "sub": "synthetic-user", "ver": 1},
    )

    async def _valid_device(_connection, _session_id):
        return None

    monkeypatch.setattr(service, "_validate_device_session", _valid_device)
    with pytest.raises(PermissionError, match="authentication required"):
        await service._authenticate(connection, "synthetic-token")
    assert any("t.recovery_state" in statement for statement in connection.statements)


async def test_normal_tenant_still_receives_session(monkeypatch):
    connection = _Connection(_account_row("normal"))
    service = _service(connection)
    service._dummy_hash = "synthetic-hash"
    monkeypatch.setattr(identity_module.bcrypt, "checkpw", lambda _password, _hash: True)

    token = await service.login("admin", "synthetic-long-password", client="synthetic-client")
    assert token
    assert any(
        statement.startswith("INSERT INTO enterprise.auth_sessions")
        for statement in connection.statements
    )


async def test_normal_tenant_existing_session_remains_valid(monkeypatch):
    connection = _Connection(_account_row("normal"))
    service = _service(connection)
    monkeypatch.setattr(
        service,
        "_claims",
        lambda _token: {"sid": "synthetic-session", "sub": "synthetic-user", "ver": 1},
    )

    async def _valid_device(_connection, _session_id):
        return None

    monkeypatch.setattr(service, "_validate_device_session", _valid_device)
    identity = await service._authenticate(connection, "synthetic-token")
    assert identity.user_id == "synthetic-user"


@pytest.mark.parametrize("recovery_state", ["quarantined", "future-recovery"])
async def test_device_login_denies_non_normal_tenant_before_session_insert(
    monkeypatch, recovery_state
):
    connection = _Connection(_device_row(recovery_state))
    monkeypatch.setattr(accounts_module.bcrypt, "checkpw", lambda _pin, _hash: True)
    monkeypatch.setattr(accounts_module, "accrued_device_usage", lambda _row, _now: (0, 0))

    with pytest.raises(PermissionError, match="invalid credentials"):
        await _service(connection).device_login("synthetic-code", "123456", client="synthetic-pad")
    assert not any(
        statement.startswith("INSERT INTO enterprise.auth_sessions")
        for statement in connection.statements
    )
    assert any("t.recovery_state" in statement for statement in connection.statements)


async def test_normal_tenant_device_login_still_receives_session(monkeypatch):
    connection = _Connection(_device_row("normal"))
    monkeypatch.setattr(accounts_module.bcrypt, "checkpw", lambda _pin, _hash: True)
    monkeypatch.setattr(accounts_module, "accrued_device_usage", lambda _row, _now: (0, 0))

    token = await _service(connection).device_login(
        "synthetic-code", "123456", client="synthetic-pad"
    )
    assert token
    assert any(
        statement.startswith("INSERT INTO enterprise.auth_sessions")
        for statement in connection.statements
    )
