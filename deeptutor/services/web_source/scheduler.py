"""PG-only compatible web-source sync scheduler facade.

The upstream scheduler persists job state in a local file-backed store.  This
enterprise branch cannot introduce local runtime stores, and a PostgreSQL job
store for web-source auto-sync has not been designed yet.  Keep the public API
shape used by the knowledge router so the service can start, while preserving
manual web-source sync and making background scheduling non-persistent and
fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

WEB_SYNC_MIN_INTERVAL_HOURS = 1
WEB_SYNC_MAX_INTERVAL_HOURS = 168
WEB_SYNC_INTERVAL_HOURS = 24


def _now_ms() -> int:
    return int(time.time() * 1000)


def normalize_sync_interval(value: Any) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        return WEB_SYNC_INTERVAL_HOURS
    return max(WEB_SYNC_MIN_INTERVAL_HOURS, min(WEB_SYNC_MAX_INTERVAL_HOURS, interval))


@dataclass(slots=True)
class WebSourceSyncJob:
    """In-memory compatibility view for one scheduled web-source sync job."""

    owner_id: str
    kb_name: str
    source_id: str
    next_run_at_ms: int
    updated_at_ms: int
    state: str = "disabled"
    last_run_at_ms: int | None = None
    attempt: int = 0
    error: str | None = "Background web-source sync requires a PostgreSQL scheduler store"
    cancel_requested: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "kb_name": self.kb_name,
            "source_id": self.source_id,
            "state": self.state,
            "next_run_at": self.next_run_at_ms,
            "last_run_at": self.last_run_at_ms,
            "attempt": self.attempt,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
        }


class DisabledWebSourceSyncRepository:
    """Repository facade that never writes local runtime state."""

    @staticmethod
    def key(job: WebSourceSyncJob) -> tuple[str, str, str]:
        return job.owner_id, job.kb_name, job.source_id

    def ensure_source(self, source_key: tuple[str, str, str]) -> WebSourceSyncJob:
        now = _now_ms()
        return WebSourceSyncJob(
            owner_id=source_key[0],
            kb_name=source_key[1],
            source_id=source_key[2],
            next_run_at_ms=now,
            updated_at_ms=now,
        )

    def delete(self, source_key: tuple[str, str, str]) -> None:
        return None

    def list_jobs(self, owner_id: str, kb_name: str) -> list[WebSourceSyncJob]:
        return []

    def get(self, source_key: tuple[str, str, str]) -> WebSourceSyncJob | None:
        return None

    def recover_interrupted(self, runner_id: str) -> None:
        return None

    def due_jobs(self, now_ms: int | None = None) -> list[WebSourceSyncJob]:
        return []

    def reconcile_sources(
        self,
        source_keys: set[tuple[str, str, str]],
        *,
        scanned_owner_ids: set[str] | None = None,
    ) -> None:
        return None


class WebSourceSyncScheduler:
    """No-local-store scheduler facade used until a PG-backed scheduler exists."""

    def __init__(self, *, repository: DisabledWebSourceSyncRepository | None = None, **_: Any) -> None:
        self._repository = repository or DisabledWebSourceSyncRepository()
        self._running = False

    @property
    def repo(self) -> DisabledWebSourceSyncRepository:
        return self._repository

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def request_cancel(self, owner_id: str, kb_name: str, source_id: str) -> bool:
        return False

    async def retry(self, owner_id: str, kb_name: str, source_id: str) -> bool:
        return False


_SCHEDULER: WebSourceSyncScheduler | None = None


def get_web_source_sync_scheduler() -> WebSourceSyncScheduler:
    global _SCHEDULER
    if _SCHEDULER is None:
        _SCHEDULER = WebSourceSyncScheduler()
    return _SCHEDULER


def set_web_source_sync_scheduler(scheduler: WebSourceSyncScheduler | None) -> None:
    """Testing seam for callers that need an explicit scheduler facade."""

    global _SCHEDULER
    _SCHEDULER = scheduler
