"""材料身份与共享内容引用；所有元数据写入与引用判断共用 owner 锁。"""

from contextlib import contextmanager
from dataclasses import fields
import math
from pathlib import Path
import time
from uuid import uuid4

from deeptutor.reading.catalog_contracts import ContentDeletionPlan
from deeptutor.reading.catalog_models import IngestionStatus, MaterialRecord, SourceKind
from deeptutor.reading.models import ReadingError

from .base import SAFE_ID, operation, validate_id


def material(row):
    if row is None:
        return None
    values = {f.name: row[f.name] for f in fields(MaterialRecord)}
    values.update(
        source_kind=SourceKind(values["source_kind"]), status=IngestionStatus(values["status"])
    )
    return MaterialRecord(**values)


def ascii_key(value):
    return value.translate(
        str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
    )


def status_progress(status, progress):
    try:
        status = IngestionStatus(status).value
    except ValueError as exc:
        raise ReadingError(str(exc)) from exc
    return status, 100 if status == "ready" else max(0, min(int(progress or 0), 99))


class Materials:
    @operation(write=True)
    def upsert_material(
        self,
        *,
        content_id: str,
        filename: str,
        title: str,
        source_kind: SourceKind | str,
        source_url: str = "",
        mime: str = "",
        render_mode: str = "text",
        cover_url: str = "",
        duration_seconds: float = 0.0,
        status: IngestionStatus | str = IngestionStatus.QUEUED,
        progress: int | None = None,
        material_id: str | None = None,
        error_code: str = "",
        error_detail: str = "",
        expected_version: int | None = None,
    ) -> MaterialRecord:
        content_id = str(content_id or "").strip()
        mid = validate_id(
            material_id or (content_id if SAFE_ID.fullmatch(content_id) else "mat_" + uuid4().hex),
            "material",
        )
        status, progress = status_progress(status, progress)
        try:
            source_kind = SourceKind(source_kind).value
        except ValueError as exc:
            raise ReadingError(str(exc)) from exc
        duration = float(duration_seconds or 0)
        if not math.isfinite(duration):
            raise ReadingError("duration must be finite")
        duration = max(0.0, duration)
        previous = self._execute(
            "SELECT version FROM enterprise.reading_materials WHERE tenant_id=%s AND owner_id=%s AND material_id=%s FOR UPDATE",
            (*self._owner, mid),
        ).fetchone()
        self._cas(previous, expected_version)
        now = time.time()
        row = self._execute(
            """INSERT INTO enterprise.reading_materials
            (tenant_id,owner_id,material_id,content_id,filename,title,source_kind,source_url,mime,render_mode,cover_url,duration_seconds,status,progress,error_code,error_detail,last_opened_at,version,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,1,%s,%s)
            ON CONFLICT(tenant_id,owner_id,material_id) DO UPDATE SET
              content_id=excluded.content_id,filename=excluded.filename,title=excluded.title,
              source_kind=excluded.source_kind,source_url=excluded.source_url,mime=excluded.mime,
              render_mode=excluded.render_mode,
              cover_url=CASE WHEN excluded.cover_url<>'' THEN excluded.cover_url ELSE reading_materials.cover_url END,
              duration_seconds=CASE WHEN excluded.duration_seconds>0 THEN excluded.duration_seconds ELSE reading_materials.duration_seconds END,
              status=excluded.status,progress=excluded.progress,error_code=excluded.error_code,error_detail=excluded.error_detail,
              updated_at=excluded.updated_at,version=reading_materials.version+1 RETURNING *""",
            (
                *self._owner,
                mid,
                content_id or mid,
                filename.strip()[:500],
                (title or filename or "Untitled material").strip()[:500],
                source_kind,
                source_url.strip()[:4096],
                mime.strip()[:255],
                render_mode.strip()[:32] or "text",
                cover_url.strip()[:4096],
                duration,
                status,
                progress,
                error_code.strip()[:128],
                error_detail.strip()[:4000],
                now,
                now,
            ),
        ).fetchone()
        return material(row)

    @operation(write=True)
    def register_manifest(self, manifest) -> MaterialRecord:
        return self.upsert_material(
            content_id=manifest.material_id,
            material_id=manifest.material_id,
            filename=manifest.filename,
            title=manifest.title,
            source_kind=SourceKind.FILE,
            mime=manifest.mime,
            render_mode=manifest.render_mode,
            status=IngestionStatus.READY,
        )

    @operation()
    def get_material(self, material_id: str) -> MaterialRecord | None:
        return material(
            self._execute(
                "SELECT * FROM enterprise.reading_materials WHERE tenant_id=%s AND owner_id=%s AND material_id=%s",
                (*self._owner, validate_id(material_id)),
            ).fetchone()
        )

    @operation()
    def find_material_by_content(self, content_id: str) -> MaterialRecord | None:
        return material(
            self._execute(
                "SELECT * FROM enterprise.reading_materials WHERE tenant_id=%s AND owner_id=%s AND content_id=%s ORDER BY created_at,material_id LIMIT 1",
                (*self._owner, str(content_id or "").strip()),
            ).fetchone()
        )

    @operation()
    def find_ready_material_by_filename(
        self, filename: str, *, mime: str = ""
    ) -> MaterialRecord | None:
        name = Path(str(filename or "")).name.strip()
        if not name:
            return None
        # ASCII 精确名称相等已保证 suffix 相同（忽略 ASCII case）；先在 SQL 筛 MIME，再 LIMIT。
        return material(
            self._execute(
                """SELECT * FROM enterprise.reading_materials
            WHERE tenant_id=%s AND owner_id=%s AND status='ready'
            AND translate(filename,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')=%s
            AND (%s='' OR lower(mime)=%s OR %s)
            ORDER BY updated_at DESC,material_id LIMIT 1""",
                (
                    *self._owner,
                    ascii_key(name),
                    mime.strip().lower(),
                    mime.strip().lower(),
                    bool(Path(name).suffix),
                ),
            ).fetchone()
        )

    @operation()
    def count_materials_for_content(self, content_id: str) -> int:
        return self._execute(
            "SELECT count(*) AS n FROM enterprise.reading_materials WHERE tenant_id=%s AND owner_id=%s AND content_id=%s",
            (*self._owner, str(content_id or "").strip()),
        ).fetchone()["n"]

    @operation(write=True)
    def update_material_status(
        self,
        material_id: str,
        status: IngestionStatus | str,
        *,
        progress: int | None = None,
        error_code: str = "",
        error_detail: str = "",
        expected_version: int | None = None,
    ) -> MaterialRecord:
        status, progress = status_progress(status, progress)
        old = self.get_material(material_id)
        self._cas(old.to_dict() if old else None, expected_version)
        row = self._execute(
            """UPDATE enterprise.reading_materials SET status=%s,progress=%s,error_code=%s,error_detail=%s,updated_at=%s,version=version+1 WHERE tenant_id=%s AND owner_id=%s AND material_id=%s RETURNING *""",
            (
                status,
                progress,
                error_code[:128],
                error_detail[:4000],
                time.time(),
                *self._owner,
                material_id,
            ),
        ).fetchone()
        if row is None:
            raise ReadingError("material not found")
        return material(row)

    @contextmanager
    def locked_content(self, material_id: str, *, expected_version: int | None = None):
        """短同步 unit 内 stage/finalize 的锁；离开 unit 后计划不能用于删载荷。

        不在锁内执行网络/模型/解析。不做跨 PG 与文件系统原子性的承诺；后续
        1.19 应在此边界安排 staged_delete 的失败恢复和提交后清理。
        """
        if self._connection is None:
            raise RuntimeError("locked_content requires a bound reading unit")
        with self._unit(write=True) as u:
            row = u.get_material(material_id)
            if row is None:
                raise ReadingError("material not found")
            u._cas(row.to_dict(), expected_version)
            u._content_guards += 1
            try:
                yield ContentDeletionPlan(
                    row.material_id,
                    row.content_id,
                    row.version,
                    u.count_materials_for_content(row.content_id),
                )
            finally:
                u._content_guards -= 1

    @operation(write=True)
    def delete_material(self, material_id: str, *, expected_version: int | None = None) -> bool:
        validate_id(material_id)
        old = self.get_material(material_id)
        self._cas(old.to_dict() if old else None, expected_version)
        if old is None:
            return False
        now = time.time()
        # 先显式 bump 可观察版本，再让 FK 清理 tabs；失败时整个 unit 回滚。
        self._execute(
            """UPDATE enterprise.reading_workspaces w SET active_material_id=CASE WHEN active_material_id=%s THEN NULL ELSE active_material_id END,version=version+1,updated_at=%s
            WHERE tenant_id=%s AND owner_id=%s AND EXISTS(SELECT 1 FROM enterprise.reading_workspace_materials t WHERE t.tenant_id=w.tenant_id AND t.owner_id=w.owner_id AND t.workspace_id=w.workspace_id AND t.material_id=%s)""",
            (material_id, now, *self._owner, material_id),
        )
        self._execute(
            """UPDATE enterprise.reading_workspace_sessions SET active_material_id=NULL,version=version+1,updated_at=%s WHERE tenant_id=%s AND owner_id=%s AND active_material_id=%s""",
            (now, *self._owner, material_id),
        )
        return bool(
            self._execute(
                "DELETE FROM enterprise.reading_materials WHERE tenant_id=%s AND owner_id=%s AND material_id=%s",
                (*self._owner, material_id),
            ).rowcount
        )
