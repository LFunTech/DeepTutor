"""SQLite cron/Partners/MarginNote 快照导入到 PG 运行投影域。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from urllib.request import pathname2url
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from deeptutor.services.cron.service import CronJob, CronRunRecord

from .planner import source_check_manifest
from .stage import MigrationStageRepository

_CRON_VERSION = "cron_sqlite/v1"
_PARTNER_STATUS_VERSION = "partner_runtime_status_sqlite/v1"
_MARGINNOTE_VERSION = "marginnote_sqlite/v1"
_SUPPORTED = {_CRON_VERSION, _PARTNER_STATUS_VERSION, _MARGINNOTE_VERSION}
_ALLOWED_PARTNER_STATES = {"running", "stopped", "reload_failed", "start_failed"}
_ALLOWED_MN_TYPES = {"note", "excerpt", "card", "mindmap_node", "document", "comment"}
_CRON_TERMINAL_STATUSES = {"ok", "error", "skipped", "uncertain"}
_CRON_STATE_KEYS = {"next_run_at_ms", "last_run_at_ms", "last_status", "last_error", "run_history"}


def _sqlite_uri(path: Path) -> str:
    return f"file:{pathname2url(str(path))}?mode=ro&immutable=1"


def _manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonb(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda obj: json.dumps(obj, ensure_ascii=False, allow_nan=False))


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default
    return parsed


def _owner_mappings(manifest: dict[str, Any]) -> dict[str, str]:
    raw = manifest.get("owner_mappings")
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    mapping: dict[str, str] = {}
    for item in raw or []:
        if isinstance(item, dict) and item.get("source_owner_id") and item.get("target_owner_id"):
            mapping[str(item["source_owner_id"])] = str(item["target_owner_id"])
    return mapping


def _read_rows(snapshot: Path, orders: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    with sqlite3.connect(_sqlite_uri(snapshot), uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        rows: dict[str, list[dict[str, Any]]] = {}
        for table, order in orders.items():
            if table not in tables:
                rows[table] = []
                continue
            rows[table] = [
                dict(row)
                for row in connection.execute(
                    f'SELECT * FROM "{table}" {order}'  # nosec B608 - table/order 来自常量
                ).fetchall()
            ]
        return rows


def _read_cron_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    return _read_rows(
        snapshot,
        {
            "cron_jobs": "ORDER BY COALESCE(next_run_at_ms, 0), id",
            "cron_meta": "ORDER BY singleton",
        },
    )


def _read_partner_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    return _read_rows(
        snapshot,
        {"partner_runtime_status": "ORDER BY updated_at, partner_id"},
    )


def _read_marginnote_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    return _read_rows(
        snapshot,
        {
            "mn4_devices": "ORDER BY paired_at, device_id",
            "mn4_cursors": "ORDER BY device_id",
            "mn4_objects": "ORDER BY updated_at, device_id, object_id",
            "mn4_tombstones": "ORDER BY deleted_at, device_id, object_id",
        },
    )


def _count(rows: dict[str, list[dict[str, Any]]]) -> int:
    return sum(len(value) for value in rows.values())


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _bool_sqlite(value: Any) -> bool:
    return bool(int(value or 0))


def _stamp(*values: Any) -> str:
    candidates = [str(value) for value in values if value not in (None, "")]
    return max(candidates) if candidates else ""


async def _verify_target_owner(connection, tenant_id: str, owner_id: str) -> None:
    row = await (
        await connection.execute(
            """
            SELECT disabled
              FROM enterprise.users
             WHERE tenant_id=%s AND id=%s
            """,
            (tenant_id, owner_id),
        )
    ).fetchone()
    if row is None:
        raise PermissionError("target owner mapping does not exist")
    if row["disabled"]:
        raise PermissionError("target owner is disabled")


async def _record_source(
    connection,
    batch_id: str,
    *,
    source: dict[str, Any],
    target_owner: str,
    rows_total: int,
    rows_done: int = 0,
    status: str = "importing",
) -> None:
    await connection.execute(
        """
        INSERT INTO migration_stage.sources(
            batch_id, source_id, source_type, source_version,
            source_owner_id, target_owner_id, fingerprint, manifest,
            rows_total, rows_done, status
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
        ON CONFLICT (batch_id, source_id) DO UPDATE SET
            source_type=EXCLUDED.source_type,
            source_version=EXCLUDED.source_version,
            source_owner_id=EXCLUDED.source_owner_id,
            target_owner_id=EXCLUDED.target_owner_id,
            fingerprint=EXCLUDED.fingerprint,
            manifest=EXCLUDED.manifest,
            rows_total=EXCLUDED.rows_total,
            rows_done=EXCLUDED.rows_done,
            status=EXCLUDED.status
        """,
        (
            batch_id,
            str(source["source_id"]),
            str(source.get("source_type") or "sqlite"),
            str(source["source_version"]),
            str(source["source_owner_id"]),
            target_owner,
            str(source["snapshot"]["sha256"]),
            Jsonb(source),
            int(rows_total),
            int(rows_done),
            status,
        ),
    )


async def _record_mapping(
    connection,
    batch_id: str,
    *,
    domain: str,
    source_id: str,
    source_owner_id: str,
    source_key: str,
    target_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await connection.execute(
        """
        INSERT INTO migration_stage.id_mappings(
            batch_id, domain, source_id, source_owner_id, source_key,
            target_key, metadata
        ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (batch_id, domain, source_id, source_owner_id, source_key)
        DO UPDATE SET target_key=EXCLUDED.target_key,
                      metadata=EXCLUDED.metadata
        """,
        (
            batch_id,
            domain,
            source_id,
            source_owner_id,
            source_key,
            target_key,
            Jsonb(metadata or {}),
        ),
    )


class _SessionResolver:
    def __init__(self, connection, *, tenant_id: str, owner_id: str, source_owner_id: str) -> None:
        self.connection = connection
        self.tenant_id = tenant_id
        self.owner_id = owner_id
        self.source_owner_id = source_owner_id

    async def session(self, source_key: Any, *, required: bool = False) -> str:
        value = str(source_key or "")
        if not value:
            if required:
                raise ValueError("missing mapping for sessions: empty source key")
            return ""
        candidates = await (
            await self.connection.execute(
                """
                SELECT DISTINCT m.target_key AS target
                  FROM migration_stage.id_mappings m
                  JOIN migration_stage.sources s
                    ON s.batch_id=m.batch_id AND s.source_id=m.source_id
                 WHERE m.domain='sessions'
                   AND m.source_owner_id=%s
                   AND m.source_key=%s
                   AND s.target_owner_id=%s
                   AND s.status='verified'
                   AND m.target_key IS NOT NULL
                """,
                (self.source_owner_id, value, self.owner_id),
            )
        ).fetchall()
        if len(candidates) == 1:
            target = str(candidates[0]["target"])
            if await self._target_session_exists(target):
                return target
            raise ValueError(f"mapped session target does not exist: {target!r}")
        if len(candidates) > 1:
            raise ValueError(f"ambiguous mapping for sessions: {value!r}")
        if await self._target_session_exists(value):
            return value
        if required:
            raise ValueError(f"missing mapping for sessions: {value!r}")
        return value

    async def _target_session_exists(self, session_id: str) -> bool:
        row = await (
            await self.connection.execute(
                """
                SELECT 1 FROM enterprise.sessions
                 WHERE tenant_id=%s AND owner_id=%s AND id=%s
                 LIMIT 1
                """,
                (self.tenant_id, self.owner_id, session_id),
            )
        ).fetchone()
        return row is not None


class SQLiteRuntimeProjectionImporter:
    """导入 `cron_sqlite`、Partners runtime status 和 MarginNote SQLite 源。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def import_manifest(self, manifest_path: str | Path, *, operator: str) -> dict[str, Any]:
        manifest_path = Path(manifest_path)
        report = source_check_manifest(manifest_path)
        if not report.ok:
            raise ValueError(f"manifest source-check failed: {report.issues}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        tenant_id = str(manifest.get("target", {}).get("tenant_id") or "")
        owners = _owner_mappings(manifest)
        repo = MigrationStageRepository(self._dsn)
        batch_id = await repo.create_batch(
            target_tenant_id=tenant_id,
            manifest_sha256=_manifest_hash(manifest_path),
            manifest=manifest,
            operator=operator,
        )
        batch = str(batch_id)
        await repo.enter_maintenance(batch_id, tenant_id=tenant_id, reason="sqlite-runtime-import")
        imported = {
            "cron_jobs": 0,
            "cron_uncertain_executions": 0,
            "partner_status": 0,
            "marginnote_devices": 0,
            "marginnote_cursors": 0,
            "marginnote_objects": 0,
            "marginnote_tombstones": 0,
        }
        skipped_newer_target = 0
        deduped_sources = 0
        try:
            async with await psycopg.AsyncConnection.connect(
                self._dsn, row_factory=dict_row
            ) as connection:
                async with connection.transaction():
                    sources = [source for source in manifest.get("sources") or []]
                    for source in sources:
                        if source.get("source_version") not in _SUPPORTED:
                            continue
                        target_owner = owners.get(str(source.get("source_owner_id") or ""))
                        if not target_owner:
                            raise PermissionError("source owner has no target owner mapping")
                        await _verify_target_owner(connection, tenant_id, target_owner)

                    for source in self._ordered_sources(sources):
                        version = str(source.get("source_version") or "")
                        if version not in _SUPPORTED:
                            continue
                        target_owner = owners[str(source["source_owner_id"])]
                        rows = self._read_source_rows(version, Path(source["snapshot"]["path"]))
                        row_total = _count(rows)
                        await _record_source(
                            connection,
                            batch,
                            source=source,
                            target_owner=target_owner,
                            rows_total=row_total,
                        )
                        if await self._source_already_verified(connection, batch, source, target_owner):
                            deduped_sources += 1
                            await _record_source(
                                connection,
                                batch,
                                source=source,
                                target_owner=target_owner,
                                rows_total=row_total,
                                rows_done=row_total,
                                status="verified",
                            )
                            continue
                        resolver = _SessionResolver(
                            connection,
                            tenant_id=tenant_id,
                            owner_id=target_owner,
                            source_owner_id=str(source["source_owner_id"]),
                        )
                        if version == _CRON_VERSION:
                            counts, skipped = await self._import_cron(
                                connection,
                                batch,
                                tenant_id,
                                target_owner,
                                source,
                                rows,
                                resolver,
                            )
                        elif version == _PARTNER_STATUS_VERSION:
                            counts, skipped = await self._import_partner_status(
                                connection,
                                tenant_id,
                                target_owner,
                                rows,
                            )
                        else:
                            counts, skipped = await self._import_marginnote(
                                connection,
                                batch,
                                tenant_id,
                                target_owner,
                                source,
                                rows,
                            )
                        for key, value in counts.items():
                            imported[key] += value
                        skipped_newer_target += skipped
                        await _record_source(
                            connection,
                            batch,
                            source=source,
                            target_owner=target_owner,
                            rows_total=row_total,
                            rows_done=row_total,
                            status="verified",
                        )
                    await connection.execute(
                        """
                        UPDATE migration_stage.batches
                           SET status='published', updated_at=now()
                         WHERE batch_id=%s
                        """,
                        (batch,),
                    )
        except BaseException as exc:
            await self._mark_failed(batch, exc)
            raise
        return {
            "batch_id": batch,
            "imported": imported,
            "deduped_sources": deduped_sources,
            "skipped_newer_target": skipped_newer_target,
        }

    @staticmethod
    def _ordered_sources(sources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        order = {_CRON_VERSION: 0, _PARTNER_STATUS_VERSION: 1, _MARGINNOTE_VERSION: 2}
        return sorted(sources, key=lambda source: order.get(str(source.get("source_version") or ""), 99))

    @staticmethod
    def _read_source_rows(version: str, snapshot: Path) -> dict[str, list[dict[str, Any]]]:
        if version == _CRON_VERSION:
            return _read_cron_rows(snapshot)
        if version == _PARTNER_STATUS_VERSION:
            return _read_partner_rows(snapshot)
        if version == _MARGINNOTE_VERSION:
            return _read_marginnote_rows(snapshot)
        raise ValueError(f"unsupported runtime source version: {version}")

    async def _mark_failed(self, batch_id: str, exc: BaseException) -> None:
        async with await psycopg.AsyncConnection.connect(self._dsn) as connection:
            await connection.execute(
                """
                UPDATE migration_stage.batches
                   SET status='failed', error=%s, updated_at=now()
                 WHERE batch_id=%s AND status <> 'published'
                """,
                (str(exc)[:4000], batch_id),
            )

    async def _source_already_verified(
        self, connection, batch_id: str, source: dict[str, Any], target_owner: str
    ) -> bool:
        row = await (
            await connection.execute(
                """
                SELECT 1
                  FROM migration_stage.sources
                 WHERE source_version=%s
                   AND source_owner_id=%s
                   AND target_owner_id=%s
                   AND fingerprint=%s
                   AND status='verified'
                   AND NOT (batch_id=%s AND source_id=%s)
                 LIMIT 1
                """,
                (
                    str(source["source_version"]),
                    str(source["source_owner_id"]),
                    target_owner,
                    str(source["snapshot"]["sha256"]),
                    batch_id,
                    str(source["source_id"]),
                ),
            )
        ).fetchone()
        return row is not None

    async def _import_cron(
        self,
        connection,
        batch_id: str,
        tenant_id: str,
        owner_id: str,
        source: dict[str, Any],
        rows: dict[str, list[dict[str, Any]]],
        resolver: _SessionResolver,
    ) -> tuple[dict[str, int], int]:
        counts = {"cron_jobs": 0, "cron_uncertain_executions": 0}
        skipped = 0
        changed = 0
        source_id, source_owner = str(source["source_id"]), str(source["source_owner_id"])
        for row in rows["cron_jobs"]:
            payload, source_state = await self._normalize_cron_payload(
                row, tenant_id=tenant_id, owner_id=owner_id, resolver=resolver
            )
            source_updated = int(row.get("updated_at_ms") or 0)
            existing = await (
                await connection.execute(
                    """
                    SELECT updated_at_ms, revision
                      FROM enterprise.cron_jobs
                     WHERE tenant_id=%s AND owner_id=%s AND job_id=%s
                     FOR UPDATE
                    """,
                    (tenant_id, owner_id, payload["id"]),
                )
            ).fetchone()
            if existing is not None and int(existing["updated_at_ms"]) > source_updated:
                skipped += 1
                continue
            in_flight = self._cron_was_in_flight(source_state)
            execution: dict[str, Any] | None = None
            if in_flight:
                execution = self._mark_cron_uncertain(payload, source_state, row, source_id, source_owner)
            revision = int(existing["revision"]) + 1 if existing is not None else 1
            params = self._cron_insert_params(payload, source_updated=source_updated, revision=revision)
            await connection.execute(
                """
                INSERT INTO enterprise.cron_jobs(
                    tenant_id, owner_id, job_id, owner_key, name, message,
                    schedule_kind, at_ms, every_seconds, cron_expr, tz,
                    enabled, delete_after_run, created_at_ms, next_run_at_ms,
                    last_run_at_ms, last_status, last_error, payload, revision, updated_at_ms
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                ON CONFLICT (tenant_id, owner_id, job_id) DO UPDATE SET
                    owner_key=EXCLUDED.owner_key,
                    name=EXCLUDED.name,
                    message=EXCLUDED.message,
                    schedule_kind=EXCLUDED.schedule_kind,
                    at_ms=EXCLUDED.at_ms,
                    every_seconds=EXCLUDED.every_seconds,
                    cron_expr=EXCLUDED.cron_expr,
                    tz=EXCLUDED.tz,
                    enabled=EXCLUDED.enabled,
                    delete_after_run=EXCLUDED.delete_after_run,
                    created_at_ms=EXCLUDED.created_at_ms,
                    next_run_at_ms=EXCLUDED.next_run_at_ms,
                    last_run_at_ms=EXCLUDED.last_run_at_ms,
                    last_status=EXCLUDED.last_status,
                    last_error=EXCLUDED.last_error,
                    payload=EXCLUDED.payload,
                    revision=EXCLUDED.revision,
                    updated_at_ms=EXCLUDED.updated_at_ms
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
                    revision,
                    source_updated,
                ),
            )
            changed += 1
            counts["cron_jobs"] += 1
            await _record_mapping(
                connection,
                batch_id,
                domain="cron_jobs",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=str(row["id"]),
                target_key=str(payload["id"]),
            )
            if execution is not None:
                await connection.execute(
                    """
                    INSERT INTO enterprise.cron_executions(
                        tenant_id, owner_id, execution_id, job_id, owner_key,
                        scheduled_run_at_ms, job_revision, worker_id, status,
                        claimed_at_ms, completed_at_ms, duration_ms, error, payload
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'uncertain',%s,%s,0,%s,%s)
                    ON CONFLICT (tenant_id, owner_id, job_id, scheduled_run_at_ms, job_revision)
                    DO NOTHING
                    """,
                    (
                        tenant_id,
                        owner_id,
                        execution["execution_id"],
                        params["job_id"],
                        params["owner_key"],
                        execution["scheduled_run_at_ms"],
                        revision,
                        execution["worker_id"],
                        execution["claimed_at_ms"],
                        execution["claimed_at_ms"],
                        params["last_error"],
                        _jsonb(params["payload"]),
                    ),
                )
                counts["cron_uncertain_executions"] += 1
        if changed:
            await connection.execute(
                """
                INSERT INTO enterprise.cron_meta(tenant_id, owner_id, revision, updated_at_ms)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (tenant_id, owner_id) DO UPDATE SET
                    revision=enterprise.cron_meta.revision + EXCLUDED.revision,
                    updated_at_ms=GREATEST(enterprise.cron_meta.updated_at_ms, EXCLUDED.updated_at_ms)
                """,
                (tenant_id, owner_id, changed, max(int(row.get("updated_at_ms") or 0) for row in rows["cron_jobs"])),
            )
        return counts, skipped

    async def _normalize_cron_payload(
        self,
        row: dict[str, Any],
        *,
        tenant_id: str,
        owner_id: str,
        resolver: _SessionResolver,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        raw = _json(row.get("payload"), {})
        if not isinstance(raw, dict):
            raise ValueError("cron payload must be an object")
        source_state = dict(raw.get("state") or {}) if isinstance(raw.get("state"), dict) else {}
        clean = dict(raw)
        clean["state"] = {key: source_state[key] for key in _CRON_STATE_KEYS if key in source_state}
        if clean["state"].get("last_status") not in (*_CRON_TERMINAL_STATUSES, None):
            clean["state"].pop("last_status", None)
        history = []
        for item in clean["state"].get("run_history") or []:
            if isinstance(item, dict) and item.get("status") in _CRON_TERMINAL_STATUSES:
                history.append(item)
        clean["state"]["run_history"] = history
        job = CronJob.from_dict(clean)
        payload = asdict(job)
        owner = payload.setdefault("owner", {})
        owner["tenant_id"] = tenant_id
        if owner.get("kind") == "partner":
            owner.setdefault("user_id", owner_id)
        else:
            owner["kind"] = "chat"
            owner["user_id"] = owner_id
            owner["session_id"] = await resolver.session(owner.get("session_id"), required=False)
        payload["owner"] = owner
        return payload, source_state

    @staticmethod
    def _cron_was_in_flight(source_state: dict[str, Any]) -> bool:
        status = str(source_state.get("last_status") or "").lower()
        if status in {"claimed", "running", "in_progress", "dispatching"}:
            return True
        return any(
            bool(source_state.get(key))
            for key in ("dispatch_started_at_ms", "claimed_at_ms", "in_flight", "running")
        )

    @staticmethod
    def _mark_cron_uncertain(
        payload: dict[str, Any],
        source_state: dict[str, Any],
        row: dict[str, Any],
        source_id: str,
        source_owner: str,
    ) -> dict[str, Any]:
        state = payload.setdefault("state", {})
        scheduled = int(
            source_state.get("next_run_at_ms")
            or row.get("next_run_at_ms")
            or source_state.get("last_run_at_ms")
            or row.get("updated_at_ms")
            or 0
        )
        claimed = int(
            source_state.get("dispatch_started_at_ms")
            or source_state.get("claimed_at_ms")
            or source_state.get("last_run_at_ms")
            or row.get("updated_at_ms")
            or scheduled
        )
        worker_id = str(source_state.get("worker_id") or source_state.get("runtime_worker_id") or "sqlite-import")
        state["next_run_at_ms"] = None
        state["last_run_at_ms"] = claimed
        state["last_status"] = "uncertain"
        state["last_error"] = str(
            source_state.get("last_error")
            or "Imported running SQLite cron job requires manual reconciliation"
        )
        history = list(state.get("run_history") or [])
        history.append(
            asdict(
                CronRunRecord(
                    run_at_ms=claimed,
                    status="uncertain",
                    duration_ms=0,
                    error=state["last_error"],
                )
            )
        )
        state["run_history"] = history[-10:]
        execution_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"deeptutor:cron-import:{source_id}:{source_owner}:{payload['id']}:{scheduled}",
            )
        )
        return {
            "execution_id": execution_id,
            "scheduled_run_at_ms": scheduled,
            "claimed_at_ms": claimed,
            "worker_id": worker_id,
        }

    @staticmethod
    def _cron_insert_params(payload: dict[str, Any], *, source_updated: int, revision: int) -> dict[str, Any]:
        job = CronJob.from_dict(payload)
        state = payload.get("state") or {}
        schedule = job.schedule
        return {
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
            "payload": payload,
            "revision": revision,
            "updated_at_ms": source_updated,
        }

    async def _import_partner_status(
        self,
        connection,
        tenant_id: str,
        owner_id: str,
        rows: dict[str, list[dict[str, Any]]],
    ) -> tuple[dict[str, int], int]:
        counts = {"partner_status": 0}
        skipped = 0
        for row in rows["partner_runtime_status"]:
            partner_id = str(row.get("partner_id") or "").strip()
            if not partner_id:
                raise ValueError("partner_id is required")
            updated_at_ms = int(round(float(row.get("updated_at") or 0) * 1000))
            payload = _json(row.get("payload"), {})
            if not isinstance(payload, dict):
                payload = {}
            payload.pop("channels", None)
            worker_id = str(
                payload.get("runtime_worker_id")
                or payload.get("worker_id")
                or payload.get("runtime_owner_id")
                or "sqlite-import"
            )
            state = str(row.get("state") or "stopped")
            if state not in _ALLOWED_PARTNER_STATES:
                state = "stopped"
            existing = await (
                await connection.execute(
                    """
                    SELECT version, updated_at_ms, expires_at_ms
                      FROM enterprise.partner_runtime_status
                     WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                     FOR UPDATE
                    """,
                    (tenant_id, owner_id, partner_id),
                )
            ).fetchone()
            if existing is not None and int(existing["updated_at_ms"]) > updated_at_ms:
                skipped += 1
                continue
            version = int(existing["version"]) + 1 if existing is not None else 1
            expires_at_ms = updated_at_ms
            payload.update(
                {
                    "tenant_id": tenant_id,
                    "owner_id": owner_id,
                    "partner_id": partner_id,
                    "worker_id": worker_id,
                    "runtime_worker_id": worker_id,
                    "runtime_owner_id": worker_id,
                    "runtime_version": version,
                    "runtime_ttl_seconds": 0.0,
                    "runtime_updated_at": updated_at_ms / 1000.0,
                    "runtime_expires_at": expires_at_ms / 1000.0,
                    "runtime_expired": True,
                    "running": False,
                    "runtime_state": "expired",
                    "started_at": row.get("started_at"),
                    "last_reload_error": row.get("last_reload_error"),
                }
            )
            await connection.execute(
                """
                INSERT INTO enterprise.partner_runtime_status(
                    tenant_id, owner_id, partner_id, worker_id, version,
                    running, state, started_at, last_reload_error, payload,
                    updated_at_ms, expires_at_ms, ttl_ms
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0)
                ON CONFLICT (tenant_id, owner_id, partner_id) DO UPDATE SET
                    worker_id=EXCLUDED.worker_id,
                    version=EXCLUDED.version,
                    running=EXCLUDED.running,
                    state=EXCLUDED.state,
                    started_at=EXCLUDED.started_at,
                    last_reload_error=EXCLUDED.last_reload_error,
                    payload=EXCLUDED.payload,
                    updated_at_ms=EXCLUDED.updated_at_ms,
                    expires_at_ms=EXCLUDED.expires_at_ms,
                    ttl_ms=0
                """,
                (
                    tenant_id,
                    owner_id,
                    partner_id,
                    worker_id,
                    version,
                    bool(row.get("running")),
                    state,
                    row.get("started_at"),
                    row.get("last_reload_error"),
                    _jsonb(payload),
                    updated_at_ms,
                    expires_at_ms,
                ),
            )
            counts["partner_status"] += 1
        return counts, skipped

    async def _import_marginnote(
        self,
        connection,
        batch_id: str,
        tenant_id: str,
        owner_id: str,
        source: dict[str, Any],
        rows: dict[str, list[dict[str, Any]]],
    ) -> tuple[dict[str, int], int]:
        counts = {
            "marginnote_devices": 0,
            "marginnote_cursors": 0,
            "marginnote_objects": 0,
            "marginnote_tombstones": 0,
        }
        skipped = 0
        kb_id = self._source_kb_id(source)
        source_id, source_owner = str(source["source_id"]), str(source["source_owner_id"])
        device_stamps: dict[str, str] = {}
        for row in rows["mn4_devices"]:
            device_id = str(row["device_id"])
            source_stamp = _stamp(row.get("last_seen"), row.get("paired_at"))
            device_stamps[device_id] = source_stamp
            existing = await (
                await connection.execute(
                    """
                    SELECT paired_at,last_seen
                      FROM enterprise.marginnote_devices
                     WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s AND device_id=%s
                     FOR UPDATE
                    """,
                    (tenant_id, owner_id, kb_id, device_id),
                )
            ).fetchone()
            if existing is not None and _stamp(existing["last_seen"], existing["paired_at"]) > source_stamp:
                skipped += 1
                continue
            await connection.execute(
                """
                INSERT INTO enterprise.marginnote_devices(
                    tenant_id, owner_id, kb_id, device_id, device_name,
                    device_kind, token_hash, paired_at, last_seen, active
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, owner_id, kb_id, device_id) DO UPDATE SET
                    device_name=EXCLUDED.device_name,
                    device_kind=EXCLUDED.device_kind,
                    token_hash=EXCLUDED.token_hash,
                    paired_at=EXCLUDED.paired_at,
                    last_seen=EXCLUDED.last_seen,
                    active=EXCLUDED.active
                """,
                (
                    tenant_id,
                    owner_id,
                    kb_id,
                    device_id,
                    str(row.get("device_name") or "")[:128],
                    str(row.get("device_kind") or "macos"),
                    str(row.get("token_hash") or ""),
                    str(row.get("paired_at") or ""),
                    str(row.get("last_seen") or ""),
                    _bool_sqlite(row.get("active")),
                ),
            )
            counts["marginnote_devices"] += 1
            await _record_mapping(
                connection,
                batch_id,
                domain="marginnote_devices",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=device_id,
                target_key=device_id,
                metadata={"kb_id": kb_id},
            )

        for row in rows["mn4_cursors"]:
            device_id = str(row["device_id"])
            source_stamp = device_stamps.get(device_id, "")
            existing = await (
                await connection.execute(
                    """
                    SELECT cursor, updated_at
                      FROM enterprise.marginnote_cursors
                     WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s AND device_id=%s
                     FOR UPDATE
                    """,
                    (tenant_id, owner_id, kb_id, device_id),
                )
            ).fetchone()
            if existing is not None and _stamp(existing["updated_at"]) > source_stamp:
                skipped += 1
                continue
            await connection.execute(
                """
                INSERT INTO enterprise.marginnote_cursors(
                    tenant_id, owner_id, kb_id, device_id, cursor, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, owner_id, kb_id, device_id) DO UPDATE SET
                    cursor=EXCLUDED.cursor,
                    updated_at=EXCLUDED.updated_at
                """,
                (tenant_id, owner_id, kb_id, device_id, str(row.get("cursor") or ""), source_stamp),
            )
            counts["marginnote_cursors"] += 1

        for row in rows["mn4_objects"]:
            object_type = str(row.get("object_type") or "")
            if object_type not in _ALLOWED_MN_TYPES:
                raise ValueError(f"unsupported MarginNote object_type: {object_type!r}")
            device_id = str(row["device_id"])
            object_id = str(row["object_id"])
            source_stamp = _stamp(row.get("synced_at"), row.get("updated_at"), row.get("created_at"))
            tombstone = await (
                await connection.execute(
                    """
                    SELECT deleted_at
                      FROM enterprise.marginnote_tombstones
                     WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                       AND device_id=%s AND object_id=%s
                    """,
                    (tenant_id, owner_id, kb_id, device_id, object_id),
                )
            ).fetchone()
            if tombstone is not None and str(tombstone["deleted_at"] or "") >= source_stamp:
                skipped += 1
                continue
            existing = await (
                await connection.execute(
                    """
                    SELECT updated_at,synced_at
                      FROM enterprise.marginnote_objects
                     WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                       AND device_id=%s AND object_id=%s
                     FOR UPDATE
                    """,
                    (tenant_id, owner_id, kb_id, device_id, object_id),
                )
            ).fetchone()
            if existing is not None and _stamp(existing["synced_at"], existing["updated_at"]) > source_stamp:
                skipped += 1
                continue
            await connection.execute(
                """
                INSERT INTO enterprise.marginnote_objects(
                    tenant_id, owner_id, kb_id, device_id, object_id,
                    object_type, title, content, excerpt, document_id,
                    document_title, page, tags, links, color,
                    created_at, updated_at, synced_at, raw
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, owner_id, kb_id, device_id, object_id)
                DO UPDATE SET
                    object_type=EXCLUDED.object_type,
                    title=EXCLUDED.title,
                    content=EXCLUDED.content,
                    excerpt=EXCLUDED.excerpt,
                    document_id=EXCLUDED.document_id,
                    document_title=EXCLUDED.document_title,
                    page=EXCLUDED.page,
                    tags=EXCLUDED.tags,
                    links=EXCLUDED.links,
                    color=EXCLUDED.color,
                    created_at=EXCLUDED.created_at,
                    updated_at=EXCLUDED.updated_at,
                    synced_at=EXCLUDED.synced_at,
                    raw=EXCLUDED.raw
                """,
                (
                    tenant_id,
                    owner_id,
                    kb_id,
                    device_id,
                    object_id,
                    object_type,
                    str(row.get("title") or ""),
                    str(row.get("content") or ""),
                    row.get("excerpt"),
                    row.get("document_id"),
                    row.get("document_title"),
                    _int_or_none(row.get("page")),
                    _jsonb(self._json_array(row.get("tags"), "tags")),
                    _jsonb(self._json_array(row.get("links"), "links")),
                    row.get("color"),
                    str(row.get("created_at") or ""),
                    str(row.get("updated_at") or ""),
                    str(row.get("synced_at") or source_stamp),
                    _jsonb(self._json_object(row.get("raw"), "raw")),
                ),
            )
            counts["marginnote_objects"] += 1
            await _record_mapping(
                connection,
                batch_id,
                domain="marginnote_objects",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=f"{device_id}:{object_id}",
                target_key=f"{device_id}:{object_id}",
                metadata={"kb_id": kb_id},
            )

        for row in rows["mn4_tombstones"]:
            device_id = str(row["device_id"])
            object_id = str(row["object_id"])
            deleted_at = str(row.get("deleted_at") or "")
            existing_object = await (
                await connection.execute(
                    """
                    SELECT updated_at,synced_at
                      FROM enterprise.marginnote_objects
                     WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                       AND device_id=%s AND object_id=%s
                     FOR UPDATE
                    """,
                    (tenant_id, owner_id, kb_id, device_id, object_id),
                )
            ).fetchone()
            if existing_object is not None and _stamp(
                existing_object["synced_at"], existing_object["updated_at"]
            ) > deleted_at:
                skipped += 1
                continue
            existing_tombstone = await (
                await connection.execute(
                    """
                    SELECT deleted_at
                      FROM enterprise.marginnote_tombstones
                     WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                       AND device_id=%s AND object_id=%s
                     FOR UPDATE
                    """,
                    (tenant_id, owner_id, kb_id, device_id, object_id),
                )
            ).fetchone()
            if existing_tombstone is not None and str(existing_tombstone["deleted_at"] or "") > deleted_at:
                skipped += 1
                continue
            await connection.execute(
                """
                INSERT INTO enterprise.marginnote_tombstones(
                    tenant_id, owner_id, kb_id, device_id, object_id, deleted_at
                ) VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, owner_id, kb_id, device_id, object_id)
                DO UPDATE SET deleted_at=EXCLUDED.deleted_at
                """,
                (tenant_id, owner_id, kb_id, device_id, object_id, deleted_at),
            )
            await connection.execute(
                """
                DELETE FROM enterprise.marginnote_objects
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                   AND device_id=%s AND object_id=%s
                """,
                (tenant_id, owner_id, kb_id, device_id, object_id),
            )
            counts["marginnote_tombstones"] += 1
        return counts, skipped

    @staticmethod
    def _source_kb_id(source: dict[str, Any]) -> str:
        for container_key in ("resource_mappings", "target", "target_resources"):
            container = source.get(container_key)
            if isinstance(container, dict) and str(container.get("kb_id") or "").strip():
                return str(container["kb_id"]).strip()
        raise ValueError("marginnote source requires resource_mappings.kb_id")

    @staticmethod
    def _json_array(value: Any, label: str) -> list[Any]:
        parsed = _json(value, [])
        if not isinstance(parsed, list):
            raise ValueError(f"MarginNote {label} must be a JSON array")
        return parsed

    @staticmethod
    def _json_object(value: Any, label: str) -> dict[str, Any]:
        parsed = _json(value, {})
        if not isinstance(parsed, dict):
            raise ValueError(f"MarginNote {label} must be a JSON object")
        return parsed


__all__ = ["SQLiteRuntimeProjectionImporter"]
