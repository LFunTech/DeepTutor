"""SQLite mastery/reading 快照导入到 PG 学习与阅读域。"""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.request import pathname2url

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from deeptutor.learning.models import LearningProgress

from .id_mapping import advance_identity_sequence, stable_text_id
from .planner import source_check_manifest
from .stage import MigrationStageRepository

_MASTERY_VERSIONS = {"mastery_sqlite/v1", "mastery_sqlite/v2"}
_READING_VERSION = "reading_catalog_sqlite/v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _sqlite_uri(path: Path) -> str:
    return f"file:{pathname2url(str(path))}?mode=ro&immutable=1"


def _manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


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


def _read_mastery_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    return _read_rows(
        snapshot,
        {
            "mastery_paths": "ORDER BY created_at, path_id",
            "mastery_path_sessions": "ORDER BY last_seen_at, path_id, session_id",
            "mastery_interactions": "ORDER BY created_at, interaction_id",
            "mastery_events": "ORDER BY revision, id",
            "mastery_topic_meta": "ORDER BY path_id",
            "mastery_topic_sources": "ORDER BY path_id, position, created_at, source_id",
        },
    )


def _read_reading_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    return _read_rows(
        snapshot,
        {
            "reading_materials": "ORDER BY created_at, material_id",
            "reading_workspaces": "ORDER BY created_at, workspace_id",
            "reading_workspace_materials": "ORDER BY workspace_id, tab_order, material_id",
            "reading_workspace_sessions": "ORDER BY workspace_id, updated_at, session_id",
            "reading_session_links": "ORDER BY workspace_id, created_at, source_session_id, target_session_id",
        },
    )


def _default_map_seed(path_id: str) -> int:
    return int.from_bytes(hashlib.sha256(path_id.encode("utf-8")).digest()[:4], "big")


def _count(rows: dict[str, list[dict[str, Any]]]) -> int:
    return sum(len(value) for value in rows.values())


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
    target_int: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await connection.execute(
        """
        INSERT INTO migration_stage.id_mappings(
            batch_id, domain, source_id, source_owner_id, source_key,
            target_key, target_int, metadata
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (batch_id, domain, source_id, source_owner_id, source_key)
        DO UPDATE SET target_key=EXCLUDED.target_key,
                      target_int=EXCLUDED.target_int,
                      metadata=EXCLUDED.metadata
        """,
        (
            batch_id,
            domain,
            source_id,
            source_owner_id,
            source_key,
            target_key,
            target_int,
            Jsonb(metadata or {}),
        ),
    )


class _MappingResolver:
    def __init__(self, connection, *, tenant_id: str, owner_id: str, source_owner_id: str) -> None:
        self.connection = connection
        self.tenant_id = tenant_id
        self.owner_id = owner_id
        self.source_owner_id = source_owner_id

    async def session(self, source_key: Any, *, required: bool = True) -> str:
        return await self._text(
            "sessions",
            source_key,
            table="enterprise.sessions",
            key_column="id",
            label="sessions",
            required=required,
        )

    async def turn(self, source_key: Any, *, required: bool = True) -> str:
        return await self._text(
            "turns",
            source_key,
            table="enterprise.turns",
            key_column="id",
            label="turns",
            required=required,
        )

    async def notebook_entry(self, source_key: Any, *, required: bool = True) -> int | None:
        return await self._integer(
            "notebook_entries",
            source_key,
            table="enterprise.notebook_entries",
            key_column="id",
            label="notebook_entries",
            required=required,
        )

    async def _text(
        self,
        domain: str,
        source_key: Any,
        *,
        table: str,
        key_column: str,
        label: str,
        required: bool,
    ) -> str:
        value = str(source_key or "")
        if not value:
            if required:
                raise ValueError(f"missing mapping for {label}: empty source key")
            return ""
        candidates = await self._mapped_values(domain, value, int_target=False)
        if not candidates:
            exists = await self._target_exists(table, key_column, value)
            if exists:
                return value
        elif len(candidates) == 1:
            target = str(next(iter(candidates)))
            if await self._target_exists(table, key_column, target):
                return target
            raise ValueError(f"mapped {label} target does not exist: {target!r}")
        else:
            raise ValueError(f"ambiguous mapping for {label}: {value!r}")
        if required:
            raise ValueError(f"missing mapping for {label}: {value!r}")
        return ""

    async def _integer(
        self,
        domain: str,
        source_key: Any,
        *,
        table: str,
        key_column: str,
        label: str,
        required: bool,
    ) -> int | None:
        value = str(source_key or "")
        if not value:
            if required:
                raise ValueError(f"missing mapping for {label}: empty source key")
            return None
        candidates = await self._mapped_values(domain, value, int_target=True)
        if not candidates and value.isdecimal():
            candidate = int(value)
            if await self._target_exists(table, key_column, candidate):
                return candidate
        elif len(candidates) == 1:
            target = int(next(iter(candidates)))
            if await self._target_exists(table, key_column, target):
                return target
            raise ValueError(f"mapped {label} target does not exist: {target!r}")
        elif len(candidates) > 1:
            raise ValueError(f"ambiguous mapping for {label}: {value!r}")
        if required:
            raise ValueError(f"missing mapping for {label}: {value!r}")
        return None

    async def _mapped_values(
        self, domain: str, source_key: str, *, int_target: bool
    ) -> set[str | int]:
        column = "target_int" if int_target else "target_key"
        rows = await (
            await self.connection.execute(
                f"""
                SELECT DISTINCT m.{column} AS target
                  FROM migration_stage.id_mappings m
                  JOIN migration_stage.sources s
                    ON s.batch_id=m.batch_id AND s.source_id=m.source_id
                 WHERE m.domain=%s
                   AND m.source_owner_id=%s
                   AND m.source_key=%s
                   AND s.target_owner_id=%s
                   AND s.status='verified'
                   AND m.{column} IS NOT NULL
                """,  # nosec B608 - column 来自封闭常量
                (domain, self.source_owner_id, source_key, self.owner_id),
            )
        ).fetchall()
        return {row["target"] for row in rows}

    async def _target_exists(self, table: str, key_column: str, value: str | int) -> bool:
        row = await (
            await self.connection.execute(
                f"""
                SELECT 1 FROM {table}
                 WHERE tenant_id=%s AND owner_id=%s AND {key_column}=%s
                 LIMIT 1
                """,  # nosec B608 - table/column 来自封闭常量
                (self.tenant_id, self.owner_id, value),
            )
        ).fetchone()
        return row is not None


class SQLiteLearningReadingImporter:
    """导入 `mastery_sqlite/v1|v2` 和 `reading_catalog_sqlite/v1` 源。"""

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
        await repo.enter_maintenance(batch_id, tenant_id=tenant_id, reason="sqlite-learning-reading-import")
        imported = {
            "mastery_paths": 0,
            "mastery_interactions": 0,
            "mastery_events": 0,
            "reading_materials": 0,
            "reading_workspaces": 0,
            "reading_sessions": 0,
            "reading_links": 0,
        }
        deduped_sources = 0
        try:
            async with await psycopg.AsyncConnection.connect(
                self._dsn, row_factory=dict_row
            ) as connection:
                async with connection.transaction():
                    sources = [source for source in manifest.get("sources") or []]
                    for source in sources:
                        target_owner = owners.get(str(source.get("source_owner_id") or ""))
                        if not target_owner:
                            raise PermissionError("source owner has no target owner mapping")
                        await _verify_target_owner(connection, tenant_id, target_owner)

                    # 阅读材料先落地，后续 mastery topic source 可引用/重写这些资源。
                    for source in self._ordered_sources(sources):
                        target_owner = owners[str(source["source_owner_id"])]
                        version = str(source["source_version"])
                        if version not in {*_MASTERY_VERSIONS, _READING_VERSION}:
                            continue
                        snapshot = Path(source["snapshot"]["path"])
                        rows = (
                            _read_reading_rows(snapshot)
                            if version == _READING_VERSION
                            else _read_mastery_rows(snapshot)
                        )
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
                        resolver = _MappingResolver(
                            connection,
                            tenant_id=tenant_id,
                            owner_id=target_owner,
                            source_owner_id=str(source["source_owner_id"]),
                        )
                        if version == _READING_VERSION:
                            counts = await self._import_reading(
                                connection,
                                batch,
                                tenant_id,
                                target_owner,
                                source,
                                rows,
                                resolver,
                            )
                        else:
                            counts = await self._import_mastery(
                                connection,
                                batch,
                                tenant_id,
                                target_owner,
                                source,
                                rows,
                                resolver,
                                version=version,
                            )
                        for key, value in counts.items():
                            imported[key] += value
                        await _record_source(
                            connection,
                            batch,
                            source=source,
                            target_owner=target_owner,
                            rows_total=row_total,
                            rows_done=row_total,
                            status="verified",
                        )
                    await advance_identity_sequence(connection, "enterprise.mastery_events", "id")
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
        return {"batch_id": batch, "imported": imported, "deduped_sources": deduped_sources}

    @staticmethod
    def _ordered_sources(sources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            sources,
            key=lambda source: 0
            if source.get("source_version") == _READING_VERSION
            else 1
            if source.get("source_version") in _MASTERY_VERSIONS
            else 2,
        )

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

    async def _import_reading(
        self,
        connection,
        batch_id: str,
        tenant_id: str,
        owner_id: str,
        source: dict[str, Any],
        rows: dict[str, list[dict[str, Any]]],
        resolver: _MappingResolver,
    ) -> dict[str, int]:
        material_map: dict[str, str] = {}
        source_id, source_owner = str(source["source_id"]), str(source["source_owner_id"])
        inserted_materials = 0
        for row in rows["reading_materials"]:
            old_id = str(row["material_id"])
            target_id = old_id
            if not _SAFE_ID.fullmatch(target_id):
                target_id = stable_text_id(
                    domain="reading_materials",
                    source_id=source_id,
                    source_owner_id=source_owner,
                    source_key=old_id,
                    prefix="mat",
                )[:128]
            existing = await self._reading_material(connection, tenant_id, owner_id, target_id)
            if existing is not None:
                if not self._same_material(existing, row):
                    raise ValueError(f"conflicting reading material: {old_id!r}")
            else:
                await connection.execute(
                    """
                    INSERT INTO enterprise.reading_materials(
                        tenant_id, owner_id, material_id, content_id, filename, title,
                        source_kind, source_url, mime, render_mode, cover_url,
                        duration_seconds, status, progress, error_code, error_detail,
                        last_opened_at, version, created_at, updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s)
                    """,
                    (
                        tenant_id,
                        owner_id,
                        target_id,
                        row["content_id"],
                        row["filename"],
                        row["title"],
                        row["source_kind"],
                        row.get("source_url") or "",
                        row.get("mime") or "",
                        row.get("render_mode") or "text",
                        row.get("cover_url") or "",
                        float(row.get("duration_seconds") or 0),
                        row.get("status") or "queued",
                        int(row.get("progress") or 0),
                        row.get("error_code") or "",
                        row.get("error_detail") or "",
                        float(row.get("last_opened_at") or 0),
                        float(row["created_at"]),
                        float(row["updated_at"]),
                    ),
                )
                inserted_materials += 1
            material_map[old_id] = target_id
            await _record_mapping(
                connection,
                batch_id,
                domain="reading_materials",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=old_id,
                target_key=target_id,
            )

        workspace_map: dict[str, str] = {}
        inserted_workspaces = 0
        for row in rows["reading_workspaces"]:
            old_id = str(row["workspace_id"])
            target_id = old_id
            active = self._mapped_optional(material_map, row.get("active_material_id"), "reading material")
            existing = await (
                await connection.execute(
                    """
                    SELECT title,description,active_material_id
                      FROM enterprise.reading_workspaces
                     WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s
                    """,
                    (tenant_id, owner_id, target_id),
                )
            ).fetchone()
            if existing is not None:
                if (
                    existing["title"] != row["title"]
                    or existing["description"] != (row.get("description") or "")
                    or existing["active_material_id"] != active
                ):
                    raise ValueError(f"conflicting reading workspace: {old_id!r}")
            else:
                await connection.execute(
                    """
                    INSERT INTO enterprise.reading_workspaces(
                        tenant_id, owner_id, workspace_id, title, description,
                        active_material_id, version, created_at, updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,1,%s,%s)
                    """,
                    (
                        tenant_id,
                        owner_id,
                        target_id,
                        row["title"],
                        row.get("description") or "",
                        active,
                        float(row["created_at"]),
                        float(row["updated_at"]),
                    ),
                )
                inserted_workspaces += 1
            workspace_map[old_id] = target_id
            await _record_mapping(
                connection,
                batch_id,
                domain="reading_workspaces",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=old_id,
                target_key=target_id,
            )

        for row in rows["reading_workspace_materials"]:
            await connection.execute(
                """
                INSERT INTO enterprise.reading_workspace_materials(
                    tenant_id, owner_id, workspace_id, material_id, tab_order,
                    pinned, opened, added_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,owner_id,workspace_id,material_id) DO NOTHING
                """,
                (
                    tenant_id,
                    owner_id,
                    workspace_map[str(row["workspace_id"])],
                    material_map[str(row["material_id"])],
                    int(row["tab_order"]),
                    bool(row.get("pinned") or 0),
                    bool(row.get("opened") or 0),
                    float(row["added_at"]),
                ),
            )

        inserted_sessions = 0
        for row in rows["reading_workspace_sessions"]:
            target_session = await resolver.session(row["session_id"])
            active = self._mapped_optional(material_map, row.get("active_material_id"), "reading material")
            result = await connection.execute(
                """
                INSERT INTO enterprise.reading_workspace_sessions(
                    tenant_id, owner_id, workspace_id, session_id, title,
                    active_material_id, version, created_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,1,%s,%s)
                ON CONFLICT (tenant_id,owner_id,session_id) DO NOTHING
                """,
                (
                    tenant_id,
                    owner_id,
                    workspace_map[str(row["workspace_id"])],
                    target_session,
                    row.get("title") or "New reading conversation",
                    active,
                    float(row["created_at"]),
                    float(row["updated_at"]),
                ),
            )
            inserted_sessions += int(result.rowcount or 0)

        inserted_links = 0
        for row in rows["reading_session_links"]:
            result = await connection.execute(
                """
                INSERT INTO enterprise.reading_session_links(
                    tenant_id, owner_id, workspace_id, source_session_id,
                    target_session_id, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,owner_id,workspace_id,source_session_id,target_session_id)
                DO NOTHING
                """,
                (
                    tenant_id,
                    owner_id,
                    workspace_map[str(row["workspace_id"])],
                    await resolver.session(row["source_session_id"]),
                    await resolver.session(row["target_session_id"]),
                    float(row["created_at"]),
                ),
            )
            inserted_links += int(result.rowcount or 0)
        return {
            "reading_materials": inserted_materials,
            "reading_workspaces": inserted_workspaces,
            "reading_sessions": inserted_sessions,
            "reading_links": inserted_links,
        }

    @staticmethod
    def _mapped_optional(mapping: dict[str, str], value: Any, label: str) -> str | None:
        key = str(value or "")
        if not key:
            return None
        if key not in mapping:
            raise ValueError(f"missing mapping for {label}: {key!r}")
        return mapping[key]

    async def _reading_material(self, connection, tenant_id: str, owner_id: str, material_id: str):
        return await (
            await connection.execute(
                """
                SELECT *
                  FROM enterprise.reading_materials
                 WHERE tenant_id=%s AND owner_id=%s AND material_id=%s
                """,
                (tenant_id, owner_id, material_id),
            )
        ).fetchone()

    @staticmethod
    def _same_material(existing: dict[str, Any], source: dict[str, Any]) -> bool:
        keys = (
            "content_id",
            "filename",
            "title",
            "source_kind",
            "source_url",
            "mime",
            "render_mode",
            "cover_url",
            "status",
            "progress",
            "error_code",
            "error_detail",
        )
        return all(str(existing[key]) == str(source.get(key) or "") for key in keys) and float(
            existing["duration_seconds"]
        ) == float(source.get("duration_seconds") or 0)

    async def _import_mastery(
        self,
        connection,
        batch_id: str,
        tenant_id: str,
        owner_id: str,
        source: dict[str, Any],
        rows: dict[str, list[dict[str, Any]]],
        resolver: _MappingResolver,
        *,
        version: str,
    ) -> dict[str, int]:
        source_id, source_owner = str(source["source_id"]), str(source["source_owner_id"])
        path_map: dict[str, str] = {}
        inserted_paths = 0
        for row in rows["mastery_paths"]:
            old_path = str(row["path_id"])
            target_path = old_path
            if not _SAFE_ID.fullmatch(target_path):
                target_path = stable_text_id(
                    domain="mastery_paths",
                    source_id=source_id,
                    source_owner_id=source_owner,
                    source_key=old_path,
                    prefix="path",
                )[:128]
            existing = await (
                await connection.execute(
                    """
                    SELECT state,revision
                      FROM enterprise.mastery_paths
                     WHERE tenant_id=%s AND owner_id=%s AND path_id=%s
                    """,
                    (tenant_id, owner_id, target_path),
                )
            ).fetchone()
            revision = int(row["revision"])
            state = self._rewrite_progress(row["state_json"], target_path, revision, row["updated_at"])
            if existing is not None:
                if existing["state"] != state or int(existing["revision"]) != revision:
                    raise ValueError(f"conflicting mastery path: {old_path!r}")
            else:
                creator = await self._owner_session(rows, row, resolver, version=version)
                await connection.execute(
                    """
                    INSERT INTO enterprise.mastery_paths(
                        tenant_id, owner_id, path_id, state, revision,
                        creator_session_id, creator_assigned, created_at, updated_at
                    ) VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)
                    """,
                    (
                        tenant_id,
                        owner_id,
                        target_path,
                        Jsonb(state),
                        revision,
                        creator or None,
                        bool(creator),
                        float(row["created_at"]),
                        float(row["updated_at"]),
                    ),
                )
                for kp_id in self._knowledge_point_ids(state):
                    await connection.execute(
                        """
                        INSERT INTO enterprise.mastery_knowledge_points(
                            tenant_id, owner_id, path_id, kp_id, active
                        ) VALUES (%s,%s,%s,%s,true)
                        """,
                        (tenant_id, owner_id, target_path, kp_id),
                    )
                inserted_paths += 1
            path_map[old_path] = target_path
            await _record_mapping(
                connection,
                batch_id,
                domain="mastery_paths",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=old_path,
                target_key=target_path,
            )

        for row in rows["mastery_path_sessions"]:
            await connection.execute(
                """
                INSERT INTO enterprise.mastery_path_sessions(
                    tenant_id, owner_id, path_id, session_id, created_at, last_seen_at
                ) VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (
                    tenant_id,
                    owner_id,
                    path_map[str(row["path_id"])],
                    await resolver.session(row["session_id"]),
                    float(row["created_at"]),
                    float(row["last_seen_at"]),
                ),
            )

        interaction_map: dict[str, str] = {}
        inserted_interactions = 0
        for row in rows["mastery_interactions"]:
            old_id = str(row["interaction_id"])
            target_id = await self._allocate_text_target(
                connection,
                tenant_id,
                owner_id,
                table="enterprise.mastery_interactions",
                key_column="interaction_id",
                domain="mastery_interactions",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=old_id,
                prefix="mi",
            )
            interaction_map[old_id] = target_id
            await _record_mapping(
                connection,
                batch_id,
                domain="mastery_interactions",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=old_id,
                target_key=target_id,
            )
            await connection.execute(
                """
                INSERT INTO enterprise.mastery_interactions(
                    tenant_id, owner_id, path_id, interaction_id, status, question,
                    session_id, turn_id, user_answer, result, created_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb,%s,%s)
                """,
                (
                    tenant_id,
                    owner_id,
                    path_map[str(row["path_id"])],
                    target_id,
                    row["status"],
                    Jsonb(_json(row["question_json"], {})),
                    await resolver.session(row.get("session_id"), required=False),
                    await resolver.turn(row.get("turn_id"), required=False),
                    row.get("user_answer") or "",
                    Jsonb(_json(row.get("result_json"), {})),
                    float(row["created_at"]),
                    float(row["updated_at"]),
                ),
            )
            inserted_interactions += 1

        inserted_events = 0
        for row in rows["mastery_events"]:
            await connection.execute(
                """
                INSERT INTO enterprise.mastery_events(
                    tenant_id, owner_id, path_id, revision, event_type, payload,
                    session_id, turn_id, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                """,
                (
                    tenant_id,
                    owner_id,
                    path_map[str(row["path_id"])],
                    int(row["revision"]),
                    row["event_type"],
                    Jsonb(_json(row.get("payload_json"), {})),
                    await resolver.session(row.get("session_id"), required=False),
                    await resolver.turn(row.get("turn_id"), required=False),
                    float(row["created_at"]),
                ),
            )
            inserted_events += 1

        meta_by_path = {str(row["path_id"]): row for row in rows["mastery_topic_meta"]}
        for old_path, target_path in path_map.items():
            meta = meta_by_path.get(old_path)
            if meta is None:
                source_path = next(row for row in rows["mastery_paths"] if row["path_id"] == old_path)
                await connection.execute(
                    """
                    INSERT INTO enterprise.mastery_topic_meta(
                        tenant_id, owner_id, path_id, goal, description, emoji,
                        map_seed, status, created_at, updated_at
                    ) VALUES (%s,%s,%s,'','','🧭',%s,'active',%s,%s)
                    """,
                    (
                        tenant_id,
                        owner_id,
                        target_path,
                        _default_map_seed(target_path),
                        float(source_path["created_at"]),
                        float(source_path["updated_at"]),
                    ),
                )
            else:
                await connection.execute(
                    """
                    INSERT INTO enterprise.mastery_topic_meta(
                        tenant_id, owner_id, path_id, goal, description, emoji,
                        map_seed, status, created_at, updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        tenant_id,
                        owner_id,
                        target_path,
                        meta.get("goal") or "",
                        meta.get("description") or "",
                        meta.get("emoji") or "🧭",
                        int(meta.get("map_seed") or _default_map_seed(target_path)),
                        meta.get("status") or "active",
                        float(meta["created_at"]),
                        float(meta["updated_at"]),
                    ),
                )

        for row in rows["mastery_topic_sources"]:
            kind = str(row["kind"])
            external_id = await self._topic_external_id(row.get("external_id"), kind, resolver)
            await connection.execute(
                """
                INSERT INTO enterprise.mastery_topic_sources(
                    tenant_id, owner_id, path_id, id, kind, external_id, label,
                    excerpt, position, available, metadata, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                """,
                (
                    tenant_id,
                    owner_id,
                    path_map[str(row["path_id"])],
                    row["source_id"],
                    kind,
                    external_id,
                    row["label"],
                    row.get("excerpt") or "",
                    int(row["position"]),
                    bool(row.get("available") or 0),
                    Jsonb(_json(row.get("metadata_json"), {})),
                    float(row["created_at"]),
                ),
            )
        return {
            "mastery_paths": inserted_paths,
            "mastery_interactions": inserted_interactions,
            "mastery_events": inserted_events,
        }

    @staticmethod
    def _rewrite_progress(state_json: Any, target_path: str, revision: int, updated_at: Any) -> dict[str, Any]:
        progress = LearningProgress.model_validate(_json(state_json, {}))
        progress.book_id = target_path
        progress.version = revision
        progress.updated_at = float(updated_at)
        return progress.model_dump(mode="json")

    @staticmethod
    def _knowledge_point_ids(state: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        for module in state.get("modules") or []:
            for kp in module.get("knowledge_points") or []:
                key = str(kp.get("id") or "")
                if not key:
                    raise ValueError("mastery knowledge point id must not be empty")
                ids.append(key)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate mastery knowledge point id in source")
        return ids

    async def _owner_session(
        self,
        rows: dict[str, list[dict[str, Any]]],
        path_row: dict[str, Any],
        resolver: _MappingResolver,
        *,
        version: str,
    ) -> str:
        raw = str(path_row.get("owner_session_id") or "")
        if not raw and version == "mastery_sqlite/v1":
            owned = [
                row
                for row in rows["mastery_path_sessions"]
                if row.get("path_id") == path_row.get("path_id") and int(row.get("owns_path") or 0)
            ]
            if owned:
                raw = str(sorted(owned, key=lambda item: (item["created_at"], item["session_id"]))[0]["session_id"])
        return await resolver.session(raw, required=False)

    async def _allocate_text_target(
        self,
        connection,
        tenant_id: str,
        owner_id: str,
        *,
        table: str,
        key_column: str,
        domain: str,
        source_id: str,
        source_owner_id: str,
        source_key: str,
        prefix: str,
    ) -> str:
        candidate = source_key if _SAFE_ID.fullmatch(source_key) else ""
        if candidate and not await self._target_text_exists(
            connection, tenant_id, owner_id, table=table, key_column=key_column, key=candidate
        ):
            return candidate
        base = stable_text_id(
            domain=domain,
            source_id=source_id,
            source_owner_id=source_owner_id,
            source_key=source_key,
            prefix=prefix,
        )[:96]
        candidate = base
        suffix = 1
        while await self._target_text_exists(
            connection, tenant_id, owner_id, table=table, key_column=key_column, key=candidate
        ):
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate

    async def _target_text_exists(
        self,
        connection,
        tenant_id: str,
        owner_id: str,
        *,
        table: str,
        key_column: str,
        key: str,
    ) -> bool:
        row = await (
            await connection.execute(
                f"""
                SELECT 1 FROM {table}
                 WHERE tenant_id=%s AND owner_id=%s AND {key_column}=%s
                 LIMIT 1
                """,  # nosec B608 - table/column 来自封闭常量
                (tenant_id, owner_id, key),
            )
        ).fetchone()
        return row is not None

    async def _topic_external_id(
        self, value: Any, kind: str, resolver: _MappingResolver
    ) -> str:
        raw = str(value or "")
        if kind == "chat" and raw and not raw.startswith("partner:"):
            return await resolver.session(raw)
        if kind == "question_bank" and raw:
            mapped = await resolver.notebook_entry(raw)
            return str(mapped)
        return raw


__all__ = ["SQLiteLearningReadingImporter"]
