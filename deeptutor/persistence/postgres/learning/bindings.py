"""路径会话关系及 typed turn/本人operation租约；无 TTL 抢占。"""

import time
import uuid

from deeptutor.learning.contracts import LearningStoreError, PathLeaseConflictError

from .authority import ExecutionAuthority, lease_from_row
from .base import validate_id


class LearningBindings:
    def _authority(self):
        if (
            not isinstance(self.authority, ExecutionAuthority)
            or self.authority.resource != self.db.resource
        ):
            raise RuntimeError("live executor authority required")
        self.authority.check(self._connection)
        return self.authority

    def _lease(self, path):
        return lease_from_row(
            self._execute(
                "SELECT * FROM enterprise.mastery_path_leases WHERE tenant_id=%s AND owner_id=%s AND path_id=%s",
                (*self._owner, path),
            ).fetchone()
        )

    def _owns(self, lease):
        a = self.authority
        return (
            isinstance(a, ExecutionAuthority)
            and lease.execution_id == a.execution_id
            and lease.executor_pid == a.pid
            and lease.executor_resource == a.resource
            and (
                lease.kind == "turn"
                and lease.turn_id == a.turn_id
                and lease.session_id == a.session_id
                and lease.fencing_token == a.fencing_token
                or lease.kind == "operation"
                and lease.operation_id == a.operation_id
                and lease.version == a.operation_version
            )
        )

    def _assert_path_write(self, path, *, release=False):
        if self.authority is not None:
            a = self._authority()
            if a.turn_id and not release:
                row = self._execute(
                    "SELECT status FROM enterprise.turns WHERE tenant_id=%s AND user_id=%s AND id=%s",
                    (*self._owner, a.turn_id),
                ).fetchone()
                if row["status"] not in ("queued", "running", "waiting_input"):
                    raise RuntimeError("terminal turn cannot mutate learning state")
        lease = self._lease(path)
        if lease is not None and not self._owns(lease):
            raise PathLeaseConflictError(lease)
        if self.authority is not None and self.authority.operation_id is not None:
            row = self._execute(
                "SELECT status,version FROM enterprise.mastery_path_operations WHERE tenant_id=%s AND owner_id=%s AND path_id=%s AND operation_id=%s",
                (*self._owner, path, self.authority.operation_id),
            ).fetchone()
            if (
                not row
                or row["status"] != "active"
                or row["version"] != self.authority.operation_version
                or lease is None
            ):
                raise RuntimeError("operation authority is no longer active")

    def get_path_lease(self, path_id):
        with self._unit() as u:
            return u._lease(validate_id(path_id))

    def bind_session(self, path_id, session_id, *, owns_path=False):
        path = validate_id(path_id)
        session_id = str(session_id or "").strip()
        if not session_id:
            raise ValueError("session_id must not be empty")
        with self._unit(write=True) as u:
            session = u._execute(
                "SELECT deleting FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s AND id=%s FOR UPDATE",
                (*u._owner, session_id),
            ).fetchone()
            if session is None or session["deleting"]:
                raise ValueError("session unavailable for learning binding")
            u._assert_path_write(path)
            previous = u.path_id_for_session(session_id)
            if previous and previous != path:
                u._assert_path_write(previous)
            with u.transaction(path, create=True):
                pass
            now = time.time()
            u._execute(
                """INSERT INTO enterprise.mastery_path_sessions(tenant_id,owner_id,path_id,session_id,created_at,last_seen_at)
              VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,owner_id,session_id)
              DO UPDATE SET path_id=EXCLUDED.path_id,last_seen_at=EXCLUDED.last_seen_at""",
                (*u._owner, path, session_id, now, now),
            )
            if owns_path:
                u._execute(
                    "UPDATE enterprise.mastery_paths SET creator_session_id=%s,creator_assigned=true WHERE tenant_id=%s AND owner_id=%s AND path_id=%s AND NOT creator_assigned",
                    (session_id, *u._owner, path),
                )
            u._signals.append((path, u.load(path).version, "session.bound"))
            if previous and previous != path:
                u._signals.append((previous, u.load(previous).version, "session.released"))

    def list_session_ids(self, path_id):
        with self._unit() as u:
            rows = u._execute(
                "SELECT session_id FROM enterprise.mastery_path_sessions WHERE tenant_id=%s AND owner_id=%s AND path_id=%s ORDER BY last_seen_at DESC,session_id DESC LIMIT 1001",
                (*u._owner, validate_id(path_id)),
            ).fetchall()
            return u._compat([row["session_id"] for row in rows])

    def path_id_for_session(self, session_id):
        if not str(session_id or "").strip():
            return ""
        with self._unit() as u:
            row = u._execute(
                "SELECT path_id FROM enterprise.mastery_path_sessions WHERE tenant_id=%s AND owner_id=%s AND session_id=%s",
                (*u._owner, session_id),
            ).fetchone()
            return row["path_id"] if row else ""

    def detach_session(self, session_id, *, delete_owned_orphans=True):
        if not str(session_id or "").strip():
            return []
        with self._unit(write=True) as u:
            owned = u._execute(
                "SELECT path_id FROM enterprise.mastery_paths WHERE tenant_id=%s AND owner_id=%s AND creator_session_id=%s ORDER BY path_id LIMIT 1001",
                (*u._owner, session_id),
            ).fetchall()
            u._compat(owned)
            linked = u.path_id_for_session(session_id)
            for path in sorted({r["path_id"] for r in owned} | ({linked} if linked else set())):
                u._assert_path_write(path, release=True)
            leases = u._execute(
                "SELECT path_id FROM enterprise.mastery_path_leases WHERE tenant_id=%s AND owner_id=%s AND session_id=%s",
                (*u._owner, session_id),
            ).fetchall()
            for row in leases:
                u.release_path_lease(row["path_id"])
            u._execute(
                "DELETE FROM enterprise.mastery_path_sessions WHERE tenant_id=%s AND owner_id=%s AND session_id=%s",
                (*u._owner, session_id),
            )
            deleted = []
            for row in owned:
                path = row["path_id"]
                progress = u.load(path)
                has_points = any(m.knowledge_points for m in progress.modules)
                remaining = u._execute(
                    "SELECT 1 FROM enterprise.mastery_path_sessions WHERE tenant_id=%s AND owner_id=%s AND path_id=%s LIMIT 1",
                    (*u._owner, path),
                ).fetchone()
                if delete_owned_orphans and not has_points and not remaining:
                    u.delete(path)
                    deleted.append(path)
                else:
                    u._execute(
                        "UPDATE enterprise.mastery_paths SET creator_session_id=NULL WHERE tenant_id=%s AND owner_id=%s AND path_id=%s",
                        (*u._owner, path),
                    )
            if linked and linked not in deleted:
                u._signals.append((linked, u.load(linked).version, "session.released"))
            return deleted

    def detach_session_history(self, session_id, *, deletion_token):
        """仅在已停止的同一删除生命周期内解绑历史；当前业务来源不在此处解绑。"""
        with self._unit(write=True) as u:
            authority = u._authority()
            if authority.turn_id or authority.operation_id:
                raise RuntimeError("unbound executor authority required for history detach")
            session = u._execute(
                "SELECT deleting,deletion_token FROM enterprise.sessions "
                "WHERE tenant_id=%s AND owner_id=%s AND id=%s FOR UPDATE",
                (*u._owner, session_id),
            ).fetchone()
            if session is None:
                return False
            if (
                not session["deleting"]
                or not deletion_token
                or str(session["deletion_token"]) != str(deletion_token)
            ):
                raise RuntimeError("Session deletion token/generation changed")
            if u._execute(
                "SELECT 1 FROM enterprise.turns WHERE tenant_id=%s AND user_id=%s AND session_id=%s "
                "AND status IN ('queued','running','waiting_input') LIMIT 1",
                (*u._owner, session_id),
            ).fetchone():
                raise LearningStoreError("active execution cannot detach learning history")
            paths = u._execute(
                "SELECT path_id FROM enterprise.mastery_interactions WHERE tenant_id=%s AND owner_id=%s AND session_id=%s "
                "UNION SELECT path_id FROM enterprise.mastery_events WHERE tenant_id=%s AND owner_id=%s AND session_id=%s "
                "ORDER BY path_id LIMIT 1001",
                (*u._owner, session_id, *u._owner, session_id),
            ).fetchall()
            u._compat(paths)
            for row in paths:
                path = row["path_id"]
                lease = u._lease(path)
                if lease is not None:
                    raise PathLeaseConflictError(lease)
                with u.transaction(path) as tx:
                    for table, column in (
                        ("mastery_interactions", "result"),
                        ("mastery_events", "payload"),
                    ):
                        # 表名/JSON 列仅来自上面的封闭常量；保留历史正文及原始来源。
                        u._execute(
                            f"UPDATE enterprise.{table} SET {column}={column} || "
                            "jsonb_build_object('detached_provenance',jsonb_build_object('session_id',session_id,'turn_id',turn_id)), "
                            "session_id='',turn_id='' WHERE tenant_id=%s AND owner_id=%s AND path_id=%s AND session_id=%s",
                            (*u._owner, path, session_id),
                        )
                    tx.emit(
                        "session.history_detached",
                        {"detached_provenance": {"session_id": session_id}},
                    )
            return True

    def acquire_path_lease(self, path_id, session_id, turn_id, *, bind_session=True):
        path = validate_id(path_id)
        with self._unit(write=True) as u:
            a = u._authority()
            if not a.turn_id or (a.session_id, a.turn_id) != (session_id, turn_id):
                raise RuntimeError(
                    "typed turn authority required; management must use begin_path_operation"
                )
            u._assert_path_write(path)
            existing = u._lease(path)
            if existing:
                return existing
            with u.transaction(path, create=True):
                pass
            if bind_session:
                u.bind_session(path, session_id)
            now = time.time()
            u._execute(
                """INSERT INTO enterprise.mastery_path_leases
              (tenant_id,owner_id,path_id,kind,session_id,turn_id,executor_resource,execution_id,executor_pid,worker_id,fencing_token,version,acquired_at)
              VALUES(%s,%s,%s,'turn',%s,%s,%s,%s,%s,%s,%s,1,%s)""",
                (
                    *u._owner,
                    path,
                    session_id,
                    turn_id,
                    a.resource,
                    a.execution_id,
                    a.pid,
                    a.execution_id,
                    a.fencing_token,
                    now,
                ),
            )
            return u._lease(path)

    def release_leases_for_turn(self, turn_id):
        if not str(turn_id or "").strip():
            return ""
        with self._unit(write=True) as u:
            a = u._authority()
            if a.turn_id != turn_id:
                raise RuntimeError("turn authority mismatch")
            row = u._execute(
                "SELECT path_id FROM enterprise.mastery_path_leases WHERE tenant_id=%s AND owner_id=%s AND turn_id=%s",
                (*u._owner, turn_id),
            ).fetchone()
            if not row:
                return ""
            u.release_path_lease(row["path_id"], turn_id=turn_id)
            return row["path_id"]

    def release_path_lease(self, path_id, *, turn_id=None):
        path = validate_id(path_id)
        with self._unit(write=True) as u:
            u._authority()
            lease = u._lease(path)
            if not lease or (turn_id is not None and lease.turn_id != turn_id):
                return False
            u._assert_path_write(path, release=True)
            if lease.kind != "turn":
                raise LearningStoreError("operation lease requires finish_path_operation")
            u._execute(
                "DELETE FROM enterprise.mastery_path_leases WHERE tenant_id=%s AND owner_id=%s AND path_id=%s",
                (*u._owner, path),
            )
            return True

    def begin_path_operation(self, path_id):
        path = validate_id(path_id)
        with self._unit(write=True) as u:
            a = u._authority()
            if a.turn_id or a.operation_id:
                raise RuntimeError("unbound executor authority required for management operation")
            u._assert_path_write(path)
            with u.transaction(path, create=True):
                pass
            operation_id, now = str(uuid.uuid4()), time.time()
            u._execute(
                """INSERT INTO enterprise.mastery_path_operations
              (tenant_id,owner_id,path_id,path_ref,operation_id,executor_resource,execution_id,executor_pid,status,version,created_at,updated_at)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'active',1,%s,%s)""",
                (*u._owner, path, path, operation_id, a.resource, a.execution_id, a.pid, now, now),
            )
            u._execute(
                """INSERT INTO enterprise.mastery_path_leases
              (tenant_id,owner_id,path_id,kind,operation_id,executor_resource,execution_id,executor_pid,version,acquired_at)
              VALUES(%s,%s,%s,'operation',%s,%s,%s,%s,1,%s)""",
                (*u._owner, path, operation_id, a.resource, a.execution_id, a.pid, now),
            )
            return u._lease(path)

    def get_path_operation(self, operation_id):
        operation_id = str(uuid.UUID(str(operation_id)))
        with self._unit() as u:
            row = u._execute(
                "SELECT * FROM enterprise.mastery_path_operations WHERE tenant_id=%s AND owner_id=%s AND operation_id=%s",
                (*u._owner, operation_id),
            ).fetchone()
            if row:
                row["operation_id"] = str(row["operation_id"])
                row["execution_id"] = str(row["execution_id"])
            return row

    def finish_path_operation(self, lease, *, failed=False):
        with self._unit(write=True) as u:
            u._authority()
            if not u._owns(lease) or lease.kind != "operation":
                raise RuntimeError("operation authority mismatch")
            row = u.get_path_operation(lease.operation_id)
            if (
                not row
                or row["execution_id"] != lease.execution_id
                or row["path_id"] != lease.path_id
            ):
                raise RuntimeError("operation authority mismatch")
            if row["status"] in ("completed", "failed") and row["version"] == lease.version + 1:
                return
            u._assert_path_write(lease.path_id, release=True)
            u._execute(
                "DELETE FROM enterprise.mastery_path_leases WHERE tenant_id=%s AND owner_id=%s AND path_id=%s AND operation_id=%s AND version=%s",
                (*u._owner, lease.path_id, lease.operation_id, lease.version),
            )
            result = u._execute(
                "UPDATE enterprise.mastery_path_operations SET status=%s,version=version+1,updated_at=%s WHERE tenant_id=%s AND owner_id=%s AND operation_id=%s AND status='active' AND version=%s",
                (
                    "failed" if failed else "completed",
                    time.time(),
                    *u._owner,
                    lease.operation_id,
                    lease.version,
                ),
            )
            if result.rowcount != 1:
                raise RuntimeError("operation version conflict")

    def recover_stopped_execution(self, execution_id):
        """仅清理由原 ExecutorLease.confirm_stopped 已确认的旧执行者；绝无 TTL 推断。"""
        with self._unit(write=True) as u:
            a = u._authority()
            if a.turn_id or a.operation_id or execution_id == a.execution_id:
                raise RuntimeError("recovery requires a new unbound executor")
            # 新执行锁排除旧进程仍存活；旧登记若还是 active 则不能被学习层抢占。
            active = u._execute(
                "SELECT 1 FROM enterprise.executor_state WHERE execution_id=%s AND status='active'",
                (execution_id,),
            ).fetchone()
            if active:
                raise RuntimeError("previous executor must be confirmed stopped before recovery")
            rows = u._execute(
                "SELECT * FROM enterprise.mastery_path_leases WHERE tenant_id=%s AND owner_id=%s AND execution_id=%s ORDER BY path_id LIMIT 1001",
                (*u._owner, execution_id),
            ).fetchall()
            u._compat(rows)
            for row in rows:
                if row["kind"] == "turn":
                    turn = u._execute(
                        "SELECT status FROM enterprise.turns WHERE tenant_id=%s AND user_id=%s AND id=%s FOR UPDATE",
                        (*u._owner, row["turn_id"]),
                    ).fetchone()
                    if turn["status"] not in ("completed", "cancelled", "failed"):
                        raise RuntimeError(
                            "turn must be durably interrupted before learning recovery"
                        )
            u._execute(
                "UPDATE enterprise.mastery_path_operations SET status='interrupted',version=version+1,updated_at=%s WHERE tenant_id=%s AND owner_id=%s AND execution_id=%s AND status='active'",
                (time.time(), *u._owner, execution_id),
            )
            u._execute(
                "DELETE FROM enterprise.mastery_path_leases WHERE tenant_id=%s AND owner_id=%s AND execution_id=%s",
                (*u._owner, execution_id),
            )
            return [row["path_id"] for row in rows]
