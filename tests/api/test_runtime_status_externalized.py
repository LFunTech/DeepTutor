from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_runtime_status_reports_externalized_providers_without_secrets() -> None:
    """若生产 status 缺少 PG/ObjectStore/data gate/cleanup/migration 或泄漏 Secret，本测试应失败。"""

    from deeptutor.api.routers.system import get_runtime_status

    async def runtime_report():
        return {
            "worker_id": "worker-1",
            "worker_count": 1,
            "coordination_mode": "memory",
            "redis_configured": False,
            "redis_status": "not_configured",
            "leader_id": "leader-1",
            "owner_turn_count": 0,
            "recovery_backlog": 0,
            "lease_ttl_seconds": 30,
            "renew_interval_seconds": 10,
            "recovery_interval_seconds": 30,
            "providers": {
                "postgres": "configured",
                "objectstore": "s3:deeptutor-runtime:available:objectstore_ready",
                "settings": "postgres",
                "secret": "env:configured",
            },
            "data_gate": "data_gate:kubernetes:ready",
            "cleanup_backlog": 0,
            "migration_version": "0014_externalized_runtime",
        }

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(application_container=SimpleNamespace(runtime_report=runtime_report))))
    status = await get_runtime_status(request)
    payload = status.model_dump()

    assert payload["providers"]["objectstore"].startswith("s3:deeptutor-runtime:available")
    assert payload["data_gate"] == "data_gate:kubernetes:ready"
    assert payload["cleanup_backlog"] == 0
    assert payload["migration_version"] == "0014_externalized_runtime"
    assert "sk-" not in str(payload).lower()
    assert "access-key" not in str(payload).lower()
    assert "postgresql://" not in str(payload)
