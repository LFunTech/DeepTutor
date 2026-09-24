"""企业组合根的多副本 runtime coordination 契约。"""

from __future__ import annotations

from types import SimpleNamespace
import uuid

import pytest


def test_enterprise_runtime_coordination_defaults_to_isolated_memory_per_scope(
    monkeypatch,
):
    """缺省单副本部署不能共享进程内 coordination 状态。"""

    from deeptutor_enterprise.bootstrap import _build_enterprise_runtime_coordination

    from deeptutor.runtime.coordination import MemoryCoordinator

    monkeypatch.setenv("DEEPTUTOR_BACKEND_WORKERS", "1")
    monkeypatch.setenv("DEEPTUTOR_TURN_COORDINATION_BACKEND", "memory")
    monkeypatch.delenv("DEEPTUTOR_REDIS_URL", raising=False)
    monkeypatch.delenv("DEEPTUTOR_REDIS_KEY_PREFIX", raising=False)

    settings, coordinator, coordinator_factory = _build_enterprise_runtime_coordination()

    assert settings.backend == "memory"
    assert isinstance(coordinator, MemoryCoordinator)
    assert coordinator_factory is not None
    scoped = coordinator_factory()
    assert isinstance(scoped, MemoryCoordinator)
    assert scoped is not coordinator


async def test_enterprise_runtime_coordination_uses_redis_for_replicated_runtime(
    monkeypatch,
):
    """多副本部署通过 Redis coordination 共享 turn lease 与事件/命令流。"""

    from deeptutor_enterprise.bootstrap import _build_enterprise_runtime_coordination

    from deeptutor.runtime.coordination import RedisCoordinator

    monkeypatch.setenv("DEEPTUTOR_BACKEND_WORKERS", "1")
    monkeypatch.setenv("DEEPTUTOR_TURN_COORDINATION_BACKEND", "redis")
    monkeypatch.setenv("DEEPTUTOR_REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("DEEPTUTOR_REDIS_KEY_PREFIX", "deeptutor-test-cn")

    settings, coordinator, coordinator_factory = _build_enterprise_runtime_coordination()
    try:
        assert settings.backend == "redis"
        assert settings.redis_url == "redis://localhost:6379/15"
        assert settings.key_prefix == "deeptutor-test-cn"
        assert isinstance(coordinator, RedisCoordinator)
        assert coordinator.key_prefix == "deeptutor-test-cn"
        assert coordinator_factory is None
    finally:
        await coordinator.close()


def test_enterprise_runtime_coordination_rejects_multiple_workers_without_redis(
    monkeypatch,
):
    """同一进程组内多 worker 不能落回 memory coordination。"""

    from deeptutor_enterprise.bootstrap import _build_enterprise_runtime_coordination

    from deeptutor.runtime.coordination import RuntimeConfigurationError

    monkeypatch.setenv("DEEPTUTOR_BACKEND_WORKERS", "2")
    monkeypatch.setenv("DEEPTUTOR_TURN_COORDINATION_BACKEND", "memory")
    monkeypatch.delenv("DEEPTUTOR_REDIS_URL", raising=False)

    with pytest.raises(RuntimeConfigurationError, match="backend_workers > 1 requires"):
        _build_enterprise_runtime_coordination()


def test_enterprise_redis_coordination_disables_singleton_executor_lease():
    """Redis coordination 模式下不能再用单执行者 PG advisory lock 阻断多 Pod。"""

    from deeptutor_enterprise.bootstrap import _requires_singleton_executor_lease

    from deeptutor.runtime.coordination import CoordinationSettings

    assert _requires_singleton_executor_lease(CoordinationSettings(backend="memory")) is True
    assert (
        _requires_singleton_executor_lease(
            CoordinationSettings(backend="redis", redis_url="redis://localhost:6379/15")
        )
        is False
    )


async def test_enterprise_redis_recovery_does_not_fail_all_nonterminal_turns(
    monkeypatch,
):
    """多副本启动恢复只能处理 Redis 过期 lease，不能把其他 Pod 的 turn 统一失败。"""

    import deeptutor_enterprise.bootstrap as bootstrap

    class _FakeResult:
        async def fetchall(self):
            return [{"id": "admin"}]

    class _FakeConnection:
        async def execute(self, *_args, **_kwargs):
            return _FakeResult()

    class _FakeTransaction:
        async def __aenter__(self):
            return _FakeConnection()

        async def __aexit__(self, *_args):
            return None

    class _FakeDatabase:
        def transaction(self, *_args, **_kwargs):
            return _FakeTransaction()

    class _FakeCoordinator:
        async def list_expired_turn_ids(self):
            return []

    class _ExplodingStore:
        def __init__(self, *_args, **_kwargs):
            pass

        async def list_nonterminal_turns(self):
            raise AssertionError("Redis recovery must not bulk-fail live turns")

    monkeypatch.setattr(bootstrap, "PostgresSessionStore", _ExplodingStore)
    enterprise = object.__new__(bootstrap.Enterprise)
    enterprise.db = _FakeDatabase()
    enterprise.deployment = SimpleNamespace(tenant_id=uuid.uuid4())
    enterprise.container = SimpleNamespace(
        settings=SimpleNamespace(backend="redis"),
        coordinator=_FakeCoordinator(),
    )

    await enterprise.recover()
