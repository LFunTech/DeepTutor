"""SQLite 源端只读 Backup API 快照与 manifest 生成。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.request import pathname2url

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "deeptutor-sqlite-source-manifest.json"
_TOOL_NAME = "deeptutor-sqlite-offline-import"


class SourceSnapshotError(RuntimeError):
    """源快照无法作为只读独立制品生成。"""


@dataclass(frozen=True)
class SourceSnapshotResult:
    """生成 manifest 后返回的核心路径。"""

    manifest_path: Path
    snapshot_path: Path
    source_id: str


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return safe.strip(".-") or "sqlite-source"


def _sqlite_uri(path: Path, *, immutable: bool = False) -> str:
    query = "mode=ro"
    if immutable:
        query += "&immutable=1"
    return f"file:{pathname2url(str(path))}?{query}"


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_record(path: Path, *, required: bool = False) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "required": required,
    }
    if path.exists():
        stat = path.stat()
        record.update({"size_bytes": stat.st_size, "sha256": _sha256(path)})
    return record


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


def _schema_hash(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        """
        SELECT type, name, tbl_name, COALESCE(sql, '')
        FROM sqlite_master
        WHERE sql IS NOT NULL
        ORDER BY type, name
        """
    ).fetchall()
    payload = "\n".join("\t".join(str(part) for part in row) for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _inspect_snapshot(snapshot: Path) -> dict[str, Any]:
    with sqlite3.connect(_sqlite_uri(snapshot, immutable=True), uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        return {
            "path": str(snapshot),
            "sha256": _sha256(snapshot),
            "size_bytes": snapshot.stat().st_size,
            "sqlite_version": sqlite3.sqlite_version,
            "integrity_check": str(integrity),
            "schema_hash": _schema_hash(conn),
            "table_counts": _table_counts(conn),
            "wal_dependency": False,
        }


def _manifest_owner_mappings(owner_mappings: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"source_owner_id": source, "target_owner_id": target}
        for source, target in sorted(owner_mappings.items())
    ]


def create_sqlite_source_snapshot(
    *,
    source_db: str | Path,
    output_dir: str | Path,
    source_id: str,
    source_version: str,
    source_owner_id: str,
    target_tenant_id: str,
    owner_mappings: dict[str, str],
    freeze_id: str,
    stopped_writers: list[str],
    operator: str,
) -> SourceSnapshotResult:
    """Use SQLite Backup API to produce an independent offline snapshot.

    The function opens the source in read-only mode, writes only into
    ``output_dir``, verifies that source main DB and WAL bytes did not change,
    and records SHM as a non-authoritative coordination sidecar.  It does not
    checkpoint, VACUUM, upgrade, delete or otherwise repair the source.
    """

    source = Path(source_db)
    if not source.exists():
        raise SourceSnapshotError(f"source database does not exist: {source}")
    if source.is_symlink():
        raise SourceSnapshotError("source database symlink is not accepted")
    if not freeze_id.strip() or not stopped_writers:
        raise SourceSnapshotError("freeze_id and stopped_writers are required")
    if source_owner_id not in owner_mappings:
        raise SourceSnapshotError("source owner must have an explicit target owner mapping")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    snapshot = out / f"{_safe_name(source_id)}.snapshot.sqlite3"
    if snapshot.exists():
        snapshot.unlink()
    for sidecar in (Path(str(snapshot) + "-wal"), Path(str(snapshot) + "-shm")):
        if sidecar.exists():
            sidecar.unlink()

    source_wal = Path(str(source) + "-wal")
    source_shm = Path(str(source) + "-shm")
    authority_before = {
        "main_sha256_before": _sha256(source),
        "wal_sha256_before": _sha256(source_wal),
        "shm_sha256_before": _sha256(source_shm),
    }

    # Backup API produces a new database file.  The destination is a new
    # artifact, so setting DELETE journal mode is acceptable and prevents the
    # artifact from depending on a destination WAL sidecar.
    with sqlite3.connect(_sqlite_uri(source), uri=True) as src:
        with sqlite3.connect(snapshot) as dst:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode = DELETE")
            dst.commit()

    authority_after = {
        "main_sha256_after": _sha256(source),
        "wal_sha256_after": _sha256(source_wal),
        "shm_sha256_after": _sha256(source_shm),
    }
    if authority_before["main_sha256_before"] != authority_after["main_sha256_after"]:
        raise SourceSnapshotError("source main database changed during backup")
    if authority_before["wal_sha256_before"] != authority_after["wal_sha256_after"]:
        raise SourceSnapshotError("source WAL changed during backup")
    if Path(str(snapshot) + "-wal").exists() and Path(str(snapshot) + "-wal").stat().st_size > 0:
        raise SourceSnapshotError("snapshot still has a WAL dependency")

    snapshot_record = _inspect_snapshot(snapshot)
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": _utc_now(),
        "producer": {
            "tool": _TOOL_NAME,
            "sqlite_version": sqlite3.sqlite_version,
        },
        "freeze": {
            "freeze_id": freeze_id,
            "operator": operator,
            "stopped_writers": list(stopped_writers),
            "recorded_at": _utc_now(),
        },
        "target": {"tenant_id": target_tenant_id},
        "owner_mappings": _manifest_owner_mappings(owner_mappings),
        "sources": [
            {
                "source_id": source_id,
                "source_type": "sqlite",
                "source_version": source_version,
                "source_owner_id": source_owner_id,
                "source_path": str(source),
                "source_authority": {**authority_before, **authority_after},
                "snapshot": snapshot_record,
                "sidecars": {
                    "wal": _file_record(source_wal, required=False),
                    "shm": _file_record(source_shm, required=False),
                },
            }
        ],
    }
    manifest_path = out / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return SourceSnapshotResult(
        manifest_path=manifest_path,
        snapshot_path=snapshot,
        source_id=source_id,
    )


__all__ = [
    "MANIFEST_FILENAME",
    "MANIFEST_VERSION",
    "SourceSnapshotError",
    "SourceSnapshotResult",
    "create_sqlite_source_snapshot",
]
