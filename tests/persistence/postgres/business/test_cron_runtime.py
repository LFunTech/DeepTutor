"""PG cron service/tool/background 接线，不再经 jobs.json/SQLite 初始化。"""

from __future__ import annotations

from dataclasses import asdict
import time

import pytest

from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.multi_user.paths import user_context
from deeptutor.services.cron.service import CronJob
from deeptutor.tools.cron_tool import run_cron_action_async

pytestmark = pytest.mark.asyncio


def _now_ms() -> int:
    return int(time.time() * 1000)


def _current_user(actor) -> CurrentUser:
    return CurrentUser(
        id=actor.user_id,
        username=actor.username,
        role=actor.role,
        scope=UserScope(
            kind="tenant",
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            root=None,
        ),
    )


def _cron_owner(actor, session_id: str = "s1") -> dict:
    return {
        "kind": "chat",
        "tenant_id": actor.tenant_id,
        "user_id": actor.user_id,
        "is_admin": actor.role == "tenant_admin",
        "session_id": session_id,
        "language": "en",
    }


async def test_pg_cron_tool_schedules_lists_dispatches_once_without_sqlite(
    business_sync_database, business_actors, pg_scope_factory, monkeypatch
):
    from deeptutor.persistence.postgres.cron import AsyncPostgresCronRepository
    from deeptutor.services.cron import repository as sqlite_repository
    from deeptutor.services.cron.postgres import PostgresCronService
    import deeptutor.tools.cron_tool as cron_tool

    actor = business_actors.tenants[0].owners[0]
    dispatched: list[str] = []

    async def on_job(job):
        dispatched.append(job.id)
        return "ok", None

    service = PostgresCronService(
        business_sync_database,
        tenant_id=actor.tenant_id,
        worker_id="worker-a",
        on_job=on_job,
    )
    monkeypatch.setattr(cron_tool, "get_cron_service", lambda: service)
    monkeypatch.setattr(
        sqlite_repository.sqlite3,
        "connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sqlite cron opened")),
    )

    with user_context(_current_user(actor)):
        scheduled = await run_cron_action_async(
            {
                "action": "schedule",
                "message": "check progress",
                "name": "progress",
                "every_seconds": 60,
                "_cron_owner": _cron_owner(actor),
            }
        )
        assert scheduled.ok, scheduled.text
        listed = await run_cron_action_async({"action": "list", "_cron_owner": _cron_owner(actor)})

    assert "progress" in listed.text
    job_id = scheduled.meta["job_id"]

    repo = AsyncPostgresCronRepository(business_sync_database, pg_scope_factory(actor))
    await repo.run(
        lambda r: r.upsert(
            {
                **asdict(CronJob.from_dict(r.list_payloads()[0])),
                "state": {
                    **asdict(CronJob.from_dict(r.list_payloads()[0]))["state"],
                    "next_run_at_ms": _now_ms() - 10,
                },
            }
        )
    )
    await service.tick_once(now_ms=_now_ms())
    await service.tick_once(now_ms=_now_ms() + 5_000)

    assert dispatched == [job_id]
    rows = await repo.run(lambda r: r.list_executions(job_id))
    refreshed = CronJob.from_dict((await repo.run(lambda r: r.list_payloads()))[0])
    assert [row["status"] for row in rows] == ["ok"]
    assert refreshed.state.last_status == "ok"
    assert refreshed.state.next_run_at_ms and refreshed.state.next_run_at_ms > _now_ms()


async def test_pg_cron_pause_resume_cancel_and_uncertain_do_not_resend(
    business_sync_database, business_actors, pg_scope_factory, monkeypatch
):
    from deeptutor.persistence.postgres.cron import AsyncPostgresCronRepository
    from deeptutor.services.cron.postgres import PostgresCronService
    import deeptutor.tools.cron_tool as cron_tool

    actor = business_actors.tenants[0].owners[0]
    attempts: list[str] = []

    async def on_job(job):
        attempts.append(job.id)
        return ("uncertain", "delivery outcome unknown") if job.name == "uncertain" else ("ok", None)

    service = PostgresCronService(
        business_sync_database,
        tenant_id=actor.tenant_id,
        worker_id="worker-a",
        on_job=on_job,
    )
    monkeypatch.setattr(cron_tool, "get_cron_service", lambda: service)

    with user_context(_current_user(actor)):
        paused = await run_cron_action_async(
            {
                "action": "schedule",
                "message": "paused",
                "name": "paused",
                "every_seconds": 60,
                "_cron_owner": _cron_owner(actor),
            }
        )
        uncertain = await run_cron_action_async(
            {
                "action": "schedule",
                "message": "uncertain",
                "name": "uncertain",
                "every_seconds": 60,
                "_cron_owner": _cron_owner(actor),
            }
        )
        doomed = await run_cron_action_async(
            {
                "action": "schedule",
                "message": "cancel me",
                "name": "doomed",
                "every_seconds": 60,
                "_cron_owner": _cron_owner(actor),
            }
        )
        assert (paused.ok, uncertain.ok, doomed.ok) == (True, True, True)
        assert (
            await run_cron_action_async(
                {"action": "pause", "job_id": paused.meta["job_id"], "_cron_owner": _cron_owner(actor)}
            )
        ).ok
        assert (
            await run_cron_action_async(
                {"action": "cancel", "job_id": doomed.meta["job_id"], "_cron_owner": _cron_owner(actor)}
            )
        ).ok

    repo = AsyncPostgresCronRepository(business_sync_database, pg_scope_factory(actor))

    async def make_due(job_id: str) -> None:
        def update(r):
            payload = next(p for p in r.list_payloads() if p["id"] == job_id)
            payload["state"]["next_run_at_ms"] = _now_ms() - 10
            r.upsert(payload)

        await repo.run(update)

    await make_due(paused.meta["job_id"])
    await make_due(uncertain.meta["job_id"])
    await service.tick_once(now_ms=_now_ms())

    assert attempts == [uncertain.meta["job_id"]]
    paused_job = CronJob.from_dict(
        next(p for p in await repo.run(lambda r: r.list_payloads()) if p["id"] == paused.meta["job_id"])
    )
    uncertain_job = CronJob.from_dict(
        next(p for p in await repo.run(lambda r: r.list_payloads()) if p["id"] == uncertain.meta["job_id"])
    )
    assert paused_job.enabled is False
    assert uncertain_job.state.next_run_at_ms is None
    assert [p["id"] for p in await repo.run(lambda r: r.list_payloads()) if p["id"] == doomed.meta["job_id"]] == []

    with user_context(_current_user(actor)):
        assert (
            await run_cron_action_async(
                {"action": "resume", "job_id": paused.meta["job_id"], "_cron_owner": _cron_owner(actor)}
            )
        ).ok
    await make_due(paused.meta["job_id"])
    await service.tick_once(now_ms=_now_ms() + 5_000)
    await service.tick_once(now_ms=_now_ms() + 10_000)

    assert attempts == [uncertain.meta["job_id"], paused.meta["job_id"]]
