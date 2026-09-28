"""移除数据库枚举 CHECK 后，会话 Store 仍拒绝未知消息/轮次状态。"""

import psycopg
import pytest

pytestmark = pytest.mark.asyncio


async def test_unknown_persisted_turn_status_cannot_be_read_or_transitioned(
    migrated_pg, pg_session_store_factory, business_actors
):
    actor = business_actors.tenants[0].owners[0]
    store = pg_session_store_factory(actor)
    await store.create_session(session_id="enum-turn")
    turn = await store.begin_turn("enum-turn")
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute("ALTER TABLE enterprise.turns DROP CONSTRAINT IF EXISTS turns_status_check")
        await connection.execute(
            "UPDATE enterprise.turns SET status='mystery' WHERE id=%s", (turn["id"],)
        )
    with pytest.raises(RuntimeError, match="unknown turn status"):
        await store.get_turn(turn["id"])
    with pytest.raises(RuntimeError, match="unknown turn status"):
        await store.transition_turn(turn["id"], "completed")
    with pytest.raises(RuntimeError, match="unknown turn status"):
        await store.begin_turn("enum-turn")
    with pytest.raises(RuntimeError, match="unknown turn status"):
        await store.list_active_turns("enum-turn")
    with pytest.raises(RuntimeError, match="unknown turn status"):
        await store.get_session("enum-turn")


async def test_unknown_persisted_message_role_cannot_be_read(
    migrated_pg, pg_session_store_factory, business_actors
):
    actor = business_actors.tenants[0].owners[0]
    store = pg_session_store_factory(actor)
    await store.create_session(session_id="enum-message")
    await store.add_message("enum-message", "user", "hi")
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute("ALTER TABLE enterprise.messages DROP CONSTRAINT IF EXISTS messages_role_check")
        await connection.execute(
            "UPDATE enterprise.messages SET role='mystery' WHERE session_id='enum-message'"
        )
    with pytest.raises(RuntimeError, match="unknown message role"):
        await store.get_messages("enum-message")
    with pytest.raises(RuntimeError, match="unknown message role"):
        await store.get_last_message("enum-message")
    with pytest.raises(ValueError, match="Unsupported message role"):
        await store.get_last_message("enum-message", role="mystery")
    with pytest.raises(RuntimeError, match="unknown message role"):
        await store.get_session("enum-message")


async def test_unknown_or_inconsistent_operation_cannot_replay(
    migrated_pg, pg_session_store_factory, business_actors
):
    actor = business_actors.tenants[0].owners[0]
    store = pg_session_store_factory(actor)
    payload = {"session_id": "enum-operation", "content": "hello", "capability": "chat"}
    await store.create_session(session_id="enum-operation")
    await store.begin_request(payload, operation_id="op-1")
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            "ALTER TABLE enterprise.operations DROP CONSTRAINT IF EXISTS operations_status_check"
        )
        await connection.execute("ALTER TABLE enterprise.operations DROP CONSTRAINT IF EXISTS operations_check")
        await connection.execute(
            "UPDATE enterprise.operations SET status='mystery' WHERE operation_id='op-1'"
        )
    with pytest.raises(RuntimeError, match="unknown operation status"):
        await store.begin_request(payload, operation_id="op-1")
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        await connection.execute(
            "UPDATE enterprise.operations SET status='registered',request=NULL "
            "WHERE operation_id='op-1'"
        )
    with pytest.raises(RuntimeError, match="inconsistent operation"):
        await store.begin_request(payload, operation_id="op-1")
