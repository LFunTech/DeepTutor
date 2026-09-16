"""PocketBase 离线 JSON snapshot 导入到 PostgreSQL。"""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .id_mapping import (
    MigrationIdAllocator,
    TypedReferenceRewriter,
    advance_identity_sequence,
    stable_text_id,
)
from .planner import source_check_manifest
from .stage import MigrationStageRepository

_SOURCE_VERSION = "pocketbase/v1"



def _manifest_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()



def _owner_mappings(manifest: dict[str, Any]) -> dict[str, str]:
    raw = manifest.get("owner_mappings")
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    mapping: dict[str, str] = {}
    for item in raw or []:
        if isinstance(item, dict) and item.get("source_owner_id") and item.get("target_owner_id"):
            mapping[str(item["source_owner_id"])] = str(item["target_owner_id"])
    return mapping



def _artifact_path(manifest_root: Path, value: str | None) -> Path:
    path = Path(str(value or ""))
    return path if path.is_absolute() else manifest_root / path



def _load_snapshot(manifest_path: Path, source: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    snapshot = _artifact_path(manifest_path.parent, source.get("snapshot", {}).get("path"))
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    collections = payload.get("collections") if isinstance(payload, dict) else {}
    if not isinstance(collections, dict):
        raise ValueError("PocketBase snapshot collections missing")
    rows: dict[str, list[dict[str, Any]]] = {}
    for name in ("users", "sessions", "messages", "turns", "turn_events", "knowledge_bases"):
        raw = collections.get(name)
        records = raw.get("records") if isinstance(raw, dict) else None
        rows[name] = [dict(record) for record in records] if isinstance(records, list) else []
    return rows



def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default



def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default



def _allowed_status(value: Any) -> str:
    status = str(value or "completed")
    return status if status in {"queued", "running", "waiting_input", "completed", "cancelled", "failed"} else "failed"



class PocketBaseOfflineImporter:
    """导入 1.37 `pocketbase/v1` JSON snapshot。"""

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
        await repo.enter_maintenance(batch_id, tenant_id=tenant_id, reason="pocketbase-import")
        imported = self._empty_counts()
        credential_resets: list[dict[str, str]] = []
        deduped_sources = 0
        try:
            for source in manifest.get("sources") or []:
                if source.get("source_version") != _SOURCE_VERSION:
                    continue
                source_id = str(source["source_id"])
                source_owner = str(source["source_owner_id"])
                target_owner = owners.get(source_owner)
                if not target_owner:
                    raise PermissionError("source owner has no target owner mapping")
                rows = _load_snapshot(manifest_path, source)
                row_total = sum(len(value) for value in rows.values())
                await repo.record_source(
                    batch_id,
                    source_id=source_id,
                    source_type="pocketbase",
                    source_version=_SOURCE_VERSION,
                    source_owner_id=source_owner,
                    target_owner_id=target_owner,
                    fingerprint=str(source["snapshot"]["sha256"]),
                    manifest=source,
                    rows_total=row_total,
                    rows_done=0,
                    status="importing",
                )
                async with await psycopg.AsyncConnection.connect(
                    self._dsn, row_factory=dict_row
                ) as connection:
                    async with connection.transaction():
                        await self._verify_target_owner(connection, tenant_id, target_owner)
                        if await self._source_already_verified(
                            connection, batch, source, target_owner
                        ):
                            deduped_sources += 1
                            await self._mark_source_verified(
                                connection, batch, source_id, rows_done=row_total
                            )
                            continue
                        counts, resets = await self._import_source(
                            connection,
                            batch_id=batch,
                            tenant_id=tenant_id,
                            source_id=source_id,
                            source_owner=source_owner,
                            target_owner=target_owner,
                            rows=rows,
                        )
                        for key, value in counts.items():
                            imported[key] += value
                        credential_resets.extend(resets)
                        await self._mark_source_verified(connection, batch, source_id, rows_done=row_total)
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
            "credential_resets_required": credential_resets,
        }

    @staticmethod
    def _empty_counts() -> dict[str, int]:
        return {
            "users": 0,
            "sessions": 0,
            "messages": 0,
            "turns": 0,
            "turn_events": 0,
            "knowledge_base_file_refs": 0,
        }

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

    @staticmethod
    async def _mark_source_verified(connection, batch_id: str, source_id: str, *, rows_done: int) -> None:
        await connection.execute(
            """
            UPDATE migration_stage.sources
               SET status='verified', rows_done=%s
             WHERE batch_id=%s AND source_id=%s
            """,
            (rows_done, batch_id, source_id),
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
                    _SOURCE_VERSION,
                    str(source["source_owner_id"]),
                    target_owner,
                    str(source["snapshot"]["sha256"]),
                    batch_id,
                    str(source["source_id"]),
                ),
            )
        ).fetchone()
        return row is not None

    @staticmethod
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

    async def _import_source(
        self,
        connection,
        *,
        batch_id: str,
        tenant_id: str,
        source_id: str,
        source_owner: str,
        target_owner: str,
        rows: dict[str, list[dict[str, Any]]],
    ) -> tuple[dict[str, int], list[dict[str, str]]]:
        users = {str(row.get("id") or ""): row for row in rows["users"]}
        if source_owner not in users:
            raise ValueError("PocketBase source owner user is missing from snapshot")
        sessions = self._owned_sessions(rows["sessions"], source_owner)
        maps = await self._build_maps(
            connection,
            batch_id=batch_id,
            tenant_id=tenant_id,
            source_id=source_id,
            source_owner=source_owner,
            target_owner=target_owner,
            sessions=sessions,
            messages=rows["messages"],
            turns=rows["turns"],
            knowledge_bases=rows["knowledge_bases"],
        )
        counts = self._empty_counts()
        await self._record_user_mapping(
            connection, batch_id, tenant_id, source_id, source_owner, target_owner
        )
        counts["users"] = 1
        resets = [{"source_user_id": source_owner, "target_owner_id": target_owner}]
        counts.update(
            await self._insert_rows(
                connection,
                tenant_id=tenant_id,
                owner_id=target_owner,
                sessions=sessions,
                messages=rows["messages"],
                turns=rows["turns"],
                turn_events=rows["turn_events"],
                knowledge_bases=rows["knowledge_bases"],
                maps=maps,
            )
        )
        return counts, resets

    @staticmethod
    def _owned_sessions(sessions: Iterable[dict[str, Any]], source_owner: str) -> list[dict[str, Any]]:
        owned: list[dict[str, Any]] = []
        for row in sessions:
            user_id = str(row.get("user_id") or "")
            if user_id and user_id != source_owner:
                raise PermissionError(f"PocketBase session owner {user_id!r} has no source entry")
            owned.append(row)
        return owned

    async def _build_maps(
        self,
        connection,
        *,
        batch_id: str,
        tenant_id: str,
        source_id: str,
        source_owner: str,
        target_owner: str,
        sessions: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        turns: list[dict[str, Any]],
        knowledge_bases: list[dict[str, Any]],
    ) -> dict[str, dict[Any, Any]]:
        allocator = MigrationIdAllocator(self._dsn)
        session_map: dict[Any, Any] = {}
        for session in sessions:
            source_session_id = str(session.get("session_id") or session.get("id") or "")
            mapped = await allocator.allocate_session_id(
                batch_id,
                tenant_id=tenant_id,
                source_id=source_id,
                source_owner_id=source_owner,
                source_session_id=source_session_id,
            )
            session_map[source_session_id] = mapped

        max_message = await (
            await connection.execute(
                "SELECT COALESCE(max(id),0) AS max_id FROM enterprise.messages WHERE tenant_id=%s",
                (tenant_id,),
            )
        ).fetchone()
        ordered_messages = sorted(
            messages,
            key=lambda row: (_as_float(row.get("msg_created_at")), str(row.get("id") or "")),
        )
        message_map = {
            str(row.get("id") or ""): int(max_message["max_id"]) + index + 1
            for index, row in enumerate(ordered_messages)
        }
        for old, new in message_map.items():
            await self._record_mapping(
                connection,
                batch_id,
                domain="messages",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=old,
                target_int=new,
            )

        turn_map = {
            str(row.get("turn_id") or row.get("id") or ""): stable_text_id(
                domain="turns",
                source_id=source_id,
                source_owner_id=f"{source_owner}->{target_owner}",
                source_key=str(row.get("turn_id") or row.get("id") or ""),
                prefix="turn",
            )
            for row in turns
        }
        for old, new in turn_map.items():
            await self._record_mapping(
                connection,
                batch_id,
                domain="turns",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=old,
                target_key=new,
            )

        resource_map: dict[Any, Any] = {}
        for message in messages:
            attachments = message.get("attachments_json")
            if not isinstance(attachments, list):
                continue
            for attachment in attachments:
                if not isinstance(attachment, dict) or not attachment.get("id"):
                    continue
                old = str(attachment["id"])
                resource_map.setdefault(
                    old,
                    stable_text_id(
                        domain="resources",
                        source_id=source_id,
                        source_owner_id=source_owner,
                        source_key=old,
                        prefix="res",
                    ),
                )
        for old, new in resource_map.items():
            await self._record_mapping(
                connection,
                batch_id,
                domain="resources",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=old,
                target_key=new,
            )

        file_map: dict[Any, Any] = {}
        for kb in knowledge_bases:
            kb_name = str(kb.get("kb_name") or kb.get("id") or "")
            raw_files = kb.get("raw_files") if isinstance(kb.get("raw_files"), list) else []
            for filename in raw_files:
                old = str(filename or "")
                if not old:
                    continue
                target = f"{kb_name}/raw_files/{old}"
                file_map[old] = target
                await self._record_mapping(
                    connection,
                    batch_id,
                    domain="knowledge_base_file_refs",
                    source_id=source_id,
                    source_owner_id=source_owner,
                    source_key=target,
                    target_key=target,
                    metadata={"kb_name": kb_name, "field": "raw_files", "filename": old},
                )

        return {
            "pocketbase.users.id": {source_owner: target_owner},
            "pocketbase.messages.id": message_map,
            "sessions.session_id": session_map,
            "messages.id": message_map,
            "turns.id": turn_map,
            "turns.turn_id": turn_map,
            "resources.attachment_id": resource_map,
            "knowledge_base_files.filename": file_map,
        }

    @staticmethod
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

    async def _record_user_mapping(
        self,
        connection,
        batch_id: str,
        tenant_id: str,
        source_id: str,
        source_owner: str,
        target_owner: str,
    ) -> None:
        await self._record_mapping(
            connection,
            batch_id,
            domain="pocketbase_users",
            source_id=source_id,
            source_owner_id=source_owner,
            source_key=source_owner,
            target_key=target_owner,
            metadata={"credential_reset_required": True, "old_credentials_imported": False},
        )
        await connection.execute(
            """
            UPDATE enterprise.users
               SET auth_version=auth_version+1
             WHERE tenant_id=%s AND id=%s
            """,
            (tenant_id, target_owner),
        )

    async def _insert_rows(
        self,
        connection,
        *,
        tenant_id: str,
        owner_id: str,
        sessions: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        turns: list[dict[str, Any]],
        turn_events: list[dict[str, Any]],
        knowledge_bases: list[dict[str, Any]],
        maps: dict[str, dict[Any, Any]],
    ) -> dict[str, int]:
        rewriter = TypedReferenceRewriter(_SOURCE_VERSION)
        for row in sessions:
            source_session_id = str(row.get("session_id") or row.get("id") or "")
            summary_up_to = row.get("summary_up_to_msg_id")
            if summary_up_to not in (None, "", 0) and str(summary_up_to) in maps["messages.id"]:
                summary_up_to = maps["messages.id"][str(summary_up_to)]
            else:
                summary_up_to = None
            await connection.execute(
                """
                INSERT INTO enterprise.sessions(
                    tenant_id, owner_id, id, title, summary,
                    summary_up_to_msg_id, preferences, created_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                """,
                (
                    tenant_id,
                    owner_id,
                    maps["sessions.session_id"][source_session_id],
                    str(row.get("title") or "New conversation")[:100],
                    row.get("compressed_summary") or "",
                    summary_up_to,
                    Jsonb(row.get("preferences_json") or {}),
                    _as_float(row.get("session_created_at")),
                    _as_float(row.get("session_updated_at")),
                ),
            )

        messages_by_source = {str(row.get("id") or ""): row for row in messages}
        for row in messages:
            rewritten = rewriter.rewrite("messages", dict(row), maps).record
            await connection.execute(
                """
                INSERT INTO enterprise.messages(
                    tenant_id, owner_id, session_id, id, role, content,
                    capability, events, attachments, metadata,
                    parent_message_id, created_at
                ) OVERRIDING SYSTEM VALUE
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s)
                """,
                (
                    tenant_id,
                    owner_id,
                    rewritten["session_id"],
                    rewritten["id"],
                    row.get("role") or "user",
                    row.get("content") or "",
                    row.get("capability") or "",
                    Jsonb(rewritten.get("events_json") or []),
                    Jsonb(rewritten.get("attachments_json") or []),
                    Jsonb(rewritten.get("metadata_json") or {}),
                    None,
                    _as_float(row.get("msg_created_at")),
                ),
            )

        for row in turns:
            rewritten = rewriter.rewrite("turns", dict(row), maps).record
            source_assistant = str(row.get("assistant_message_id") or "")
            user_message_id = self._derive_user_message_id(source_assistant, messages_by_source, maps)
            await connection.execute(
                """
                INSERT INTO enterprise.turns(
                    tenant_id, user_id, session_id, id, capability, status,
                    owner_id, fencing_token, error, failure_code, retryable,
                    assistant_message_id, user_message_id, next_seq,
                    state_version, finished_at, created_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    tenant_id,
                    owner_id,
                    rewritten["session_id"],
                    rewritten["turn_id"],
                    row.get("capability") or "",
                    _allowed_status(row.get("status")),
                    row.get("owner_id") or "",
                    _as_int(row.get("fencing_token")),
                    row.get("error") or "",
                    row.get("failure_code") or "",
                    bool(row.get("retryable") or False),
                    rewritten.get("assistant_message_id"),
                    user_message_id,
                    0,
                    max(1, _as_int(row.get("state_version"), 1)),
                    _as_float(row.get("finished_at")) or None,
                    _as_float(row.get("turn_created_at")),
                    _as_float(row.get("turn_updated_at")),
                ),
            )

        for row in turn_events:
            rewritten = rewriter.rewrite("turn_events", dict(row), maps).record
            event = {
                "type": row.get("type") or "",
                "source": row.get("source") or "",
                "stage": row.get("stage") or "",
                "content": row.get("content") or "",
                "metadata": rewritten.get("metadata_json") or {},
                "timestamp": row.get("event_timestamp"),
            }
            await connection.execute(
                """
                INSERT INTO enterprise.turn_events(
                    tenant_id, owner_id, session_id, turn_id, seq, event
                ) VALUES (%s,%s,%s,%s,%s,%s::jsonb)
                """,
                (
                    tenant_id,
                    owner_id,
                    maps["sessions.session_id"].get(str(row.get("session_id") or "")),
                    rewritten["turn_id"],
                    _as_int(row.get("seq")),
                    Jsonb(event),
                ),
            )

        await advance_identity_sequence(connection, "enterprise.messages", "id")
        return {
            "sessions": len(sessions),
            "messages": len(messages),
            "turns": len(turns),
            "turn_events": len(turn_events),
            "knowledge_base_file_refs": sum(
                len(row.get("raw_files") or [])
                for row in knowledge_bases
                if isinstance(row.get("raw_files"), list)
            ),
        }

    @staticmethod
    def _derive_user_message_id(
        source_assistant: str,
        messages_by_source: dict[str, dict[str, Any]],
        maps: dict[str, dict[Any, Any]],
    ) -> int | None:
        assistant = messages_by_source.get(source_assistant)
        if assistant is None:
            return None
        session_id = str(assistant.get("session_id") or "")
        created_at = _as_float(assistant.get("msg_created_at"))
        candidates = [
            row
            for row in messages_by_source.values()
            if str(row.get("session_id") or "") == session_id
            and str(row.get("role") or "") == "user"
            and _as_float(row.get("msg_created_at")) <= created_at
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda row: (_as_float(row.get("msg_created_at")), str(row.get("id") or "")))
        return maps["messages.id"].get(str(candidates[-1].get("id") or ""))


__all__ = ["PocketBaseOfflineImporter"]
