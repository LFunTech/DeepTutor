"""SQLite chat_history 快照导入到 PG 会话/题库域。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from urllib.request import pathname2url

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .id_mapping import (
    SourceMessage,
    TypedReferenceRewriter,
    advance_identity_sequence,
    allocate_message_dag_ids,
    stable_text_id,
)
from .planner import source_check_manifest
from .stage import MigrationStageRepository


def _sqlite_uri(path: Path) -> str:
    return f"file:{pathname2url(str(path))}?mode=ro&immutable=1"


def _manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
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


def _read_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    with sqlite3.connect(_sqlite_uri(snapshot), uri=True) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        def read(table: str, order: str) -> list[dict[str, Any]]:
            if table not in tables:
                return []
            return [dict(row) for row in connection.execute(f"SELECT * FROM {table} {order}")]

        return {
            "sessions": read("sessions", "ORDER BY created_at, id"),
            "messages": read("messages", "ORDER BY id"),
            "turns": read("turns", "ORDER BY created_at, id"),
            "turn_events": read("turn_events", "ORDER BY turn_id, seq"),
            "notebook_entries": read("notebook_entries", "ORDER BY id"),
            "notebook_categories": read("notebook_categories", "ORDER BY id"),
            "notebook_entry_categories": read(
                "notebook_entry_categories", "ORDER BY entry_id, category_id"
            ),
        }


class SQLiteChatHistoryImporter:
    """导入 1.30 manifest 中的 `chat_history_sqlite/v1` 源。"""

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
        await repo.enter_maintenance(batch_id, tenant_id=tenant_id, reason="sqlite-chat-import")
        imported = {"sessions": 0, "messages": 0, "turns": 0, "turn_events": 0,
                    "notebook_entries": 0, "notebook_categories": 0}
        for source in manifest.get("sources") or []:
            if source.get("source_version") != "chat_history_sqlite/v1":
                continue
            target_owner = owners.get(str(source.get("source_owner_id") or ""))
            if not target_owner:
                raise PermissionError("source owner has no target owner mapping")
            snapshot = Path(source["snapshot"]["path"])
            rows = _read_rows(snapshot)
            row_total = sum(len(value) for value in rows.values())
            await repo.record_source(
                batch_id,
                source_id=str(source["source_id"]),
                source_type="sqlite",
                source_version="chat_history_sqlite/v1",
                source_owner_id=str(source["source_owner_id"]),
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
                    maps = await self._build_maps(
                        connection,
                        repo,
                        batch_id,
                        tenant_id,
                        target_owner,
                        str(source["source_id"]),
                        str(source["source_owner_id"]),
                        rows,
                    )
                    counts = await self._insert_rows(
                        connection,
                        tenant_id,
                        target_owner,
                        rows,
                        maps,
                    )
                    for key, value in counts.items():
                        imported[key] += value
                    await connection.execute(
                        """
                        UPDATE migration_stage.sources
                           SET status='verified', rows_done=%s
                         WHERE batch_id=%s AND source_id=%s
                        """,
                        (row_total, str(batch_id), str(source["source_id"])),
                    )
                    await connection.execute(
                        """
                        UPDATE migration_stage.batches
                           SET status='published', updated_at=now()
                         WHERE batch_id=%s
                        """,
                        (str(batch_id),),
                    )
        return {"batch_id": str(batch_id), "imported": imported}

    async def _verify_target_owner(self, connection, tenant_id: str, owner_id: str) -> None:
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

    async def _build_maps(
        self,
        connection,
        repo: MigrationStageRepository,
        batch_id,
        tenant_id: str,
        target_owner: str,
        source_id: str,
        source_owner: str,
        rows: dict[str, list[dict[str, Any]]],
    ) -> dict[str, dict[Any, Any]]:
        allocator = _SessionAllocator(self._dsn)
        session_map: dict[Any, Any] = {}
        for session in rows["sessions"]:
            mapped = await allocator.allocate_session_id(
                batch_id,
                tenant_id=tenant_id,
                source_id=source_id,
                source_owner_id=source_owner,
                source_session_id=str(session["id"]),
            )
            session_map[session["id"]] = mapped

        max_message = await (
            await connection.execute(
                "SELECT COALESCE(max(id),0) AS max_id FROM enterprise.messages WHERE tenant_id=%s",
                (tenant_id,),
            )
        ).fetchone()
        message_map = allocate_message_dag_ids(
            [
                SourceMessage(
                    source_id=int(row["id"]),
                    parent_id=(int(row["parent_message_id"]) if row.get("parent_message_id") else None),
                    created_at=float(row["created_at"]),
                )
                for row in rows["messages"]
            ],
            start_after=int(max_message["max_id"]),
        )
        for old, new in message_map.items():
            await repo.record_mapping(
                batch_id,
                domain="messages",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=str(old),
                target_int=new,
            )

        turn_map = {
            row["id"]: stable_text_id(
                domain="turns",
                source_id=source_id,
                source_owner_id=f"{source_owner}->{target_owner}",
                source_key=str(row["id"]),
                prefix="turn",
            )
            for row in rows["turns"]
        }
        for old, new in turn_map.items():
            await repo.record_mapping(
                batch_id,
                domain="turns",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=str(old),
                target_key=new,
            )

        entry_start = await self._max_id(connection, "enterprise.notebook_entries", tenant_id, target_owner)
        category_start = await self._max_id(
            connection, "enterprise.notebook_categories", tenant_id, target_owner
        )
        entry_map = {
            int(row["id"]): entry_start + index + 1
            for index, row in enumerate(sorted(rows["notebook_entries"], key=lambda item: item["id"]))
        }
        category_map = {
            int(row["id"]): category_start + index + 1
            for index, row in enumerate(sorted(rows["notebook_categories"], key=lambda item: item["id"]))
        }
        for old, new in entry_map.items():
            await repo.record_mapping(
                batch_id,
                domain="notebook_entries",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=str(old),
                target_int=new,
            )
        for old, new in category_map.items():
            await repo.record_mapping(
                batch_id,
                domain="notebook_categories",
                source_id=source_id,
                source_owner_id=source_owner,
                source_key=str(old),
                target_int=new,
            )
        return {
            "sessions.id": session_map,
            "messages.id": message_map,
            "turns.id": turn_map,
            "resources.attachment_id": {},
            "notebook_entries.id": entry_map,
            "notebook_categories.id": category_map,
        }

    async def _max_id(self, connection, table: str, tenant_id: str, owner_id: str) -> int:
        row = await (
            await connection.execute(
                f"SELECT COALESCE(max(id),0) AS max_id FROM {table} "
                "WHERE tenant_id=%s AND owner_id=%s",
                (tenant_id, owner_id),
                prepare=False,
            )
        ).fetchone()
        return int(row["max_id"])

    async def _insert_rows(
        self,
        connection,
        tenant_id: str,
        owner_id: str,
        rows: dict[str, list[dict[str, Any]]],
        maps: dict[str, dict[Any, Any]],
    ) -> dict[str, int]:
        rewriter = TypedReferenceRewriter("chat_history_sqlite/v1")
        session_rows = []
        for row in rows["sessions"]:
            payload = {
                "id": row["id"],
                "summary_up_to_msg_id": row["summary_up_to_msg_id"],
                "preferences_json": _json(row.get("preferences_json"), {}),
            }
            rewritten = rewriter.rewrite("sessions", payload, maps).record
            session_rows.append((row, rewritten))
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
                    maps["sessions.id"][row["id"]],
                    row["title"],
                    row.get("compressed_summary") or "",
                    rewritten.get("summary_up_to_msg_id") or None,
                    Jsonb(rewritten.get("preferences_json") or {}),
                    float(row["created_at"]),
                    float(row["updated_at"]),
                ),
            )
        for row in rows["messages"]:
            payload = {
                **row,
                "events_json": _json(row.get("events_json"), []),
                "attachments_json": _json(row.get("attachments_json"), []),
                "metadata_json": _json(row.get("metadata_json"), {}),
            }
            rewritten = rewriter.rewrite("messages", payload, maps).record
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
                    maps["messages.id"][int(row["id"])],
                    row["role"],
                    row["content"],
                    row.get("capability") or "",
                    Jsonb(rewritten.get("events_json") or []),
                    Jsonb(rewritten.get("attachments_json") or []),
                    Jsonb(rewritten.get("metadata_json") or {}),
                    rewritten.get("parent_message_id"),
                    float(row["created_at"]),
                ),
            )
        source_parent_by_message = {
            int(row["id"]): (
                int(row["parent_message_id"]) if row.get("parent_message_id") else None
            )
            for row in rows["messages"]
        }
        for row in rows["turns"]:
            assistant_source = row.get("assistant_message_id")
            user_source = row.get("user_message_id")
            if not user_source and assistant_source:
                user_source = source_parent_by_message.get(int(assistant_source))
            payload = {
                "id": row["id"],
                "session_id": row["session_id"],
                "assistant_message_id": assistant_source,
                "user_message_id": user_source,
            }
            rewritten = rewriter.rewrite("turns", payload, maps).record
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
                    maps["turns.id"][row["id"]],
                    row.get("capability") or "",
                    row.get("status") or "completed",
                    row.get("owner_id") or "",
                    int(row.get("fencing_token") or 0),
                    row.get("error") or "",
                    row.get("failure_code") or "",
                    bool(row.get("retryable") or 0),
                    rewritten.get("assistant_message_id"),
                    rewritten.get("user_message_id"),
                    0,
                    int(row.get("state_version") or 1),
                    row.get("finished_at"),
                    float(row["created_at"]),
                    float(row["updated_at"]),
                ),
            )
        for row in rows["turn_events"]:
            metadata = _json(row.get("metadata_json"), {})
            rewritten = rewriter.rewrite(
                "turn_events",
                {"turn_id": row["turn_id"], "metadata_json": metadata},
                maps,
            ).record
            event = {
                "type": row.get("type") or "",
                "source": row.get("source") or "",
                "stage": row.get("stage") or "",
                "content": row.get("content") or "",
                "metadata": rewritten.get("metadata_json") or {},
                "timestamp": row.get("timestamp"),
                "created_at": row.get("created_at"),
            }
            session_id = await self._turn_session(connection, tenant_id, owner_id, rewritten["turn_id"])
            await connection.execute(
                """
                INSERT INTO enterprise.turn_events(
                    tenant_id, owner_id, session_id, turn_id, seq, event
                ) VALUES (%s,%s,%s,%s,%s,%s::jsonb)
                """,
                (
                    tenant_id,
                    owner_id,
                    session_id,
                    rewritten["turn_id"],
                    int(row["seq"]),
                    Jsonb(event),
                ),
            )
        for row in rows["notebook_categories"]:
            await connection.execute(
                """
                INSERT INTO enterprise.notebook_categories(
                    tenant_id, owner_id, id, name, created_at
                ) VALUES (%s,%s,%s,%s,%s)
                """,
                (
                    tenant_id,
                    owner_id,
                    maps["notebook_categories.id"][int(row["id"])],
                    row["name"],
                    float(row["created_at"]),
                ),
            )
        for row in rows["notebook_entries"]:
            payload = {
                **row,
                "session_id": row["session_id"],
                "turn_id": row.get("turn_id") or "",
                "followup_session_id": row.get("followup_session_id") or "",
                "user_answer_images_json": _json(row.get("user_answer_images_json"), []),
            }
            rewritten = rewriter.rewrite("notebook_entries", payload, maps).record
            await connection.execute(
                """
                INSERT INTO enterprise.notebook_entries(
                    tenant_id, owner_id, id, session_id, turn_id, question_id,
                    question, question_type, options, correct_answer, explanation,
                    difficulty, user_answer, user_answer_images, source,
                    material_id, material_title, section_id, section_title,
                    score_trend, is_correct, resolved, bookmarked,
                    followup_session_id, ai_judgment, created_at, updated_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s::jsonb,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                """,
                (
                    tenant_id,
                    owner_id,
                    maps["notebook_entries.id"][int(row["id"])],
                    rewritten["session_id"],
                    rewritten.get("turn_id") or "",
                    row["question_id"],
                    row["question"],
                    row.get("question_type") or "",
                    Jsonb(_json(row.get("options_json"), {})),
                    row.get("correct_answer") or "",
                    row.get("explanation") or "",
                    row.get("difficulty") or "",
                    row.get("user_answer") or "",
                    Jsonb(rewritten.get("user_answer_images_json") or []),
                    row.get("source") or "deep_question",
                    row.get("material_id") or "",
                    row.get("material_title") or "",
                    row.get("section_id") or "",
                    row.get("section_title") or "",
                    row.get("score_trend") or "new",
                    bool(row.get("is_correct") or 0),
                    bool(row.get("resolved") or 0),
                    bool(row.get("bookmarked") or 0),
                    rewritten.get("followup_session_id") or "",
                    row.get("ai_judgment") or "",
                    float(row["created_at"]),
                    float(row["updated_at"]),
                ),
            )
        for row in rows["notebook_entry_categories"]:
            await connection.execute(
                """
                INSERT INTO enterprise.notebook_entry_categories(
                    tenant_id, owner_id, entry_id, category_id
                ) VALUES (%s,%s,%s,%s)
                """,
                (
                    tenant_id,
                    owner_id,
                    maps["notebook_entries.id"][int(row["entry_id"])],
                    maps["notebook_categories.id"][int(row["category_id"])],
                ),
            )
        await advance_identity_sequence(connection, "enterprise.messages", "id")
        await advance_identity_sequence(connection, "enterprise.notebook_entries", "id")
        await advance_identity_sequence(connection, "enterprise.notebook_categories", "id")
        return {
            "sessions": len(session_rows),
            "messages": len(rows["messages"]),
            "turns": len(rows["turns"]),
            "turn_events": len(rows["turn_events"]),
            "notebook_entries": len(rows["notebook_entries"]),
            "notebook_categories": len(rows["notebook_categories"]),
        }

    async def _turn_session(self, connection, tenant_id: str, owner_id: str, turn_id: str) -> str:
        row = await (
            await connection.execute(
                """
                SELECT session_id FROM enterprise.turns
                 WHERE tenant_id=%s AND user_id=%s AND id=%s
                """,
                (tenant_id, owner_id, turn_id),
            )
        ).fetchone()
        if row is None:
            raise ValueError(f"missing mapped turn {turn_id}")
        return str(row["session_id"])


class _SessionAllocator:
    def __init__(self, dsn: str) -> None:
        from .id_mapping import MigrationIdAllocator

        self._inner = MigrationIdAllocator(dsn)

    async def allocate_session_id(self, *args, **kwargs):
        return await self._inner.allocate_session_id(*args, **kwargs)


__all__ = ["SQLiteChatHistoryImporter"]
