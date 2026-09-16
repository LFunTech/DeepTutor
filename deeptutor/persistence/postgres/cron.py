"""PostgreSQL-backed cron repository with scoped claims and execution CAS."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import inspect
import json
import time
from typing import Any, Callable, TypeVar
import uuid

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres._ownership import Lease
from deeptutor.persistence.postgres.connection import SyncDatabase
from deeptutor.persistence.postgres.scope import TenantScope
from deeptutor.services.cron.repository import CronRepository
from deeptutor.services.cron.service import (
    CronJob,
    CronRunRecord,
    compute_next_run,
)

T = TypeVar("T")

_MAX_RUN_HISTORY = 10
_TERMINAL_STATUSES = {"ok", "error", "skipped", "uncertain"}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _jsonb(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda obj: json.dumps(obj, ensure_ascii=False, allow_nan=False))


def _complete_callback(result: T) -> T:
    if inspect.isawaitable(result) or inspect.isgenerator(result) or inspect.isasyncgen(result):
        if inspect.iscoroutine(result) or inspect.isgenerator(result):
            result.close()
        raise TypeError("cron repository callback must complete synchronously")
    return result


class CronRepositoryError(RuntimeError):
    """Base class for PG cron repository consistency errors."""


class CronClaimConflict(CronRepositoryError):
    """The stored job/execution no longer matches the claim token."""


@dataclass(frozen=True, slots=True)
class CronExecutionClaim:
    """A fenced right to dispatch one due cron job once."""

    execution_id: str
    job: CronJob
    job_revision: int
    scheduled_run_at_ms: int
    claimed_at_ms: int
    worker_id: str

    def with_revision(self, job_revision: int) -> "CronExecutionClaim":
        return replace(self, job_revision=job_revision)


class PostgresCronRepository(CronRepository):
    """Synchronous PG cron repository bound to one trusted tenant/user scope."""

    def __init__(self, database: SyncDatabase, scope: TenantScope) -> None:
        if not isinstance(database, SyncDatabase) or not isinstance(scope, TenantScope):
            raise TypeError("SyncDatabase and trusted TenantScope required")
        self.db = database
        self.scope = scope
        self._owner = (scope.tenant_id, scope.user_id)
        self._connection = self._lease = None
        self._failed = False

    def _bind(self, connection) -> "PostgresCronRepository":
        unit = type(self)(self.db, self.scope)
        unit._connection = connection
        unit._lease = Lease()
        return unit

    def _check(self) -> None:
        if self._lease is not None:
            self._lease.check()
        if self._failed:
            raise CronRepositoryError("cron unit is poisoned; transaction must roll back")

    @contextmanager
    def _unit(self, *, write: bool = False):
        if self._connection is not None:
            self._check()
            try:
                if write:
                    self._ensure_meta()
                yield self
            except BaseException:
                self._failed = True
                raise
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "use AsyncPostgresCronRepository.run; synchronous repository cannot block event loop"
            )
        unit = None
        try:
            with self.db.transaction(self.scope) as connection:
                unit = self._bind(connection)
                with unit._unit(write=write):
                    yield unit
        finally:
            if unit is not None:
                unit._lease.active = False

    def _execute(self, sql: str, params: tuple = ()):
        self._check()
        try:
            return self._connection.execute(sql, params)
        except BaseException:
            self._failed = True
            raise

    def _ensure_meta(self) -> None:
        tenant_id, owner_id = self._owner
        self._execute(
            """
            INSERT INTO enterprise.cron_meta(tenant_id, owner_id, revision, updated_at_ms)
            VALUES (%s, %s, 0, %s)
            ON CONFLICT (tenant_id, owner_id) DO NOTHING
            """,
            (tenant_id, owner_id, _now_ms()),
        )

    def _bump_revision(self) -> None:
        tenant_id, owner_id = self._owner
        self._execute(
            """
            UPDATE enterprise.cron_meta
               SET revision = revision + 1, updated_at_ms = %s
             WHERE tenant_id = %s AND owner_id = %s
            """,
            (_now_ms(), tenant_id, owner_id),
        )

    @staticmethod
    def _job_from_payload(payload: dict[str, Any]) -> CronJob:
        return CronJob.from_dict(deepcopy(payload))

    @staticmethod
    def _payload_state(payload: dict[str, Any]) -> dict[str, Any]:
        state = payload.setdefault("state", {})
        if not isinstance(state, dict):
            payload["state"] = state = {}
        history = state.setdefault("run_history", [])
        if not isinstance(history, list):
            state["run_history"] = []
        return state

    @staticmethod
    def _upsert_params(payload: dict[str, Any], *, revision: int | None = None) -> dict[str, Any]:
        job = PostgresCronRepository._job_from_payload(payload)
        state = payload.get("state") or {}
        schedule = job.schedule
        params = {
            "job_id": job.id,
            "owner_key": job.owner.key,
            "name": job.name,
            "message": job.message,
            "schedule_kind": schedule.kind,
            "at_ms": schedule.at_ms,
            "every_seconds": schedule.every_seconds,
            "cron_expr": schedule.expr,
            "tz": schedule.tz or "",
            "enabled": job.enabled,
            "delete_after_run": job.delete_after_run,
            "created_at_ms": job.created_at_ms,
            "next_run_at_ms": state.get("next_run_at_ms"),
            "last_run_at_ms": state.get("last_run_at_ms"),
            "last_status": state.get("last_status"),
            "last_error": state.get("last_error"),
            "payload": deepcopy(payload),
            "updated_at_ms": _now_ms(),
        }
        if revision is not None:
            params["revision"] = revision
        return params

    # ── CronRepository protocol ──────────────────────────────────

    def revision(self) -> int:
        with self._unit() as unit:
            row = unit._execute(
                """
                SELECT revision FROM enterprise.cron_meta
                 WHERE tenant_id = %s AND owner_id = %s
                """,
                unit._owner,
            ).fetchone()
            return int(row["revision"]) if row else 0

    def list_payloads(self) -> list[dict[str, Any]]:
        with self._unit() as unit:
            rows = unit._execute(
                """
                SELECT payload FROM enterprise.cron_jobs
                 WHERE tenant_id = %s AND owner_id = %s
                 ORDER BY COALESCE(next_run_at_ms, 0), job_id
                """,
                unit._owner,
            ).fetchall()
            return [deepcopy(row["payload"]) for row in rows]

    def upsert(self, payload: dict[str, Any]) -> None:
        payload = deepcopy(payload)
        params = self._upsert_params(payload)
        tenant_id, owner_id = self._owner
        with self._unit(write=True) as unit:
            unit._execute(
                """
                INSERT INTO enterprise.cron_jobs(
                    tenant_id, owner_id, job_id, owner_key, name, message,
                    schedule_kind, at_ms, every_seconds, cron_expr, tz,
                    enabled, delete_after_run, created_at_ms, next_run_at_ms,
                    last_run_at_ms, last_status, last_error, payload, revision, updated_at_ms
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, 1, %s
                )
                ON CONFLICT (tenant_id, owner_id, job_id) DO UPDATE SET
                    owner_key = EXCLUDED.owner_key,
                    name = EXCLUDED.name,
                    message = EXCLUDED.message,
                    schedule_kind = EXCLUDED.schedule_kind,
                    at_ms = EXCLUDED.at_ms,
                    every_seconds = EXCLUDED.every_seconds,
                    cron_expr = EXCLUDED.cron_expr,
                    tz = EXCLUDED.tz,
                    enabled = EXCLUDED.enabled,
                    delete_after_run = EXCLUDED.delete_after_run,
                    created_at_ms = EXCLUDED.created_at_ms,
                    next_run_at_ms = EXCLUDED.next_run_at_ms,
                    last_run_at_ms = EXCLUDED.last_run_at_ms,
                    last_status = EXCLUDED.last_status,
                    last_error = EXCLUDED.last_error,
                    payload = EXCLUDED.payload,
                    revision = enterprise.cron_jobs.revision + 1,
                    updated_at_ms = EXCLUDED.updated_at_ms
                """,
                (
                    tenant_id,
                    owner_id,
                    params["job_id"],
                    params["owner_key"],
                    params["name"],
                    params["message"],
                    params["schedule_kind"],
                    params["at_ms"],
                    params["every_seconds"],
                    params["cron_expr"],
                    params["tz"],
                    params["enabled"],
                    params["delete_after_run"],
                    params["created_at_ms"],
                    params["next_run_at_ms"],
                    params["last_run_at_ms"],
                    params["last_status"],
                    params["last_error"],
                    _jsonb(params["payload"]),
                    params["updated_at_ms"],
                ),
            )
            unit._bump_revision()

    def delete(self, job_id: str, *, owner_key: str | None = None) -> bool:
        with self._unit(write=True) as unit:
            if owner_key is None:
                rows = unit._execute(
                    """
                    DELETE FROM enterprise.cron_jobs
                     WHERE tenant_id = %s AND owner_id = %s AND job_id = %s
                     RETURNING 1
                    """,
                    (*unit._owner, job_id),
                ).fetchall()
            else:
                rows = unit._execute(
                    """
                    DELETE FROM enterprise.cron_jobs
                     WHERE tenant_id = %s AND owner_id = %s AND job_id = %s AND owner_key = %s
                     RETURNING 1
                    """,
                    (*unit._owner, job_id, owner_key),
                ).fetchall()
            changed = bool(rows)
            if changed:
                unit._bump_revision()
            return changed

    def delete_owner(self, owner_key: str) -> int:
        with self._unit(write=True) as unit:
            rows = unit._execute(
                """
                DELETE FROM enterprise.cron_jobs
                 WHERE tenant_id = %s AND owner_id = %s AND owner_key = %s
                 RETURNING 1
                """,
                (*unit._owner, owner_key),
            ).fetchall()
            count = len(rows)
            if count:
                unit._bump_revision()
            return count

    def set_enabled(self, job_id: str, enabled: bool, *, owner_key: str | None = None) -> bool:
        with self._unit(write=True) as unit:
            row = unit._execute(
                """
                SELECT payload, revision
                  FROM enterprise.cron_jobs
                 WHERE tenant_id = %s AND owner_id = %s AND job_id = %s
                 FOR UPDATE
                """,
                (*unit._owner, job_id),
            ).fetchone()
            if row is None:
                return False
            payload = deepcopy(row["payload"])
            job = self._job_from_payload(payload)
            if owner_key is not None and job.owner.key != owner_key:
                return False
            if job.enabled == enabled:
                return True
            payload["enabled"] = enabled
            params = self._upsert_params(payload, revision=int(row["revision"]) + 1)
            unit._execute(
                """
                UPDATE enterprise.cron_jobs
                   SET enabled = %s,
                       payload = %s,
                       revision = %s,
                       updated_at_ms = %s
                 WHERE tenant_id = %s AND owner_id = %s AND job_id = %s
                   AND revision = %s
                """,
                (
                    enabled,
                    _jsonb(params["payload"]),
                    params["revision"],
                    params["updated_at_ms"],
                    *unit._owner,
                    job_id,
                    row["revision"],
                ),
            )
            unit._bump_revision()
            return True

    # ── PG execution state ────────────────────────────────────────

    def claim_due(
        self,
        now_ms: int | None = None,
        *,
        worker_id: str,
        limit: int = 1,
    ) -> list[CronExecutionClaim]:
        if not worker_id:
            raise ValueError("worker_id is required")
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        now_ms = _now_ms() if now_ms is None else int(now_ms)
        with self._unit(write=True) as unit:
            due_rows = unit._execute(
                """
                SELECT job_id, owner_key, next_run_at_ms, payload, revision
                  FROM enterprise.cron_jobs
                 WHERE tenant_id = %s AND owner_id = %s
                   AND enabled
                   AND next_run_at_ms IS NOT NULL
                   AND next_run_at_ms <= %s
                 ORDER BY next_run_at_ms, job_id
                 FOR UPDATE SKIP LOCKED
                 LIMIT %s
                """,
                (*unit._owner, now_ms, limit),
            ).fetchall()
            claims: list[CronExecutionClaim] = []
            for row in due_rows:
                payload = deepcopy(row["payload"])
                job = self._job_from_payload(payload)
                scheduled_run_at_ms = int(row["next_run_at_ms"])
                claimed_at_ms = _now_ms()
                claim_revision = int(row["revision"]) + 1
                execution_id = str(uuid.uuid4())
                state = self._payload_state(payload)
                state["next_run_at_ms"] = None
                unit._execute(
                    """
                    UPDATE enterprise.cron_jobs
                       SET next_run_at_ms = NULL,
                           payload = %s,
                           revision = revision + 1,
                           updated_at_ms = %s
                     WHERE tenant_id = %s AND owner_id = %s
                       AND job_id = %s AND revision = %s
                    """,
                    (
                        _jsonb(payload),
                        claimed_at_ms,
                        *unit._owner,
                        row["job_id"],
                        row["revision"],
                    ),
                )
                unit._execute(
                    """
                    INSERT INTO enterprise.cron_executions(
                        tenant_id, owner_id, execution_id, job_id, owner_key,
                        scheduled_run_at_ms, job_revision, worker_id, status,
                        claimed_at_ms, duration_ms, payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'claimed', %s, 0, %s)
                    """,
                    (
                        *unit._owner,
                        execution_id,
                        row["job_id"],
                        row["owner_key"],
                        scheduled_run_at_ms,
                        claim_revision,
                        worker_id,
                        claimed_at_ms,
                        _jsonb(asdict(job)),
                    ),
                )
                claims.append(
                    CronExecutionClaim(
                        execution_id=execution_id,
                        job=job,
                        job_revision=claim_revision,
                        scheduled_run_at_ms=scheduled_run_at_ms,
                        claimed_at_ms=claimed_at_ms,
                        worker_id=worker_id,
                    )
                )
            if claims:
                unit._bump_revision()
            return claims

    def complete_execution(
        self,
        claim: CronExecutionClaim,
        *,
        status: str,
        error: str | None = None,
        completed_at_ms: int | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(claim, CronExecutionClaim):
            raise TypeError("CronExecutionClaim is required")
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"unsupported cron execution status {status!r}")
        completed_at_ms = _now_ms() if completed_at_ms is None else int(completed_at_ms)
        duration_ms = max(0, completed_at_ms - claim.claimed_at_ms)
        with self._unit(write=True) as unit:
            execution = unit._execute(
                """
                SELECT *
                  FROM enterprise.cron_executions
                 WHERE tenant_id = %s AND owner_id = %s AND execution_id = %s
                 FOR UPDATE
                """,
                (*unit._owner, claim.execution_id),
            ).fetchone()
            if execution is None or execution["worker_id"] != claim.worker_id:
                raise CronClaimConflict("cron execution claim is not current")
            if execution["status"] != "claimed":
                if execution["status"] != status:
                    raise CronClaimConflict("cron execution already completed differently")
                return unit._payload_for_job(execution["job_id"])

            row = unit._execute(
                """
                SELECT payload, revision, schedule_kind, delete_after_run
                  FROM enterprise.cron_jobs
                 WHERE tenant_id = %s AND owner_id = %s AND job_id = %s
                 FOR UPDATE
                """,
                (*unit._owner, execution["job_id"]),
            ).fetchone()
            if row is None or int(row["revision"]) != claim.job_revision:
                raise CronClaimConflict("cron job version no longer matches claim")

            payload = deepcopy(row["payload"])
            state = self._payload_state(payload)
            state["last_run_at_ms"] = claim.claimed_at_ms
            state["last_status"] = status
            state["last_error"] = error
            history = [
                *state.get("run_history", []),
                asdict(
                    CronRunRecord(
                        run_at_ms=claim.claimed_at_ms,
                        status=status,
                        duration_ms=duration_ms,
                        error=error,
                    )
                ),
            ][-_MAX_RUN_HISTORY:]
            state["run_history"] = history

            next_payload: dict[str, Any] | None
            if status == "uncertain":
                state["next_run_at_ms"] = None
                next_payload = payload
            else:
                job = self._job_from_payload(payload)
                if job.delete_after_run or job.schedule.kind == "at":
                    next_payload = None
                else:
                    next_run_at_ms = compute_next_run(job.schedule, completed_at_ms)
                    if next_run_at_ms is None:
                        next_payload = None
                    else:
                        state["next_run_at_ms"] = next_run_at_ms
                        next_payload = payload

            unit._execute(
                """
                UPDATE enterprise.cron_executions
                   SET status = %s,
                       completed_at_ms = %s,
                       duration_ms = %s,
                       error = %s
                 WHERE tenant_id = %s AND owner_id = %s AND execution_id = %s
                """,
                (status, completed_at_ms, duration_ms, error, *unit._owner, claim.execution_id),
            )
            if next_payload is None:
                unit._execute(
                    """
                    DELETE FROM enterprise.cron_jobs
                     WHERE tenant_id = %s AND owner_id = %s AND job_id = %s
                    """,
                    (*unit._owner, execution["job_id"]),
                )
            else:
                params = self._upsert_params(next_payload, revision=claim.job_revision + 1)
                unit._execute(
                    """
                    UPDATE enterprise.cron_jobs
                       SET next_run_at_ms = %s,
                           last_run_at_ms = %s,
                           last_status = %s,
                           last_error = %s,
                           payload = %s,
                           revision = %s,
                           updated_at_ms = %s
                     WHERE tenant_id = %s AND owner_id = %s AND job_id = %s
                       AND revision = %s
                    """,
                    (
                        params["next_run_at_ms"],
                        params["last_run_at_ms"],
                        params["last_status"],
                        params["last_error"],
                        _jsonb(params["payload"]),
                        params["revision"],
                        params["updated_at_ms"],
                        *unit._owner,
                        execution["job_id"],
                        claim.job_revision,
                    ),
                )
            unit._bump_revision()
            return deepcopy(next_payload) if next_payload is not None else None

    def _payload_for_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._execute(
            """
            SELECT payload FROM enterprise.cron_jobs
             WHERE tenant_id = %s AND owner_id = %s AND job_id = %s
            """,
            (*self._owner, job_id),
        ).fetchone()
        return deepcopy(row["payload"]) if row else None

    def list_executions(self, job_id: str | None = None) -> list[dict[str, Any]]:
        with self._unit() as unit:
            if job_id is None:
                rows = unit._execute(
                    """
                    SELECT execution_id::text AS execution_id, job_id, owner_key,
                           scheduled_run_at_ms, job_revision, worker_id, status,
                           claimed_at_ms, completed_at_ms, duration_ms, error
                      FROM enterprise.cron_executions
                     WHERE tenant_id = %s AND owner_id = %s
                     ORDER BY claimed_at_ms, execution_id
                    """,
                    unit._owner,
                ).fetchall()
            else:
                rows = unit._execute(
                    """
                    SELECT execution_id::text AS execution_id, job_id, owner_key,
                           scheduled_run_at_ms, job_revision, worker_id, status,
                           claimed_at_ms, completed_at_ms, duration_ms, error
                      FROM enterprise.cron_executions
                     WHERE tenant_id = %s AND owner_id = %s AND job_id = %s
                     ORDER BY claimed_at_ms, execution_id
                    """,
                    (*unit._owner, job_id),
                ).fetchall()
            return [dict(row) for row in rows]


class AsyncPostgresCronRepository:
    """Async façade that runs each callback in one bounded PG transaction."""

    def __init__(self, database: SyncDatabase, scope: TenantScope) -> None:
        self._repo = PostgresCronRepository(database, scope)

    async def run(self, callback: Callable[[PostgresCronRepository], T]) -> T:
        unit = None

        def work(connection):
            nonlocal unit
            unit = self._repo._bind(connection)
            try:
                return _complete_callback(callback(unit))
            finally:
                unit._lease.active = False

        return await self._repo.db.run(self._repo.scope, work)


__all__ = [
    "AsyncPostgresCronRepository",
    "CronClaimConflict",
    "CronExecutionClaim",
    "CronRepositoryError",
    "PostgresCronRepository",
]
