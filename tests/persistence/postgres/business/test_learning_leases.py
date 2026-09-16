"""真实执行锁/登记、turn栅栏及本人管理操作竞争和恢复。"""

import asyncio
import importlib

import pytest

from deeptutor.learning.models import LearningProgress
from deeptutor.persistence.postgres.executor import ExecutorLease

pytestmark = pytest.mark.asyncio


async def test_typed_authority_is_available():
    module = importlib.import_module("deeptutor.persistence.postgres.learning")
    assert hasattr(module, "ExecutionAuthority"), "typed executor authority is missing"


async def test_owner_operation_conflicts_with_turn_without_creating_fake_sessions(
    migrated_pg, business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    from deeptutor.learning.contracts import PathLeaseConflictError
    from deeptutor.persistence.postgres.learning import AsyncLearningStore, ExecutionAuthority

    actor = business_actors.tenants[0].owners[0]
    scope = pg_scope_factory(actor)
    executor = ExecutorLease(migrated_pg.runtime_dsn, resource=business_sync_database.resource)
    await executor.acquire()
    try:
        authority = ExecutionAuthority(executor)
        store = AsyncLearningStore(business_sync_database, scope, authority=authority)
        op = await store.run(lambda u: u.begin_path_operation("p"))
        assert op.kind == "operation" and not op.session_id and not op.turn_id
        session_store = pg_session_store_factory(actor)
        session = await session_store.create_session("real")
        turn = await session_store.begin_turn(
            session["id"], owner_id=executor.execution_id, fencing_token=7
        )
        teaching_authority = await ExecutionAuthority.for_turn(
            executor, business_sync_database, scope, session["id"], turn["id"]
        )
        teaching = AsyncLearningStore(business_sync_database, scope, authority=teaching_authority)
        with pytest.raises(PathLeaseConflictError):
            await teaching.run(lambda u: u.acquire_path_lease("p", session["id"], turn["id"]))
        assert await teaching.run(lambda u: u.path_id_for_session(session["id"])) == ""
        operation_store = AsyncLearningStore(
            business_sync_database, scope, authority=authority.for_operation(op)
        )
        await operation_store.run(lambda u: u.finish_path_operation(op))
        lease = await teaching.run(lambda u: u.acquire_path_lease("p", session["id"], turn["id"]))
        assert lease.kind == "turn" and lease.fencing_token == 7
        with pytest.raises(PathLeaseConflictError):
            await store.run(lambda u: u.begin_path_operation("p"))
        assert await teaching.run(lambda u: u.release_path_lease("p", turn_id="wrong")) is False
        assert await teaching.run(lambda u: u.release_leases_for_turn(turn["id"])) == "p"
        assert await teaching.run(lambda u: u.get_path_lease("p")) is None
        rows = await business_sync_database.run(
            scope,
            lambda c: c.execute(
                "SELECT id FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s",
                (scope.tenant_id, scope.user_id),
            ).fetchall(),
        )
        assert [r["id"] for r in rows] == [session["id"]]
    finally:
        await executor.close()


async def test_stale_worker_cannot_write_release_or_automatically_recover(
    migrated_pg, business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    from deeptutor.persistence.postgres.learning import AsyncLearningStore, ExecutionAuthority

    actor = business_actors.tenants[0].owners[0]
    scope = pg_scope_factory(actor)
    executor = ExecutorLease(migrated_pg.runtime_dsn, resource=business_sync_database.resource)
    await executor.acquire()
    sessions = pg_session_store_factory(actor)
    session = await sessions.create_session("real")
    turn = await sessions.begin_turn(session["id"], owner_id=executor.execution_id, fencing_token=7)
    authority = await ExecutionAuthority.for_turn(
        executor, business_sync_database, scope, session["id"], turn["id"]
    )
    store = AsyncLearningStore(business_sync_database, scope, authority=authority)
    try:
        await store.run(lambda u: u.acquire_path_lease("p", session["id"], turn["id"]))
        await business_sync_database.run(
            scope,
            lambda c: c.execute(
                "UPDATE enterprise.turns SET fencing_token=8 WHERE tenant_id=%s AND user_id=%s AND id=%s",
                (scope.tenant_id, scope.user_id, turn["id"]),
            ),
        )
        for operation in (
            lambda u: u.release_leases_for_turn(turn["id"]),
            lambda u: u.save(LearningProgress(book_id="p", version=1)),
        ):
            with pytest.raises(RuntimeError, match="authority|fenc"):
                await store.run(operation)
        assert (
            await AsyncLearningStore(business_sync_database, scope).run(
                lambda u: u.get_path_lease("p")
            )
        ).fencing_token == 7
    finally:
        await executor.close()


async def test_unknown_executor_cannot_be_replaced_and_stopped_operation_recovers(
    migrated_pg, business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.persistence.postgres.learning import AsyncLearningStore, ExecutionAuthority

    scope = pg_scope_factory(business_actors.tenants[0].owners[0])
    first = ExecutorLease(migrated_pg.runtime_dsn, resource=business_sync_database.resource)
    await first.acquire()
    stale = AsyncLearningStore(business_sync_database, scope, authority=ExecutionAuthority(first))
    op = await stale.run(lambda u: u.begin_path_operation("recover"))
    second = ExecutorLease(migrated_pg.runtime_dsn, resource=business_sync_database.resource)
    try:
        with pytest.raises(RuntimeError, match="another executor"):
            await second.acquire()
        await first.connection.close()
        with pytest.raises(RuntimeError, match="confirmed stopped"):
            await second.acquire()
        assert (
            await AsyncLearningStore(business_sync_database, scope).run(
                lambda u: u.get_path_lease("recover")
            )
        ).operation_id == op.operation_id
        await ExecutorLease.confirm_stopped(
            migrated_pg.runtime_dsn, resource=first.resource, execution_id=first.execution_id
        )
        await second.acquire()
        current = AsyncLearningStore(
            business_sync_database, scope, authority=ExecutionAuthority(second)
        )
        assert await current.run(lambda u: u.recover_stopped_execution(first.execution_id)) == [
            "recover"
        ]
        new = await current.run(lambda u: u.begin_path_operation("recover"))
        with pytest.raises(RuntimeError, match="authority"):
            await stale.run(lambda u: u.release_path_lease("recover"))
        assert (
            await current.run(lambda u: u.get_path_lease("recover"))
        ).operation_id == new.operation_id
        rows = await business_sync_database.run(
            scope,
            lambda c: c.execute(
                "SELECT status,version FROM enterprise.mastery_path_operations WHERE tenant_id=%s AND owner_id=%s AND operation_id=%s",
                (scope.tenant_id, scope.user_id, op.operation_id),
            ).fetchall(),
        )
        assert rows == [{"status": "interrupted", "version": 2}]
    finally:
        await first.close()
        await second.close()


async def test_concurrent_owner_operations_have_one_winner(
    migrated_pg, business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.learning.contracts import PathLeaseConflictError
    from deeptutor.persistence.postgres.learning import AsyncLearningStore, ExecutionAuthority

    scope = pg_scope_factory(business_actors.tenants[0].owners[0])
    executor = ExecutorLease(migrated_pg.runtime_dsn, resource=business_sync_database.resource)
    await executor.acquire()
    try:
        store = AsyncLearningStore(
            business_sync_database, scope, authority=ExecutionAuthority(executor)
        )
        results = await asyncio.gather(
            store.run(lambda u: u.begin_path_operation("same")),
            store.run(lambda u: u.begin_path_operation("same")),
            return_exceptions=True,
        )
        assert sum(isinstance(r, PathLeaseConflictError) for r in results) == 1
        assert sum(getattr(r, "kind", None) == "operation" for r in results) == 1
    finally:
        await executor.close()


async def test_management_delete_keeps_recoverable_terminal_and_finish_is_idempotent(
    migrated_pg, business_sync_database, business_actors, pg_scope_factory
):
    from deeptutor.persistence.postgres.learning import AsyncLearningStore, ExecutionAuthority

    scope = pg_scope_factory(business_actors.tenants[0].owners[0])
    executor = ExecutorLease(migrated_pg.runtime_dsn, resource=business_sync_database.resource)
    await executor.acquire()
    try:
        authority = ExecutionAuthority(executor)
        store = AsyncLearningStore(business_sync_database, scope, authority=authority)
        op = await store.run(lambda u: u.begin_path_operation("deleted"))
        bound = AsyncLearningStore(
            business_sync_database, scope, authority=authority.for_operation(op)
        )
        await bound.run(lambda u: u.delete("deleted"))
        assert await store.run(lambda u: u.load("deleted")) is None
        await bound.run(lambda u: u.finish_path_operation(op))
        terminal = await store.run(lambda u: u.get_path_operation(op.operation_id))
        assert terminal["status"] == "completed" and terminal["version"] == 2
        replacement = await store.run(lambda u: u.begin_path_operation("deleted"))
        await bound.run(lambda u: u.finish_path_operation(op))
        assert (
            await store.run(lambda u: u.get_path_lease("deleted"))
        ).operation_id == replacement.operation_id
    finally:
        await executor.close()


async def test_management_delete_fk_failure_restores_operation_and_lease(
    migrated_pg, business_sync_database, business_actors, pg_scope_factory, pg_session_store_factory
):
    from deeptutor.learning.contracts import LearningReferenceError
    from deeptutor.persistence.postgres.learning import AsyncLearningStore, ExecutionAuthority
    from tests.persistence.postgres.business.test_learning_store import _modules

    actor = business_actors.tenants[0].owners[0]
    scope = pg_scope_factory(actor)
    sessions = pg_session_store_factory(actor)
    session = await sessions.create_session("referenced")
    executor = ExecutorLease(migrated_pg.runtime_dsn, resource=business_sync_database.resource)
    await executor.acquire()
    try:
        authority = ExecutionAuthority(executor)
        store = AsyncLearningStore(business_sync_database, scope, authority=authority)
        await store.run(lambda u: u.save(LearningProgress(book_id="p", modules=_modules())))
        await sessions.upsert_notebook_entries(
            session["id"],
            [
                dict(
                    question_id="q",
                    question="q",
                    source="mastery_path",
                    material_id="p",
                    section_id="kp",
                )
            ],
        )
        op = await store.run(lambda u: u.begin_path_operation("p"))
        bound = AsyncLearningStore(
            business_sync_database, scope, authority=authority.for_operation(op)
        )
        with pytest.raises(LearningReferenceError):
            await bound.run(lambda u: u.delete("p"))
        assert (await store.run(lambda u: u.get_path_operation(op.operation_id)))[
            "status"
        ] == "active"
        assert (await store.run(lambda u: u.get_path_lease("p"))).operation_id == op.operation_id
        assert (await store.run(lambda u: u.load("p"))).version == 1
        await bound.run(lambda u: u.finish_path_operation(op, failed=True))
        assert (await store.run(lambda u: u.get_path_operation(op.operation_id)))[
            "status"
        ] == "failed"
    finally:
        await executor.close()
