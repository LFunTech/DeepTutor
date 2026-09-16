"""PostgreSQL 题库分类 CRUD 与条目关联 mixin。"""

from __future__ import annotations

from collections.abc import Sequence
import time
from typing import Any

import psycopg


class PostgresNotebookCategoryMixin:
    """宿主提供同一 ``db/scope/_owner`` 及共用版本、分类加载 helper。"""

    async def create_category(self, name: str) -> dict[str, Any]:
        cleaned = str(name or "").strip()
        if not cleaned:
            raise ValueError("Category name must not be blank")
        now = time.time()
        try:
            async with self.db.transaction(self.scope) as connection:
                row = await (
                    await connection.execute(
                        "INSERT INTO enterprise.notebook_categories"
                        " (tenant_id,owner_id,name,created_at) VALUES(%s,%s,%s,%s)"
                        " RETURNING id,name,created_at,version",
                        (*self._owner, cleaned, now),
                    )
                ).fetchone()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError(f"A category named {cleaned!r} already exists.") from exc
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "created_at": float(row["created_at"]),
            "version": int(row["version"]),
        }

    async def list_categories(
        self, session_ids: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        session_join = ""
        params: list[Any] = []
        if session_ids is not None:
            session_join = " AND e.session_id=ANY(%s)"
            params.append(list(session_ids))
        params.extend(self._owner)
        async with self.db.transaction(self.scope) as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT c.id,c.name,c.created_at,c.version,count(e.id) AS entry_count
                    FROM enterprise.notebook_categories c
                    LEFT JOIN enterprise.notebook_entry_categories ec
                      ON ec.tenant_id=c.tenant_id AND ec.owner_id=c.owner_id
                     AND ec.category_id=c.id
                    LEFT JOIN enterprise.notebook_entries e
                      ON e.tenant_id=ec.tenant_id AND e.owner_id=ec.owner_id
                     AND e.id=ec.entry_id
                    """
                    + session_join
                    + " WHERE c.tenant_id=%s AND c.owner_id=%s"
                    + " GROUP BY c.tenant_id,c.owner_id,c.id"
                    + ' ORDER BY c.name COLLATE "C",c.id',
                    params,
                )
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "created_at": float(row["created_at"]),
                "entry_count": int(row["entry_count"]),
                "version": int(row["version"]),
            }
            for row in rows
        ]

    async def rename_category(
        self,
        category_id: int,
        name: str,
        *,
        expected_version: int | None = None,
    ) -> bool:
        expected_version = self._expected_version(expected_version)
        cleaned = str(name or "").strip()
        if not cleaned:
            raise ValueError("Category name must not be blank")
        suffix = " AND version=%s" if expected_version is not None else ""
        params: list[Any] = [cleaned, *self._owner, category_id]
        if expected_version is not None:
            params.append(expected_version)
        try:
            async with self.db.transaction(self.scope) as connection:
                row = await (
                    await connection.execute(
                        "UPDATE enterprise.notebook_categories"
                        " SET name=%s,version=version+1"
                        " WHERE tenant_id=%s AND owner_id=%s AND id=%s"
                        + suffix
                        + " RETURNING version",
                        params,
                    )
                ).fetchone()
                if row:
                    return True
                if expected_version is not None:
                    return await self._raise_version_conflict(
                        connection,
                        "notebook_categories",
                        "notebook category",
                        category_id,
                        expected_version,
                    )
                return False
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError(f"A category named {cleaned!r} already exists.") from exc

    async def delete_category(
        self, category_id: int, *, expected_version: int | None = None
    ) -> bool:
        expected_version = self._expected_version(expected_version)
        suffix = " AND version=%s" if expected_version is not None else ""
        params: list[Any] = [*self._owner, category_id]
        if expected_version is not None:
            params.append(expected_version)
        async with self.db.transaction(self.scope) as connection:
            row = await (
                await connection.execute(
                    "DELETE FROM enterprise.notebook_categories"
                    " WHERE tenant_id=%s AND owner_id=%s AND id=%s" + suffix + " RETURNING id",
                    params,
                )
            ).fetchone()
            if row:
                return True
            if expected_version is not None:
                return await self._raise_version_conflict(
                    connection,
                    "notebook_categories",
                    "notebook category",
                    category_id,
                    expected_version,
                )
            return False

    async def add_entry_to_category(self, entry_id: int, category_id: int) -> bool:
        async with self.db.transaction(self.scope) as connection:
            category = await (
                await connection.execute(
                    "SELECT id FROM enterprise.notebook_categories"
                    " WHERE tenant_id=%s AND owner_id=%s AND id=%s FOR KEY SHARE",
                    (*self._owner, category_id),
                )
            ).fetchone()
            if category is None:
                return False
            entry = await (
                await connection.execute(
                    "SELECT id FROM enterprise.notebook_entries"
                    " WHERE tenant_id=%s AND owner_id=%s AND id=%s FOR KEY SHARE",
                    (*self._owner, entry_id),
                )
            ).fetchone()
            if entry is None:
                return False
            await connection.execute(
                "INSERT INTO enterprise.notebook_entry_categories"
                " (tenant_id,owner_id,entry_id,category_id) VALUES(%s,%s,%s,%s)"
                " ON CONFLICT DO NOTHING",
                (*self._owner, entry_id, category_id),
            )
            return True

    async def remove_entry_from_category(self, entry_id: int, category_id: int) -> bool:
        async with self.db.transaction(self.scope) as connection:
            row = await (
                await connection.execute(
                    "DELETE FROM enterprise.notebook_entry_categories"
                    " WHERE tenant_id=%s AND owner_id=%s AND entry_id=%s AND category_id=%s"
                    " RETURNING entry_id",
                    (*self._owner, entry_id, category_id),
                )
            ).fetchone()
            return row is not None

    async def get_entry_categories(self, entry_id: int) -> list[dict[str, Any]]:
        async with self.db.transaction(self.scope) as connection:
            return (await self._load_categories_for(connection, [entry_id])).get(entry_id, [])

    async def link_entries_to_category(
        self, entry_ids: list[int], category_id: int, *, link: bool = True
    ) -> int:
        unique_ids = list(dict.fromkeys(int(entry_id) for entry_id in entry_ids))
        if not unique_ids:
            return 0
        async with self.db.transaction(self.scope) as connection:
            category = await (
                await connection.execute(
                    "SELECT id FROM enterprise.notebook_categories"
                    " WHERE tenant_id=%s AND owner_id=%s AND id=%s FOR KEY SHARE",
                    (*self._owner, category_id),
                )
            ).fetchone()
            if category is None:
                return 0
            known_rows = await (
                await connection.execute(
                    "SELECT id FROM enterprise.notebook_entries"
                    " WHERE tenant_id=%s AND owner_id=%s AND id=ANY(%s)"
                    " ORDER BY id FOR KEY SHARE",
                    (*self._owner, unique_ids),
                )
            ).fetchall()
            known_ids = [int(row["id"]) for row in known_rows]
            if not known_ids:
                return 0
            if link:
                cursor = await connection.execute(
                    """
                    INSERT INTO enterprise.notebook_entry_categories
                      (tenant_id,owner_id,entry_id,category_id)
                    SELECT %s,%s,entry_id,%s FROM unnest(%s::bigint[]) AS entry_id
                    ON CONFLICT DO NOTHING
                    """,
                    (*self._owner, category_id, known_ids),
                )
            else:
                cursor = await connection.execute(
                    "DELETE FROM enterprise.notebook_entry_categories"
                    " WHERE tenant_id=%s AND owner_id=%s AND category_id=%s"
                    " AND entry_id=ANY(%s)",
                    (*self._owner, category_id, known_ids),
                )
            return max(0, int(cursor.rowcount or 0))

    async def find_category_by_name(self, name: str) -> dict[str, Any] | None:
        cleaned = str(name or "").strip()
        async with self.db.transaction(self.scope) as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT id,name,created_at,version
                    FROM enterprise.notebook_categories
                    WHERE tenant_id=%s AND owner_id=%s
                      AND name_key=translate(%s,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')
                    ORDER BY id LIMIT 1
                    """,
                    (*self._owner, cleaned),
                )
            ).fetchone()
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "created_at": float(row["created_at"]),
            "version": int(row["version"]),
        }


__all__ = ["PostgresNotebookCategoryMixin"]
