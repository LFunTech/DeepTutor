"""PostgreSQL 学习聚合 Store；同步完整操作与异步 worker 共用相同实现。"""

from contextlib import contextmanager
import time

from deeptutor.learning.contracts import LearningConflictError, LearningStoreError
from deeptutor.learning.models import LearningProgress

from .base import StoreBase, jsonb, validate_id
from .bindings import LearningBindings
from .notebook import LearningNotebook
from .queries import LearningQueries
from .transaction import LearningTransaction


class PostgresLearningStore(LearningQueries, LearningBindings, LearningNotebook, StoreBase):
    def load(self, book_id):
        path = validate_id(book_id)
        with self._unit() as u:
            row = u._execute(
                "SELECT state,revision,updated_at FROM enterprise.mastery_paths WHERE tenant_id=%s AND owner_id=%s AND path_id=%s",
                (*u._owner, path),
            ).fetchone()
            return u._progress(row)

    @staticmethod
    def _progress(row):
        if row is None:
            return None
        progress = LearningProgress.model_validate(row["state"])
        progress.version, progress.updated_at = row["revision"], row["updated_at"]
        return progress

    def _sync_points(self, progress):
        ids = [kp.id for module in progress.modules for kp in module.knowledge_points]
        if len(ids) != len(set(ids)) or any(not key for key in ids):
            raise ValueError("knowledge point IDs must be nonempty and unique within path")
        self._execute(
            "UPDATE enterprise.mastery_knowledge_points SET active=false WHERE tenant_id=%s AND owner_id=%s AND path_id=%s AND NOT(kp_id=ANY(%s))",
            (*self._owner, progress.book_id, ids),
        )
        for key in ids:
            self._execute(
                """INSERT INTO enterprise.mastery_knowledge_points(tenant_id,owner_id,path_id,kp_id,active)
              VALUES(%s,%s,%s,%s,true) ON CONFLICT(tenant_id,owner_id,path_id,kp_id) DO UPDATE SET active=true""",
                (*self._owner, progress.book_id, key),
            )

    @contextmanager
    def transaction(self, book_id, *, create=False):
        path = validate_id(book_id)
        with self._unit(write=True) as u:
            if u._open_path is not None:
                raise LearningStoreError("nested learning transactions are not supported")
            u._assert_path_write(path)
            row = u._execute(
                "SELECT * FROM enterprise.mastery_paths WHERE tenant_id=%s AND owner_id=%s AND path_id=%s FOR UPDATE",
                (*u._owner, path),
            ).fetchone()
            created = row is None
            if created:
                if not create:
                    raise KeyError(path)
                progress = LearningProgress(book_id=path)
                u._execute(
                    "INSERT INTO enterprise.mastery_paths(tenant_id,owner_id,path_id,state,revision,created_at,updated_at) VALUES(%s,%s,%s,%s,0,%s,%s)",
                    (
                        *u._owner,
                        path,
                        jsonb(progress.model_dump(mode="json")),
                        progress.created_at,
                        progress.updated_at,
                    ),
                )
            else:
                progress = u._progress(row)
            tx = LearningTransaction(u, progress, created=created)
            u._open_path = path
            u._current_tx = tx
            try:
                yield tx
                u._check()
                if tx.progress.book_id != path:
                    raise ValueError("transaction cannot move aggregate to another path")
                if tx.changed:
                    revision, now = tx.base_revision + 1, time.time()
                    tx.progress.version, tx.progress.updated_at = revision, now
                    u._sync_points(tx.progress)
                    result = u._execute(
                        "UPDATE enterprise.mastery_paths SET state=%s,revision=%s,updated_at=%s WHERE tenant_id=%s AND owner_id=%s AND path_id=%s AND revision=%s",
                        (
                            jsonb(tx.progress.model_dump(mode="json")),
                            revision,
                            now,
                            *u._owner,
                            path,
                            tx.base_revision,
                        ),
                    )
                    if result.rowcount != 1:
                        raise LearningConflictError(path, tx.base_revision, u.load(path).version)
                    for name, payload, session_id, turn_id in tx.events:
                        u._execute(
                            "INSERT INTO enterprise.mastery_events(tenant_id,owner_id,path_id,revision,event_type,payload,session_id,turn_id,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                *u._owner,
                                path,
                                revision,
                                name,
                                jsonb(payload),
                                session_id,
                                turn_id,
                                now,
                            ),
                        )
                    u._signals.append(
                        (path, revision, tx.events[-1][0] if tx.events else "topic.changed")
                    )
            finally:
                tx._lease.active = False
                u._open_path = None
                u._current_tx = None

    def mutate(self, book_id, mutation, *, create=False):
        with self.transaction(book_id, create=create) as tx:
            result = mutation(tx)
        return tx.progress, result

    def save(self, progress):
        # 输入对象只在最终提交确认后推进，失败/取消/未知提交保持调用者版本不变。
        with self._unit(write=True) as u:
            with u.transaction(progress.book_id, create=True) as tx:
                if progress.version != tx.base_revision:
                    raise LearningConflictError(
                        progress.book_id, progress.version, tx.base_revision
                    )
                tx.progress = progress.model_copy(deep=True)
                tx.touch()
                if tx.base_revision:
                    tx.emit("path.saved")

            def confirmed():
                progress.version = tx.progress.version
                progress.updated_at = tx.progress.updated_at

            u._effects.append(confirmed)

    def delete(self, book_id):
        path = validate_id(book_id)
        with self._unit(write=True) as u:
            u._assert_path_write(path)
            lease = u._lease(path)
            if lease is not None and lease.kind == "operation":
                u.finish_path_operation(lease)
            u._execute(
                "DELETE FROM enterprise.mastery_paths WHERE tenant_id=%s AND owner_id=%s AND path_id=%s",
                (*u._owner, path),
            )
            u._signals.append((path, 0, "topic.deleted"))

    def exists(self, book_id):
        return self.load(book_id) is not None
