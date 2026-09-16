"""PostgreSQL cron service wiring for default PG-only runtime."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
import logging
import time
from typing import Awaitable, Callable
import uuid

from deeptutor.persistence.postgres.connection import SyncDatabase
from deeptutor.persistence.postgres.cron import (
    AsyncPostgresCronRepository,
    CronClaimConflict,
    CronExecutionClaim,
)
from deeptutor.persistence.postgres.scope import TenantScope
from deeptutor.services.cron.service import (
    CronJob,
    CronOwner,
    CronSchedule,
    compute_next_run,
    validate_schedule,
)

logger = logging.getLogger(__name__)

_MAX_SLEEP_SECONDS = 60.0
_TERMINAL_STATUSES = {"ok", "error", "skipped", "uncertain"}


def _now_ms() -> int:
    return int(time.time() * 1000)


class PostgresCronService:
    """Async cron service backed by owner-scoped PG repositories."""

    def __init__(
        self,
        database: SyncDatabase,
        *,
        tenant_id: str,
        worker_id: str,
        on_job: Callable[[CronJob], Awaitable[tuple[str, str | None]]] | None = None,
        owner_scope: Callable[[], TenantScope] | None = None,
    ) -> None:
        if not isinstance(database, SyncDatabase):
            raise TypeError("SyncDatabase is required")
        self.database = database
        self.tenant_id = str(tenant_id)
        self.worker_id = worker_id or f"cron-{uuid.uuid4().hex[:8]}"
        self.on_job = on_job
        self._owner_scope = owner_scope
        self.change_notifier: Callable[[], None] | None = None
        self._timer_task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._running = False

    def _current_scope(self) -> TenantScope:
        if self._owner_scope is not None:
            scope = self._owner_scope()
            if scope.tenant_id != self.tenant_id:
                raise PermissionError("cron scope belongs to a different tenant")
            return scope

        from deeptutor.multi_user.context import get_current_user

        user = get_current_user()
        if (
            user.scope.kind != "tenant"
            or user.scope.tenant_id != self.tenant_id
            or user.scope.user_id != user.id
        ):
            raise PermissionError("PostgreSQL tenant identity is required for cron")
        return TenantScope(self.tenant_id, user.id)

    def _repo(self, scope: TenantScope) -> AsyncPostgresCronRepository:
        return AsyncPostgresCronRepository(self.database, scope)

    async def _all_owner_scopes(self) -> list[TenantScope]:
        identity_scope = TenantScope(self.tenant_id, "@cron")

        def query(connection):
            rows = connection.execute(
                """
                SELECT id FROM enterprise.users
                 WHERE tenant_id = %s AND disabled = false
                 ORDER BY id
                """,
                (self.tenant_id,),
            ).fetchall()
            return [TenantScope(self.tenant_id, row["id"]) for row in rows]

        return await self.database.run(identity_scope, query)

    @staticmethod
    def _bind_owner_to_scope(owner: CronOwner, scope: TenantScope) -> CronOwner:
        if owner.kind == "chat" and owner.user_id and owner.user_id != scope.user_id:
            raise PermissionError("cron chat owner must match the authenticated user")
        return replace(
            owner,
            tenant_id=scope.tenant_id,
            user_id=scope.user_id if owner.kind == "chat" else owner.user_id,
        )

    def _changed(self) -> None:
        self._wake.set()
        if self.change_notifier is not None:
            self.change_notifier()

    # ── job management ────────────────────────────────────────────

    async def add_job(
        self,
        *,
        name: str,
        message: str,
        schedule: CronSchedule,
        owner: CronOwner,
        delete_after_run: bool | None = None,
    ) -> CronJob:
        validate_schedule(schedule)
        if not message.strip():
            raise ValueError("message is required")
        scope = self._current_scope()
        owner = self._bind_owner_to_scope(owner, scope)
        job = CronJob(
            id=uuid.uuid4().hex[:10],
            name=name.strip() or message.strip()[:48],
            message=message.strip(),
            schedule=schedule,
            owner=owner,
            delete_after_run=(
                delete_after_run if delete_after_run is not None else schedule.kind == "at"
            ),
            created_at_ms=_now_ms(),
        )
        job.state.next_run_at_ms = compute_next_run(schedule, _now_ms())
        await self._repo(scope).run(lambda r: r.upsert(asdict(job)))
        self._changed()
        return job

    async def list_jobs(self, owner_key: str | None = None) -> list[CronJob]:
        scope = self._current_scope()
        jobs = [
            CronJob.from_dict(payload)
            for payload in await self._repo(scope).run(lambda r: r.list_payloads())
        ]
        if owner_key is not None:
            jobs = [job for job in jobs if job.owner.key == owner_key]
        return sorted(jobs, key=lambda job: job.state.next_run_at_ms or 0)

    async def get_job(self, job_id: str) -> CronJob | None:
        for job in await self.list_jobs():
            if job.id == job_id:
                return job
        return None

    async def cancel_job(self, job_id: str, *, owner_key: str | None = None) -> bool:
        scope = self._current_scope()
        removed = await self._repo(scope).run(lambda r: r.delete(job_id, owner_key=owner_key))
        if removed:
            self._changed()
        return removed

    async def set_job_enabled(
        self, job_id: str, enabled: bool, *, owner_key: str | None = None
    ) -> bool:
        scope = self._current_scope()
        changed = await self._repo(scope).run(
            lambda r: r.set_enabled(job_id, enabled, owner_key=owner_key)
        )
        if changed:
            self._changed()
        return changed

    async def remove_owner_jobs(self, owner_key: str) -> int:
        removed = 0
        for scope in await self._all_owner_scopes():
            removed += await self._repo(scope).run(lambda r: r.delete_owner(owner_key))
        if removed:
            self._changed()
        return removed

    # ── scheduler ─────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._timer_task = asyncio.create_task(self._loop(), name="cron:pg-scheduler")
        logger.info("PostgreSQL cron service started")

    async def stop(self) -> None:
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            try:
                await self._timer_task
            except asyncio.CancelledError:
                pass
            self._timer_task = None

    def reload(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("PostgreSQL cron tick failed")
            sleep_s = await self._seconds_until_next_due()
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=sleep_s)
            except asyncio.TimeoutError:
                pass

    async def _seconds_until_next_due(self) -> float:
        due_times: list[int] = []
        for scope in await self._all_owner_scopes():
            payloads = await self._repo(scope).run(lambda r: r.list_payloads())
            for payload in payloads:
                job = CronJob.from_dict(payload)
                if job.enabled and job.state.next_run_at_ms:
                    due_times.append(job.state.next_run_at_ms)
        if not due_times:
            return _MAX_SLEEP_SECONDS
        delta_s = (min(due_times) - _now_ms()) / 1000
        return max(0.05, min(delta_s, _MAX_SLEEP_SECONDS))

    async def tick_once(self, *, now_ms: int | None = None) -> int:
        now_ms = _now_ms() if now_ms is None else int(now_ms)
        claimed = 0
        for scope in await self._all_owner_scopes():
            repo = self._repo(scope)
            claims = await repo.run(
                lambda r: r.claim_due(now_ms, worker_id=self.worker_id, limit=25)
            )
            claimed += len(claims)
            for claim in claims:
                await self._run_claim(scope, claim)
        return claimed

    async def _run_claim(self, scope: TenantScope, claim: CronExecutionClaim) -> None:
        status, error = "skipped", None
        if self.on_job is not None:
            try:
                status, error = await self.on_job(claim.job)
            except Exception as exc:  # noqa: BLE001
                status, error = "error", f"{type(exc).__name__}: {exc}"
                logger.exception("Cron job %s (%s) crashed", claim.job.id, claim.job.name)
        if status not in _TERMINAL_STATUSES:
            status, error = "error", f"unsupported cron execution status {status!r}"
        try:
            await self._repo(scope).run(
                lambda r: r.complete_execution(claim, status=status, error=error)
            )
        except CronClaimConflict:
            logger.info("Cron job %s completion lost its claim", claim.job.id)
        except Exception:
            # Claiming already nulled next_run_at_ms, so a persistence failure
            # here leaves the execution pending for operator reconciliation
            # instead of blindly dispatching the same external effect again.
            logger.exception("Cron job %s completion could not be persisted", claim.job.id)


__all__ = ["PostgresCronService"]
