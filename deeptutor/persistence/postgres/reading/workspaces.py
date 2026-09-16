"""Workspace 会员与顺序聚合；所有 mutation 先 owner 锁后 CAS 行锁。"""

from dataclasses import fields
import time
from uuid import uuid4

from deeptutor.reading.catalog_contracts import ReadingPageRequired
from deeptutor.reading.catalog_models import WorkspaceRecord, WorkspaceTab
from deeptutor.reading.models import ReadingError

from .base import operation, validate_id
from .materials import material


def workspace(row):
    if row is None:
        return None
    tabs = row.get("tabs") or []
    if len(tabs) > 500:
        raise ReadingPageRequired("workspace has more than 500 tabs; use list_tabs_page")
    values = {f.name: row[f.name] for f in fields(WorkspaceRecord) if f.name != "tabs"}
    return WorkspaceRecord(
        **values,
        tabs=tuple(
            WorkspaceTab(
                material=material(t["material"]),
                tab_order=t["tab_order"],
                pinned=t["pinned"],
                opened=t["opened"],
                added_at=t["added_at"],
            )
            for t in tabs
        ),
    )


# 单条 SQL 的同一 MVCC 快照，不在 READ COMMITTED 下先查 header 再另查 tabs。
WORKSPACE_SELECT = """SELECT w.*, COALESCE(t.tabs,'[]'::jsonb) AS tabs
 FROM enterprise.reading_workspaces w LEFT JOIN LATERAL (
   SELECT jsonb_agg(x.payload ORDER BY x.tab_order,x.material_id) AS tabs FROM (
    SELECT wm.tab_order,wm.material_id,jsonb_build_object(
     'material',to_jsonb(m),'tab_order',wm.tab_order,'pinned',wm.pinned,
     'opened',wm.opened,'added_at',wm.added_at) AS payload
    FROM enterprise.reading_workspace_materials wm
    JOIN enterprise.reading_materials m USING(tenant_id,owner_id,material_id)
    WHERE wm.tenant_id=w.tenant_id AND wm.owner_id=w.owner_id AND wm.workspace_id=w.workspace_id
    ORDER BY wm.tab_order,wm.material_id LIMIT 501
   ) x
 ) t ON true"""


class Workspaces:
    def _workspace_row(self, wid, expected_version=None, *, missing=False):
        row = self._execute(
            "SELECT * FROM enterprise.reading_workspaces WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s FOR UPDATE",
            (*self._owner, validate_id(wid, "workspace")),
        ).fetchone()
        self._cas(row, expected_version)
        if row is None and not missing:
            raise ReadingError("workspace not found")
        return row

    def _require_materials(self, ids):
        for mid in ids:
            validate_id(mid, "material")
        rows = self._execute(
            "SELECT material_id FROM enterprise.reading_materials WHERE tenant_id=%s AND owner_id=%s AND material_id=ANY(%s)",
            (*self._owner, list(ids)),
        ).fetchall()
        if {r["material_id"] for r in rows} != set(ids):
            raise ReadingError("material not found")

    def _workspace_result(self, wid, return_summary):
        return self.get_workspace_summary(wid) if return_summary else self.get_workspace(wid)

    def _touch_workspace(self, wid, active, return_summary=False):
        self._execute(
            "UPDATE enterprise.reading_workspaces SET active_material_id=%s,version=version+1,updated_at=%s WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s",
            (active, time.time(), *self._owner, wid),
        )
        return self._workspace_result(wid, return_summary)

    def _tab_ids(self, wid):
        from .pages import MAX_WORKSPACE_MATERIALS

        rows = self._execute(
            "SELECT material_id FROM enterprise.reading_workspace_materials WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s ORDER BY tab_order,material_id LIMIT %s",
            (*self._owner, wid, MAX_WORKSPACE_MATERIALS + 1),
        ).fetchall()
        if len(rows) > MAX_WORKSPACE_MATERIALS:
            raise ReadingError(f"workspace exceeds {MAX_WORKSPACE_MATERIALS} materials")
        return [r["material_id"] for r in rows]

    def _order_tabs(self, wid, ids):
        # 延迟 UNIQUE 允许 0..N-1 单条重排；非负 CHECK 永远成立。
        self._execute(
            """UPDATE enterprise.reading_workspace_materials wm SET tab_order=x.ord-1
         FROM unnest(%s::text[]) WITH ORDINALITY x(material_id,ord)
         WHERE wm.tenant_id=%s AND wm.owner_id=%s AND wm.workspace_id=%s AND wm.material_id=x.material_id""",
            (list(ids), *self._owner, wid),
        )

    @operation(write=True)
    def create_workspace(
        self,
        title: str,
        material_ids=(),
        *,
        description: str = "",
        workspace_id: str | None = None,
        return_summary: bool = False,
    ) -> WorkspaceRecord:
        wid = validate_id(workspace_id or "rw_" + uuid4().hex, "workspace")
        from .pages import MAX_WORKSPACE_MATERIALS, bounded_ids

        ids = list(dict.fromkeys(bounded_ids(material_ids, MAX_WORKSPACE_MATERIALS)))
        self._require_materials(ids)
        now = time.time()
        self._execute(
            """INSERT INTO enterprise.reading_workspaces(tenant_id,owner_id,workspace_id,title,description,active_material_id,version,created_at,updated_at)
          VALUES(%s,%s,%s,%s,%s,%s,1,%s,%s)""",
            (
                *self._owner,
                wid,
                (title or "Untitled reading workspace").strip()[:300],
                description.strip()[:2000],
                ids[0] if ids else None,
                now,
                now,
            ),
        )
        self._execute(
            """INSERT INTO enterprise.reading_workspace_materials(tenant_id,owner_id,workspace_id,material_id,tab_order,pinned,opened,added_at)
          SELECT %s,%s,%s,mid,ord-1,false,true,%s FROM unnest(%s::text[]) WITH ORDINALITY x(mid,ord)""",
            (*self._owner, wid, now, ids),
        )
        return self._workspace_result(wid, return_summary)

    @operation()
    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        return workspace(
            self._execute(
                WORKSPACE_SELECT + " WHERE w.tenant_id=%s AND w.owner_id=%s AND w.workspace_id=%s",
                (*self._owner, validate_id(workspace_id, "workspace")),
            ).fetchone()
        )

    @operation(write=True)
    def update_workspace(
        self,
        workspace_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        expected_version: int | None = None,
        return_summary: bool = False,
    ) -> WorkspaceRecord:
        row = self._workspace_row(workspace_id, expected_version)
        self._execute(
            """UPDATE enterprise.reading_workspaces SET title=%s,description=%s,updated_at=%s,version=version+1 WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s""",
            (
                (title or "Untitled reading workspace").strip()[:300]
                if title is not None
                else row["title"],
                description.strip()[:2000] if description is not None else row["description"],
                time.time(),
                *self._owner,
                workspace_id,
            ),
        )
        return self._workspace_result(workspace_id, return_summary)

    @operation(write=True)
    def delete_workspace(self, workspace_id: str, *, expected_version: int | None = None) -> bool:
        if self._workspace_row(workspace_id, expected_version, missing=True) is None:
            return False
        return bool(
            self._execute(
                "DELETE FROM enterprise.reading_workspaces WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s",
                (*self._owner, workspace_id),
            ).rowcount
        )

    @operation(write=True)
    def add_material(
        self,
        workspace_id: str,
        material_id: str,
        *,
        make_active: bool = False,
        expected_version: int | None = None,
        return_summary: bool = False,
    ) -> WorkspaceRecord:
        row = self._workspace_row(workspace_id, expected_version)
        self._require_materials([material_id])
        from .pages import MAX_WORKSPACE_MATERIALS

        size = self._execute(
            "SELECT count(*) AS n,count(*) FILTER(WHERE material_id=%s) AS member FROM enterprise.reading_workspace_materials WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s",
            (material_id, *self._owner, workspace_id),
        ).fetchone()
        if size["n"] >= MAX_WORKSPACE_MATERIALS and not size["member"]:
            raise ReadingError(f"workspace exceeds {MAX_WORKSPACE_MATERIALS} materials")
        # 指定 PK 避免 ON CONFLICT 把延迟顺序 UNIQUE 当 arbiter。
        self._execute(
            """INSERT INTO enterprise.reading_workspace_materials(tenant_id,owner_id,workspace_id,material_id,tab_order,pinned,opened,added_at)
         SELECT %s,%s,%s,%s,COALESCE(max(tab_order),-1)+1,false,true,%s FROM enterprise.reading_workspace_materials
         WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s
         ON CONFLICT(tenant_id,owner_id,workspace_id,material_id) DO NOTHING""",
            (*self._owner, workspace_id, material_id, time.time(), *self._owner, workspace_id),
        )
        return self._touch_workspace(
            workspace_id,
            material_id
            if make_active or row["active_material_id"] is None
            else row["active_material_id"],
            return_summary,
        )

    @operation(write=True)
    def remove_material(
        self,
        workspace_id: str,
        material_id: str,
        *,
        expected_version: int | None = None,
        return_summary: bool = False,
    ) -> WorkspaceRecord:
        row = self._workspace_row(workspace_id, expected_version)
        validate_id(material_id, "material")
        # FK SET NULL 本身不 bump version；先显式更新并确保 session 不偷偷换教材。
        self._execute(
            """UPDATE enterprise.reading_workspace_sessions SET active_material_id=NULL,version=version+1,updated_at=%s
          WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s AND active_material_id=%s""",
            (time.time(), *self._owner, workspace_id, material_id),
        )
        if not self._execute(
            "DELETE FROM enterprise.reading_workspace_materials WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s AND material_id=%s",
            (*self._owner, workspace_id, material_id),
        ).rowcount:
            raise ReadingError("material does not belong to this reading workspace")
        ids = self._tab_ids(workspace_id)
        self._order_tabs(workspace_id, ids)
        active = (
            (ids[0] if ids else None)
            if row["active_material_id"] == material_id
            else row["active_material_id"]
        )
        return self._touch_workspace(workspace_id, active, return_summary)

    @operation(write=True)
    def reorder_materials(
        self,
        workspace_id: str,
        material_ids,
        *,
        expected_version: int | None = None,
        return_summary: bool = False,
    ) -> WorkspaceRecord:
        row = self._workspace_row(workspace_id, expected_version)
        from .pages import MAX_WORKSPACE_MATERIALS, bounded_ids

        ids = bounded_ids(material_ids, MAX_WORKSPACE_MATERIALS)
        if len(ids) != len(set(ids)) or set(ids) != set(self._tab_ids(workspace_id)):
            raise ReadingError("tab order must include every workspace material exactly once")
        self._order_tabs(workspace_id, ids)
        return self._touch_workspace(workspace_id, row["active_material_id"], return_summary)

    @operation(write=True)
    def set_active_material(
        self,
        workspace_id: str,
        material_id: str,
        *,
        expected_version: int | None = None,
        return_summary: bool = False,
    ) -> WorkspaceRecord:
        self._workspace_row(workspace_id, expected_version)
        validate_id(material_id, "material")
        if not self._execute(
            "SELECT 1 FROM enterprise.reading_workspace_materials WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s AND material_id=%s",
            (*self._owner, workspace_id, material_id),
        ).fetchone():
            raise ReadingError("material does not belong to this reading workspace")
        self._execute(
            "UPDATE enterprise.reading_materials SET last_opened_at=%s,version=version+1 WHERE tenant_id=%s AND owner_id=%s AND material_id=%s",
            (time.time(), *self._owner, material_id),
        )
        return self._touch_workspace(workspace_id, material_id, return_summary)
