"""默认与企业共享的删除编排；PG 决定门禁，执行器只负责确认停止。"""


class SessionCleanupPending(RuntimeError):
    def __init__(self, report):
        super().__init__("Session deleted; physical resource cleanup is pending")
        self.report = report


async def delete_session_lifecycle(store, cancel_turn, session_id):
    token = await store.claim_deletion(session_id)
    if token is None:
        return False
    # mark 已提交后才能取消；任何等待期间 begin_request 都被 PG 门禁拒绝。
    for turn in await store.list_active_turns(session_id):
        await cancel_turn(str(turn["id"]))
    if await store.list_active_turns(session_id):
        from deeptutor.services.session.question_bank import QuestionBankReferenceConflict

        raise QuestionBankReferenceConflict("Session deletion pending: execution has not stopped")
    from deeptutor.core.providers import get_providers

    providers = get_providers()
    if providers is not None and providers.learning is not None:
        from deeptutor.learning.runtime import get_learning_runtime

        runtime = get_learning_runtime()
        if runtime.scope != store.scope:
            raise PermissionError("Learning/session deletion scope mismatch")
        deleted = await runtime.delete_session(session_id, token)
    else:
        deleted = await store.delete_session(session_id, deletion_token=token)
    if deleted:
        report = await cleanup_session_resources(store)
        if report["pending"]:
            raise SessionCleanupPending(report)
    return deleted


async def cleanup_session_resources(store):
    from deeptutor.core.providers import get_providers
    from deeptutor.services.storage import get_attachment_store

    async with store.db.transaction(store.scope) as c:
        pending = await (
            await c.execute(
                "SELECT count(*) AS count FROM enterprise.session_objects WHERE tenant_id=%s AND owner_id=%s AND state='cleanup'",
                store._owner,
            )
        ).fetchone()
    if not pending["count"]:
        return {"completed": 0, "pending": 0, "errors": []}
    providers = get_providers()
    if providers is None or providers.resources is None:
        # 账本已提交；缺显式文件根不回退全局路径，也不把逻辑删除当物理完成。
        return {
            "completed": 0,
            "pending": pending["count"],
            "errors": [{"error": "ResourceProviderUnavailable"}],
        }
    return await get_attachment_store().cleanup_pending()
