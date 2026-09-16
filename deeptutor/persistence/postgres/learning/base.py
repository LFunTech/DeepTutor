"""连接绑定完整 unit；作用域、失效、poison 与提交后效果只在这里管理。"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import inspect
import json

import psycopg
from psycopg.types.json import Jsonb

from deeptutor.learning.contracts import LearningReferenceError, LearningStoreError
from deeptutor.learning.event_hub import publish_topic_signal
from deeptutor.persistence.postgres._ownership import Lease
from deeptutor.persistence.postgres.connection import CommitCompletedAfterCancellation, SyncDatabase
from deeptutor.persistence.postgres.scope import TenantScope


def jsonb(value):
    return Jsonb(value, dumps=lambda obj: json.dumps(obj, ensure_ascii=False, allow_nan=False))


def validate_id(value):
    value = str(value or "").strip()
    if not value or any(part in value for part in ("/", "\\", "..", ":")):
        raise ValueError("invalid mastery path ID")
    return value


def redact(value):
    if isinstance(value, dict):
        return {
            key: redact(item)
            for key, item in value.items()
            if key not in {"expected_answer", "correct_answer", "explanation"}
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class StoreBase:
    def __init__(self, database: SyncDatabase, scope: TenantScope, *, authority=None):
        if not isinstance(database, SyncDatabase) or not isinstance(scope, TenantScope):
            raise TypeError("SyncDatabase and trusted TenantScope required")
        self.db, self.scope, self.authority = database, scope, authority
        self._owner = (scope.tenant_id, scope.user_id)
        self._connection = None
        self._handle_lease = None
        self._failed = False
        self._signals = []
        self._effects = []
        self._locked = False
        self._open_path = None

    @property
    def event_scope(self):
        # resource 来自部署的 canonical 配置，不使用 DSN 密文、目录或 SQLite 路径。
        return (
            "pg-learning:"
            + hashlib.sha256(
                json.dumps([self.db.resource, *self._owner], separators=(",", ":")).encode()
            ).hexdigest()
        )

    def _bind(self, connection):
        unit = type(self)(self.db, self.scope, authority=self.authority)
        unit._connection = connection
        unit._handle_lease = Lease()
        return unit

    def _check(self):
        if self._handle_lease is not None:
            self._handle_lease.check()
        if self._failed:
            raise LearningStoreError("learning unit is poisoned; transaction must roll back")

    def _check_session_reference(self, session_id):
        if not session_id:
            return
        row = self._execute(
            "SELECT deleting FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s AND id=%s FOR UPDATE",
            (*self._owner, session_id),
        ).fetchone()
        if row is None or row["deleting"]:
            self._failed = True
            raise LearningReferenceError("session unavailable for learning reference")

    def _lock_owner(self):
        if not self._locked:
            # 与 notebook 写入相同的 owner advisory 锁：跨域修改统一先 owner 再 path/turn/FK。
            key = json.dumps(
                ["deeptutor-notebook-export", *self._owner],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            self._connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
            self._locked = True

    @contextmanager
    def _unit(self, *, write=False):
        if self._connection is not None:
            self._check()
            try:
                if write:
                    self._lock_owner()
                yield self
            except BaseException:
                self._failed = True
                raise
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "use AsyncLearningStore.run; synchronous Store cannot block event loop"
            )
        unit = None
        try:
            with self.db.transaction(self.scope) as connection:
                unit = self._bind(connection)
                with unit._unit(write=write):
                    yield unit
                unit._finish()
        finally:
            if unit is not None:
                unit._handle_lease.active = False
        unit._publish()

    def _finish(self):
        self._check()
        if self._open_path is not None:
            raise LearningStoreError("learning transaction context is still open")
        if self.authority is not None:
            self.authority.check(self._connection)

    def _publish(self):
        for effect in self._effects:
            effect()
        for path, revision, reason in self._signals:
            publish_topic_signal(path, revision, reason, scope=self.event_scope)

    def _execute(self, sql, params=()):
        self._check()
        try:
            return self._connection.execute(sql, params)
        except psycopg.errors.ForeignKeyViolation as exc:
            self._failed = True
            raise LearningReferenceError("learning reference missing or still in use") from exc
        except BaseException:
            self._failed = True
            raise


class AsyncLearningStore:
    """每个 run 是完整且有界的事务；callback 得到真实同步领域 Store。

    1.17 的服务接线形式：await store.run(lambda unit: LearningService(unit).method(...))。
    不把同步 contextmanager 跨 await/thread yield；callback 内禁止外部副作用与嵌套 run。
    """

    def __init__(self, database, scope, *, authority=None):
        from .store import PostgresLearningStore

        self._store = PostgresLearningStore(database, scope, authority=authority)
        self.event_scope = self._store.event_scope

    async def run(self, operation):
        unit = None

        def work(connection):
            nonlocal unit
            unit = self._store._bind(connection)
            try:
                result = operation(unit)
                if (
                    inspect.isawaitable(result)
                    or inspect.isgenerator(result)
                    or inspect.isasyncgen(result)
                ):
                    if inspect.iscoroutine(result) or inspect.isgenerator(result):
                        result.close()
                    raise TypeError("learning callback must complete synchronously")
                unit._finish()
                return result
            finally:
                unit._handle_lease.active = False

        try:
            result = await self._store.db.run(self._store.scope, work)
        except CommitCompletedAfterCancellation:
            unit._publish()
            raise
        else:
            unit._publish()
            return result
