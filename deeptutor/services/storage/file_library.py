"""PostgreSQL-backed persistent file library (issue #1437).

The file library keeps file bytes on the configured owner resource root and
persists metadata in the existing PostgreSQL ``enterprise.resource_objects``
table.  It intentionally does not provide a SQLite/local fallback: the library
is part of the supported business runtime and must fail closed when PostgreSQL
or owner resources are unavailable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import threading
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.connection import SyncDatabase
from deeptutor.persistence.postgres.scope import TenantScope

logger = logging.getLogger(__name__)

_LIBRARY_RESOURCE_KIND = "file_library"
_LIBRARY_BUCKET = "owner-file-library"
_ACTIVE_STATE = "ready"
_DELETED_STATE = "deleted"
_VALID_STATES = {_ACTIVE_STATE, _DELETED_STATE}
_MAX_FILENAME_LENGTH = 512


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


def _uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _clean_filename(filename: str) -> str:
    cleaned = str(filename or "").strip()
    if not cleaned:
        raise ValueError("filename is required")
    if "\x00" in cleaned:
        raise ValueError("filename contains invalid characters")
    return cleaned[:_MAX_FILENAME_LENGTH]


def _object_name_for(file_id: UUID, filename: str) -> str:
    suffix = Path(filename).suffix
    if len(suffix) > 32 or "/" in suffix or "\\" in suffix or "\x00" in suffix:
        suffix = ""
    return f"{file_id}{suffix}"


def _require_object_name(name: Any) -> str:
    value = str(name or "")
    if not value or value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise RuntimeError("invalid file library object key")
    return value


class FileLibraryStore:
    """Persistent file library store backed by PostgreSQL metadata.

    Parameters
    ----------
    db:
        Started :class:`~deeptutor.persistence.postgres.connection.SyncDatabase`.
    scope:
        Trusted tenant/user scope for the current owner.
    root:
        Owner-scoped directory for the file bytes.  The store creates a
        ``library`` subdirectory under the root passed by the runtime/provider.

    ``db_path`` is accepted only to fail with a clear error for legacy callers;
    SQLite is not a supported runtime backend anymore.
    """

    def __init__(
        self,
        db: SyncDatabase | None = None,
        scope: TenantScope | None = None,
        root: Path | str | None = None,
        *,
        db_path: Path | str | None = None,
    ) -> None:
        if db_path is not None and (db is None or scope is None):
            raise RuntimeError("FileLibraryStore requires PostgreSQL; SQLite db_path is unsupported")
        if not isinstance(db, SyncDatabase):
            raise TypeError("FileLibraryStore requires a started SyncDatabase")
        if not isinstance(scope, TenantScope):
            raise TypeError("FileLibraryStore requires a trusted TenantScope")
        if root is None:
            raise RuntimeError("FileLibraryStore requires an owner resource root")
        self._db = db
        self._scope = scope
        self._root = Path(root).resolve()
        self._add_lock = threading.Lock()

    # ------------------------------------------------------------------
    # File I/O helpers
    # ------------------------------------------------------------------

    def _ensure_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def _file_path(self, object_name: str) -> Path:
        safe = _require_object_name(object_name)
        path = (self._root / safe).resolve()
        if not path.is_relative_to(self._root):
            raise RuntimeError("file library object escaped owner root")
        return path

    def _write_file(self, object_name: str, data: bytes) -> None:
        self._ensure_root()
        target = self._file_path(object_name)
        tmp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with tmp.open("wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
            try:
                directory_fd = os.open(str(self._root), os.O_RDONLY | os.O_DIRECTORY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            with contextlib_suppress_oserror():
                tmp.unlink()

    def _delete_file(self, object_name: str) -> None:
        target = self._file_path(object_name)
        with contextlib_suppress_oserror():
            target.unlink()

    # ------------------------------------------------------------------
    # Public API — add / get / delete
    # ------------------------------------------------------------------

    async def add_file(
        self,
        *,
        data: bytes,
        filename: str,
        mime_type: str = "",
    ) -> dict[str, Any]:
        """Add a file, deduplicating active rows by SHA-256 in application code."""
        return await asyncio.to_thread(self._add_file_sync, data, filename, mime_type)

    def _add_file_sync(
        self,
        data: bytes,
        filename: str,
        mime_type: str,
    ) -> dict[str, Any]:
        if not isinstance(data, bytes):
            raise TypeError("file data must be bytes")
        clean_name = _clean_filename(filename)
        clean_mime = str(mime_type or "")[:255]
        sha = _sha256(data)
        now = _utc_now()
        file_id = uuid4()
        object_name = _object_name_for(file_id, clean_name)
        file_written = False

        def write(connection):
            nonlocal file_written
            self._lock_owner(connection)
            existing = connection.execute(
                """
                SELECT * FROM enterprise.resource_objects
                 WHERE tenant_id=%s AND owner_id=%s
                   AND resource_kind=%s AND content_hash=%s
                   AND state<>%s
                 ORDER BY created_at ASC, id ASC
                 LIMIT 1
                """,
                (
                    self._scope.tenant_id,
                    self._scope.user_id,
                    _LIBRARY_RESOURCE_KIND,
                    sha,
                    _DELETED_STATE,
                ),
            ).fetchone()
            if existing is not None:
                return self._row_to_entry(existing)

            self._write_file(object_name, data)
            file_written = True
            row = connection.execute(
                """
                INSERT INTO enterprise.resource_objects(
                    tenant_id, owner_id, id, resource_kind, resource_id, bucket,
                    object_key, content_hash, size_bytes, mime_type, state,
                    version, retention, metadata, created_by, created_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s)
                RETURNING *
                """,
                (
                    self._scope.tenant_id,
                    self._scope.user_id,
                    file_id,
                    _LIBRARY_RESOURCE_KIND,
                    str(file_id),
                    _LIBRARY_BUCKET,
                    object_name,
                    sha,
                    len(data),
                    clean_mime,
                    _ACTIVE_STATE,
                    "default",
                    Jsonb({"filename": clean_name}),
                    self._scope.user_id,
                    now,
                    now,
                ),
            ).fetchone()
            return self._row_to_entry(row)

        with self._add_lock:
            try:
                return self._db_run(write)
            except BaseException:
                if file_written:
                    self._delete_file(object_name)
                raise

    async def get_file(self, file_id: str) -> dict[str, Any] | None:
        """Return the entry for *file_id*, or None if not found."""
        return await asyncio.to_thread(self._get_file_sync, file_id)

    def _get_file_sync(self, file_id: str) -> dict[str, Any] | None:
        parsed = _uuid_or_none(file_id)
        if parsed is None:
            return None

        def read(connection):
            row = connection.execute(
                """
                SELECT * FROM enterprise.resource_objects
                 WHERE tenant_id=%s AND owner_id=%s AND id=%s AND resource_kind=%s
                """,
                (self._scope.tenant_id, self._scope.user_id, parsed, _LIBRARY_RESOURCE_KIND),
            ).fetchone()
            return None if row is None else self._row_to_entry(row)

        return self._db_run(read)

    async def delete_file(self, file_id: str) -> bool:
        """Soft-delete a library entry."""
        return await asyncio.to_thread(self._delete_file_sync, file_id)

    def _delete_file_sync(self, file_id: str) -> bool:
        parsed = _uuid_or_none(file_id)
        if parsed is None:
            return False
        now = _utc_now()

        def write(connection):
            row = self._resource_for_update(connection, parsed)
            if row is None:
                return False
            entry = self._row_to_entry(row)
            if entry["is_deleted"]:
                return True
            connection.execute(
                """
                UPDATE enterprise.resource_objects
                   SET state=%s, deleted_at=%s, updated_at=%s, version=version+1
                 WHERE tenant_id=%s AND owner_id=%s AND id=%s AND resource_kind=%s
                """,
                (
                    _DELETED_STATE,
                    now,
                    now,
                    self._scope.tenant_id,
                    self._scope.user_id,
                    parsed,
                    _LIBRARY_RESOURCE_KIND,
                ),
            )
            return True

        return self._db_run(write)

    async def hard_delete_file(self, file_id: str) -> bool:
        """Permanently delete an already-soft-deleted entry and its file bytes."""
        return await asyncio.to_thread(self._hard_delete_file_sync, file_id)

    def _hard_delete_file_sync(self, file_id: str) -> bool:
        parsed = _uuid_or_none(file_id)
        if parsed is None:
            return False
        object_name: str | None = None

        def write(connection):
            nonlocal object_name
            row = self._resource_for_update(connection, parsed)
            if row is None:
                return False
            entry = self._row_to_entry(row)
            if not entry["is_deleted"]:
                return False
            object_name = entry["library_path"]
            connection.execute(
                """
                DELETE FROM enterprise.resource_objects
                 WHERE tenant_id=%s AND owner_id=%s AND id=%s AND resource_kind=%s
                """,
                (self._scope.tenant_id, self._scope.user_id, parsed, _LIBRARY_RESOURCE_KIND),
            )
            return True

        deleted = self._db_run(write)
        if deleted and object_name:
            self._delete_file(object_name)
        return bool(deleted)

    async def restore_file(self, file_id: str) -> bool:
        """Restore a soft-deleted entry."""
        return await asyncio.to_thread(self._restore_file_sync, file_id)

    def _restore_file_sync(self, file_id: str) -> bool:
        parsed = _uuid_or_none(file_id)
        if parsed is None:
            return False
        now = _utc_now()

        def write(connection):
            row = self._resource_for_update(connection, parsed)
            if row is None:
                return False
            entry = self._row_to_entry(row)
            if not entry["is_deleted"]:
                return True
            duplicate = connection.execute(
                """
                SELECT 1 FROM enterprise.resource_objects
                 WHERE tenant_id=%s AND owner_id=%s AND resource_kind=%s
                   AND content_hash=%s AND state<>%s AND id<>%s
                 LIMIT 1
                """,
                (
                    self._scope.tenant_id,
                    self._scope.user_id,
                    _LIBRARY_RESOURCE_KIND,
                    entry["sha256"],
                    _DELETED_STATE,
                    parsed,
                ),
            ).fetchone()
            if duplicate is not None:
                return False
            connection.execute(
                """
                UPDATE enterprise.resource_objects
                   SET state=%s, deleted_at=NULL, updated_at=%s, version=version+1
                 WHERE tenant_id=%s AND owner_id=%s AND id=%s AND resource_kind=%s
                """,
                (
                    _ACTIVE_STATE,
                    now,
                    self._scope.tenant_id,
                    self._scope.user_id,
                    parsed,
                    _LIBRARY_RESOURCE_KIND,
                ),
            )
            return True

        return self._db_run(write)

    # ------------------------------------------------------------------
    # Listing and search
    # ------------------------------------------------------------------

    async def list_files(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List active library entries, newest first."""
        return await asyncio.to_thread(self._list_files_sync, limit, offset)

    def _list_files_sync(self, limit: int, offset: int) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))

        def read(connection):
            rows = connection.execute(
                """
                SELECT * FROM enterprise.resource_objects
                 WHERE tenant_id=%s AND owner_id=%s
                   AND resource_kind=%s AND state<>%s
                 ORDER BY created_at DESC, id DESC
                 LIMIT %s OFFSET %s
                """,
                (
                    self._scope.tenant_id,
                    self._scope.user_id,
                    _LIBRARY_RESOURCE_KIND,
                    _DELETED_STATE,
                    limit,
                    offset,
                ),
            ).fetchall()
            return [self._row_to_entry(row) for row in rows]

        return self._db_run(read)

    async def search_files(self, query: str) -> list[dict[str, Any]]:
        """Search active entries by filename."""
        return await asyncio.to_thread(self._search_files_sync, query.strip())

    def _search_files_sync(self, query: str) -> list[dict[str, Any]]:
        if not query:
            return []
        pattern = f"%{query}%"

        def read(connection):
            rows = connection.execute(
                """
                SELECT * FROM enterprise.resource_objects
                 WHERE tenant_id=%s AND owner_id=%s
                   AND resource_kind=%s AND state<>%s
                   AND metadata->>'filename' ILIKE %s
                 ORDER BY created_at DESC, id DESC
                """,
                (
                    self._scope.tenant_id,
                    self._scope.user_id,
                    _LIBRARY_RESOURCE_KIND,
                    _DELETED_STATE,
                    pattern,
                ),
            ).fetchall()
            return [self._row_to_entry(row) for row in rows]

        return self._db_run(read)

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def resolve_path(self, file_id: str) -> Path | None:
        """Return the stored file path for an active entry, or None."""
        parsed = _uuid_or_none(file_id)
        if parsed is None:
            return None

        def read(connection):
            row = connection.execute(
                """
                SELECT * FROM enterprise.resource_objects
                 WHERE tenant_id=%s AND owner_id=%s AND id=%s AND resource_kind=%s
                """,
                (self._scope.tenant_id, self._scope.user_id, parsed, _LIBRARY_RESOURCE_KIND),
            ).fetchone()
            if row is None:
                return None
            entry = self._row_to_entry(row)
            if entry["is_deleted"]:
                return None
            path = self._file_path(entry["library_path"])
            return path if path.is_file() else None

        return self._db_run(read)

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _db_run(self, operation):
        with self._db.transaction(self._scope) as connection:
            return operation(connection)

    def _lock_owner(self, connection) -> None:
        row = connection.execute(
            """
            SELECT 1 FROM enterprise.users
             WHERE tenant_id=%s AND id=%s AND disabled=false
             FOR UPDATE
            """,
            (self._scope.tenant_id, self._scope.user_id),
        ).fetchone()
        if row is None:
            raise PermissionError("file library owner is unavailable")

    def _resource_for_update(self, connection, file_id: UUID):
        return connection.execute(
            """
            SELECT * FROM enterprise.resource_objects
             WHERE tenant_id=%s AND owner_id=%s AND id=%s AND resource_kind=%s
             FOR UPDATE
            """,
            (self._scope.tenant_id, self._scope.user_id, file_id, _LIBRARY_RESOURCE_KIND),
        ).fetchone()

    @staticmethod
    def _row_to_entry(row: dict[str, Any]) -> dict[str, Any]:
        state = str(row["state"])
        if state not in _VALID_STATES:
            raise RuntimeError(f"unknown file library state: {state!r}")
        metadata = row.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise RuntimeError("invalid file library metadata")
        filename = metadata.get("filename")
        if not isinstance(filename, str) or not filename:
            raise RuntimeError("file library row is missing filename")
        object_name = _require_object_name(row["object_key"])
        deleted_at = _timestamp(row.get("deleted_at"))
        if state == _DELETED_STATE and deleted_at is None:
            raise RuntimeError("deleted file library row is missing deleted_at")
        if state == _ACTIVE_STATE and deleted_at is not None:
            raise RuntimeError("active file library row has deleted_at")
        return {
            "id": str(row["id"]),
            "sha256": str(row["content_hash"]),
            "filename": filename,
            "mime_type": str(row.get("mime_type") or ""),
            "size_bytes": int(row["size_bytes"]),
            "library_path": object_name,
            "created_at": _timestamp(row["created_at"]),
            "updated_at": _timestamp(row["updated_at"]),
            "is_deleted": state == _DELETED_STATE,
            "deleted_at": deleted_at,
        }


class contextlib_suppress_oserror:
    """Tiny local context manager to avoid importing contextlib for one case."""

    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return exc_type is not None and issubclass(exc_type, OSError)


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_instances: dict[tuple[int, str, str, str], FileLibraryStore] = {}


def get_file_library_store() -> FileLibraryStore:
    """Return the PostgreSQL FileLibraryStore singleton for the current owner."""
    from deeptutor.app.container import get_application_container
    from deeptutor.core.providers import get_providers

    providers = get_providers()
    container = providers.container if providers is not None and providers.container is not None else None
    if container is None:
        container = get_application_container()
    runtime = getattr(container, "postgres_runtime", None)
    if runtime is None or getattr(runtime, "sync_db", None) is None:
        raise RuntimeError("PostgreSQL file library runtime is not configured")
    scope = runtime.scope_for_current_user()
    resources = getattr(runtime, "resources", None) or getattr(container, "resources_provider", None)
    if resources is None:
        raise RuntimeError("PostgreSQL file library resources are not configured")
    root = Path(resources.owner_root(scope.tenant_id, scope.user_id, "attachments")) / "library"
    key = (id(runtime.sync_db), scope.tenant_id, scope.user_id, str(root.resolve()))
    if key not in _instances:
        _instances[key] = FileLibraryStore(runtime.sync_db, scope, root=root)
    return _instances[key]


def reset_file_library_store() -> None:
    """Clear process-wide FileLibraryStore singletons (tests)."""
    _instances.clear()
