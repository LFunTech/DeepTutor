"""命令状态写入前必须解释已有命令类型，不依赖数据库 CHECK。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from deeptutor.persistence.postgres.scope import TenantScope
from deeptutor.persistence.postgres.session import PostgresSessionStore


class _Cursor:
    def __init__(self, row):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    def __init__(self):
        self.accepted_updated = False

    async def execute(self, statement, _params):
        if statement.startswith("SELECT kind FROM enterprise.turn_commands"):
            return _Cursor({"kind": "future-command"})
        if statement.startswith("UPDATE enterprise.turn_commands SET accepted="):
            self.accepted_updated = True
            return SimpleNamespace(rowcount=1)
        raise AssertionError(f"unexpected command query: {statement}")


class _Database:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def transaction(self, _scope):
        yield self.connection


@pytest.mark.asyncio
async def test_finish_command_rejects_unknown_persisted_kind_before_updating(monkeypatch):
    async def _lock(_self, _connection):
        return None

    async def _turn(_self, _connection, _turn_id, *, lock=False):
        assert lock
        return {"id": "turn"}

    monkeypatch.setattr(PostgresSessionStore, "_lock_notebook_export_scope", _lock)
    monkeypatch.setattr(PostgresSessionStore, "_turn", _turn)
    connection = _Connection()
    store = PostgresSessionStore(
        db=_Database(connection),
        scope=TenantScope("10000000-0000-0000-0000-000000000001", "owner"),
    )

    with pytest.raises(ValueError, match="Unknown command kind"):
        await store.finish_command("turn", "command", True)
    assert not connection.accepted_updated
