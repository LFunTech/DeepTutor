"""PG 用户授权策略的历史未知值不得被过滤或覆盖。"""

from contextlib import contextmanager

import pytest

from deeptutor.multi_user import grants
from deeptutor.persistence.postgres.scope import TenantScope


class _Cursor:
    def __init__(self, *, row=None, rows=()):
        self.row = row
        self.rows = list(rows)

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, row):
        self.row = row
        self.writes = 0

    def execute(self, statement, _params):
        if statement.startswith("SELECT"):
            return _Cursor(row=self.row, rows=[self.row])
        if statement.startswith("INSERT INTO enterprise.runtime_policies"):
            self.writes += 1
            return _Cursor()
        raise AssertionError(f"unexpected policy query: {statement}")


class _Database:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def transaction(self, _scope):
        yield self.connection


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            {"subject_kind": "owner", "status": "future-status", "document": {}},
            "unknown persisted status",
        ),
        (
            {"subject_kind": "future-kind", "status": "active", "document": {}},
            "unknown persisted subject kind",
        ),
    ],
)
def test_pg_grant_read_rejects_unknown_policy_values(monkeypatch, row, message):
    connection = _Connection(row)
    scope = TenantScope("10000000-0000-0000-0000-000000000001", "owner")
    monkeypatch.setattr(grants, "_pg_runtime", lambda: (_Database(connection), scope))

    with pytest.raises(ValueError, match=message):
        grants._load_pg_grant("student")


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            {"subject_kind": "owner", "status": "future-status", "document": {}},
            "unknown persisted status",
        ),
        (
            {"subject_kind": "future-kind", "status": "active", "document": {}},
            "unknown persisted subject kind",
        ),
    ],
)
def test_pg_grant_write_rejects_unknown_policy_values_before_upsert(monkeypatch, row, message):
    connection = _Connection(row)
    scope = TenantScope("10000000-0000-0000-0000-000000000001", "owner")
    monkeypatch.setattr(grants, "_pg_runtime", lambda: (_Database(connection), scope))

    with pytest.raises(ValueError, match=message):
        grants._save_pg_grant("student", grants.empty_grant("student"))
    assert connection.writes == 0


def test_pg_grant_valid_policy_is_still_loaded_and_updated(monkeypatch):
    row = {
        "subject_kind": "owner",
        "status": "active",
        "document": grants.empty_grant("student"),
    }
    connection = _Connection(row)
    scope = TenantScope("10000000-0000-0000-0000-000000000001", "owner")
    monkeypatch.setattr(grants, "_pg_runtime", lambda: (_Database(connection), scope))

    assert grants._load_pg_grant("student") == grants.empty_grant("student")
    assert grants._save_pg_grant("student", grants.empty_grant("student")) is True
    assert connection.writes == 1
