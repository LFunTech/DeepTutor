"""Learning 的显式 PG 应用边界：可信 scope、完整 worker unit 与执行权。"""

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar

from deeptutor.persistence.postgres.connection import CommitCompletedAfterCancellation
from deeptutor.persistence.postgres.learning import AsyncLearningStore, ExecutionAuthority

_bound: ContextVar["LearningRuntime | None"] = ContextVar("learning_runtime", default=None)


class LearningProviderUnavailable(RuntimeError):
    """需要完成 PG provider 装配；禁止旧目录/SQLite fallback。"""


class LearningCommitConfirmed(CommitCompletedAfterCancellation):
    """仅代表 learning worker 已确认提交，result 不来自身份授权事务。"""

    stage = "learning_commit"


class LearningPostCommitAuthorizationError(RuntimeError):
    """学习提交已确认，但提交后的身份检查失败；禁止盲目重试业务写入。"""

    stage = "post_authorization"

    def __init__(self, result):
        super().__init__("Learning committed but post-commit authorization failed")
        self.result = result


class LearningRuntime:
    def __init__(
        self,
        database,
        scope,
        *,
        executor,
        session_store,
        authorize,
        authority=None,
        source_provider=None,
    ):
        if not callable(authorize):
            raise TypeError("current identity authorization callback required")
        if session_store.scope != scope:
            raise ValueError("learning/session scope mismatch")
        self.database, self.scope, self.executor = database, scope, executor
        self.session_store, self.authorize = session_store, authorize
        self.authority, self.source_provider = authority, source_provider
        self._store = AsyncLearningStore(database, scope, authority=authority)
        self.event_scope = self._store.event_scope

    def _with_authority(self, authority):
        return type(self)(
            self.database,
            self.scope,
            executor=self.executor,
            session_store=self.session_store,
            authorize=self.authorize,
            authority=authority,
            source_provider=self.source_provider,
        )

    async def run(self, callback):
        try:
            await self.authorize()
        except CommitCompletedAfterCancellation as exc:
            raise RuntimeError("Learning authorization failed before the learning unit") from exc
        try:
            result = await self._store.run(callback)
        except CommitCompletedAfterCancellation as exc:
            raise LearningCommitConfirmed(exc.result) from exc
        try:
            await self.authorize()
        except BaseException as exc:
            raise LearningPostCommitAuthorizationError(result) from exc
        return result

    async def check_execution(self):
        manager = self._with_authority(ExecutionAuthority(self.executor))
        await manager.run(lambda unit: bool(unit._authority()))

    async def _cleanup(self, callback):
        # 清理不是继续教学授权：仅允许调用方持有的 typed execution 释放自身资源。
        # Store 仍验证 executor 存活/栅栏/租约归属；撤权不能造成已停止任务的永久锁。
        task = asyncio.create_task(self._store.run(callback))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        result = task.result()
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def release_turn_lease(self):
        if self.authority is None or not self.authority.turn_id:
            raise RuntimeError("typed turn authority required for cleanup")
        return await self._cleanup(
            lambda unit: unit.release_leases_for_turn(self.authority.turn_id)
        )

    @asynccontextmanager
    async def bind(self):
        await self.authorize()
        token = _bound.set(self)
        try:
            yield self
        finally:
            _bound.reset(token)

    async def for_turn(self, session_id, turn_id):
        await self.authorize()
        authority = await ExecutionAuthority.for_turn(
            self.executor, self.database, self.scope, session_id, turn_id
        )
        return self._with_authority(authority)

    @asynccontextmanager
    async def operation(self, path_id):
        """本人路径的 typed operation；竞争保留为领域冲突，不伪造聊天会话。"""
        authority = ExecutionAuthority(self.executor)
        manager = self._with_authority(authority)
        lease, failed = None, True
        try:
            try:
                lease = await manager.run(lambda u: u.begin_path_operation(path_id))
            except (LearningCommitConfirmed, LearningPostCommitAuthorizationError) as exc:
                lease = exc.result
                raise
            owner = self._with_authority(authority.for_operation(lease))
            async with owner.bind():
                yield owner
                failed = False
        finally:
            if lease is not None:
                owner = self._with_authority(authority.for_operation(lease))

                def finish(unit):
                    state = unit.get_path_operation(lease.operation_id)
                    if state is None or state["status"] == "active":
                        unit.finish_path_operation(lease, failed=failed)

                await owner._cleanup(finish)

    async def event_page(self, path_id, *, cursor=None, after_revision=0, limit=200):
        def read(unit):
            if cursor is not None:
                key = unit._decode(cursor, f"events:{path_id}")
                head = unit._execute(
                    "SELECT revision,id FROM enterprise.mastery_events WHERE tenant_id=%s "
                    "AND owner_id=%s AND path_id=%s ORDER BY revision DESC,id DESC LIMIT 1",
                    (*unit._owner, path_id),
                ).fetchone()
                if tuple(key) > ((head["revision"], head["id"]) if head else (0, 0)):
                    raise ValueError("learning cursor is ahead of committed history")
            page = unit.list_event_page(
                path_id, cursor=cursor, after_revision=after_revision, limit=limit
            )
            last = page.items[-1] if page.items else None
            durable_cursor = (
                unit._cursor(f"events:{path_id}", [last.revision, last.id])
                if last is not None
                else cursor
            )
            return {
                "events": [event.model_dump(mode="json") for event in page.items],
                "next_cursor": page.next_cursor,
                "cursor": durable_cursor,
            }

        return await self.run(read)

    async def delete_session(self, session_id, deletion_token):
        from deeptutor.learning.contracts import LearningReferenceError, PathLeaseConflictError
        from deeptutor.persistence.postgres.reading.base import SessionExecution
        from deeptutor.services.session.question_bank import QuestionBankReferenceConflict

        manager = self._with_authority(ExecutionAuthority(self.executor))

        def delete(unit):
            with unit._unit(write=True):
                owned = unit._execute(
                    "SELECT path_id FROM enterprise.mastery_paths WHERE tenant_id=%s "
                    "AND owner_id=%s AND creator_session_id=%s ORDER BY path_id LIMIT 1001",
                    (*unit._owner, session_id),
                ).fetchall()
                unit._compat(owned)
                scratch = [
                    row["path_id"]
                    for row in owned
                    if not any(m.knowledge_points for m in unit.load(row["path_id"]).modules)
                ]
                unit.detach_session_history(session_id, deletion_token=deletion_token)
                unit.detach_session(session_id, delete_owned_orphans=False)
                deleted = SessionExecution(unit).delete_session(
                    session_id, deletion_token=deletion_token
                )
                if deleted:
                    for path in scratch:
                        if not unit.list_session_page(path, limit=1).items:
                            unit.delete(path)
                return deleted

        try:
            return await manager.run(delete)
        except (LearningReferenceError, PathLeaseConflictError) as exc:
            await self.session_store._release_known_failed_delete(session_id, deletion_token)
            raise QuestionBankReferenceConflict(str(exc)) from exc
        except QuestionBankReferenceConflict:
            await self.session_store._release_known_failed_delete(session_id, deletion_token)
            raise

    async def recover_once(self):
        """仅持新真实执行锁后恢复当前scope的旧lease，不扫描用户目录、不重跑模型。"""
        authority = ExecutionAuthority(self.executor)
        manager = self._with_authority(authority)

        def candidates(unit):
            rows = unit._execute(
                "SELECT execution_id,turn_id FROM enterprise.mastery_path_leases "
                "WHERE tenant_id=%s AND owner_id=%s AND execution_id<>%s "
                "ORDER BY execution_id,path_id LIMIT 1001",
                (*unit._owner, authority.execution_id),
            ).fetchall()
            return unit._compat(rows)

        rows = await manager.run(candidates)
        for row in rows:
            await self.authorize()
            await self.executor.check()
            if row["turn_id"]:
                turn = await self.session_store.get_turn(row["turn_id"])
                if turn and turn["status"] in ("queued", "running", "waiting_input"):
                    await self.session_store.finalize_turn(
                        turn["id"],
                        status="failed",
                        failure_code="worker_lost",
                        retryable=True,
                        error="Previous executor stopped; start a new operation to retry",
                    )
        for execution_id in dict.fromkeys(str(row["execution_id"]) for row in rows):
            await manager.run(lambda u: u.recover_stopped_execution(execution_id))
        return len(rows)

    async def recover_stopped_execution(self, execution_id):
        manager = self._with_authority(ExecutionAuthority(self.executor))
        return await manager.run(lambda u: u.recover_stopped_execution(execution_id))


def get_learning_runtime():
    runtime = _bound.get()
    if runtime is None:
        from deeptutor.core.providers import get_providers

        providers = get_providers()
        provider = getattr(providers, "learning", None)
        if provider is None and providers is None:
            from deeptutor.app.container import get_application_container

            provider = getattr(get_application_container(), "learning_provider", None)
        runtime = provider.get() if provider is not None and hasattr(provider, "get") else provider
    if not isinstance(runtime, LearningRuntime):
        raise LearningProviderUnavailable(
            "PostgreSQL learning provider is not configured; upgrade the application composition"
        )
    return runtime
