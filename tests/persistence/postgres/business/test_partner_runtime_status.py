from __future__ import annotations

from dataclasses import dataclass

import pytest

from deeptutor.persistence.postgres.partner_runtime_status import (
    PartnerRuntimeStatusConflict,
    PostgresPartnerRuntimeStatusRepository,
)

pytestmark = pytest.mark.asyncio


@dataclass
class MutableClock:
    value: float

    def __call__(self) -> float:
        return self.value


def _repo(database, actor, *, worker_id: str, clock: MutableClock, ttl_seconds: float = 30.0):
    return PostgresPartnerRuntimeStatusRepository(
        database,
        tenant_id=actor.tenant_id,
        worker_id=worker_id,
        ttl_seconds=ttl_seconds,
        clock=clock,
    )


async def test_pg_partner_runtime_status_is_owner_scoped_and_sanitized(
    business_sync_database, business_actors
):
    owner = business_actors.tenants[0].owners[0]
    other = business_actors.tenants[0].owners[1]
    clock = MutableClock(1_700_000_000.0)
    leader = _repo(business_sync_database, owner, worker_id="leader-a", clock=clock)
    reader = _repo(business_sync_database, owner, worker_id="reader-b", clock=clock)

    written = leader.set(
        "ada",
        owner_id=owner.user_id,
        running=True,
        state="running",
        payload={
            "partner_id": "ada",
            "name": "Ada",
            "channels": {"telegram": {"token": "secret-token"}},
        },
        started_at="2026-09-01T12:00:00",
    )

    assert written["tenant_id"] == owner.tenant_id
    assert written["owner_id"] == owner.user_id
    assert written["partner_id"] == "ada"
    assert written["runtime_worker_id"] == "leader-a"
    assert written["runtime_owner_id"] == "leader-a"  # legacy response key means worker
    assert written["runtime_version"] == 1
    assert written["runtime_ttl_seconds"] == 30.0
    assert written["runtime_expires_at"] == pytest.approx(clock.value + 30.0)
    assert written["running"] is True
    assert written["runtime_state"] == "running"
    assert written["started_at"] == "2026-09-01T12:00:00"
    assert "channels" not in written
    assert "secret-token" not in str(written)

    status = reader.get("ada", owner_id=owner.user_id)
    assert status is not None
    assert status["name"] == "Ada"
    assert status["runtime_version"] == 1
    assert status["runtime_expired"] is False
    assert reader.list(owner_id=owner.user_id)["ada"]["runtime_worker_id"] == "leader-a"

    assert reader.get("ada", owner_id=other.user_id) is None
    assert reader.list(owner_id=other.user_id) == {}


async def test_pg_partner_runtime_status_rejects_stale_worker_until_ttl_then_rebuilds(
    business_sync_database, business_actors
):
    owner = business_actors.tenants[0].owners[0]
    clock = MutableClock(2_000.0)
    worker_a = _repo(business_sync_database, owner, worker_id="worker-a", clock=clock)
    worker_b = _repo(business_sync_database, owner, worker_id="worker-b", clock=clock)
    worker_c = _repo(business_sync_database, owner, worker_id="worker-c", clock=clock)

    first = worker_a.set(
        "ada",
        owner_id=owner.user_id,
        running=True,
        state="running",
        payload={"name": "Ada"},
    )
    assert first["runtime_version"] == 1

    with pytest.raises(PartnerRuntimeStatusConflict, match="current worker"):
        worker_b.set(
            "ada",
            owner_id=owner.user_id,
            running=False,
            state="stopped",
            payload={"name": "Ada"},
        )

    clock.value += 31.0
    expired = worker_b.get("ada", owner_id=owner.user_id)
    assert expired is not None
    assert expired["running"] is False
    assert expired["runtime_state"] == "expired"
    assert expired["runtime_expired"] is True
    assert expired["runtime_worker_id"] == "worker-a"

    rebuilt = worker_b.set(
        "ada",
        owner_id=owner.user_id,
        running=True,
        state="running",
        payload={"name": "Ada v2"},
    )
    assert rebuilt["runtime_version"] == 2
    assert rebuilt["runtime_worker_id"] == "worker-b"

    with pytest.raises(PartnerRuntimeStatusConflict, match="current worker"):
        worker_a.set(
            "ada",
            owner_id=owner.user_id,
            running=False,
            state="stopped",
            payload={"name": "Ada stale"},
        )

    clock.value += 31.0
    rebuilt_again = worker_c.set(
        "ada",
        owner_id=owner.user_id,
        running=True,
        state="running",
        payload={"name": "Ada v3"},
    )
    assert rebuilt_again["runtime_version"] == 3
    assert rebuilt_again["runtime_worker_id"] == "worker-c"


async def test_default_partner_runtime_status_repository_uses_pg_runtime_without_sqlite(
    monkeypatch, business_sync_database, business_actors
):
    owner = business_actors.tenants[0].owners[0]
    from deeptutor.services.partners import runtime_status as status_module

    class _Config:
        tenant_id = owner.tenant_id

    class _Runtime:
        config = _Config()
        sync_db = business_sync_database

    class _Container:
        worker_id = "default-worker"
        postgres_runtime = _Runtime()

    def _sqlite_should_not_open(*_args, **_kwargs):
        raise AssertionError("default runtime status must not open SQLite")

    monkeypatch.setattr(status_module, "_repository", None)
    monkeypatch.setattr("deeptutor.app.container.get_application_container", lambda: _Container())
    monkeypatch.setattr(status_module.sqlite3, "connect", _sqlite_should_not_open)
    try:
        repository = status_module.get_partner_runtime_status_repository()
        assert isinstance(repository, PostgresPartnerRuntimeStatusRepository)
        repository.set(
            "ada",
            owner_id=owner.user_id,
            running=True,
            state="running",
            payload={"name": "Ada"},
        )
        assert repository.get("ada", owner_id=owner.user_id)["tenant_id"] == owner.tenant_id
    finally:
        status_module._repository = None
