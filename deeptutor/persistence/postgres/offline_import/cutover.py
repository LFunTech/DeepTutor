"""离线导入后的受控 cutover 与 rollback 检查。"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Literal

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


@dataclass(slots=True)
class CutoverReleaseRequest:
    """开放 PG-only 目标前由操作者确认的外部状态。"""

    stopped_writers: set[str]
    identity_generations: dict[str, int]
    device_generations: dict[str, int] = field(default_factory=dict)
    reconciled_external_actions: set[str] = field(default_factory=set)


@dataclass(slots=True)
class RollbackCheckRequest:
    """回退/恢复决策所需的受控确认。"""

    target: Literal[
        "legacy_sqlite",
        "legacy_pocketbase",
        "schema1_legacy_build",
        "compatible_pg_build",
        "restore_pg_backup",
    ]
    source_backends_unchanged: bool
    identity_generations: dict[str, int]
    device_generations: dict[str, int] = field(default_factory=dict)
    reconciled_external_actions: set[str] = field(default_factory=set)
    compatible_pg_build: bool = False
    restored_pg_backup: bool = False
    identity_reconciled_after_restore: bool = False


@dataclass(slots=True)
class CutoverCheckReport:
    ok: bool
    batch_id: str
    issues: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "batch_id": self.batch_id,
            "issues": self.issues,
            "details": self.details,
        }


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _issue(
    issues: list[dict[str, Any]],
    code: str,
    message: str,
    *,
    detail: dict[str, Any] | None = None,
) -> None:
    item: dict[str, Any] = {"code": code, "message": message}
    if detail:
        item["detail"] = detail
    issues.append(item)


class OfflineCutoverCoordinator:
    """在维护态内开放 PG-only 目标，并检查允许的回退路线。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def prepare_release(
        self, batch_id: str, request: CutoverReleaseRequest
    ) -> CutoverCheckReport:
        batch_id = str(batch_id)
        issues: list[dict[str, Any]] = []
        details: dict[str, Any] = {}
        async with await psycopg.AsyncConnection.connect(
            self._dsn, row_factory=dict_row
        ) as connection:
            batch = await self._batch(connection, batch_id)
            if batch is None:
                return CutoverCheckReport(
                    ok=False,
                    batch_id=batch_id,
                    issues=[{"code": "batch_missing", "message": "migration batch not found"}],
                )
            tenant_id = str(batch["target_tenant_id"])
            details["tenant_id"] = tenant_id
            if batch["status"] != "published":
                _issue(
                    issues,
                    "batch_not_published",
                    "cutover requires a published migration batch",
                    detail={"status": batch["status"]},
                )
            verify_report = batch.get("verify_report") if isinstance(batch.get("verify_report"), dict) else {}
            if not verify_report or verify_report.get("ok") is not True:
                _issue(
                    issues,
                    "verify_report_not_ok",
                    "cutover requires a successful verify/report result",
                )
            lock = await self._maintenance_lock(connection, tenant_id)
            if not lock or not lock["active"] or str(lock["batch_id"]) != batch_id:
                _issue(
                    issues,
                    "maintenance_not_active",
                    "target tenant must remain in maintenance for this batch before release",
                    detail={"lock": dict(lock) if lock else None},
                )
            required_writers = await self._required_writers(connection, batch_id, batch)
            missing = sorted(required_writers - {str(item) for item in request.stopped_writers})
            details["required_stopped_writers"] = sorted(required_writers)
            if missing:
                _issue(
                    issues,
                    "writer_not_stopped",
                    "not all source writers were confirmed stopped",
                    detail={"missing": missing},
                )
            target_owners = await self._target_owners(connection, batch_id)
            await self._check_identity_generations(
                connection,
                tenant_id,
                target_owners,
                request.identity_generations,
                issues,
            )
            await self._check_device_generations(
                connection,
                tenant_id,
                request.device_generations,
                issues,
            )
            await self._check_unresolved_external_actions(
                connection,
                tenant_id,
                target_owners,
                request.reconciled_external_actions,
                issues,
            )
        return CutoverCheckReport(ok=not issues, batch_id=batch_id, issues=issues, details=details)

    async def release(
        self, batch_id: str, request: CutoverReleaseRequest) -> CutoverCheckReport:
        batch_id = str(batch_id)
        prepared = await self.prepare_release(batch_id, request)
        if not prepared.ok:
            return prepared
        async with await psycopg.AsyncConnection.connect(
            self._dsn, row_factory=dict_row
        ) as connection:
            async with connection.transaction():
                batch = await self._batch(connection, batch_id, lock=True)
                if batch is None:
                    return CutoverCheckReport(
                        ok=False,
                        batch_id=batch_id,
                        issues=[{"code": "batch_missing", "message": "migration batch not found"}],
                    )
                tenant_id = str(batch["target_tenant_id"])
                baseline = await self._tenant_business_digest(connection, tenant_id)
                verify_report = (
                    dict(batch["verify_report"])
                    if isinstance(batch.get("verify_report"), dict)
                    else {}
                )
                opened_at = await (
                    await connection.execute("SELECT now()::text AS opened_at")
                ).fetchone()
                verify_report["cutover"] = {
                    "opened": True,
                    "opened_at": opened_at["opened_at"],
                    "stopped_writers": sorted(request.stopped_writers),
                    "identity_generations": dict(sorted(request.identity_generations.items())),
                    "device_generations": dict(sorted(request.device_generations.items())),
                    "target_baseline_digest": baseline["digest"],
                    "target_baseline_tables": baseline["tables"],
                }
                await connection.execute(
                    """
                    UPDATE migration_stage.batches
                       SET verify_report=%s::jsonb, updated_at=now()
                     WHERE batch_id=%s
                    """,
                    (Jsonb(verify_report), batch_id),
                )
                await connection.execute(
                    """
                    UPDATE enterprise.maintenance_locks
                       SET active=false, released_at=now(), updated_at=now()
                     WHERE tenant_id=%s AND batch_id=%s
                    """,
                    (tenant_id, batch_id),
                )
        prepared.details["released"] = True
        return prepared

    async def check_rollback(
        self, batch_id: str, request: RollbackCheckRequest
    ) -> CutoverCheckReport:
        batch_id = str(batch_id)
        issues: list[dict[str, Any]] = []
        details: dict[str, Any] = {"target": request.target}
        async with await psycopg.AsyncConnection.connect(
            self._dsn, row_factory=dict_row
        ) as connection:
            batch = await self._batch(connection, batch_id)
            if batch is None:
                return CutoverCheckReport(
                    ok=False,
                    batch_id=batch_id,
                    issues=[{"code": "batch_missing", "message": "migration batch not found"}],
                    details=details,
                )
            tenant_id = str(batch["target_tenant_id"])
            target_owners = await self._target_owners(connection, batch_id)
            verify_report = batch.get("verify_report") if isinstance(batch.get("verify_report"), dict) else {}
            cutover = verify_report.get("cutover") if isinstance(verify_report.get("cutover"), dict) else {}
            if cutover.get("opened") is not True:
                _issue(
                    issues,
                    "cutover_not_opened",
                    "rollback checks require a recorded cutover release",
                )
            await self._check_identity_generations(
                connection,
                tenant_id,
                target_owners,
                request.identity_generations,
                issues,
            )
            await self._check_device_generations(
                connection,
                tenant_id,
                request.device_generations,
                issues,
            )
            await self._check_unresolved_external_actions(
                connection,
                tenant_id,
                target_owners,
                request.reconciled_external_actions,
                issues,
            )
            if request.target in {"legacy_sqlite", "legacy_pocketbase"}:
                if not request.source_backends_unchanged:
                    _issue(
                        issues,
                        "source_backend_changed",
                        "legacy source changed after cutover and cannot be used for rollback",
                    )
                current = await self._tenant_business_digest(connection, tenant_id)
                baseline_digest = str(cutover.get("target_baseline_digest") or "")
                details["current_target_digest"] = current["digest"]
                details["baseline_target_digest"] = baseline_digest
                if baseline_digest and current["digest"] != baseline_digest:
                    _issue(
                        issues,
                        "pg_new_writes_block_legacy_rollback",
                        "target PostgreSQL changed after cutover; legacy SQLite/PocketBase rollback would lose data",
                    )
            elif request.target == "schema1_legacy_build":
                _issue(
                    issues,
                    "schema1_legacy_build_incompatible",
                    "old schema-1 build must not run against the upgraded PostgreSQL schema",
                )
            elif request.target == "compatible_pg_build" and not request.compatible_pg_build:
                _issue(
                    issues,
                    "compatible_pg_build_not_verified",
                    "compatible PostgreSQL rollback build was not explicitly verified",
                )
            elif request.target == "restore_pg_backup":
                if not request.restored_pg_backup:
                    _issue(
                        issues,
                        "pg_backup_restore_not_confirmed",
                        "PG backup restore was not confirmed",
                    )
                if not request.identity_reconciled_after_restore:
                    _issue(
                        issues,
                        "identity_restore_not_reconciled",
                        "identity/device generations must be reconciled after restoring an old PG backup",
                    )
        return CutoverCheckReport(ok=not issues, batch_id=batch_id, issues=issues, details=details)

    @staticmethod
    async def _batch(connection, batch_id: str, *, lock: bool = False):
        suffix = " FOR UPDATE" if lock else ""
        return await (
            await connection.execute(
                """
                SELECT batch_id,target_tenant_id,status,verify_report,source_manifest
                  FROM migration_stage.batches
                 WHERE batch_id=%s
                """
                + suffix,
                (batch_id,),
            )
        ).fetchone()

    @staticmethod
    async def _maintenance_lock(connection, tenant_id: str):
        return await (
            await connection.execute(
                """
                SELECT tenant_id,batch_id,active,generation,reason
                  FROM enterprise.maintenance_locks
                 WHERE tenant_id=%s
                """,
                (tenant_id,),
            )
        ).fetchone()

    @staticmethod
    async def _required_writers(connection, batch_id: str, batch: dict[str, Any]) -> set[str]:
        batch_manifest = (
            batch.get("source_manifest") if isinstance(batch.get("source_manifest"), dict) else {}
        )
        freeze = (
            batch_manifest.get("freeze")
            if isinstance(batch_manifest.get("freeze"), dict)
            else {}
        )
        writers = {
            str(item)
            for item in (freeze.get("stopped_writers") or [])
            if str(item).strip()
        }
        rows = await (
            await connection.execute(
                "SELECT manifest FROM migration_stage.sources WHERE batch_id=%s",
                (batch_id,),
            )
        ).fetchall()
        for row in rows:
            manifest = row["manifest"] if isinstance(row["manifest"], dict) else {}
            freeze = manifest.get("freeze") if isinstance(manifest.get("freeze"), dict) else {}
            raw = freeze.get("stopped_writers") or manifest.get("stopped_writers") or []
            writers.update(str(item) for item in raw if str(item).strip())
        return writers

    @staticmethod
    async def _target_owners(connection, batch_id: str) -> set[str]:
        rows = await (
            await connection.execute(
                """
                SELECT DISTINCT target_owner_id
                  FROM migration_stage.sources
                 WHERE batch_id=%s
                """,
                (batch_id,),
            )
        ).fetchall()
        return {str(row["target_owner_id"]) for row in rows}

    @staticmethod
    async def _check_identity_generations(
        connection,
        tenant_id: str,
        required_owners: set[str],
        expected: dict[str, int],
        issues: list[dict[str, Any]],
    ) -> None:
        for owner_id in sorted(required_owners):
            if owner_id not in expected:
                _issue(
                    issues,
                    "identity_generation_missing",
                    "target owner auth_version confirmation is missing",
                    detail={"user_id": owner_id},
                )
                continue
            row = await (
                await connection.execute(
                    """
                    SELECT auth_version,disabled,deleted_at
                      FROM enterprise.users
                     WHERE tenant_id=%s AND id=%s
                    """,
                    (tenant_id, owner_id),
                )
            ).fetchone()
            if row is None:
                _issue(
                    issues,
                    "identity_missing",
                    "target owner identity is missing",
                    detail={"user_id": owner_id},
                )
                continue
            if int(row["auth_version"]) != int(expected[owner_id]) or row["disabled"] or row["deleted_at"]:
                _issue(
                    issues,
                    "identity_generation_mismatch",
                    "target owner identity generation changed or was disabled",
                    detail={
                        "user_id": owner_id,
                        "expected": expected[owner_id],
                        "actual": int(row["auth_version"]),
                        "disabled": bool(row["disabled"]),
                    },
                )

    @staticmethod
    async def _check_device_generations(
        connection,
        tenant_id: str,
        expected: dict[str, int],
        issues: list[dict[str, Any]],
    ) -> None:
        for credential_id, generation in sorted(expected.items()):
            row = await (
                await connection.execute(
                    """
                    SELECT generation,revoked_at
                      FROM enterprise.device_credentials
                     WHERE tenant_id=%s AND id=%s
                    """,
                    (tenant_id, credential_id),
                )
            ).fetchone()
            if row is None:
                _issue(
                    issues,
                    "device_generation_missing",
                    "device credential confirmation points to a missing credential",
                    detail={"device_credential_id": credential_id},
                )
                continue
            if int(row["generation"]) != int(generation) or row["revoked_at"] is not None:
                _issue(
                    issues,
                    "device_generation_mismatch",
                    "device credential generation changed or was revoked",
                    detail={
                        "device_credential_id": credential_id,
                        "expected": generation,
                        "actual": int(row["generation"]),
                        "revoked": row["revoked_at"] is not None,
                    },
                )

    @staticmethod
    async def _check_unresolved_external_actions(
        connection,
        tenant_id: str,
        owners: set[str],
        reconciled: set[str],
        issues: list[dict[str, Any]],
    ) -> None:
        if "*" in reconciled or not owners:
            return
        rows = await (
            await connection.execute(
                """
                SELECT execution_id,job_id,owner_id
                  FROM enterprise.cron_executions
                 WHERE tenant_id=%s AND owner_id = ANY(%s) AND status='uncertain'
                 ORDER BY owner_id,job_id,execution_id
                """,
                (tenant_id, sorted(owners)),
            )
        ).fetchall()
        unresolved = [
            {
                "execution_id": str(row["execution_id"]),
                "job_id": row["job_id"],
                "owner_id": row["owner_id"],
            }
            for row in rows
            if str(row["execution_id"]) not in reconciled
        ]
        if unresolved:
            _issue(
                issues,
                "external_action_unresolved",
                "uncertain external cron executions must be reconciled before cutover/rollback",
                detail={"executions": unresolved},
            )

    async def _tenant_business_digest(self, connection, tenant_id: str) -> dict[str, Any]:
        table_rows = await (
            await connection.execute(
                """
                SELECT DISTINCT table_name
                  FROM information_schema.columns
                 WHERE table_schema='enterprise' AND column_name='tenant_id'
                 ORDER BY table_name
                """
            )
        ).fetchall()
        excluded = {"maintenance_locks"}
        tables: dict[str, dict[str, Any]] = {}
        for row in table_rows:
            table = str(row["table_name"])
            if table in excluded:
                continue
            result = await (
                await connection.execute(
                    sql.SQL(
                        """
                        SELECT count(*)::bigint AS rows,
                               COALESCE(
                                 md5(string_agg(row_hash, '' ORDER BY row_hash)),
                                 ''
                               ) AS digest
                          FROM (
                            SELECT md5(row_to_json(t)::text) AS row_hash
                              FROM (SELECT * FROM enterprise.{table} WHERE tenant_id=%s) t
                          ) hashed
                        """
                    ).format(table=sql.Identifier(table)),
                    (tenant_id,),
                )
            ).fetchone()
            tables[table] = {"rows": int(result["rows"]), "digest": result["digest"]}
        return {"digest": _digest(tables), "tables": tables}


__all__ = [
    "CutoverCheckReport",
    "CutoverReleaseRequest",
    "OfflineCutoverCoordinator",
    "RollbackCheckRequest",
]
