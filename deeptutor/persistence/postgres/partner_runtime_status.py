"""PostgreSQL-backed Partner runtime status projection."""

from __future__ import annotations

from copy import deepcopy
import json
import math
import time
from typing import Any, Callable

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.connection import SyncDatabase
from deeptutor.persistence.postgres.scope import TenantScope

_ALLOWED_STATES = frozenset({"running", "stopped", "reload_failed", "start_failed"})
_DEFAULT_TTL_SECONDS = 60.0


def _jsonb(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda obj: json.dumps(obj, ensure_ascii=False, allow_nan=False))


class PartnerRuntimeStatusError(RuntimeError):
    """Base class for PG Partner runtime-status consistency errors."""


class PartnerRuntimeStatusConflict(PartnerRuntimeStatusError):
    """A non-expired status is owned by another worker."""


class PostgresPartnerRuntimeStatusRepository:
    """Owner-scoped PG projection for Partner lifecycle status.

    The row is keyed by trusted tenant/owner/partner and records the current
    worker plus a monotonically increasing version.  A different worker may only
    replace the projection after the existing TTL expires, preventing a stale
    process from overwriting a newer leader's status.
    """

    def __init__(
        self,
        database: SyncDatabase,
        *,
        tenant_id: str,
        worker_id: str,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
        current_owner_id: str | None = None,
    ) -> None:
        if not isinstance(database, SyncDatabase):
            raise TypeError("SyncDatabase is required")
        if not worker_id or "\x00" in worker_id:
            raise ValueError("worker_id is required")
        if not math.isfinite(ttl_seconds) or ttl_seconds < 0:
            raise ValueError("ttl_seconds must be a finite non-negative number")
        # TenantScope normalizes and validates the UUID once.
        normalized_tenant = TenantScope(tenant_id, "@partner-runtime").tenant_id
        self.db = database
        self.tenant_id = normalized_tenant
        self.worker_id = str(worker_id)
        self.ttl_seconds = float(ttl_seconds)
        self._ttl_ms = int(round(self.ttl_seconds * 1000))
        self._clock = clock
        self._current_owner_id = str(current_owner_id or "") or None

    def _now_ms(self) -> int:
        now = float(self._clock())
        if not math.isfinite(now) or now < 0:
            raise ValueError("clock must return a finite non-negative timestamp")
        return int(round(now * 1000))

    def _scope(self, owner_id: str) -> TenantScope:
        return TenantScope(self.tenant_id, owner_id)

    def _resolve_owner_id(self, owner_id: str | None) -> str:
        if owner_id:
            return str(owner_id)
        if self._current_owner_id:
            return self._current_owner_id
        from deeptutor.multi_user.context import get_current_user_or_none

        user = get_current_user_or_none()
        if (
            user is not None
            and user.scope.kind == "tenant"
            and user.scope.tenant_id == self.tenant_id
            and user.id == user.scope.user_id
        ):
            return user.id
        raise PermissionError("Partner runtime status owner is required")

    def _safe_payload(
        self,
        partner_id: str,
        *,
        owner_id: str,
        worker_id: str,
        running: bool,
        state: str,
        payload: dict[str, Any] | None,
        started_at: str | None,
        last_reload_error: str | None,
        version: int,
        updated_at_ms: int,
        expires_at_ms: int,
    ) -> dict[str, Any]:
        safe_payload = deepcopy(payload or {})
        if not isinstance(safe_payload, dict):
            safe_payload = {}
        safe_payload.pop("channels", None)
        safe_payload.update(
            {
                "tenant_id": self.tenant_id,
                "owner_id": owner_id,
                "partner_id": partner_id,
                "worker_id": worker_id,
                "runtime_worker_id": worker_id,
                # Backward-compatible response key; older callers treated this
                # as the process/worker owner, not the Partner's human owner.
                "runtime_owner_id": worker_id,
                "runtime_version": version,
                "runtime_ttl_seconds": self.ttl_seconds,
                "runtime_updated_at": updated_at_ms / 1000.0,
                "runtime_expires_at": expires_at_ms / 1000.0,
                "runtime_expired": False,
                "running": bool(running),
                "runtime_state": state,
                "started_at": started_at,
                "last_reload_error": last_reload_error,
            }
        )
        return safe_payload

    def _project(self, row: dict[str, Any], *, now_ms: int | None = None) -> dict[str, Any]:
        payload = deepcopy(row["payload"] or {})
        if not isinstance(payload, dict):
            payload = {}
        updated_at_ms = int(row["updated_at_ms"])
        expires_at_ms = int(row["expires_at_ms"])
        ttl_ms = int(row["ttl_ms"])
        expired = (self._now_ms() if now_ms is None else now_ms) > expires_at_ms
        state = "expired" if expired else str(row["state"])
        payload.update(
            {
                "tenant_id": str(row["tenant_id"]),
                "owner_id": str(row["owner_id"]),
                "partner_id": str(row["partner_id"]),
                "worker_id": str(row["worker_id"]),
                "runtime_worker_id": str(row["worker_id"]),
                "runtime_owner_id": str(row["worker_id"]),
                "runtime_version": int(row["version"]),
                "runtime_ttl_seconds": ttl_ms / 1000.0,
                "runtime_updated_at": updated_at_ms / 1000.0,
                "runtime_expires_at": expires_at_ms / 1000.0,
                "runtime_expired": expired,
                "running": bool(row["running"]) and not expired,
                "runtime_state": state,
                "started_at": row["started_at"],
                "last_reload_error": row["last_reload_error"],
            }
        )
        return payload

    def set(
        self,
        partner_id: str,
        *,
        owner_id: str,
        running: bool,
        state: str,
        payload: dict[str, Any] | None = None,
        started_at: str | None = None,
        last_reload_error: str | None = None,
        worker_id: str | None = None,
    ) -> dict[str, Any]:
        partner_id = str(partner_id or "").strip()
        if not partner_id:
            raise ValueError("partner_id is required")
        if state not in _ALLOWED_STATES:
            raise ValueError(f"unsupported Partner runtime state {state!r}")
        owner_id = self._resolve_owner_id(owner_id)
        worker_id = str(worker_id or self.worker_id)
        if not worker_id:
            raise ValueError("worker_id is required")
        now_ms = self._now_ms()
        expires_at_ms = now_ms + self._ttl_ms
        with self.db.transaction(self._scope(owner_id)) as connection:
            row = connection.execute(
                """
                SELECT worker_id, version, expires_at_ms
                  FROM enterprise.partner_runtime_status
                 WHERE tenant_id = %s AND owner_id = %s AND partner_id = %s
                 FOR UPDATE
                """,
                (self.tenant_id, owner_id, partner_id),
            ).fetchone()
            if row is not None and row["worker_id"] != worker_id and int(row["expires_at_ms"]) >= now_ms:
                raise PartnerRuntimeStatusConflict("Partner runtime status is owned by current worker")
            version = int(row["version"]) + 1 if row is not None else 1
            safe_payload = self._safe_payload(
                partner_id,
                owner_id=owner_id,
                worker_id=worker_id,
                running=running,
                state=state,
                payload=payload,
                started_at=started_at,
                last_reload_error=last_reload_error,
                version=version,
                updated_at_ms=now_ms,
                expires_at_ms=expires_at_ms,
            )
            if row is None:
                connection.execute(
                    """
                    INSERT INTO enterprise.partner_runtime_status(
                        tenant_id, owner_id, partner_id, worker_id, version,
                        running, state, started_at, last_reload_error, payload,
                        updated_at_ms, expires_at_ms, ttl_ms
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.tenant_id,
                        owner_id,
                        partner_id,
                        worker_id,
                        version,
                        bool(running),
                        state,
                        started_at,
                        last_reload_error,
                        _jsonb(safe_payload),
                        now_ms,
                        expires_at_ms,
                        self._ttl_ms,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE enterprise.partner_runtime_status
                       SET worker_id = %s,
                           version = %s,
                           running = %s,
                           state = %s,
                           started_at = %s,
                           last_reload_error = %s,
                           payload = %s,
                           updated_at_ms = %s,
                           expires_at_ms = %s,
                           ttl_ms = %s
                     WHERE tenant_id = %s AND owner_id = %s AND partner_id = %s
                    """,
                    (
                        worker_id,
                        version,
                        bool(running),
                        state,
                        started_at,
                        last_reload_error,
                        _jsonb(safe_payload),
                        now_ms,
                        expires_at_ms,
                        self._ttl_ms,
                        self.tenant_id,
                        owner_id,
                        partner_id,
                    ),
                )
        return safe_payload

    def get(self, partner_id: str, *, owner_id: str | None = None) -> dict[str, Any] | None:
        partner_id = str(partner_id or "").strip()
        if not partner_id:
            return None
        owner_id = self._resolve_owner_id(owner_id)
        now_ms = self._now_ms()
        with self.db.transaction(self._scope(owner_id)) as connection:
            row = connection.execute(
                """
                SELECT tenant_id, owner_id, partner_id, worker_id, version, running, state,
                       started_at, last_reload_error, payload, updated_at_ms, expires_at_ms, ttl_ms
                  FROM enterprise.partner_runtime_status
                 WHERE tenant_id = %s AND owner_id = %s AND partner_id = %s
                """,
                (self.tenant_id, owner_id, partner_id),
            ).fetchone()
        return self._project(row, now_ms=now_ms) if row else None

    def list(self, *, owner_id: str | None = None) -> dict[str, dict[str, Any]]:
        owner_id = self._resolve_owner_id(owner_id)
        now_ms = self._now_ms()
        with self.db.transaction(self._scope(owner_id)) as connection:
            rows = connection.execute(
                """
                SELECT tenant_id, owner_id, partner_id, worker_id, version, running, state,
                       started_at, last_reload_error, payload, updated_at_ms, expires_at_ms, ttl_ms
                  FROM enterprise.partner_runtime_status
                 WHERE tenant_id = %s AND owner_id = %s
                 ORDER BY updated_at_ms DESC, partner_id
                """,
                (self.tenant_id, owner_id),
            ).fetchall()
        return {str(row["partner_id"]): self._project(row, now_ms=now_ms) for row in rows}

    def delete(self, partner_id: str, *, owner_id: str | None = None) -> None:
        partner_id = str(partner_id or "").strip()
        if not partner_id:
            return
        owner_id = self._resolve_owner_id(owner_id)
        with self.db.transaction(self._scope(owner_id)) as connection:
            connection.execute(
                """
                DELETE FROM enterprise.partner_runtime_status
                 WHERE tenant_id = %s AND owner_id = %s AND partner_id = %s
                """,
                (self.tenant_id, owner_id, partner_id),
            )


__all__ = [
    "PartnerRuntimeStatusConflict",
    "PartnerRuntimeStatusError",
    "PostgresPartnerRuntimeStatusRepository",
]
