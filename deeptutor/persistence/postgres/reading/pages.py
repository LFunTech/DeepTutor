"""显式 keyset 分页，游标绑定资源/scope/query，不代表额外授权。"""

import base64
from dataclasses import fields
import hashlib
from itertools import islice
import json
import math

from deeptutor.reading.catalog_contracts import (
    MembershipRecord,
    ReadingPage,
    WorkspaceSummaryRecord,
)
from deeptutor.reading.catalog_models import WorkspaceTab
from deeptutor.reading.models import ReadingError

from .base import operation, validate_id
from .materials import material
from .queries import limit_size, literal
from .sessions import session

MAX_WORKSPACE_MATERIALS = 10000


def bounded_ids(values, maximum=500):
    # 在复制/去重之前限制输入；生成器也只能消费 maximum+1 项。
    rows = list(islice(iter(values), maximum + 1))
    if len(rows) > maximum:
        raise ReadingError(f"input exceeds {maximum} IDs")
    for value in rows:
        validate_id(value)
    return rows


def summary(row):
    return WorkspaceSummaryRecord(**{f.name: row[f.name] for f in fields(WorkspaceSummaryRecord)})


class Pages:
    def _cursor(self, query, cursor, kinds):
        fingerprint = hashlib.sha256(
            json.dumps(
                [self.db.resource, *self._owner, query],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if cursor is None:
            return fingerprint, None
        try:
            if not isinstance(cursor, str) or len(cursor) > 4096:
                raise ValueError()
            data = json.loads(base64.b64decode(cursor.encode(), altchars=b"-_", validate=True))
            if not isinstance(data, list) or len(data) != 2 or data[0] != fingerprint:
                raise ValueError()
            values = data[1]
            if not isinstance(values, list) or len(values) != len(kinds):
                raise ValueError()
            for value, kind in zip(values, kinds):
                if kind == "number" and (
                    type(value) not in (int, float) or not math.isfinite(value)
                ):
                    raise ValueError()
                if kind == "int" and (type(value) is not int or value < 0):
                    raise ValueError()
                if kind == "text" and (not isinstance(value, str) or len(value) > 500):
                    raise ValueError()
                if kind == "id":
                    validate_id(value)
            return fingerprint, values
        except (ValueError, TypeError, UnicodeError, ReadingError) as exc:
            raise ReadingError("invalid reading cursor or query/scope mismatch") from exc

    @staticmethod
    def _page(rows, limit, fingerprint, keys, convert):
        count = limit_size(limit)
        visible = rows[:count]
        cursor = None
        if len(rows) > count:
            cursor = base64.urlsafe_b64encode(
                json.dumps(
                    [fingerprint, [visible[-1][key] for key in keys]],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            ).decode()
        return ReadingPage(tuple(convert(r) for r in visible), cursor)

    @operation()
    def list_materials_page(
        self, *, search="", status=None, library_filter="all", limit=100, cursor=None
    ):
        where, params = self._material_where(search, status, library_filter)
        fp, keys = self._cursor(
            ["materials", search, getattr(status, "value", status), library_filter],
            cursor,
            ["number", "id"],
        )
        if keys is not None:
            where += " AND (m.updated_at,m.material_id)<(%s,%s)"
            params += keys
        rows = self._execute(
            "SELECT m.* FROM enterprise.reading_materials m WHERE "
            + where
            + " ORDER BY m.updated_at DESC,m.material_id DESC LIMIT %s",
            (*params, limit_size(limit) + 1),
        ).fetchall()
        return self._page(rows, limit, fp, ["updated_at", "material_id"], material)

    @operation()
    def get_workspace_summary(self, workspace_id):
        row = self._execute(
            """SELECT w.*,(SELECT count(*) FROM enterprise.reading_workspace_materials t
          WHERE t.tenant_id=w.tenant_id AND t.owner_id=w.owner_id AND t.workspace_id=w.workspace_id) AS tab_count
          FROM enterprise.reading_workspaces w WHERE w.tenant_id=%s AND w.owner_id=%s AND w.workspace_id=%s""",
            (*self._owner, validate_id(workspace_id)),
        ).fetchone()
        return summary(row) if row else None

    @operation()
    def list_workspaces_page(self, *, search="", limit=100, cursor=None):
        fp, keys = self._cursor(["workspaces", search], cursor, ["number", "id"])
        clause = ""
        params = [*self._owner, literal(search)]
        if keys is not None:
            clause = " AND (w.updated_at,w.workspace_id)<(%s,%s)"
            params += keys
        rows = self._execute(
            """SELECT w.*,(SELECT count(*) FROM enterprise.reading_workspace_materials t
          WHERE t.tenant_id=w.tenant_id AND t.owner_id=w.owner_id AND t.workspace_id=w.workspace_id) AS tab_count
          FROM enterprise.reading_workspaces w WHERE w.tenant_id=%s AND w.owner_id=%s
          AND translate(w.title,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') LIKE %s ESCAPE '\\' """
            + clause
            + " ORDER BY w.updated_at DESC,w.workspace_id DESC LIMIT %s",
            (*params, limit_size(limit) + 1),
        ).fetchall()
        return self._page(rows, limit, fp, ["updated_at", "workspace_id"], summary)

    @operation()
    def list_tabs_page(self, workspace_id, *, limit=100, cursor=None):
        validate_id(workspace_id)
        fp, keys = self._cursor(["tabs", workspace_id], cursor, ["int", "id"])
        clause = ""
        params = [*self._owner, workspace_id]
        if keys is not None:
            clause = " AND (t.tab_order,t.material_id)>(%s,%s)"
            params += keys
        rows = self._execute(
            """SELECT t.*,to_jsonb(m) AS material FROM enterprise.reading_workspace_materials t
          JOIN enterprise.reading_materials m USING(tenant_id,owner_id,material_id)
          WHERE t.tenant_id=%s AND t.owner_id=%s AND t.workspace_id=%s"""
            + clause
            + " ORDER BY t.tab_order,t.material_id LIMIT %s",
            (*params, limit_size(limit) + 1),
        ).fetchall()
        return self._page(
            rows,
            limit,
            fp,
            ["tab_order", "material_id"],
            lambda r: WorkspaceTab(
                material(r["material"]), r["tab_order"], r["pinned"], r["opened"], r["added_at"]
            ),
        )

    @operation()
    def list_sessions_page(self, workspace_id, *, limit=100, cursor=None):
        validate_id(workspace_id)
        fp, keys = self._cursor(["sessions", workspace_id], cursor, ["number", "id"])
        clause = ""
        params = [*self._owner, workspace_id]
        if keys is not None:
            clause = " AND (updated_at,session_id)<(%s,%s)"
            params += keys
        rows = self._execute(
            "SELECT * FROM enterprise.reading_workspace_sessions WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s"
            + clause
            + " ORDER BY updated_at DESC,session_id DESC LIMIT %s",
            (*params, limit_size(limit) + 1),
        ).fetchall()
        return self._page(rows, limit, fp, ["updated_at", "session_id"], session)

    @operation()
    def list_session_links_page(self, workspace_id, source_session_id, *, limit=100, cursor=None):
        validate_id(workspace_id)
        validate_id(source_session_id)
        fp, keys = self._cursor(
            ["links", workspace_id, source_session_id], cursor, ["number", "id"]
        )
        clause = ""
        params = [*self._owner, workspace_id, source_session_id]
        if keys is not None:
            clause = " AND (created_at,target_session_id)>(%s,%s)"
            params += keys
        rows = self._execute(
            "SELECT * FROM enterprise.reading_session_links WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s AND source_session_id=%s"
            + clause
            + " ORDER BY created_at,target_session_id LIMIT %s",
            (*params, limit_size(limit) + 1),
        ).fetchall()
        return self._page(
            rows, limit, fp, ["created_at", "target_session_id"], lambda r: r["target_session_id"]
        )

    @operation()
    def list_collections_page(self, material_ids, *, limit=100, cursor=None):
        ids = sorted(set(bounded_ids(material_ids)))
        fp, keys = self._cursor(["collections", ids], cursor, ["text", "id", "id"])
        params = [*self._owner, ids]
        clause = ""
        key = "translate(w.title,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')"
        if keys is not None:
            clause = f" AND ({key},w.workspace_id,t.material_id)>(%s,%s,%s)"
            params += keys
        rows = self._execute(
            f"""SELECT t.material_id,w.workspace_id,w.title,{key} AS title_key
          FROM enterprise.reading_workspace_materials t JOIN enterprise.reading_workspaces w USING(tenant_id,owner_id,workspace_id)
          WHERE t.tenant_id=%s AND t.owner_id=%s AND t.material_id=ANY(%s)"""
            + clause
            + f" ORDER BY {key},w.workspace_id,t.material_id LIMIT %s",
            (*params, limit_size(limit) + 1),
        ).fetchall()
        return self._page(
            rows,
            limit,
            fp,
            ["title_key", "workspace_id", "material_id"],
            lambda r: MembershipRecord(r["material_id"], r["workspace_id"], r["title"]),
        )
