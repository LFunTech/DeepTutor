"""EduPlus2 换票不得绕过 Core 学校状态门禁直接签发会话。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

from deeptutor_enterprise.eduplus2 import service as service_module
from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
from deeptutor_enterprise.scope import TenantScope
import pytest

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        if self.rows is not None:
            return self.rows
        return [] if self.row is None else [self.row]


class _Connection:
    def __init__(self, user):
        self.user = user
        self.statements = []

    async def execute(self, statement, _params=None):
        statement = statement.strip()
        self.statements.append(statement)
        if statement.startswith("SELECT * FROM eduplus2.identity_bindings"):
            return _Cursor(rows=[{
                "provider": "eduplus2",
                "status": "active",
                "internal_user_id": "synthetic-user",
            }])
        if statement.startswith("SELECT u.*"):
            return _Cursor(self.user)
        return _Cursor()


class _Database:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def transaction(self, _scope):
        yield self.connection


def _service(connection, monkeypatch):
    issued = []

    async def _issue_session(_connection, _row, **_kwargs):
        issued.append(True)
        return "synthetic-dt-token"

    identity = SimpleNamespace(
        tenant_id="10000000-0000-0000-0000-000000000001",
        epoch="synthetic-epoch",
        token_seconds=3600,
        _issue_session=_issue_session,
    )
    service = object.__new__(EduPlus2AccessService)
    service.db = _Database(connection)
    service.identity = identity
    service.dt_token_seconds = 900
    service._scope = TenantScope(identity.tenant_id, "@eduplus2")

    async def _verified(_token):
        return SimpleNamespace(
            claims={"azp": "client-a", "tid": "10001", "eui": "user-a", "sub": "user-a"},
            token_hash="h" * 64,
            header={"kid": "synthetic-kid"},
        )

    async def _registration(_connection, **_kwargs):
        registration = {
            "id": UUID("20000000-0000-0000-0000-000000000001"),
            "external_tenant_id": "10001",
            "external_app_id": "51",
            "resolve_version": "v1",
        }
        resolved = {"external_tenant_id": "10001", "external_app_id": "51"}
        return registration, resolved

    async def _none(*_args, **_kwargs):
        return None

    monkeypatch.setattr(service, "_verified_claims", _verified)
    monkeypatch.setattr(service, "_enforce_exchange_replay_and_rate_limit", _none)
    monkeypatch.setattr(service, "_ensure_registration", _registration)
    monkeypatch.setattr(service, "_ensure_not_revoked", _none)
    monkeypatch.setattr(service, "_fetch_profile", _none)
    monkeypatch.setattr(service, "_check_permission", _none)
    monkeypatch.setattr(service, "_audit", _none)
    monkeypatch.setattr(service_module.jwt, "get_unverified_claims", lambda _token: {"sid": "sid"})
    return service, issued


def _user(recovery_state):
    return {
        "id": "synthetic-user",
        "auth_version": 1,
        "local_enabled": True,
        "external_eligibility": "allowed",
        "provisioning_status": "ready",
        "recovery_state": recovery_state,
        "tenant_auth_epoch": "synthetic-epoch",
    }


@pytest.mark.parametrize("recovery_state", ["quarantined", "future-recovery"])
async def test_exchange_rejects_non_normal_tenant_before_token_issue(monkeypatch, recovery_state):
    connection = _Connection(_user(recovery_state))
    service, issued = _service(connection, monkeypatch)

    with pytest.raises(PermissionError, match="user or tenant is inactive"):
        await service.exchange_user_jwt("synthetic-eduplus2-token", request_id="synthetic-request")
    assert issued == []
    assert any("t.recovery_state" in statement for statement in connection.statements)


async def test_exchange_normal_tenant_still_issues_token(monkeypatch):
    connection = _Connection(_user("normal"))
    service, issued = _service(connection, monkeypatch)

    result = await service.exchange_user_jwt(
        "synthetic-eduplus2-token", request_id="synthetic-request"
    )
    assert result["dt_token"] == "synthetic-dt-token"
    assert issued == [True]


async def test_exchange_rejects_mismatched_local_auth_epoch(monkeypatch):
    user = _user("normal")
    user["tenant_auth_epoch"] = "old-epoch"
    connection = _Connection(user)
    service, issued = _service(connection, monkeypatch)

    with pytest.raises(PermissionError, match="user or tenant is inactive"):
        await service.exchange_user_jwt("synthetic-eduplus2-token", request_id="synthetic-request")
    assert issued == []
