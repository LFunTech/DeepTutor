"""从已持真实 PG 执行锁的能力派生学习执行权，不接受客户端 worker/fence 证明。"""

from dataclasses import dataclass
from typing import Literal

from deeptutor.learning.models import MasteryPathLease
from deeptutor.persistence.postgres.executor import ExecutorLease, lock_key


class PathLease(MasteryPathLease):
    kind: Literal["turn", "operation"]
    operation_id: str | None = None
    executor_resource: str
    execution_id: str
    executor_pid: int
    worker_id: str | None = None
    fencing_token: int | None = None
    version: int


def lease_from_row(row):
    if row is None:
        return None
    values = dict(row)
    values["session_id"] = values["session_id"] or ""
    values["turn_id"] = values["turn_id"] or ""
    values["execution_id"] = str(values["execution_id"])
    values["operation_id"] = str(values["operation_id"]) if values["operation_id"] else None
    return PathLease.model_validate(values)


@dataclass(frozen=True, init=False)
class ExecutionAuthority:
    executor: ExecutorLease
    resource: str
    execution_id: str
    pid: int
    session_id: str
    turn_id: str
    fencing_token: int | None
    operation_id: str | None
    operation_version: int | None

    def __init__(self, executor):
        if (
            not isinstance(executor, ExecutorLease)
            or not executor.active
            or executor.connection is None
            or executor.connection.closed
        ):
            raise RuntimeError("live ExecutorLease authority required")
        for key, value in dict(
            executor=executor,
            resource=executor.resource,
            execution_id=executor.execution_id,
            pid=executor.connection.info.backend_pid,
            session_id="",
            turn_id="",
            fencing_token=None,
            operation_id=None,
            operation_version=None,
        ).items():
            object.__setattr__(self, key, value)

    def _copy(self, **changes):
        result = object.__new__(type(self))
        for key in self.__dataclass_fields__:
            object.__setattr__(result, key, changes.get(key, getattr(self, key)))
        return result

    @classmethod
    async def for_turn(cls, executor, database, scope, session_id, turn_id):
        authority = cls(executor)
        if authority.resource != database.resource:
            raise ValueError("executor/database resource mismatch")

        def read(c):
            authority.check(c)
            row = c.execute(
                "SELECT owner_id,fencing_token,status FROM enterprise.turns WHERE tenant_id=%s AND user_id=%s AND session_id=%s AND id=%s FOR SHARE",
                (scope.tenant_id, scope.user_id, session_id, turn_id),
            ).fetchone()
            if (
                not row
                or row["owner_id"] != authority.execution_id
                or row["status"] not in ("queued", "running", "waiting_input")
            ):
                raise RuntimeError("turn execution authority unavailable")
            return row["fencing_token"]

        fence = await database.run(scope, read)
        return authority._copy(session_id=session_id, turn_id=turn_id, fencing_token=fence)

    def for_operation(self, lease):
        if (
            not isinstance(lease, PathLease)
            or lease.kind != "operation"
            or lease.execution_id != self.execution_id
            or lease.executor_resource != self.resource
        ):
            raise RuntimeError("operation execution authority mismatch")
        return self._copy(operation_id=lease.operation_id, operation_version=lease.version)

    def check(self, connection):
        if (
            not self.executor.active
            or self.executor.connection is None
            or self.executor.connection.closed
            or self.executor.execution_id != self.execution_id
        ):
            raise RuntimeError("executor authority unavailable")
        # 行 SHARE 锁持续到提交，登记不能在写事务中途被接管；还检查相同backend实际持锁。
        row = connection.execute(
            "SELECT execution_id FROM enterprise.executor_state WHERE resource=%s AND execution_id=%s AND status='active' FOR SHARE",
            (self.resource, self.execution_id),
        ).fetchone()
        key = lock_key(self.resource) & ((1 << 64) - 1)
        locked = connection.execute(
            "SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=%s AND classid=%s AND objid=%s AND objsubid=1 AND granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database())",
            (self.pid, key >> 32, key & 0xFFFFFFFF),
        ).fetchone()
        if not row or not locked:
            raise RuntimeError("executor authority unavailable")
        if self.turn_id:
            row = connection.execute(
                "SELECT owner_id,fencing_token FROM enterprise.turns WHERE tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND user_id=current_setting('app.user_id',true) AND session_id=%s AND id=%s FOR SHARE",
                (self.session_id, self.turn_id),
            ).fetchone()
            # 已完成 turn 的 finally 仍可释放，但不能借此重新取得租约或继续教学写入。
            if (
                not row
                or row["owner_id"] != self.execution_id
                or row["fencing_token"] != self.fencing_token
            ):
                raise RuntimeError("turn fencing authority changed")
