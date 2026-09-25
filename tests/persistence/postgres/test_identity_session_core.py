"""Core PG 身份、会话与执行租约的真实生命周期契约。"""

from __future__ import annotations

import importlib.abc
import sys
from uuid import uuid4

import pytest

from tests.fixtures.postgres import single_database_user_dsn


class _RejectEnterpriseImports(importlib.abc.MetaPathFinder):
    """若 core 在导入或运行时反向加载企业包，立即让测试失败。"""

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001
        if fullname == "deeptutor_enterprise" or fullname.startswith("deeptutor_enterprise."):
            raise AssertionError(f"core must not import enterprise package: {fullname}")
        return None


async def test_core_only_identity_session_turn_event_and_executor_lifecycle(pg_dsn):
    blocker = _RejectEnterpriseImports()
    sys.meta_path.insert(0, blocker)
    try:
        from jose import jwt

        from deeptutor.persistence.postgres.connection import Database
        from deeptutor.persistence.postgres.executor import ExecutorLease
        from deeptutor.persistence.postgres.identity.service import IdentityService
        from deeptutor.persistence.postgres.migrations.runner import MigrationRunner
        from deeptutor.persistence.postgres.scope import TenantScope
        from deeptutor.persistence.postgres.session import PostgresSessionStore

        await MigrationRunner(pg_dsn).apply()
        runtime_dsn = single_database_user_dsn(pg_dsn)
        tenant_id = str(uuid4())
        async with Database(runtime_dsn, resource="core-only-lifecycle") as db:
            identity = IdentityService(
                db,
                tenant_id=tenant_id,
                signing_key="s" * 48,
                auth_epoch="epoch-1",
                bootstrap_secret="b" * 48,
            )
            admin = await identity.bootstrap("admin", "long-password-1", secret="b" * 48)
            token = await identity.login("admin", "long-password-1", client="core-only-test")
            actor = await identity.authenticate(token)
            assert actor.user_id == admin["id"]
            # 提取阶段保留已签发企业令牌的默认 issuer 兼容语义。
            assert jwt.get_unverified_claims(token)["iss"] == "deeptutor-enterprise"

            store = PostgresSessionStore(db, TenantScope(tenant_id, actor.user_id))
            session = await store.create_session("Core PG", session_id="core-session")
            user_message_id = await store.add_message(session["id"], "user", "question")
            turn = await store.begin_turn(
                session["id"],
                "chat",
                owner_id="core-worker",
                fencing_token=7,
            )
            appended = await store.append_events(
                turn["id"],
                [{"type": "content", "content": "answer"}],
                fencing_token=7,
            )
            final = await store.finalize_turn(
                turn["id"],
                status="completed",
                content="answer",
                parent_message_id=user_message_id,
                user_message_id=user_message_id,
                events=[{"type": "done", "metadata": {}}],
                fencing_token=7,
            )
            assert appended[0]["seq"] == 1
            assert final["turn"]["status"] == "completed"
            assert [row["content"] for row in await store.get_messages(session["id"])] == [
                "question",
                "answer",
            ]
            assert [event["type"] for event in await store.get_events(turn["id"])] == [
                "content",
                "done",
            ]

            lease = ExecutorLease(runtime_dsn, resource="core-only-lifecycle")
            await lease.acquire()
            await lease.check()
            await lease.close()

            await identity.logout(token)
            with pytest.raises(PermissionError, match="authentication required"):
                await identity.authenticate(token)
    finally:
        sys.meta_path.remove(blocker)
