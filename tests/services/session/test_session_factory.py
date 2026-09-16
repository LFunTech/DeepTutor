from __future__ import annotations

import pytest

from deeptutor.core.providers import ApplicationProviders, provider_context
import deeptutor.services.session as session_package
from deeptutor.services.session.scope import StoreScope
import deeptutor.services.session.turn_runtime as turn_runtime_module


class _StoreProvider:
    def __init__(self, store) -> None:
        self._store = store

    def get(self):
        return self._store


class _Store:
    store_scope = StoreScope("postgres", "factory-test", "owner-1", tenant_id="tenant-1")


class _OtherStore:
    store_scope = StoreScope("postgres", "factory-test", "owner-2", tenant_id="tenant-1")


def test_session_factory_fails_closed_without_postgres_provider() -> None:
    """旧 PocketBase/SQLite fallback 已被新 PG-only 契约替代。"""

    assert not hasattr(session_package, "_pocketbase_store_instances")
    with pytest.raises(Exception, match="postgres.*missing|PostgreSQL session store provider is not configured"):
        session_package.get_session_store()


def test_provider_context_supplies_one_pg_store_and_runtime_per_scope() -> None:
    turn_runtime_module._runtime_instances.clear()
    first = _Store()
    second = _OtherStore()

    with provider_context(ApplicationProviders(store=_StoreProvider(first))):
        assert session_package.get_session_store() is first
        first_runtime = turn_runtime_module.get_turn_runtime_manager()
        second_runtime = turn_runtime_module.get_turn_runtime_manager()

    with provider_context(ApplicationProviders(store=_StoreProvider(second))):
        other_runtime = turn_runtime_module.get_turn_runtime_manager()

    assert first_runtime is second_runtime
    assert first_runtime.store is first
    assert other_runtime is not first_runtime
    assert other_runtime.store is second
    assert len(turn_runtime_module._runtime_instances) == 2
