"""PostgreSQL-backed MarginNote 4 object/device store.

This adapter preserves the legacy ``MarginNoteStore`` public behavior while
persisting every row under an explicit tenant/owner/KB/device composite key.
It never derives authority from a filesystem ``db_path`` and does not create or
open SQLite state; API/tool wiring switches to it in the following task.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
import math
import secrets
import time
from typing import Any

from psycopg.types.json import Jsonb

from deeptutor.capabilities.marginnote4.models import (
    ALL_TYPES,
    MarginNoteObject,
    PairedDevice,
    SyncBatch,
    SyncResult,
)
from deeptutor.persistence.postgres.connection import SyncDatabase
from deeptutor.persistence.postgres.scope import TenantScope

_DEVICE_PREFIX = "dtmn4"
_DEVICE_SEPARATOR = "."


class MarginNoteCursorConflict(RuntimeError):
    """Raised when a device submits a sync batch from a stale cursor."""


def _encode_owner_id(owner_id: str) -> str:
    encoded = base64.urlsafe_b64encode(owner_id.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def owner_id_from_device_id(device_id: str) -> str | None:
    parts = str(device_id or "").split(_DEVICE_SEPARATOR, 2)
    if len(parts) != 3 or parts[0] != _DEVICE_PREFIX or not parts[1] or not parts[2]:
        return None
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        owner_id = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001 - malformed public device id simply has no owner
        return None
    return owner_id or None


def _new_device_id(owner_id: str) -> str:
    return f"{_DEVICE_PREFIX}{_DEVICE_SEPARATOR}{_encode_owner_id(owner_id)}{_DEVICE_SEPARATOR}{secrets.token_urlsafe(12)}"

def _jsonb(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda obj: json.dumps(obj, ensure_ascii=False, allow_nan=False))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _require_text(value: object, name: str, *, max_length: int | None = None) -> str:
    text = str(value or "").strip()
    if not text or "\x00" in text or (max_length is not None and len(text) > max_length):
        raise ValueError(f"{name} is required")
    return text


class PostgresMarginNoteStore:
    """Synchronous owner-scoped MarginNote store backed by PG tables."""

    def __init__(
        self,
        database: SyncDatabase,
        scope: TenantScope,
        *,
        kb_id: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(database, SyncDatabase):
            raise TypeError("SyncDatabase is required")
        if not isinstance(scope, TenantScope):
            raise TypeError("trusted TenantScope is required")
        self.db = database
        self.scope = scope
        self.tenant_id = scope.tenant_id
        self.owner_id = scope.user_id
        self.kb_id = _require_text(kb_id, "kb_id", max_length=255)
        self._clock = clock

    def _now_iso(self) -> str:
        value = float(self._clock())
        if not math.isfinite(value) or value < 0:
            raise ValueError("clock must return a finite non-negative timestamp")
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()

    def _values(self, device_id: str = "") -> tuple[str, str, str] | tuple[str, str, str, str]:
        if device_id:
            return (self.tenant_id, self.owner_id, self.kb_id, device_id)
        return (self.tenant_id, self.owner_id, self.kb_id)

    def _run(self, operation):
        with self.db.transaction(self.scope) as connection:
            return operation(connection)

    @staticmethod
    def _row_to_device(row: dict[str, Any]) -> PairedDevice:
        return PairedDevice(
            device_id=str(row["device_id"]),
            device_name=str(row["device_name"]),
            device_kind=str(row["device_kind"]),
            paired_at=str(row["paired_at"]),
            last_seen=str(row["last_seen"]),
            active=bool(row["active"]),
        )

    @staticmethod
    def _row_to_object(row: dict[str, Any]) -> MarginNoteObject:
        tags = row["tags"] or []
        links = row["links"] or []
        raw = row["raw"] or {}
        return MarginNoteObject(
            object_id=str(row["object_id"]),
            object_type=str(row["object_type"]),
            title=str(row["title"]),
            content=str(row["content"]),
            excerpt=row["excerpt"],
            document_id=row["document_id"],
            document_title=row["document_title"],
            page=row["page"],
            tags=list(tags) if isinstance(tags, list) else [],
            links=list(links) if isinstance(links, list) else [],
            color=row["color"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            synced_at=str(row["synced_at"]),
            device_id=str(row["device_id"]),
            raw=dict(raw) if isinstance(raw, dict) else {},
        )

    # -- device pairing -------------------------------------------------

    def pair_device(
        self,
        *,
        device_name: str = "",
        device_kind: str = "macos",
    ) -> tuple[PairedDevice, str]:
        device_id = _new_device_id(self.owner_id)
        token = secrets.token_urlsafe(32)
        now = self._now_iso()
        device_kind = _require_text(device_kind, "device_kind", max_length=32)
        token_hash = _hash_token(token)

        def write(connection):
            connection.execute(
                """
                INSERT INTO enterprise.marginnote_devices(
                    tenant_id, owner_id, kb_id, device_id, device_name,
                    device_kind, token_hash, paired_at, last_seen, active
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true)
                """,
                (
                    self.tenant_id,
                    self.owner_id,
                    self.kb_id,
                    device_id,
                    str(device_name or "")[:128],
                    device_kind,
                    token_hash,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO enterprise.marginnote_cursors(
                    tenant_id, owner_id, kb_id, device_id, cursor, updated_at
                ) VALUES (%s,%s,%s,%s,'',%s)
                """,
                (*self._values(device_id), now),
            )

        self._run(write)
        return (
            PairedDevice(
                device_id=device_id,
                device_name=str(device_name or "")[:128],
                device_kind=device_kind,
                paired_at=now,
                last_seen=now,
            ),
            token,
        )

    def revoke_device(self, device_id: str) -> bool:
        device_id = _require_text(device_id, "device_id")

        def write(connection):
            result = connection.execute(
                """
                UPDATE enterprise.marginnote_devices
                   SET active=false
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                   AND device_id=%s AND active=true
                """,
                self._values(device_id),
            )
            return result.rowcount > 0

        return self._run(write)

    def verify_token(self, device_id: str, token: str) -> bool:
        if not device_id or not token:
            return False

        def read(connection):
            row = connection.execute(
                """
                SELECT token_hash, active
                  FROM enterprise.marginnote_devices
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s AND device_id=%s
                """,
                self._values(device_id),
            ).fetchone()
            return bool(
                row is not None
                and row["active"]
                and secrets.compare_digest(str(row["token_hash"]), _hash_token(token))
            )

        return self._run(read)

    def list_devices(self) -> list[PairedDevice]:
        def read(connection):
            rows = connection.execute(
                """
                SELECT device_id, device_name, device_kind, paired_at, last_seen, active
                  FROM enterprise.marginnote_devices
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                 ORDER BY paired_at, device_id
                """,
                self._values(),
            ).fetchall()
            return [self._row_to_device(row) for row in rows]

        return self._run(read)

    def touch_device(self, device_id: str) -> None:
        device_id = _require_text(device_id, "device_id")
        now = self._now_iso()

        def write(connection):
            connection.execute(
                """
                UPDATE enterprise.marginnote_devices
                   SET last_seen=%s
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s AND device_id=%s
                """,
                (now, *self._values(device_id)),
            )

        self._run(write)

    # -- sync ingest ----------------------------------------------------

    def ingest(self, batch: SyncBatch) -> SyncResult:
        device_id = _require_text(batch.device_id, "device_id")
        stored = updated = deleted = 0
        now = self._now_iso()

        def write(connection):
            nonlocal stored, updated, deleted
            row = connection.execute(
                """
                SELECT cursor
                  FROM enterprise.marginnote_cursors
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s AND device_id=%s
                 FOR UPDATE
                """,
                self._values(device_id),
            ).fetchone()
            current_cursor = str(row["cursor"]) if row else ""
            if str(batch.cursor or "") != current_cursor:
                raise MarginNoteCursorConflict("MarginNote sync cursor is stale")
            for obj in batch.objects:
                if obj.object_type not in ALL_TYPES:
                    continue
                previous = connection.execute(
                    """
                    SELECT synced_at
                      FROM enterprise.marginnote_objects
                     WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                       AND device_id=%s AND object_id=%s
                    """,
                    (*self._values(device_id), obj.object_id),
                ).fetchone()
                synced_at = obj.synced_at or now
                connection.execute(
                    """
                    INSERT INTO enterprise.marginnote_objects(
                        tenant_id, owner_id, kb_id, device_id, object_id,
                        object_type, title, content, excerpt, document_id,
                        document_title, page, tags, links, color,
                        created_at, updated_at, synced_at, raw
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id, owner_id, kb_id, device_id, object_id)
                    DO UPDATE SET
                        object_type=excluded.object_type,
                        title=excluded.title,
                        content=excluded.content,
                        excerpt=excluded.excerpt,
                        document_id=excluded.document_id,
                        document_title=excluded.document_title,
                        page=excluded.page,
                        tags=excluded.tags,
                        links=excluded.links,
                        color=excluded.color,
                        created_at=excluded.created_at,
                        updated_at=excluded.updated_at,
                        synced_at=excluded.synced_at,
                        raw=excluded.raw
                    """,
                    (
                        self.tenant_id,
                        self.owner_id,
                        self.kb_id,
                        device_id,
                        str(obj.object_id),
                        str(obj.object_type),
                        str(obj.title or ""),
                        str(obj.content or ""),
                        obj.excerpt,
                        obj.document_id,
                        obj.document_title,
                        obj.page,
                        _jsonb(obj.tags),
                        _jsonb(obj.links),
                        obj.color,
                        str(obj.created_at or ""),
                        str(obj.updated_at or ""),
                        synced_at,
                        _jsonb(obj.raw),
                    ),
                )
                if previous is None:
                    stored += 1
                else:
                    updated += 1

            for object_id in batch.deleted_ids:
                object_id = _require_text(object_id, "object_id")
                connection.execute(
                    """
                    INSERT INTO enterprise.marginnote_tombstones(
                        tenant_id, owner_id, kb_id, device_id, object_id, deleted_at
                    ) VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id, owner_id, kb_id, device_id, object_id)
                    DO UPDATE SET deleted_at=excluded.deleted_at
                    """,
                    (*self._values(device_id), object_id, now),
                )
                connection.execute(
                    """
                    DELETE FROM enterprise.marginnote_objects
                     WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                       AND device_id=%s AND object_id=%s
                    """,
                    (*self._values(device_id), object_id),
                )
                deleted += 1

            connection.execute(
                """
                INSERT INTO enterprise.marginnote_cursors(
                    tenant_id, owner_id, kb_id, device_id, cursor, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, owner_id, kb_id, device_id)
                DO UPDATE SET cursor=excluded.cursor, updated_at=excluded.updated_at
                """,
                (*self._values(device_id), now, now),
            )

        self._run(write)
        return SyncResult(stored=stored, updated=updated, deleted=deleted, new_cursor=now)

    def get_cursor(self, device_id: str) -> str:
        if not device_id:
            return ""

        def read(connection):
            row = connection.execute(
                """
                SELECT cursor
                  FROM enterprise.marginnote_cursors
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s AND device_id=%s
                """,
                self._values(device_id),
            ).fetchone()
            return str(row["cursor"]) if row else ""

        return self._run(read)

    # -- read operations ------------------------------------------------

    def get(self, object_id: str, *, device_id: str = "") -> MarginNoteObject | None:
        object_id = _require_text(object_id, "object_id")

        def read(connection):
            if device_id:
                row = connection.execute(
                    """
                    SELECT * FROM enterprise.marginnote_objects
                     WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                       AND device_id=%s AND object_id=%s
                    """,
                    (*self._values(device_id), object_id),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT * FROM enterprise.marginnote_objects
                     WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s AND object_id=%s
                     ORDER BY updated_at DESC, device_id
                     LIMIT 1
                    """,
                    (*self._values(), object_id),
                ).fetchone()
            return self._row_to_object(row) if row else None

        return self._run(read)

    def search(
        self,
        query: str,
        *,
        object_type: str = "",
        device_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not query:
            return []
        needle = f"%{query.lower()}%"
        limit = max(1, min(int(limit), 1000))

        def read(connection):
            sql = """
                SELECT * FROM enterprise.marginnote_objects
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                   AND (lower(title) LIKE %s OR lower(content) LIKE %s
                    OR lower(coalesce(excerpt,'')) LIKE %s
                    OR lower(coalesce(document_title,'')) LIKE %s)
            """
            params: list[Any] = [*self._values(), needle, needle, needle, needle]
            if object_type:
                sql += " AND object_type=%s"
                params.append(object_type)
            if device_id:
                sql += " AND device_id=%s"
                params.append(device_id)
            sql += " ORDER BY updated_at DESC, object_id LIMIT %s"
            params.append(limit)
            rows = connection.execute(sql, tuple(params)).fetchall()
            return [_to_summary(self._row_to_object(row), query) for row in rows]

        return self._run(read)

    def list_objects(
        self,
        *,
        object_type: str = "",
        document_id: str = "",
        device_id: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 2000))

        def read(connection):
            sql = """
                SELECT * FROM enterprise.marginnote_objects
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
            """
            params: list[Any] = [*self._values()]
            if object_type:
                sql += " AND object_type=%s"
                params.append(object_type)
            if document_id:
                sql += " AND document_id=%s"
                params.append(document_id)
            if device_id:
                sql += " AND device_id=%s"
                params.append(device_id)
            sql += " ORDER BY coalesce(document_title, title), updated_at DESC, object_id LIMIT %s"
            params.append(limit)
            rows = connection.execute(sql, tuple(params)).fetchall()
            return [_to_summary(self._row_to_object(row), "") for row in rows]

        return self._run(read)

    def list_documents(self, *, device_id: str = "") -> list[dict[str, Any]]:
        def read(connection):
            sql = """
                SELECT document_id, document_title, count(*) AS n
                  FROM enterprise.marginnote_objects
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                   AND document_id IS NOT NULL
            """
            params: list[Any] = [*self._values()]
            if device_id:
                sql += " AND device_id=%s"
                params.append(device_id)
            sql += " GROUP BY document_id, document_title ORDER BY document_title, document_id"
            rows = connection.execute(sql, tuple(params)).fetchall()
            return [
                {
                    "document_id": row["document_id"],
                    "title": row["document_title"] or "(untitled)",
                    "count": int(row["n"]),
                }
                for row in rows
            ]

        return self._run(read)

    def linked_objects(self, object_id: str, *, device_id: str = "") -> list[dict[str, Any]]:
        obj = self.get(object_id, device_id=device_id)
        if obj is None:
            return []
        linked_ids = {str(link) for link in obj.links if str(link)}

        def read_linked_ids(connection):
            sql = """
                SELECT object_id FROM enterprise.marginnote_objects
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                   AND links @> %s
            """
            params: list[Any] = [*self._values(), _jsonb([object_id])]
            if device_id:
                sql += " AND device_id=%s"
                params.append(device_id)
            rows = connection.execute(sql, tuple(params)).fetchall()
            return {str(row["object_id"]) for row in rows}

        linked_ids |= self._run(read_linked_ids)
        results: list[dict[str, Any]] = []
        for linked_id in sorted(linked_ids):
            linked = self.get(linked_id, device_id=device_id)
            if linked is not None:
                results.append(_to_summary(linked, ""))
        return results

    def collect_tags(self, *, device_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 2000))

        def read(connection):
            sql = """
                SELECT tags FROM enterprise.marginnote_objects
                 WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
            """
            params: list[Any] = [*self._values()]
            if device_id:
                sql += " AND device_id=%s"
                params.append(device_id)
            return connection.execute(sql, tuple(params)).fetchall()

        rows = self._run(read)
        counts: dict[str, int] = {}
        for row in rows:
            tags = row["tags"] or []
            if not isinstance(tags, list):
                continue
            for tag in tags:
                text = str(tag).strip()
                if text:
                    counts[text] = counts.get(text, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [{"tag": tag, "count": count} for tag, count in ranked[:limit]]

    def count(self, *, device_id: str = "") -> int:
        def read(connection):
            if device_id:
                row = connection.execute(
                    """
                    SELECT count(*) AS n
                      FROM enterprise.marginnote_objects
                     WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s AND device_id=%s
                    """,
                    self._values(device_id),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT count(*) AS n
                      FROM enterprise.marginnote_objects
                     WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
                    """,
                    self._values(),
                ).fetchone()
            return int(row["n"])

        return self._run(read)


def _to_summary(obj: MarginNoteObject, query: str) -> dict[str, Any]:
    body = obj.content or obj.excerpt or ""
    return {
        "object_id": obj.object_id,
        "object_type": obj.object_type,
        "title": obj.title,
        "document_title": obj.document_title,
        "page": obj.page,
        "tags": obj.tags,
        "snippet": _snippet(body, query),
        "updated_at": obj.updated_at,
    }


def _snippet(body: str, query: str, width: int = 160) -> str:
    if not body:
        return ""
    if not query:
        return body[:width]
    idx = body.lower().find(query.lower())
    if idx < 0:
        return body[:width]
    start = max(0, idx - width // 3)
    return body[start : start + width]


__all__ = ["MarginNoteCursorConflict", "PostgresMarginNoteStore", "owner_id_from_device_id"]
