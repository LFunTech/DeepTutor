"""PG cron repository：真实 schedule/meta/execution 状态与领取语义。"""

from __future__ import annotations

from dataclasses import asdict
import time

import pytest

from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule

pytestmark = pytest.mark.asyncio


def _now_ms() -> int:
    return int(time.time() * 1000)


def _payload(
    job_id: str,
    *,
    schedule: CronSchedule,
    next_run_at_ms: int | None,
    owner: CronOwner | None = None,
    enabled: bool = True,
    delete_after_run: bool = False,
) -> dict:
    job = CronJob(
        id=job_id,
        name=f"job {job_id}",
        message=f"run {job_id}",
        schedule=schedule,
        owner=owner or CronOwner(kind="chat", user_id="owner-1-1", session_id="s1"),
        enabled=enabled,
        delete_after_run=delete_after_run,
        created_at_ms=_now_ms() - 120_000,
    )
    job.state.next_run_at_ms = next_run_at_ms
    return asdict(job)


async def test_schedule_shapes_revision_and_trusted_owner_isolation(
    business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.persistence.postgres.cron import AsyncPostgresCronRepository

    actor = business_actors.tenants[0].owners[0]
    other = business_actors.tenants[0].owners[1]
    repo = AsyncPostgresCronRepository(business_sync_database, pg_scope_factory(actor))
    other_repo = AsyncPostgresCronRepository(business_sync_database, pg_scope_factory(other))
    now = _now_ms()

    async def insert_seed_data() -> None:
        await repo.run(
            lambda r: (
                r.upsert(
                    _payload(
                        "at",
                        schedule=CronSchedule(kind="at", at_ms=now + 60_000),
                        next_run_at_ms=now + 60_000,
                    )
                ),
                r.upsert(
                    _payload(
                        "every",
                        schedule=CronSchedule(kind="every", every_seconds=90),
                        next_run_at_ms=now + 30_000,
                        enabled=False,
                    )
                ),
                r.upsert(
                    _payload(
                        "cron",
                        schedule=CronSchedule(
                            kind="cron", expr="15 8 * * *", tz="Asia/Shanghai"
                        ),
                        next_run_at_ms=now + 120_000,
                        owner=CronOwner(kind="partner", partner_id="ada"),
                    )
                ),
            )
        )
        await other_repo.run(
            lambda r: r.upsert(
                _payload(
                    "other-owner",
                    schedule=CronSchedule(kind="every", every_seconds=60),
                    next_run_at_ms=now + 5_000,
                    owner=CronOwner(kind="chat", user_id=other.user_id),
                )
            )
        )

    await insert_seed_data()

    rows = await repo.run(lambda r: [CronJob.from_dict(p) for p in r.list_payloads()])

    assert [job.id for job in rows] == ["every", "at", "cron"]
    assert rows[0].enabled is False
    assert rows[1].schedule.kind == "at" and rows[1].schedule.at_ms == now + 60_000
    assert rows[2].owner.key == "partner:ada"
    assert rows[2].schedule.expr == "15 8 * * *"
    assert rows[2].schedule.tz == "Asia/Shanghai"
    assert await repo.run(lambda r: r.revision()) == 3
    assert [CronJob.from_dict(p).id for p in await other_repo.run(lambda r: r.list_payloads())] == [
        "other-owner"
    ]


async def test_claim_due_jobs_is_atomic_and_completion_reschedules_with_execution_record(
    business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.persistence.postgres.cron import AsyncPostgresCronRepository

    repo = AsyncPostgresCronRepository(
        business_sync_database, pg_scope_factory(business_actors.tenants[0].owners[0])
    )
    due_at = _now_ms() - 1_000
    await repo.run(
        lambda r: r.upsert(
            _payload(
                "due",
                schedule=CronSchedule(kind="every", every_seconds=60),
                next_run_at_ms=due_at,
            )
        )
    )

    first_claims = await repo.run(lambda r: r.claim_due(_now_ms(), worker_id="worker-a"))
    second_claims = await repo.run(lambda r: r.claim_due(_now_ms(), worker_id="worker-b"))

    assert [claim.job.id for claim in first_claims] == ["due"]
    assert second_claims == []
    assert [CronJob.from_dict(p).state.next_run_at_ms for p in await repo.run(lambda r: r.list_payloads())] == [
        None
    ]

    completed_at = _now_ms()
    await repo.run(
        lambda r: r.complete_execution(
            first_claims[0], status="ok", error=None, completed_at_ms=completed_at
        )
    )
    executions = await repo.run(lambda r: r.list_executions("due"))
    refreshed = CronJob.from_dict((await repo.run(lambda r: r.list_payloads()))[0])

    assert [(row["worker_id"], row["status"]) for row in executions] == [("worker-a", "ok")]
    assert refreshed.state.last_status == "ok"
    assert refreshed.state.last_run_at_ms == first_claims[0].claimed_at_ms
    assert refreshed.state.next_run_at_ms == completed_at + 60_000
    assert refreshed.state.run_history[-1].duration_ms >= 0


async def test_claim_respects_enabled_time_boundaries_and_uncertain_results_do_not_resend(
    business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.persistence.postgres.cron import AsyncPostgresCronRepository

    repo = AsyncPostgresCronRepository(
        business_sync_database, pg_scope_factory(business_actors.tenants[0].owners[0])
    )
    now = _now_ms()
    future_at = now + 60_000
    await repo.run(
        lambda r: (
            r.upsert(
                _payload(
                    "disabled",
                    schedule=CronSchedule(kind="every", every_seconds=60),
                    next_run_at_ms=now - 1_000,
                    enabled=False,
                )
            ),
            r.upsert(
                _payload(
                    "future",
                    schedule=CronSchedule(kind="every", every_seconds=60),
                    next_run_at_ms=future_at,
                )
            ),
            r.upsert(
                _payload(
                    "uncertain",
                    schedule=CronSchedule(kind="every", every_seconds=60),
                    next_run_at_ms=now - 500,
                )
            ),
            r.upsert(
                _payload(
                    "once",
                    schedule=CronSchedule(kind="at", at_ms=now - 100),
                    next_run_at_ms=now - 100,
                    delete_after_run=True,
                )
            ),
        )
    )

    claims = await repo.run(lambda r: r.claim_due(now, worker_id="worker-a", limit=10))
    assert [claim.job.id for claim in claims] == ["uncertain", "once"]
    assert await repo.run(lambda r: r.claim_due(future_at - 1, worker_id="worker-a")) == []

    by_id = {claim.job.id: claim for claim in claims}
    await repo.run(lambda r: r.complete_execution(by_id["once"], status="ok"))
    await repo.run(lambda r: r.complete_execution(by_id["uncertain"], status="uncertain"))

    remaining = {
        CronJob.from_dict(payload).id: CronJob.from_dict(payload)
        for payload in await repo.run(lambda r: r.list_payloads())
    }
    assert set(remaining) == {"disabled", "uncertain", "future"}
    assert remaining["disabled"].enabled is False
    assert remaining["uncertain"].state.next_run_at_ms is None
    assert await repo.run(lambda r: r.claim_due(_now_ms() + 10_000, worker_id="worker-a")) == []
    assert [claim.job.id for claim in await repo.run(
        lambda r: r.claim_due(future_at, worker_id="worker-a")
    )] == ["future"]


async def test_stale_claim_completion_is_rejected_and_idempotent_completion_is_safe(
    business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.persistence.postgres.cron import AsyncPostgresCronRepository, CronClaimConflict

    repo = AsyncPostgresCronRepository(
        business_sync_database, pg_scope_factory(business_actors.tenants[0].owners[0])
    )
    await repo.run(
        lambda r: r.upsert(
            _payload(
                "cas",
                schedule=CronSchedule(kind="every", every_seconds=60),
                next_run_at_ms=_now_ms() - 10,
            )
        )
    )
    [claim] = await repo.run(lambda r: r.claim_due(_now_ms(), worker_id="worker-a"))

    with pytest.raises(CronClaimConflict):
        await repo.run(
            lambda r: r.complete_execution(
                claim.with_revision(claim.job_revision - 1),
                status="ok",
                completed_at_ms=_now_ms(),
            )
        )

    await repo.run(lambda r: r.complete_execution(claim, status="error", error="boom"))
    await repo.run(lambda r: r.complete_execution(claim, status="error", error="boom"))
    executions = await repo.run(lambda r: r.list_executions("cas"))
    refreshed = CronJob.from_dict((await repo.run(lambda r: r.list_payloads()))[0])

    assert [row["status"] for row in executions] == ["error"]
    assert refreshed.state.last_error == "boom"
    assert len(refreshed.state.run_history) == 1
