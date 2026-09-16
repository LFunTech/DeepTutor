"""PostgreSQL 题库条目、分类与稳定分页 Store mixin。"""

from __future__ import annotations

from collections.abc import Sequence
import json
import time
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from deeptutor.services.session.question_bank import (
    QuestionBankQuery,
    QuestionBankReferenceConflict,
    QuestionBankVersionConflict,
)

from .notebook_categories import PostgresNotebookCategoryMixin
from .notebook_query import decode_cursor, encode_cursor, question_bank_filters
from .notebook_upsert import (
    UPSERT_SQL,
    mastery_reference_query,
    prepare_upsert,
    reading_reference_query,
    require_mastery_reference,
    require_reading_reference,
)


def _json(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda item: json.dumps(item, ensure_ascii=False, allow_nan=False))


class PostgresNotebookMixin(PostgresNotebookCategoryMixin):
    """依赖宿主的 ``db``、``scope`` 与 ``_owner``，不建立第二数据源。"""

    @staticmethod
    def _serialize_notebook_entry(row: dict[str, Any]) -> dict[str, Any]:
        images = row.get("user_answer_images")
        return {
            "id": int(row["id"]),
            "session_id": row["session_id"],
            "session_title": row.get("session_title") or "",
            "turn_id": row.get("turn_id") or "",
            "question_id": row.get("question_id") or "",
            "question": row["question"],
            "question_type": row.get("question_type") or "",
            "options": row.get("options") if isinstance(row.get("options"), dict) else {},
            "correct_answer": row.get("correct_answer") or "",
            "explanation": row.get("explanation") or "",
            "difficulty": row.get("difficulty") or "",
            "user_answer": row.get("user_answer") or "",
            "user_answer_images": (
                [item for item in images if isinstance(item, dict)]
                if isinstance(images, list)
                else []
            ),
            "is_correct": bool(row.get("is_correct")),
            "source": row.get("source") or "deep_question",
            "material_id": row.get("material_id") or "",
            "material_title": row.get("material_title") or "",
            "section_id": row.get("section_id") or "",
            "section_title": row.get("section_title") or "",
            "score_trend": row.get("score_trend") or "new",
            "resolved": bool(row.get("resolved")),
            "bookmarked": bool(row.get("bookmarked")),
            "followup_session_id": row.get("followup_session_id") or "",
            "ai_judgment": row.get("ai_judgment") or "",
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "version": int(row["version"]),
        }

    async def _lock_notebook_export_scope(self, connection) -> None:
        """串行化同一拥有者的 Store 写入与首屏导出快照建立。"""
        key = json.dumps(
            ["deeptutor-notebook-export", *self._owner],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (key,),
        )

    async def upsert_notebook_entries(self, session_id: str, items: list[dict[str, Any]]) -> int:
        if not items:
            return 0
        try:
            async with self.db.transaction(self.scope) as connection:
                await self._lock_notebook_export_scope(connection)
                now = time.time()
                session = await (
                    await connection.execute(
                        "SELECT id,deleting FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s AND id=%s FOR UPDATE",
                        (*self._owner, session_id),
                    )
                ).fetchone()
                if session is None:
                    raise ValueError(f"Session not found: {session_id}")
                if session["deleting"]:
                    raise ValueError(f"Session is deleting: {session_id}")
                processed = 0
                for item in items:
                    prepared = prepare_upsert(self._owner, session_id, item, now)
                    if prepared is None:
                        continue
                    source, params = prepared
                    if item.get("followup_session_id"):
                        await self._check_followup_session(connection, item["followup_session_id"])
                    if source == "mastery_path":
                        row = await (
                            await connection.execute(
                                *mastery_reference_query(self._owner, session_id, item)
                            )
                        ).fetchone()
                        require_mastery_reference(row)
                    if source == "immersive_reading":
                        row = await (
                            await connection.execute(*reading_reference_query(self._owner, item))
                        ).fetchone()
                        require_reading_reference(row)
                    await connection.execute(UPSERT_SQL, params)
                    processed += 1
                return processed
        except psycopg.errors.ForeignKeyViolation as exc:
            raise ValueError("question-bank reference does not exist in this scope") from exc

    async def _load_categories_for(
        self, connection, entry_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        if not entry_ids:
            return {}
        rows = await (
            await connection.execute(
                """
                SELECT ec.entry_id,c.id,c.name
                FROM enterprise.notebook_entry_categories ec
                JOIN enterprise.notebook_categories c
                  ON c.tenant_id=ec.tenant_id AND c.owner_id=ec.owner_id
                 AND c.id=ec.category_id
                WHERE ec.tenant_id=%s AND ec.owner_id=%s AND ec.entry_id=ANY(%s)
                ORDER BY c.name COLLATE "C",c.id
                """,
                (*self._owner, entry_ids),
            )
        ).fetchall()
        result: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(int(row["entry_id"]), []).append(
                {"id": int(row["id"]), "name": row["name"]}
            )
        return result

    async def list_notebook_entries(
        self,
        category_id: int | None = None,
        bookmarked: bool | None = None,
        is_correct: bool | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        session_id: str | None = None,
        session_ids: Sequence[str] | None = None,
        source: str = "",
        material_id: str = "",
        section_id: str = "",
        resolved: bool | None = None,
        score_trend: str = "",
        search: str = "",
        uncategorized: bool = False,
        sort: str = "recent",
        cursor: str | None = None,
    ) -> dict[str, Any]:
        query = QuestionBankQuery(
            category_id=category_id,
            uncategorized=uncategorized,
            bookmarked=bookmarked,
            is_correct=is_correct,
            source=source,
            material_id=material_id,
            section_id=section_id,
            resolved=resolved,
            score_trend=score_trend,
            search=search,
            session_id=session_id,
            session_ids=session_ids,
            sort=sort,
            limit=limit,
            offset=offset,
            cursor=cursor,
        ).normalized()
        joins, filters, params = question_bank_filters(query)
        scope_params = [*self._owner, *params]
        base_where = " WHERE n.tenant_id=%s AND n.owner_id=%s" + filters
        order = "ASC" if query.sort == "oldest" else "DESC"
        cursor_mode = query.cursor is not None
        async with self.db.transaction(self.scope) as connection:
            boundary: tuple[float, int] | None = None
            after: tuple[float, int] | None = None
            fence_id: int | None = None
            if cursor_mode and query.cursor:
                boundary_created, boundary_id, after_created, after_id, fence_id = decode_cursor(
                    query
                )
                boundary = (boundary_created, boundary_id)
                after = (after_created, after_id)
            elif cursor_mode:
                await self._lock_notebook_export_scope(connection)
                row = await (
                    await connection.execute(
                        "SELECT n.created_at,n.id,max(n.id) OVER () AS fence_id"
                        " FROM enterprise.notebook_entries n"
                        + joins
                        + base_where
                        + " ORDER BY n.created_at DESC,n.id DESC LIMIT 1",
                        scope_params,
                    )
                ).fetchone()
                if row is not None:
                    boundary = (float(row["created_at"]), int(row["id"]))
                    fence_id = int(row["fence_id"])

            bounded_where = base_where
            bounded_params = list(scope_params)
            if fence_id is not None:
                bounded_where += " AND n.id<=%s"
                bounded_params.append(fence_id)
            if boundary is not None:
                bounded_where += " AND (n.created_at,n.id)<= (%s,%s)"
                bounded_params.extend(boundary)
            count_row = await (
                await connection.execute(
                    "SELECT count(*) AS total FROM enterprise.notebook_entries n"
                    + joins
                    + bounded_where,
                    bounded_params,
                )
            ).fetchone()
            total = int(count_row["total"]) if count_row else 0

            page_where = bounded_where
            page_params = list(bounded_params)
            if after is not None:
                comparison = ">" if query.sort == "oldest" else "<"
                page_where += f" AND (n.created_at,n.id){comparison}(%s,%s)"
                page_params.extend(after)
            fetch_limit = query.limit + 1 if cursor_mode else query.limit
            rows = await (
                await connection.execute(
                    """
                    SELECT n.*,coalesce(s.title,'') AS session_title
                    FROM enterprise.notebook_entries n
                    LEFT JOIN enterprise.sessions s
                      ON s.tenant_id=n.tenant_id AND s.owner_id=n.owner_id AND s.id=n.session_id
                    """
                    + joins
                    + page_where
                    + f" ORDER BY n.created_at {order},n.id {order} LIMIT %s OFFSET %s",
                    (*page_params, fetch_limit, 0 if cursor_mode else query.offset),
                )
            ).fetchall()
            has_more = cursor_mode and len(rows) > query.limit
            visible_rows = rows[: query.limit]
            items = [self._serialize_notebook_entry(row) for row in visible_rows]
            grouped = await self._load_categories_for(
                connection, [int(item["id"]) for item in items]
            )
            for item in items:
                item["categories"] = grouped.get(int(item["id"]), [])
            result: dict[str, Any] = {"items": items, "total": total}
            if cursor_mode:
                next_cursor = None
                if has_more and boundary is not None and visible_rows:
                    last = visible_rows[-1]
                    next_cursor = encode_cursor(
                        query,
                        boundary_created_at=boundary[0],
                        boundary_id=boundary[1],
                        after_created_at=float(last["created_at"]),
                        after_id=int(last["id"]),
                        fence_id=fence_id,
                    )
                result["next_cursor"] = next_cursor
            return result

    async def has_question_bank_entries(self) -> bool:
        async with self.db.transaction(self.scope) as connection:
            row = await (
                await connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM enterprise.notebook_entries"
                    " WHERE tenant_id=%s AND owner_id=%s) AS present",
                    self._owner,
                )
            ).fetchone()
            return bool(row and row["present"])

    @staticmethod
    def _session_scope_clause(session_ids: Sequence[str] | None) -> tuple[str, list[Any]]:
        if session_ids is None:
            return "", []
        return " AND n.session_id=ANY(%s)", [list(session_ids)]

    async def question_bank_stats(self, session_ids: Sequence[str] | None = None) -> dict[str, int]:
        session_filter, params = self._session_scope_clause(session_ids)
        async with self.db.transaction(self.scope) as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT count(*) AS total,
                      count(*) FILTER (WHERE NOT n.is_correct) AS wrong,
                      count(*) FILTER (WHERE NOT n.is_correct AND NOT n.resolved) AS unresolved,
                      count(*) FILTER (WHERE n.bookmarked) AS bookmarked,
                      count(*) FILTER (WHERE NOT EXISTS(
                        SELECT 1 FROM enterprise.notebook_entry_categories ec
                        WHERE ec.tenant_id=n.tenant_id AND ec.owner_id=n.owner_id
                          AND ec.entry_id=n.id)) AS uncategorized
                    FROM enterprise.notebook_entries n
                    WHERE n.tenant_id=%s AND n.owner_id=%s
                    """
                    + session_filter,
                    (*self._owner, *params),
                )
            ).fetchone()
        return {
            key: int(row[key] if row else 0)
            for key in ("total", "wrong", "unresolved", "bookmarked", "uncategorized")
        }

    async def list_question_bank_materials(
        self, session_ids: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        session_filter, params = self._session_scope_clause(session_ids)
        async with self.db.transaction(self.scope) as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT n.source,n.material_id,
                      coalesce(nullif(max(n.material_title),''),n.material_id,'Unnamed material')
                        AS material_title,
                      count(*) AS entry_count,
                      count(*) FILTER (WHERE NOT n.is_correct AND NOT n.resolved)
                        AS unresolved_count
                    FROM enterprise.notebook_entries n
                    WHERE n.tenant_id=%s AND n.owner_id=%s AND n.material_id<>''
                    """
                    + session_filter
                    + " GROUP BY n.source,n.material_id"
                    + " ORDER BY translate(coalesce(nullif(max(n.material_title),''),n.material_id),"
                    + " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') COLLATE \"C\","
                    + " n.source,n.material_id",
                    (*self._owner, *params),
                )
            ).fetchall()
        return [
            {
                "source": row["source"],
                "material_id": row["material_id"],
                "material_title": row["material_title"],
                "entry_count": int(row["entry_count"]),
                "unresolved_count": int(row["unresolved_count"]),
            }
            for row in rows
        ]

    async def _entry_with_categories(self, connection, where: str, params: Sequence[Any]):
        row = await (
            await connection.execute(
                """
                SELECT n.*,coalesce(s.title,'') AS session_title
                FROM enterprise.notebook_entries n
                LEFT JOIN enterprise.sessions s
                  ON s.tenant_id=n.tenant_id AND s.owner_id=n.owner_id AND s.id=n.session_id
                WHERE n.tenant_id=%s AND n.owner_id=%s AND
                """
                + where,
                (*self._owner, *params),
            )
        ).fetchone()
        if row is None:
            return None
        entry = self._serialize_notebook_entry(row)
        entry["categories"] = (await self._load_categories_for(connection, [entry["id"]])).get(
            entry["id"], []
        )
        return entry

    async def get_notebook_entry(self, entry_id: int) -> dict[str, Any] | None:
        async with self.db.transaction(self.scope) as connection:
            return await self._entry_with_categories(connection, "n.id=%s", (entry_id,))

    async def find_notebook_entry(
        self, session_id: str, question_id: str, turn_id: str | None = None
    ) -> dict[str, Any] | None:
        async with self.db.transaction(self.scope) as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT n.*,coalesce(s.title,'') AS session_title
                    FROM enterprise.notebook_entries n
                    LEFT JOIN enterprise.sessions s
                      ON s.tenant_id=n.tenant_id AND s.owner_id=n.owner_id AND s.id=n.session_id
                    WHERE n.tenant_id=%s AND n.owner_id=%s AND n.session_id=%s
                      AND n.turn_id=%s AND n.question_id=%s
                    """,
                    (*self._owner, session_id, turn_id if turn_id is not None else "", question_id),
                )
            ).fetchone()
            return self._serialize_notebook_entry(row) if row else None

    @staticmethod
    def _expected_version(expected_version: int | None) -> int | None:
        if expected_version is None:
            return None
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected_version must be a positive integer")
        return expected_version

    async def _raise_version_conflict(
        self, connection, table: str, entity: str, entity_id: int, expected: int
    ) -> bool:
        row = await (
            await connection.execute(
                f"SELECT version FROM enterprise.{table}"
                " WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (*self._owner, entity_id),
            )
        ).fetchone()
        if row is None:
            return False
        raise QuestionBankVersionConflict(entity, entity_id, expected, int(row["version"]))

    async def _check_followup_session(self, c, session_id):
        row = await (
            await c.execute(
                "SELECT deleting FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s AND id=%s FOR UPDATE",
                (*self._owner, session_id),
            )
        ).fetchone()
        if row is None or row["deleting"]:
            raise ValueError("follow-up session unavailable")

    async def update_notebook_entry(
        self,
        entry_id: int,
        updates: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> bool:
        expected_version = self._expected_version(expected_version)
        allowed = {
            "bookmarked",
            "followup_session_id",
            "user_answer",
            "is_correct",
            "ai_judgment",
            "resolved",
        }
        fields = {key: value for key, value in updates.items() if key in allowed}
        if not fields:
            return False
        for key in ("bookmarked", "is_correct", "resolved"):
            if key in fields:
                fields[key] = bool(fields[key])
        for key in ("followup_session_id", "user_answer", "ai_judgment"):
            if key in fields:
                fields[key] = str(fields[key] or "")
        assignments = ",".join(f"{key}=%s" for key in fields)
        where_version = " AND version=%s" if expected_version is not None else ""
        params = [*fields.values(), time.time(), *self._owner, entry_id]
        if expected_version is not None:
            params.append(expected_version)
        try:
            async with self.db.transaction(self.scope) as connection:
                await self._lock_notebook_export_scope(connection)
                if fields.get("followup_session_id"):
                    await self._check_followup_session(connection, fields["followup_session_id"])
                row = await (
                    await connection.execute(
                        f"UPDATE enterprise.notebook_entries SET {assignments},"
                        " updated_at=%s,version=version+1"
                        " WHERE tenant_id=%s AND owner_id=%s AND id=%s"
                        + where_version
                        + " RETURNING version",
                        params,
                    )
                ).fetchone()
                if row is not None:
                    return True
                if expected_version is not None:
                    return await self._raise_version_conflict(
                        connection,
                        "notebook_entries",
                        "notebook entry",
                        entry_id,
                        expected_version,
                    )
                return False
        except psycopg.errors.ForeignKeyViolation as exc:
            raise ValueError("question-bank reference does not exist in this scope") from exc

    async def delete_notebook_entry(
        self, entry_id: int, *, expected_version: int | None = None
    ) -> bool:
        expected_version = self._expected_version(expected_version)
        suffix = " AND version=%s" if expected_version is not None else ""
        params = [*self._owner, entry_id]
        if expected_version is not None:
            params.append(expected_version)
        try:
            async with self.db.transaction(self.scope) as connection:
                await self._lock_notebook_export_scope(connection)
                deleted = await (
                    await connection.execute(
                        "DELETE FROM enterprise.notebook_entries"
                        " WHERE tenant_id=%s AND owner_id=%s AND id=%s" + suffix + " RETURNING id",
                        params,
                    )
                ).fetchone()
                if deleted:
                    return True
                if expected_version is not None:
                    return await self._raise_version_conflict(
                        connection,
                        "notebook_entries",
                        "notebook entry",
                        entry_id,
                        expected_version,
                    )
                return False
        except psycopg.errors.ForeignKeyViolation as exc:
            raise QuestionBankReferenceConflict(
                "notebook entry is still a learning source"
            ) from exc


__all__ = ["PostgresNotebookMixin"]
