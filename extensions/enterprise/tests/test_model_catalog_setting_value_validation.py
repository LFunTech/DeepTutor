"""模型运行时读取和维护不能绕过 PG 治理状态的程序校验。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

from deeptutor_enterprise import model_catalog
import pytest

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self, row):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.row = row
        self.writes = 0

    async def execute(self, statement, _params):
        if statement.startswith("SELECT"):
            if "status IN" in statement:
                return _Cursor(None)
            return _Cursor(self.row)
        if statement.startswith("INSERT"):
            self.writes += 1
            return _Cursor(None)
        raise AssertionError(f"unexpected catalog query: {statement}")


class _Database:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def transaction(self, _scope):
        yield self.connection


def _store(row):
    connection = _Connection(row)
    store = SimpleNamespace(
        db=_Database(connection),
        scope=SimpleNamespace(tenant_id="10000000-0000-0000-0000-000000000001"),
    )
    return store, connection


async def test_model_catalog_runtime_rejects_unknown_setting_status_before_fallback():
    store, _connection = _store({"active": {}, "desired": {}, "status": "future-status"})

    with pytest.raises(ValueError, match="unknown persisted status"):
        await model_catalog.load_runtime_model_deployments(store, ())


async def test_model_catalog_maintenance_rejects_unknown_setting_status_before_upsert():
    store, connection = _store({"status": "future-status"})

    with pytest.raises(ValueError, match="unknown persisted status"):
        await model_catalog.save_runtime_model_catalog(store, catalog={}, actor_id="operator")
    assert connection.writes == 0


async def test_model_catalog_secret_lookup_rejects_unknown_reference_status():
    store, _connection = _store(
        {"provider": "env", "reference": "env:MODEL_SECRET", "status": "future-status"}
    )

    with pytest.raises(ValueError, match="unknown persisted status"):
        await model_catalog._secret_reference(store, "model.primary")


async def test_model_catalog_known_states_preserve_existing_behavior():
    setting_store, connection = _store({"active": {}, "desired": {}, "status": "saved"})
    assert await model_catalog.load_runtime_model_deployments(setting_store, ()) == ()
    await model_catalog.save_runtime_model_catalog(
        setting_store, catalog={}, actor_id="operator"
    )
    assert connection.writes == 1

    secret_store, _connection = _store(
        {"provider": "env", "reference": "env:MODEL_SECRET", "status": "active"}
    )
    assert await model_catalog._secret_reference(secret_store, "model.primary") == "env:MODEL_SECRET"


async def test_model_catalog_known_unavailable_secret_state_still_fails_closed():
    store, _connection = _store(
        {"provider": "env", "reference": "env:MODEL_SECRET", "status": "failed"}
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        await model_catalog._secret_reference(store, "model.primary")
