"""阅读 session 是真实 chat session 的同 scope/workspace 关联，不制造假会话。"""

from dataclasses import fields
import time

from deeptutor.reading.catalog_models import ReadingSessionRecord
from deeptutor.reading.models import ReadingError

from .base import operation, validate_id


def session(row):
    return ReadingSessionRecord(**{f.name: row[f.name] for f in fields(ReadingSessionRecord)})


class Sessions:
    def _reading_session(self, wid, sid, expected_version=None):
        validate_id(wid, "workspace")
        validate_id(sid, "session")
        row = self._execute(
            "SELECT * FROM enterprise.reading_workspace_sessions WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s AND session_id=%s FOR UPDATE",
            (*self._owner, wid, sid),
        ).fetchone()
        self._cas(row, expected_version)
        return row

    @operation(write=True)
    def attach_session(
        self,
        workspace_id: str,
        session_id: str,
        *,
        title: str = "New reading conversation",
        active_material_id: str | None = None,
        expected_version: int | None = None,
    ) -> ReadingSessionRecord:
        validate_id(workspace_id, "workspace")
        validate_id(session_id, "session")
        # 与 SessionStore.delete_session 相同顺序：先真实 chat，再 reading 关联。
        chat = self._execute(
            "SELECT deleting FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s AND id=%s FOR UPDATE",
            (*self._owner, session_id),
        ).fetchone()
        if chat is None or chat["deleting"]:
            raise ReadingError("chat session unavailable")
        self._workspace_row(workspace_id)
        old = self._execute(
            "SELECT * FROM enterprise.reading_workspace_sessions WHERE tenant_id=%s AND owner_id=%s AND session_id=%s FOR UPDATE",
            (*self._owner, session_id),
        ).fetchone()
        self._cas(old, expected_version)
        if old and old["workspace_id"] != workspace_id:
            raise ReadingError("session already belongs to another reading workspace")
        if active_material_id is not None:
            validate_id(active_material_id, "material")
        now = time.time()
        row = self._execute(
            """INSERT INTO enterprise.reading_workspace_sessions(tenant_id,owner_id,workspace_id,session_id,title,active_material_id,version,created_at,updated_at)
          VALUES(%s,%s,%s,%s,%s,%s,1,%s,%s) ON CONFLICT(tenant_id,owner_id,session_id) DO UPDATE SET
          title=excluded.title,active_material_id=excluded.active_material_id,updated_at=excluded.updated_at,version=reading_workspace_sessions.version+1 RETURNING *""",
            (
                *self._owner,
                workspace_id,
                session_id,
                (title or "New reading conversation").strip()[:300],
                active_material_id,
                now,
                now,
            ),
        ).fetchone()
        return session(row)

    @operation(write=True)
    def rename_session(
        self, workspace_id: str, session_id: str, title: str, *, expected_version: int | None = None
    ) -> ReadingSessionRecord:
        if self._reading_session(workspace_id, session_id, expected_version) is None:
            raise ReadingError("reading session not found in this workspace")
        return session(
            self._execute(
                """UPDATE enterprise.reading_workspace_sessions SET title=%s,version=version+1,updated_at=%s WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s AND session_id=%s RETURNING *""",
                (
                    (title or "New reading conversation").strip()[:300],
                    time.time(),
                    *self._owner,
                    workspace_id,
                    session_id,
                ),
            ).fetchone()
        )

    @operation(write=True)
    def detach_session(
        self, workspace_id: str, session_id: str, *, expected_version: int | None = None
    ) -> bool:
        if self._reading_session(workspace_id, session_id, expected_version) is None:
            return False
        return bool(
            self._execute(
                "DELETE FROM enterprise.reading_workspace_sessions WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s AND session_id=%s",
                (*self._owner, workspace_id, session_id),
            ).rowcount
        )

    @operation(write=True)
    def link_session(
        self, workspace_id: str, source_session_id: str, target_session_id: str
    ) -> None:
        for value in (workspace_id, source_session_id, target_session_id):
            validate_id(value)
        if source_session_id == target_session_id:
            raise ReadingError("a reading session cannot reference itself")
        for sid in sorted((source_session_id, target_session_id)):
            row = self._execute(
                "SELECT deleting FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s AND id=%s FOR UPDATE",
                (*self._owner, sid),
            ).fetchone()
            if row is None or row["deleting"]:
                raise ReadingError("chat session unavailable for reading link")
        self._execute(
            """INSERT INTO enterprise.reading_session_links(tenant_id,owner_id,workspace_id,source_session_id,target_session_id,created_at)
          VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,owner_id,workspace_id,source_session_id,target_session_id) DO NOTHING""",
            (*self._owner, workspace_id, source_session_id, target_session_id, time.time()),
        )

    @operation(write=True)
    def unlink_session(
        self, workspace_id: str, source_session_id: str, target_session_id: str
    ) -> bool:
        for value in (workspace_id, source_session_id, target_session_id):
            validate_id(value)
        return bool(
            self._execute(
                "DELETE FROM enterprise.reading_session_links WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s AND source_session_id=%s AND target_session_id=%s",
                (*self._owner, workspace_id, source_session_id, target_session_id),
            ).rowcount
        )
