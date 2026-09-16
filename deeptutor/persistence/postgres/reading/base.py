"""同步领域完整操作单位、owner 锁、lease 与有界 worker façade。"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from functools import wraps
import inspect
import json
import re

import psycopg

from deeptutor.persistence.postgres._ownership import Lease
from deeptutor.persistence.postgres.connection import SyncDatabase
from deeptutor.persistence.postgres.scope import TenantScope
from deeptutor.persistence.postgres.session_statements import session_statement_contract
from deeptutor.reading.catalog_contracts import ReadingConflictError, ReadingReferenceError
from deeptutor.reading.models import ReadingError

SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def validate_id(value, kind="reading"):
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ReadingError(f"invalid {kind} ID")
    return value


def complete(result):
    if inspect.isawaitable(result) or inspect.isgenerator(result) or inspect.isasyncgen(result):
        if inspect.iscoroutine(result) or inspect.isgenerator(result):
            result.close()
        raise TypeError("reading callback must complete synchronously")
    return result


def operation(*, write=False):
    def decorate(fn):
        @wraps(fn)
        def run(self, *args, **kwargs):
            with self._unit(write=write) as u:
                return fn(u, *args, **kwargs)

        return run

    return decorate


class StoreBase:
    def __init__(self, database: SyncDatabase, scope: TenantScope):
        if not isinstance(database, SyncDatabase) or not isinstance(scope, TenantScope):
            raise TypeError("SyncDatabase and trusted TenantScope required")
        self.db, self.scope = database, scope
        self._owner = (scope.tenant_id, scope.user_id)
        self._connection = self._lease = None
        self._failed = self._locked = False
        self._content_guards = 0

    def _bind(self, connection):
        u = type(self)(self.db, self.scope)
        u._connection, u._lease = connection, Lease()
        return u

    def _check(self):
        if self._lease is not None:
            self._lease.check()
        if self._failed:
            raise ReadingError("reading unit is poisoned; transaction must roll back")

    def _lock_owner(self):
        if not self._locked:
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
                "use AsyncReadingCatalogStore.run; synchronous Store cannot block event loop"
            )
        u = None
        try:
            with self.db.transaction(self.scope) as connection:
                u = self._bind(connection)
                with u._unit(write=write):
                    yield u
                u._finish()
        except psycopg.errors.ForeignKeyViolation as exc:
            raise ReadingReferenceError("reading reference missing or still in use") from exc
        finally:
            if u is not None:
                u._lease.active = False

    def _finish(self):
        self._check()
        if self._content_guards:
            raise ReadingError("content deletion guard still open")

    def _execute(self, sql, params=()):
        self._check()
        try:
            return self._connection.execute(sql, params)
        except psycopg.errors.ForeignKeyViolation as exc:
            self._failed = True
            raise ReadingReferenceError("reading reference missing or still in use") from exc
        except BaseException:
            self._failed = True
            raise

    @staticmethod
    def _cas(row, expected_version):
        actual = row["version"] if row else None
        if expected_version is not None and (
            type(expected_version) is not int or expected_version != actual
        ):
            raise ReadingConflictError(expected_version, actual)

    @operation(write=True)
    def compose(self, callback):
        """给后续 Session 专用操作传同连接；不新开事务、不绕过 Session 领域校验。

        callback(unit, execution) 必须同步完整完成；execution 只接收封闭的
        SessionStatement 与数据参数，不接受 SQL 文本或调用方指定的 scope。
        这里只组合行级语句；Session 的完整校验/审计仍由其领域算法负责。
        """
        return complete(callback(self, SessionExecution(self)))


class SessionExecution:
    """仅供 Session 专用 SQL 单位组合：没有原生 connection/cursor/生命周期出口。"""

    __slots__ = ("_unit",)

    def __init__(self, unit):
        self._unit = unit

    def _workflow(self, workflow):
        with self._unit._unit(write=True):
            value = None
            while True:
                try:
                    step = workflow.send(value)
                except StopIteration as result:
                    return result.value
                cursor = self._execute_step(step.statement, step.params)
                value = cursor.fetchall() if step.many else cursor.fetchone()

    def create_session(self, title=None, session_id=None, preferences=None):
        from ..session_workflows import create_session

        return self._workflow(create_session(title, session_id, preferences))

    def update_session_title(self, session_id, title, *, expected_version=None):
        from ..session_workflows import update_title

        return self._workflow(update_title(session_id, title, expected_version))

    def update_session_preferences(self, session_id, preferences, *, expected_version=None):
        from ..session_workflows import update_preferences

        return self._workflow(update_preferences(session_id, preferences, expected_version))

    def delete_session(self, session_id, *, deletion_token=None):
        from ..session_workflows import delete_session

        return self._workflow(delete_session(session_id, deletion_token))

    def execute(self, statement, params=()):
        from ..session_statements import SessionStatement

        # 对外保持 1.18 三种 row 原语；新生命周期步骤只能由完整领域算法调度。
        with self._unit._unit(write=True):
            if type(statement) is not SessionStatement or statement not in (
                SessionStatement.CREATE_ROW,
                SessionStatement.GET_ROW,
                SessionStatement.LOCK_ROW,
            ):
                raise ReadingError("only public SessionStatement row operations are accepted")
            return self._execute_step(statement, params)

    def _execute_step(self, statement, params=()):
        # 必须在单位内校验：即使 callback 吞掉拒绝，也使整个外层事务 poison。
        with self._unit._unit(write=True) as unit:
            try:
                sql, arity = session_statement_contract(statement)
            except ValueError as exc:
                raise ReadingError(str(exc)) from exc
            if type(params) not in (tuple, list):
                raise ReadingError("SessionStatement parameters must be a tuple/list of strings")
            values = tuple(params)
            if len(values) != arity or any(type(value) is not str for value in values):
                raise ReadingError("SessionStatement parameter count/type mismatch")
            # scope 仅来自绑定 unit。普通参数经驱动绑定，不能变成语句/事务控制。
            return SessionResult(unit, unit._execute(sql, (*unit._owner, *values)))


class SessionResult:
    __slots__ = ("_unit", "_result")

    def __init__(self, unit, result):
        self._unit, self._result = unit, result

    def fetchone(self):
        with self._unit._unit() as _:
            return self._result.fetchone()

    def fetchall(self):
        with self._unit._unit() as _:
            return self._result.fetchall()

    @property
    def rowcount(self):
        self._unit._check()
        return self._result.rowcount


class AsyncReadingCatalogStore:
    def __init__(self, database, scope):
        from .store import PostgresReadingCatalogStore

        self._store = PostgresReadingCatalogStore(database, scope)

    async def run(self, callback):
        def work(connection):
            u = self._store._bind(connection)
            try:
                result = complete(callback(u))
                u._finish()
                return result
            finally:
                u._lease.active = False

        try:
            return await self._store.db.run(self._store.scope, work)
        except psycopg.errors.ForeignKeyViolation as exc:
            raise ReadingReferenceError("reading reference missing or still in use") from exc
