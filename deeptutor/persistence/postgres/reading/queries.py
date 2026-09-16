"""Reading 有界 SQL 读取；所有关联结果来自单语句快照。"""

from itertools import islice

from deeptutor.reading.catalog_contracts import ReadingPageRequired
from deeptutor.reading.models import ReadingError

from .base import operation, validate_id
from .materials import ascii_key, material
from .sessions import session
from .workspaces import workspace


def limit_size(limit):
    return max(1, min(int(limit), 500))


def literal(value):
    return (
        "%"
        + ascii_key(value.strip()).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        + "%"
    )


def bounded(rows, api):
    if len(rows) > 500:
        raise ReadingPageRequired(f"result exceeds 500; use {api}")
    return rows


class Queries:
    def _material_where(self, search, status, library_filter):
        clauses = ["m.tenant_id=%s", "m.owner_id=%s"]
        params = list(self._owner)
        if search.strip():
            clauses.append(
                "(translate(m.title,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') LIKE %s ESCAPE '\\' OR translate(m.filename,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') LIKE %s ESCAPE '\\')"
            )
            params += [literal(search), literal(search)]
        if status is not None:
            clauses.append("m.status=%s")
            params.append(getattr(status, "value", status))
        if library_filter == "unassigned":
            clauses.append(
                "NOT EXISTS(SELECT 1 FROM enterprise.reading_workspace_materials t WHERE t.tenant_id=m.tenant_id AND t.owner_id=m.owner_id AND t.material_id=m.material_id)"
            )
        elif library_filter == "processing":
            clauses.append("m.status IN ('queued','processing')")
        elif library_filter == "failed":
            clauses.append("m.status='failed'")
        elif library_filter != "all":
            raise ReadingError("unsupported material library filter")
        return " AND ".join(clauses), params

    @operation()
    def list_materials(self, *, search="", status=None, library_filter="all", limit=200, offset=0):
        where, params = self._material_where(search, status, library_filter)
        rows = self._execute(
            "SELECT m.* FROM enterprise.reading_materials m WHERE "
            + where
            + " ORDER BY m.updated_at DESC,m.material_id DESC LIMIT %s OFFSET %s",
            (*params, limit_size(limit), max(0, int(offset))),
        ).fetchall()
        return [material(r) for r in rows]

    @operation()
    def list_workspaces(self, *, search="", limit=100, offset=0):
        rows = self._execute(
            """WITH selected AS MATERIALIZED (
          SELECT * FROM enterprise.reading_workspaces WHERE tenant_id=%s AND owner_id=%s
           AND translate(title,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') LIKE %s ESCAPE '\\'
          ORDER BY updated_at DESC,workspace_id DESC LIMIT %s OFFSET %s
        ), tabs AS MATERIALIZED (
          SELECT t.workspace_id,t.tab_order,t.material_id,jsonb_build_object('material',to_jsonb(m),'tab_order',t.tab_order,'pinned',t.pinned,'opened',t.opened,'added_at',t.added_at) AS payload
          FROM enterprise.reading_workspace_materials t JOIN selected w USING(tenant_id,owner_id,workspace_id)
          JOIN enterprise.reading_materials m USING(tenant_id,owner_id,material_id)
          ORDER BY t.workspace_id,t.tab_order,t.material_id LIMIT 501
        ) SELECT w.*,(SELECT count(*) FROM tabs) AS tab_total,
          COALESCE((SELECT jsonb_agg(t.payload ORDER BY t.tab_order,t.material_id) FROM tabs t WHERE t.workspace_id=w.workspace_id),'[]'::jsonb) AS tabs
          FROM selected w ORDER BY w.updated_at DESC,w.workspace_id DESC""",
            (*self._owner, literal(search), limit_size(limit), max(0, int(offset))),
        ).fetchall()
        if rows and rows[0]["tab_total"] > 500:
            raise ReadingPageRequired(
                "workspace batch exceeds 500 tabs; use list_workspaces_page/list_tabs_page"
            )
        return [workspace(r) for r in rows]

    @operation()
    def collections_for_materials(self, material_ids):
        from .pages import bounded_ids

        ids = list(dict.fromkeys(bounded_ids(material_ids)))
        if len(ids) > 500:
            raise ReadingPageRequired("material ID input exceeds 500; use list_collections_page")
        for mid in ids:
            validate_id(mid, "material")
        result = {mid: [] for mid in ids}
        if not ids:
            return result
        rows = self._execute(
            """SELECT t.material_id,w.workspace_id,w.title FROM enterprise.reading_workspace_materials t
          JOIN enterprise.reading_workspaces w USING(tenant_id,owner_id,workspace_id)
          WHERE t.tenant_id=%s AND t.owner_id=%s AND t.material_id=ANY(%s)
          ORDER BY translate(w.title,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),w.workspace_id,t.material_id LIMIT 501""",
            (*self._owner, ids),
        ).fetchall()
        for r in bounded(rows, "list_collections_page"):
            result[r["material_id"]].append(
                {"workspace_id": r["workspace_id"], "title": r["title"]}
            )
        return result

    @operation()
    def collections_for_material(self, material_id):
        validate_id(material_id, "material")
        return self.collections_for_materials([material_id])[material_id]

    @operation()
    def library_counts(self, material_ids=None):
        from .pages import MAX_WORKSPACE_MATERIALS

        ids = None
        if material_ids is not None:
            raw = list(islice(iter(material_ids), MAX_WORKSPACE_MATERIALS + 1))
            if len(raw) > MAX_WORKSPACE_MATERIALS:
                raise ReadingError(f"input exceeds {MAX_WORKSPACE_MATERIALS} IDs")
            # 旧 counts 的空串过滤、字符串化与 None=全部合同保留。
            ids = list(dict.fromkeys(str(x) for x in raw if str(x)))
        row = self._execute(
            """SELECT count(*) AS all,
          count(*) FILTER(WHERE NOT EXISTS(SELECT 1 FROM enterprise.reading_workspace_materials t WHERE t.tenant_id=m.tenant_id AND t.owner_id=m.owner_id AND t.material_id=m.material_id)) AS unassigned,
          count(*) FILTER(WHERE status IN ('queued','processing')) AS processing,
          count(*) FILTER(WHERE status='failed') AS failed,
          count(*) FILTER(WHERE render_mode='video' OR source_kind='video') AS video,
          count(*) FILTER(WHERE render_mode='audio' OR source_kind='audio') AS audio,
          count(*) FILTER(WHERE render_mode NOT IN ('video','audio') AND source_kind='web') AS web,
          count(*) FILTER(WHERE render_mode NOT IN ('video','audio') AND source_kind='file') AS document
          FROM enterprise.reading_materials m WHERE tenant_id=%s AND owner_id=%s AND (%s::text[] IS NULL OR material_id=ANY(%s::text[]))""",
            (*self._owner, ids, ids),
        ).fetchone()
        return {
            **{k: row[k] for k in ("all", "unassigned", "processing", "failed")},
            "by_kind": {k: row[k] for k in ("document", "web", "video", "audio")},
        }

    @operation()
    def list_sessions(self, workspace_id):
        rows = self._execute(
            "SELECT * FROM enterprise.reading_workspace_sessions WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s ORDER BY updated_at DESC,session_id DESC LIMIT 501",
            (*self._owner, validate_id(workspace_id, "workspace")),
        ).fetchall()
        return [session(r) for r in bounded(rows, "list_sessions_page")]

    @operation()
    def list_session_links(self, workspace_id, source_session_id):
        rows = self._execute(
            "SELECT target_session_id FROM enterprise.reading_session_links WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s AND source_session_id=%s ORDER BY created_at,target_session_id LIMIT 501",
            (
                *self._owner,
                validate_id(workspace_id, "workspace"),
                validate_id(source_session_id, "session"),
            ),
        ).fetchall()
        return [r["target_session_id"] for r in bounded(rows, "list_session_links_page")]
