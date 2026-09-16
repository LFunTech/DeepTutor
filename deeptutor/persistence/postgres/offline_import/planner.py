"""离线导入 source-check 与 plan。

本模块只读取 manifest 对应的不可变制品，不连接业务 PG、不访问模型、不启动
后台 writer，也不要求源端活动数据库仍存在。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from urllib.request import pathname2url

from .registry import ReferenceRegistry, UnsupportedSourceVersion, get_reference_registry
from .sqlite_snapshot import MANIFEST_VERSION


@dataclass
class ImportPlanReport:
    """source-check/plan 的可序列化报告。"""

    ok: bool
    issues: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": list(self.issues),
            "sources": list(self.sources),
        }


def _issue(
    issues: list[dict[str, Any]],
    code: str,
    message: str,
    *,
    source_id: str | None = None,
    path: str | None = None,
) -> None:
    item: dict[str, Any] = {"code": code, "message": message}
    if source_id:
        item["source_id"] = source_id
    if path:
        item["path"] = path
    issues.append(item)


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sqlite_uri(path: Path, *, immutable: bool = False) -> str:
    query = "mode=ro"
    if immutable:
        query += "&immutable=1"
    return f"file:{pathname2url(str(path))}?{query}"


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_path(manifest_root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return manifest_root / path


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _owner_mapping(manifest: dict[str, Any]) -> dict[str, str]:
    raw = manifest.get("owner_mappings")
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        mapping: dict[str, str] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            source = item.get("source_owner_id")
            target = item.get("target_owner_id")
            if source and target:
                mapping[str(source)] = str(target)
        return mapping
    return {}


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    counts: dict[str, int] = {}
    for (name,) in rows:
        quoted = str(name).replace('"', '""')
        counts[str(name)] = int(conn.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0])
    return counts


def _columns(conn: sqlite3.Connection, table: str) -> set[str] | None:
    rows = conn.execute(f'PRAGMA table_info("{table.replace(chr(34), chr(34) * 2)}")').fetchall()
    if not rows:
        return None
    return {str(row[1]) for row in rows}


def _inspect_sqlite_snapshot(
    snapshot: Path,
    registry: ReferenceRegistry,
    source: dict[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, Any] | None:
    source_id = str(source.get("source_id") or "")
    try:
        with sqlite3.connect(_sqlite_uri(snapshot, immutable=True), uri=True) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity.lower() != "ok":
                _issue(
                    issues,
                    "sqlite_integrity_failed",
                    f"SQLite integrity_check returned {integrity!r}",
                    source_id=source_id,
                    path=str(snapshot),
                )
            counts = _table_counts(conn)
            declared_counts = source.get("snapshot", {}).get("table_counts")
            if isinstance(declared_counts, dict) and declared_counts != counts:
                _issue(
                    issues,
                    "snapshot_table_counts_mismatch",
                    "snapshot table counts do not match manifest",
                    source_id=source_id,
                    path=str(snapshot),
                )
            for table, required_columns in registry.required_tables.items():
                columns = _columns(conn, table)
                if columns is None:
                    _issue(
                        issues,
                        "schema_missing_table",
                        f"required table {table!r} is missing",
                        source_id=source_id,
                        path=str(snapshot),
                    )
                    continue
                missing = sorted(required_columns - columns)
                if missing:
                    _issue(
                        issues,
                        "schema_missing_column",
                        f"required table {table!r} misses columns: {', '.join(missing)}",
                        source_id=source_id,
                        path=str(snapshot),
                    )
            return counts
    except sqlite3.Error as exc:
        _issue(
            issues,
            "sqlite_open_failed",
            "snapshot cannot be opened read-only as SQLite",
            source_id=source_id,
            path=str(snapshot),
        )
        return None


def _inspect_pocketbase_snapshot(
    snapshot: Path,
    registry: ReferenceRegistry,
    source: dict[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, int] | None:
    source_id = str(source.get("source_id") or "")
    try:
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _issue(
            issues,
            "pocketbase_snapshot_unreadable",
            f"PocketBase snapshot cannot be read: {exc}",
            source_id=source_id,
            path=str(snapshot),
        )
        return None
    if payload.get("snapshot_format") != "pocketbase_export/v1":
        _issue(
            issues,
            "pocketbase_snapshot_format_unsupported",
            "PocketBase snapshot format is unsupported",
            source_id=source_id,
            path=str(snapshot),
        )
    collections = payload.get("collections")
    if not isinstance(collections, dict):
        _issue(
            issues,
            "pocketbase_collections_missing",
            "PocketBase snapshot must include collections",
            source_id=source_id,
            path=str(snapshot),
        )
        return None
    counts: dict[str, int] = {}
    for collection, required_fields in registry.required_tables.items():
        raw = collections.get(collection)
        if not isinstance(raw, dict):
            _issue(
                issues,
                "pocketbase_collection_missing",
                f"required collection {collection!r} is missing",
                source_id=source_id,
                path=str(snapshot),
            )
            continue
        records = raw.get("records")
        count = len(records) if isinstance(records, list) else int(raw.get("count") or 0)
        counts[collection] = count
        schema = raw.get("schema")
        if not isinstance(schema, list):
            _issue(
                issues,
                "pocketbase_schema_missing",
                f"required collection {collection!r} schema is missing",
                source_id=source_id,
                path=str(snapshot),
            )
            continue
        field_names = {str(field.get("name") or "") for field in schema if isinstance(field, dict)}
        missing = sorted(required_fields - field_names)
        if missing:
            _issue(
                issues,
                "pocketbase_schema_missing_field",
                f"required collection {collection!r} misses fields: {', '.join(missing)}",
                source_id=source_id,
                path=str(snapshot),
            )

    declared_counts = source.get("snapshot", {}).get("record_counts")
    if isinstance(declared_counts, dict) and declared_counts != counts:
        _issue(
            issues,
            "pocketbase_record_counts_mismatch",
            "PocketBase snapshot record counts do not match manifest",
            source_id=source_id,
            path=str(snapshot),
        )
    declared_schema_hash = source.get("snapshot", {}).get("schema_hash")
    actual_schema_hash = payload.get("summary", {}).get("schema_hash")
    if declared_schema_hash and actual_schema_hash and declared_schema_hash != actual_schema_hash:
        _issue(
            issues,
            "pocketbase_schema_hash_mismatch",
            "PocketBase snapshot schema hash does not match manifest",
            source_id=source_id,
            path=str(snapshot),
        )
    declared_content_hash = source.get("snapshot", {}).get("content_sha256")
    actual_content_hash = payload.get("summary", {}).get("content_sha256")
    if declared_content_hash and actual_content_hash and declared_content_hash != actual_content_hash:
        _issue(
            issues,
            "pocketbase_content_hash_mismatch",
            "PocketBase snapshot content hash does not match manifest",
            source_id=source_id,
            path=str(snapshot),
        )
    return counts


def _snapshot_counts(snapshot: Path, registry: ReferenceRegistry) -> dict[str, int]:
    if registry.source_format == "pocketbase_json":
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        collections = payload.get("collections") if isinstance(payload, dict) else {}
        if not isinstance(collections, dict):
            return {}
        counts: dict[str, int] = {}
        for name, raw in collections.items():
            if not isinstance(raw, dict):
                continue
            records = raw.get("records")
            counts[str(name)] = (
                len(records) if isinstance(records, list) else int(raw.get("count") or 0)
            )
        return dict(sorted(counts.items()))
    with sqlite3.connect(_sqlite_uri(snapshot, immutable=True), uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return _table_counts(conn)


def _validate_manifest(manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    try:
        manifest = _load_manifest(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [{"code": "manifest_unreadable", "message": str(exc)}]

    root = manifest_path.parent
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        _issue(issues, "unsupported_manifest_version", "unsupported manifest version")
    freeze = manifest.get("freeze")
    if not isinstance(freeze, dict) or not freeze.get("freeze_id"):
        _issue(issues, "freeze_missing", "manifest must include a freeze_id")
    elif not freeze.get("stopped_writers"):
        _issue(issues, "freeze_missing_stopped_writers", "freeze must list stopped writers")

    mappings = _owner_mapping(manifest)
    seen_sources: set[str] = set()
    for source in manifest.get("sources") or []:
        if not isinstance(source, dict):
            _issue(issues, "source_malformed", "source entry must be an object")
            continue
        source_id = str(source.get("source_id") or "")
        if not source_id:
            _issue(issues, "source_id_missing", "source_id is required")
        elif source_id in seen_sources:
            _issue(issues, "source_id_duplicate", "source_id must be unique", source_id=source_id)
        seen_sources.add(source_id)

        owner_id = source.get("source_owner_id")
        if not owner_id or str(owner_id) not in mappings:
            _issue(
                issues,
                "owner_mapping_missing",
                "source owner must have an explicit target owner mapping",
                source_id=source_id,
            )

        source_version = str(source.get("source_version") or "")
        try:
            registry = get_reference_registry(source_version)
        except UnsupportedSourceVersion:
            _issue(
                issues,
                "unknown_source_version",
                f"source version {source_version!r} is not registered",
                source_id=source_id,
            )
            registry = None

        snapshot_path = _artifact_path(root, source.get("snapshot", {}).get("path"))
        source_path = Path(str(source.get("source_path") or ""))
        if snapshot_path is None:
            _issue(issues, "snapshot_path_missing", "snapshot path is required", source_id=source_id)
            continue
        if source_path and snapshot_path.resolve(strict=False) == source_path.resolve(strict=False):
            _issue(
                issues,
                "snapshot_is_source_database",
                "snapshot path must not be the activity source database",
                source_id=source_id,
                path=str(snapshot_path),
            )
        if not _is_under(snapshot_path, root):
            _issue(
                issues,
                "artifact_path_escape",
                "snapshot artifact must live under the manifest directory",
                source_id=source_id,
                path=str(snapshot_path),
            )
        if snapshot_path.is_symlink():
            _issue(
                issues,
                "artifact_symlink",
                "snapshot artifact must not be a symlink",
                source_id=source_id,
                path=str(snapshot_path),
            )
        if not snapshot_path.exists():
            _issue(
                issues,
                "snapshot_missing",
                "snapshot artifact is missing",
                source_id=source_id,
                path=str(snapshot_path),
            )
            continue
        declared = source.get("snapshot", {})
        if declared.get("sha256") and declared.get("sha256") != _sha256(snapshot_path):
            _issue(
                issues,
                "snapshot_hash_mismatch",
                "snapshot sha256 does not match manifest",
                source_id=source_id,
                path=str(snapshot_path),
            )
        if declared.get("size_bytes") is not None and declared.get("size_bytes") != snapshot_path.stat().st_size:
            _issue(
                issues,
                "snapshot_size_mismatch",
                "snapshot size does not match manifest",
                source_id=source_id,
                path=str(snapshot_path),
            )
        snapshot_wal = Path(str(snapshot_path) + "-wal")
        if snapshot_wal.exists() and snapshot_wal.stat().st_size > 0:
            _issue(
                issues,
                "snapshot_has_wal_dependency",
                "independent snapshot must not depend on a WAL sidecar",
                source_id=source_id,
                path=str(snapshot_wal),
            )

        sidecars = source.get("sidecars") if isinstance(source.get("sidecars"), dict) else {}
        wal = sidecars.get("wal") if isinstance(sidecars.get("wal"), dict) else {}
        if wal.get("required"):
            wal_path = _artifact_path(root, wal.get("path"))
            if wal_path is None or not wal_path.exists():
                _issue(
                    issues,
                    "required_wal_sidecar_missing",
                    "manifest declares a required WAL sidecar but the artifact is missing",
                    source_id=source_id,
                )
            elif not _is_under(wal_path, root):
                _issue(
                    issues,
                    "artifact_path_escape",
                    "required WAL sidecar must live under the manifest directory",
                    source_id=source_id,
                    path=str(wal_path),
                )
            elif wal_path.is_symlink():
                _issue(
                    issues,
                    "artifact_symlink",
                    "required WAL sidecar must not be a symlink",
                    source_id=source_id,
                    path=str(wal_path),
                )
            elif wal.get("sha256") and wal.get("sha256") != _sha256(wal_path):
                _issue(
                    issues,
                    "sidecar_hash_mismatch",
                    "required WAL sidecar sha256 does not match manifest",
                    source_id=source_id,
                    path=str(wal_path),
                )

        if registry is not None:
            if registry.source_format == "pocketbase_json":
                _inspect_pocketbase_snapshot(snapshot_path, registry, source, issues)
            else:
                _inspect_sqlite_snapshot(snapshot_path, registry, source, issues)

    if not manifest.get("sources"):
        _issue(issues, "sources_missing", "manifest must include at least one source")
    return manifest, issues


def source_check_manifest(manifest_path: str | Path) -> ImportPlanReport:
    """Validate an offline source manifest and its read-only artifacts."""

    _manifest, issues = _validate_manifest(Path(manifest_path))
    return ImportPlanReport(ok=not issues, issues=issues)


def plan_sqlite_import(manifest_path: str | Path) -> ImportPlanReport:
    """Return a deterministic read-only import plan for a checked manifest."""

    path = Path(manifest_path)
    manifest, issues = _validate_manifest(path)
    if issues:
        return ImportPlanReport(ok=False, issues=issues)

    mappings = _owner_mapping(manifest)
    root = path.parent
    planned_sources: list[dict[str, Any]] = []
    for source in manifest.get("sources") or []:
        registry = get_reference_registry(str(source["source_version"]))
        snapshot_path = _artifact_path(root, source.get("snapshot", {}).get("path"))
        counts: dict[str, int] = {}
        if snapshot_path is not None:
            counts = _snapshot_counts(snapshot_path, registry)
        planned_sources.append(
            {
                "source_id": source["source_id"],
                "source_type": source["source_type"],
                "source_version": source["source_version"],
                "source_owner_id": source["source_owner_id"],
                "target_owner_id": mappings[str(source["source_owner_id"])],
                "table_counts": counts,
                "reference_fields": [field.path for field in registry.reference_fields],
            }
        )
    return ImportPlanReport(ok=True, sources=planned_sources)


__all__ = ["ImportPlanReport", "plan_sqlite_import", "source_check_manifest"]
