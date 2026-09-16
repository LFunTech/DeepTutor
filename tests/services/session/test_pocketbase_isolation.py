"""旧 PocketBase runtime 隔离测试已替换为 PG-only 契约测试。

PocketBase 现仅作为受控离线 exporter/importer 的源端；业务运行期不得构造
``PocketBaseSessionStore``，也不得通过旧配置重新启用远端 backend。原来的
同用户/跨用户可见性要求由真实 PostgreSQL RLS/owner 测试继续覆盖。
"""

from __future__ import annotations

import pytest

from tests.services.session.pg_helpers import pg_session_runtime

pytestmark = pytest.mark.asyncio


async def test_pocketbase_session_store_constructor_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.pocketbase_client.get_pb_client",
        lambda: object(),
        raising=True,
    )
    from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore

    with pytest.raises(RuntimeError, match="PostgreSQL-only runtime"):
        PocketBaseSessionStore()


async def test_legacy_pocketbase_config_does_not_enable_runtime_backend(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.config.load_integrations_settings",
        lambda: {"pocketbase_url": "http://pocketbase:8090"},
    )
    from deeptutor.services import pocketbase_client

    assert pocketbase_client.is_pocketbase_enabled() is False
    with pytest.raises(RuntimeError, match="controlled offline export/import"):
        pocketbase_client.get_pb_client()


async def test_pg_session_owner_isolation_replaces_pocketbase_runtime(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="session-pocketbase-replacement") as runtime:
        alice = await runtime.create_user("alice")
        bob = await runtime.create_user("bob")
        alice_store = runtime.store(alice)
        bob_store = runtime.store(bob)

        await alice_store.create_session(title="A's chat", session_id="s_alice")
        await bob_store.create_session(title="B's chat", session_id="s_bob")

        assert {row["id"] for row in await alice_store.list_sessions()} == {"s_alice"}
        assert {row["id"] for row in await bob_store.list_sessions()} == {"s_bob"}
        assert await bob_store.get_session("s_alice") is None
        assert await bob_store.update_session_title("s_alice", "hijacked") is False
        assert await bob_store.delete_session("s_alice") is False
        assert (await alice_store.get_session("s_alice"))["title"] == "A's chat"
