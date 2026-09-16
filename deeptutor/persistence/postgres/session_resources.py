"""PG 权威的不可变会话附件；文件不提供授权、路径或提交补偿依据。"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
import hashlib
from urllib.parse import quote, unquote, urlsplit
from uuid import UUID, uuid4

from deeptutor.persistence.resources import OwnerResourceProvider
from deeptutor.runtime.externalized_providers import ObjectBlobRef
from deeptutor.services.storage.attachment_store import _coerce_filename

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


def attachment_key(attachment, session_id):
    if type(attachment) is not dict:
        raise ValueError("attachment must be an object")
    url = urlsplit(str(attachment.get("url") or ""))
    parts = url.path.split("/")
    if (
        url.scheme
        or url.netloc
        or url.query
        or url.fragment
        or len(parts) != 6
        or parts[1:3] != ["files", "attachments"]
    ):
        raise ValueError("attachment source lacks a PostgreSQL authority provider")
    if unquote(parts[3]) != session_id:
        raise ValueError("attachment session mismatch")
    try:
        key = UUID(parts[4])
    except ValueError as exc:
        raise ValueError("invalid immutable attachment object") from exc
    return key, unquote(parts[5])


async def link_attachments(store, c, session, message_id, attachments):
    seen = set()
    for attachment in attachments or []:
        key, filename = attachment_key(attachment, session["id"])
        if key in seen:
            raise ValueError("duplicate attachment object")
        seen.add(key)
        row = await (
            await c.execute(
                "SELECT filename FROM enterprise.session_objects WHERE tenant_id=%s AND owner_id=%s AND object_id=%s AND session_ref=%s AND incarnation=%s AND state='ready' FOR UPDATE",
                (*store._owner, key, session["id"], session["incarnation"]),
            )
        ).fetchone()
        if row is None or row["filename"] != filename:
            raise ValueError("attachment unavailable in this scope/session generation")
        await c.execute(
            "INSERT INTO enterprise.message_objects(tenant_id,owner_id,session_id,message_id,object_id) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (*store._owner, session["id"], message_id, key),
        )


async def queue_unreferenced(store, c, session_id):
    await c.execute(
        "UPDATE enterprise.session_objects o SET state='cleanup',updated_at=now() WHERE o.tenant_id=%s AND o.owner_id=%s AND o.session_ref=%s AND o.state='ready' AND NOT EXISTS (SELECT 1 FROM enterprise.message_objects m WHERE m.tenant_id=o.tenant_id AND m.owner_id=o.owner_id AND m.object_id=o.object_id)",
        (*store._owner, session_id),
    )


class PostgresAttachmentStore:
    """显式 session Store + 受控根，禁止发现本地路径或落回 admin scope。"""

    def __init__(self, store, resources):
        if not isinstance(resources, OwnerResourceProvider):
            raise TypeError("explicit OwnerResourceProvider required")
        self.store, self.resources = store, resources
        self.directory = resources.bind_directory(*store._owner, "attachments")

    async def _io(self, fn, *args):
        task = asyncio.create_task(asyncio.to_thread(fn, *args))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        result = task.result()
        if cancelled:
            raise asyncio.CancelledError()
        return result

    @contextmanager
    def _file_lock(self, key):
        with self.directory.open(create=True) as files:
            with files.lock(str(key) + ".lock"):
                yield

    @asynccontextmanager
    async def _locked_object(self, key):
        manager = self._file_lock(key)
        # 获取后即使收到取消也必须释放锁。
        task = asyncio.create_task(asyncio.to_thread(manager.__enter__))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        try:
            if cancelled:
                raise asyncio.CancelledError()
            yield
        finally:
            await self._io(manager.__exit__, None, None, None)

    async def _authorized(self, c):
        row = await (
            await c.execute(
                "SELECT id FROM enterprise.users WHERE tenant_id=%s AND id=%s AND NOT disabled AND deleted_at IS NULL",
                self.store._owner,
            )
        ).fetchone()
        if row is None:
            raise PermissionError("attachment owner unavailable")

    def _write_object(self, key, data):
        with self.directory.open(create=True) as files:
            files.write(str(key) + ".blob", data)

    def _read_object(self, key, max_bytes):
        with self.directory.open() as files:
            return files.read(str(key) + ".blob", max_bytes=max_bytes)

    def _delete_object(self, key):
        with self.directory.open() as files:
            files.delete(str(key) + ".blob")

    async def put(self, *, session_id, attachment_id, filename, data, mime_type=""):
        key = uuid4()
        try:
            return await self._put(
                key,
                session_id=session_id,
                attachment_id=attachment_id,
                filename=filename,
                data=data,
                mime_type=mime_type,
            )
        except BaseException as exc:
            # 即使提交结果未知，调用方仍可按不可复用 token 查询/显式撤回。
            exc.resource_operation_id = str(key)
            raise

    async def _put(self, key, *, session_id, attachment_id, filename, data, mime_type):
        if type(data) is not bytes or len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError("attachment byte limit exceeded")
        if not isinstance(attachment_id, str) or not attachment_id or len(attachment_id) > 255:
            raise ValueError("invalid attachment ID")
        filename = _coerce_filename(filename)
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            await self.store._lock_notebook_export_scope(c)
            session = self.store._require_session(
                await self.store._session(c, session_id, lock=True)
            )
            await c.execute(
                "INSERT INTO enterprise.session_objects(tenant_id,owner_id,object_id,session_id,session_ref,incarnation,attachment_id,filename,mime_type,byte_size,sha256,state) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'candidate')",
                (
                    *self.store._owner,
                    key,
                    session_id,
                    session_id,
                    session["incarnation"],
                    attachment_id,
                    filename,
                    mime_type,
                    len(data),
                    hashlib.sha256(data).hexdigest(),
                ),
            )
        # 候选意图已确认提交。文件锁覆盖状态复验/写入/发布；清理不会抢在在途写前完成。
        async with self._locked_object(key):
            async with self.store.db.transaction(self.store.scope) as c:
                await self._authorized(c)
                row = await (
                    await c.execute(
                        "SELECT state,session_ref FROM enterprise.session_objects WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                        (*self.store._owner, key),
                    )
                ).fetchone()
                if not row or row["state"] != "candidate" or row["session_ref"] != session_id:
                    raise RuntimeError("attachment candidate was withdrawn")
            await self._io(self._write_object, key, data)
            # unknown/取消不补偿删除；候选记录仍可在维护态对账。
            async with self.store.db.transaction(self.store.scope) as c:
                await self._authorized(c)
                await self.store._lock_notebook_export_scope(c)
                current = self.store._require_session(
                    await self.store._session(c, session_id, lock=True)
                )
                if current["incarnation"] != session["incarnation"]:
                    raise RuntimeError("session generation changed")
                result = await c.execute(
                    "UPDATE enterprise.session_objects SET state='ready',updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND object_id=%s AND state='candidate' AND session_ref=%s",
                    (*self.store._owner, key, session_id),
                )
                if result.rowcount != 1:
                    raise RuntimeError("attachment candidate was withdrawn")
        return "/files/attachments/" + "/".join(
            quote(v, safe="") for v in (session_id, str(key), filename)
        )

    async def read_attachment(self, *, session_id, attachment_id, filename):
        key = UUID(str(attachment_id))
        # 在任何资源目录 I/O 前先授权；取得文件锁后仍再次复验以关闭撤销竞争。
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            visible = await (
                await c.execute(
                    "SELECT 1 FROM enterprise.session_objects o JOIN enterprise.sessions s ON (s.tenant_id,s.owner_id,s.id,s.incarnation)=(o.tenant_id,o.owner_id,o.session_ref,o.incarnation) WHERE o.tenant_id=%s AND o.owner_id=%s AND o.object_id=%s AND o.session_ref=%s AND o.filename=%s AND o.state='ready' AND NOT s.deleting AND EXISTS(SELECT 1 FROM enterprise.message_objects m WHERE m.tenant_id=o.tenant_id AND m.owner_id=o.owner_id AND m.object_id=o.object_id)",
                    (*self.store._owner, key, session_id, filename),
                )
            ).fetchone()
            if visible is None:
                raise FileNotFoundError("attachment not found")
        # 文件锁先于事务；只有本操作持有的 FD 读取，不返回可被换链的 Path。
        async with self._locked_object(key):
            async with self.store.db.transaction(self.store.scope) as c:
                await self._authorized(c)
                await self.store._lock_notebook_export_scope(c)
                row = await (
                    await c.execute(
                        "SELECT o.byte_size,o.sha256 FROM enterprise.session_objects o JOIN enterprise.sessions s ON (s.tenant_id,s.owner_id,s.id,s.incarnation)=(o.tenant_id,o.owner_id,o.session_ref,o.incarnation) WHERE o.tenant_id=%s AND o.owner_id=%s AND o.object_id=%s AND o.session_ref=%s AND o.filename=%s AND o.state='ready' AND NOT s.deleting AND EXISTS(SELECT 1 FROM enterprise.message_objects m WHERE m.tenant_id=o.tenant_id AND m.owner_id=o.owner_id AND m.object_id=o.object_id)",
                        (*self.store._owner, key, session_id, filename),
                    )
                ).fetchone()
                if row is None:
                    raise FileNotFoundError("attachment not found")
                # 有界本地读；未在该事务内做解析、网络或文件流式传输。
                data = await self._io(self._read_object, key, row["byte_size"])
                if (
                    len(data) != row["byte_size"]
                    or hashlib.sha256(data).hexdigest() != row["sha256"]
                ):
                    raise OSError("attachment integrity mismatch")
                return data

    async def list_operations(self, *, after=None, limit=100):
        cursor = UUID(str(after)) if after else UUID(int=0)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("operation page limit must be between 1 and 1000")
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            return await (
                await c.execute(
                    "SELECT object_id,session_id,filename,state,attempts,last_error,EXISTS(SELECT 1 FROM enterprise.message_objects m WHERE m.tenant_id=o.tenant_id AND m.owner_id=o.owner_id AND m.object_id=o.object_id) AS referenced FROM enterprise.session_objects o WHERE tenant_id=%s AND owner_id=%s AND object_id>%s AND state<>'deleted' ORDER BY object_id LIMIT %s",
                    (*self.store._owner, cursor, limit),
                )
            ).fetchall()

    async def get_operation(self, object_id):
        key = UUID(str(object_id))
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            return await (
                await c.execute(
                    "SELECT object_id,session_id,filename,state,attempts,last_error,created_at,updated_at,EXISTS(SELECT 1 FROM enterprise.message_objects m WHERE m.tenant_id=o.tenant_id AND m.owner_id=o.owner_id AND m.object_id=o.object_id) AS referenced FROM enterprise.session_objects o WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                    (*self.store._owner, key),
                )
            ).fetchone()

    async def withdraw_operation(self, object_id):
        """操作者按已报告 token 明确撤回，不自动猜测 unknown 提交是否失败。"""
        key = UUID(str(object_id))
        # 不为不存在/未授权 token 创建锁文件。
        if await self.get_operation(key) is None:
            raise FileNotFoundError("attachment operation not found")
        async with self._locked_object(key):
            async with self.store.db.transaction(self.store.scope) as c:
                await self._authorized(c)
                await self.store._lock_notebook_export_scope(c)
                row = await (
                    await c.execute(
                        "SELECT state FROM enterprise.session_objects WHERE tenant_id=%s AND owner_id=%s AND object_id=%s FOR UPDATE",
                        (*self.store._owner, key),
                    )
                ).fetchone()
                referenced = await (
                    await c.execute(
                        "SELECT 1 FROM enterprise.message_objects WHERE tenant_id=%s AND owner_id=%s AND object_id=%s LIMIT 1",
                        (*self.store._owner, key),
                    )
                ).fetchone()
                if referenced:
                    raise ValueError("referenced attachment cannot be withdrawn")
                if row and row["state"] != "deleted":
                    await c.execute(
                        "UPDATE enterprise.session_objects SET state='cleanup',updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                        (*self.store._owner, key),
                    )
        return await self.cleanup_pending()

    async def list_cleanup(self, limit=100):
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            return await (
                await c.execute(
                    "SELECT object_id,state,attempts,last_error FROM enterprise.session_objects WHERE tenant_id=%s AND owner_id=%s AND state='cleanup' ORDER BY created_at,object_id LIMIT %s",
                    (*self.store._owner, max(1, min(int(limit), 1000))),
                )
            ).fetchall()

    async def cleanup_pending(self, limit=100):
        completed, errors = 0, []
        for row in await self.list_cleanup(limit):
            key = row["object_id"]
            try:
                async with self._locked_object(key):
                    async with self.store.db.transaction(self.store.scope) as c:
                        await self._authorized(c)
                        current = await (
                            await c.execute(
                                "SELECT state FROM enterprise.session_objects WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                                (*self.store._owner, key),
                            )
                        ).fetchone()
                    if not current or current["state"] != "cleanup":
                        continue
                    await self._io(self._delete_object, key)
                    async with self.store.db.transaction(self.store.scope) as c:
                        await c.execute(
                            "UPDATE enterprise.session_objects SET state='deleted',attempts=attempts+1,last_error='',updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND object_id=%s AND state='cleanup'",
                            (*self.store._owner, key),
                        )
                    completed += 1
            except OSError as exc:
                # 包括目录/锁获取失败；只记录异常类型，不保存机器路径。
                error = type(exc).__name__
                async with self.store.db.transaction(self.store.scope) as c:
                    await c.execute(
                        "UPDATE enterprise.session_objects SET attempts=attempts+1,last_error=%s,updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND object_id=%s AND state='cleanup'",
                        (error, *self.store._owner, key),
                    )
                errors.append({"object_id": str(key), "error": error})
        async with self.store.db.transaction(self.store.scope) as c:
            count = await (
                await c.execute(
                    "SELECT count(*) AS count FROM enterprise.session_objects WHERE tenant_id=%s AND owner_id=%s AND state='cleanup'",
                    self.store._owner,
                )
            ).fetchone()
        return {"completed": completed, "pending": count["count"], "errors": errors}

    async def delete_session(self, session_id):
        # 会话删除事务已登记对象；禁止按可复用 session ID 再扫描目录。
        return await self.cleanup_pending()

    async def delete_attachment(self, session_id, attachment_id):
        key = UUID(str(attachment_id))
        async with self.store.db.transaction(self.store.scope) as c:
            await self.store._lock_notebook_export_scope(c)
            await c.execute(
                "UPDATE enterprise.session_objects o SET state='cleanup',updated_at=now() WHERE o.tenant_id=%s AND o.owner_id=%s AND o.object_id=%s AND o.session_id=%s AND NOT EXISTS(SELECT 1 FROM enterprise.message_objects m WHERE m.tenant_id=o.tenant_id AND m.owner_id=o.owner_id AND m.object_id=o.object_id)",
                (*self.store._owner, key, session_id),
            )
        return await self.cleanup_pending()


class PostgresObjectAttachmentStore:
    """PG-visible chat attachments whose bytes live in S3-compatible ObjectStore."""

    def __init__(self, store, object_store, *, bucket=""):
        self.store = store
        self.object_store = object_store
        configured_bucket = getattr(getattr(object_store, "config", None), "bucket", "")
        self.bucket = str(bucket or configured_bucket or "").strip()
        if not self.bucket:
            raise ValueError("object-store bucket is required for PG attachment resources")

    async def _io(self, fn, *args, **kwargs):
        task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        result = task.result()
        if cancelled:
            raise asyncio.CancelledError()
        return result

    async def _authorized(self, c):
        row = await (
            await c.execute(
                "SELECT id FROM enterprise.users WHERE tenant_id=%s AND id=%s AND NOT disabled AND deleted_at IS NULL",
                self.store._owner,
            )
        ).fetchone()
        if row is None:
            raise PermissionError("attachment owner unavailable")

    def _object_key(self, object_id):
        tenant_id, owner_id = self.store._owner
        owner_hash = hashlib.sha256(str(owner_id).encode()).hexdigest()
        return f"tenants/{tenant_id}/owners/{owner_hash}/chat-attachments/{object_id}"

    def _blob_ref(self, row) -> ObjectBlobRef:
        return ObjectBlobRef(
            key=row["object_key"],
            size_bytes=int(row["size_bytes"]),
            sha256=row["content_hash"],
            content_type=row["mime_type"] or "application/octet-stream",
        )

    async def put(self, *, session_id, attachment_id, filename, data, mime_type=""):
        key = uuid4()
        try:
            return await self._put(
                key,
                session_id=session_id,
                attachment_id=attachment_id,
                filename=filename,
                data=data,
                mime_type=mime_type,
            )
        except BaseException as exc:
            exc.resource_operation_id = str(key)
            raise

    async def _put(self, key, *, session_id, attachment_id, filename, data, mime_type):
        if type(data) is not bytes or len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError("attachment byte limit exceeded")
        if not isinstance(attachment_id, str) or not attachment_id or len(attachment_id) > 255:
            raise ValueError("invalid attachment ID")
        filename = _coerce_filename(filename)
        content_type = str(mime_type or "application/octet-stream")
        digest = hashlib.sha256(data).hexdigest()
        object_key = self._object_key(key)
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            await self.store._lock_notebook_export_scope(c)
            session = self.store._require_session(
                await self.store._session(c, session_id, lock=True)
            )
            await c.execute(
                "INSERT INTO enterprise.session_objects(tenant_id,owner_id,object_id,session_id,session_ref,incarnation,attachment_id,filename,mime_type,byte_size,sha256,state) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'candidate')",
                (
                    *self.store._owner,
                    key,
                    session_id,
                    session_id,
                    session["incarnation"],
                    attachment_id,
                    filename,
                    content_type,
                    len(data),
                    digest,
                ),
            )
            await c.execute(
                "INSERT INTO enterprise.resource_objects(tenant_id,owner_id,id,resource_kind,resource_id,bucket,object_key,content_hash,size_bytes,mime_type,state,created_by) VALUES(%s,%s,%s,'chat_attachment',%s,%s,%s,%s,%s,%s,'pending',%s)",
                (
                    *self.store._owner,
                    key,
                    session_id,
                    self.bucket,
                    object_key,
                    digest,
                    len(data),
                    content_type,
                    self.store._owner[1],
                ),
            )
        try:
            ref = await self._io(
                self.object_store.put_bytes,
                object_key,
                data,
                expected_sha256=digest,
                content_type=content_type,
            )
            if ref.key != object_key or ref.size_bytes != len(data) or ref.sha256 != digest:
                raise OSError("object-store verification mismatch")
            async with self.store.db.transaction(self.store.scope) as c:
                await self._authorized(c)
                await self.store._lock_notebook_export_scope(c)
                current = self.store._require_session(
                    await self.store._session(c, session_id, lock=True)
                )
                if current["incarnation"] != session["incarnation"]:
                    raise RuntimeError("session generation changed")
                result = await c.execute(
                    "UPDATE enterprise.session_objects SET state='ready',updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND object_id=%s AND state='candidate' AND session_ref=%s",
                    (*self.store._owner, key, session_id),
                )
                if result.rowcount != 1:
                    raise RuntimeError("attachment candidate was withdrawn")
                result = await c.execute(
                    "UPDATE enterprise.resource_objects SET state='ready',updated_at=now(),cleanup_error='' WHERE tenant_id=%s AND owner_id=%s AND id=%s AND state='pending'",
                    (*self.store._owner, key),
                )
                if result.rowcount != 1:
                    raise RuntimeError("resource object candidate was withdrawn")
        except BaseException:
            await self._record_cleanup_request(key, error="upload_publish_failed")
            raise
        return "/files/attachments/" + "/".join(
            quote(v, safe="") for v in (session_id, str(key), filename)
        )

    async def _visible_resource(self, session_id, key, filename):
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            row = await (
                await c.execute(
                    "SELECT r.object_key,r.size_bytes,r.content_hash,r.mime_type "
                    "FROM enterprise.session_objects o "
                    "JOIN enterprise.sessions s ON (s.tenant_id,s.owner_id,s.id,s.incarnation)=(o.tenant_id,o.owner_id,o.session_ref,o.incarnation) "
                    "JOIN enterprise.resource_objects r ON (r.tenant_id,r.owner_id,r.id)=(o.tenant_id,o.owner_id,o.object_id) "
                    "WHERE o.tenant_id=%s AND o.owner_id=%s AND o.object_id=%s AND o.session_ref=%s AND o.filename=%s AND o.state='ready' AND r.state='ready' AND NOT s.deleting "
                    "AND EXISTS(SELECT 1 FROM enterprise.message_objects m WHERE m.tenant_id=o.tenant_id AND m.owner_id=o.owner_id AND m.object_id=o.object_id)",
                    (*self.store._owner, key, session_id, filename),
                )
            ).fetchone()
            if row is None:
                raise FileNotFoundError("attachment not found")
            return row

    async def read_attachment(self, *, session_id, attachment_id, filename):
        key = UUID(str(attachment_id))
        filename = _coerce_filename(filename)
        # 先由 PG 可见性账本授权，再访问 ObjectStore；bucket/key 本身不授权。
        row = await self._visible_resource(session_id, key, filename)
        data = await self._io(self.object_store.get_bytes, self._blob_ref(row))
        if len(data) != row["size_bytes"] or hashlib.sha256(data).hexdigest() != row["content_hash"]:
            raise OSError("attachment integrity mismatch")
        return data

    def resolve_path(self, *, session_id, attachment_id, filename):
        del session_id, attachment_id, filename
        return None

    async def list_operations(self, *, after=None, limit=100):
        cursor = UUID(str(after)) if after else UUID(int=0)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("operation page limit must be between 1 and 1000")
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            return await (
                await c.execute(
                    "SELECT object_id,session_id,filename,state,attempts,last_error,EXISTS(SELECT 1 FROM enterprise.message_objects m WHERE m.tenant_id=o.tenant_id AND m.owner_id=o.owner_id AND m.object_id=o.object_id) AS referenced FROM enterprise.session_objects o WHERE tenant_id=%s AND owner_id=%s AND object_id>%s AND state<>'deleted' ORDER BY object_id LIMIT %s",
                    (*self.store._owner, cursor, limit),
                )
            ).fetchall()

    async def get_operation(self, object_id):
        key = UUID(str(object_id))
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            return await (
                await c.execute(
                    "SELECT object_id,session_id,filename,state,attempts,last_error,created_at,updated_at,EXISTS(SELECT 1 FROM enterprise.message_objects m WHERE m.tenant_id=o.tenant_id AND m.owner_id=o.owner_id AND m.object_id=o.object_id) AS referenced FROM enterprise.session_objects o WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                    (*self.store._owner, key),
                )
            ).fetchone()

    async def _record_cleanup_request(self, key, *, error=""):
        try:
            async with self.store.db.transaction(self.store.scope) as c:
                await c.execute(
                    "UPDATE enterprise.session_objects SET state='cleanup',last_error=%s,updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND object_id=%s AND state<>'deleted'",
                    (str(error or ""), *self.store._owner, key),
                )
                await c.execute(
                    "UPDATE enterprise.resource_objects SET state='delete-pending',cleanup_error=%s,updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND id=%s AND state<>'deleted'",
                    (str(error or ""), *self.store._owner, key),
                )
                await c.execute(
                    "INSERT INTO enterprise.resource_cleanup_jobs(tenant_id,owner_id,object_id,state,last_error) VALUES(%s,%s,%s,'pending',%s) ON CONFLICT(tenant_id,owner_id,object_id) DO UPDATE SET state='pending',last_error=EXCLUDED.last_error,updated_at=now()",
                    (*self.store._owner, key, str(error or "")),
                )
        except Exception:
            return

    async def withdraw_operation(self, object_id):
        key = UUID(str(object_id))
        if await self.get_operation(key) is None:
            raise FileNotFoundError("attachment operation not found")
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            await self.store._lock_notebook_export_scope(c)
            referenced = await (
                await c.execute(
                    "SELECT 1 FROM enterprise.message_objects WHERE tenant_id=%s AND owner_id=%s AND object_id=%s LIMIT 1",
                    (*self.store._owner, key),
                )
            ).fetchone()
            if referenced:
                raise ValueError("referenced attachment cannot be withdrawn")
            await c.execute(
                "UPDATE enterprise.session_objects SET state='cleanup',updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND object_id=%s AND state<>'deleted'",
                (*self.store._owner, key),
            )
        return await self.cleanup_pending()

    async def list_cleanup(self, limit=100):
        async with self.store.db.transaction(self.store.scope) as c:
            await self._authorized(c)
            return await (
                await c.execute(
                    "SELECT object_id,state,attempts,last_error FROM enterprise.session_objects WHERE tenant_id=%s AND owner_id=%s AND state='cleanup' ORDER BY created_at,object_id LIMIT %s",
                    (*self.store._owner, max(1, min(int(limit), 1000))),
                )
            ).fetchall()

    async def cleanup_pending(self, limit=100):
        completed, errors = 0, []
        for row in await self.list_cleanup(limit):
            key = row["object_id"]
            try:
                async with self.store.db.transaction(self.store.scope) as c:
                    await self._authorized(c)
                    await self.store._lock_notebook_export_scope(c)
                    current = await (
                        await c.execute(
                            "SELECT o.state,r.object_key,r.size_bytes,r.content_hash,r.mime_type "
                            "FROM enterprise.session_objects o "
                            "JOIN enterprise.resource_objects r ON (r.tenant_id,r.owner_id,r.id)=(o.tenant_id,o.owner_id,o.object_id) "
                            "WHERE o.tenant_id=%s AND o.owner_id=%s AND o.object_id=%s "
                            "AND NOT EXISTS(SELECT 1 FROM enterprise.message_objects m WHERE m.tenant_id=o.tenant_id AND m.owner_id=o.owner_id AND m.object_id=o.object_id) "
                            "FOR UPDATE OF o,r",
                            (*self.store._owner, key),
                        )
                    ).fetchone()
                    if not current or current["state"] != "cleanup":
                        continue
                    await c.execute(
                        "UPDATE enterprise.resource_objects SET state='delete-pending',updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND id=%s AND state<>'deleted'",
                        (*self.store._owner, key),
                    )
                    await c.execute(
                        "INSERT INTO enterprise.resource_cleanup_jobs(tenant_id,owner_id,object_id,state,last_error) VALUES(%s,%s,%s,'running','') ON CONFLICT(tenant_id,owner_id,object_id) DO UPDATE SET state='running',last_error='',updated_at=now()",
                        (*self.store._owner, key),
                    )
                await self._io(self.object_store.delete, self._blob_ref(current))
                async with self.store.db.transaction(self.store.scope) as c:
                    await c.execute(
                        "UPDATE enterprise.session_objects SET state='deleted',attempts=attempts+1,last_error='',updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND object_id=%s AND state='cleanup'",
                        (*self.store._owner, key),
                    )
                    await c.execute(
                        "UPDATE enterprise.resource_objects SET state='deleted',cleanup_error='',deleted_at=now(),updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                        (*self.store._owner, key),
                    )
                    await c.execute(
                        "UPDATE enterprise.resource_cleanup_jobs SET state='done',attempt=attempt+1,last_error='',updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND object_id=%s",
                        (*self.store._owner, key),
                    )
                completed += 1
            except Exception as exc:
                error = getattr(exc, "code", "") or type(exc).__name__
                async with self.store.db.transaction(self.store.scope) as c:
                    await c.execute(
                        "UPDATE enterprise.session_objects SET attempts=attempts+1,last_error=%s,updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND object_id=%s AND state='cleanup'",
                        (error, *self.store._owner, key),
                    )
                    await c.execute(
                        "UPDATE enterprise.resource_objects SET state='delete-pending',cleanup_error=%s,updated_at=now() WHERE tenant_id=%s AND owner_id=%s AND id=%s AND state<>'deleted'",
                        (error, *self.store._owner, key),
                    )
                    await c.execute(
                        "INSERT INTO enterprise.resource_cleanup_jobs(tenant_id,owner_id,object_id,state,attempt,last_error) VALUES(%s,%s,%s,'failed',1,%s) ON CONFLICT(tenant_id,owner_id,object_id) DO UPDATE SET state='failed',attempt=enterprise.resource_cleanup_jobs.attempt+1,last_error=EXCLUDED.last_error,updated_at=now()",
                        (*self.store._owner, key, error),
                    )
                errors.append({"object_id": str(key), "error": error})
        async with self.store.db.transaction(self.store.scope) as c:
            count = await (
                await c.execute(
                    "SELECT count(*) AS count FROM enterprise.session_objects WHERE tenant_id=%s AND owner_id=%s AND state='cleanup'",
                    self.store._owner,
                )
            ).fetchone()
        return {"completed": completed, "pending": count["count"], "errors": errors}

    async def delete_session(self, session_id):
        del session_id
        return await self.cleanup_pending()

    async def delete_attachment(self, session_id, attachment_id):
        key = UUID(str(attachment_id))
        async with self.store.db.transaction(self.store.scope) as c:
            await self.store._lock_notebook_export_scope(c)
            await c.execute(
                "UPDATE enterprise.session_objects o SET state='cleanup',updated_at=now() WHERE o.tenant_id=%s AND o.owner_id=%s AND o.object_id=%s AND o.session_id=%s AND NOT EXISTS(SELECT 1 FROM enterprise.message_objects m WHERE m.tenant_id=o.tenant_id AND m.owner_id=o.owner_id AND m.object_id=o.object_id)",
                (*self.store._owner, key, session_id),
            )
        return await self.cleanup_pending()
