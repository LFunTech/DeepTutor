"""真实 PostgreSQL 会话契约：隔离、并发、分支及原子终态。"""

import asyncio
from dataclasses import FrozenInstanceError
import importlib
import json
from uuid import uuid4

from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.scope import TenantScope
from deeptutor_enterprise.stores.postgres.connection import Database
import psycopg
from psycopg.types.json import Jsonb
import pytest


def test_pg_session_repository_is_available():
    assert importlib.util.find_spec("deeptutor_enterprise.stores.postgres.session") is not None, (
        "缺失真实 PG 会话持久化实现"
    )


@pytest.fixture
async def stores(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    tenants = [str(uuid4()), str(uuid4())]
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        for tenant in tenants:
            await c.execute(
                "INSERT INTO enterprise.tenants(id,external_eligibility,local_enabled,provisioning_status,auth_epoch) VALUES(%s,'not_required',true,'ready','test')",
                (tenant,),
            )
            for owner in ("alice", "bob"):
                await c.execute(
                    "INSERT INTO enterprise.users(tenant_id,id,username,role) VALUES(%s,%s,%s,'user')",
                    (tenant, owner, owner),
                )
    try:
        cls = importlib.import_module(
            "deeptutor_enterprise.stores.postgres.session"
        ).PostgresSessionStore
    except (ImportError, AttributeError):
        pytest.fail("缺失 PostgresSessionStore：需要真实 PG 会话持久化实现")
    async with Database(
        pg_dsn.replace("user=postgres", "user=dt_enterprise_app"), resource="test-session-db"
    ) as db:
        yield (
            cls(db, TenantScope(tenants[0], "alice")),
            cls(db, TenantScope(tenants[0], "bob")),
            cls(db, TenantScope(tenants[1], "alice")),
        )


async def test_sessions_are_owner_scoped_and_missing_ids_are_not_taken_over(stores):
    a, b, other_tenant = stores
    first = await a.create_session("  algebra  ", session_id="same-id")
    await other_tenant.create_session("different", session_id="same-id")
    assert first["title"] == "algebra"
    assert (await a.get_session("same-id"))["title"] == "algebra"
    assert await b.get_session("same-id") is None
    assert await b.list_sessions() == []
    assert (await other_tenant.list_sessions())[0]["title"] == "different"
    for store, session_id in ((b, "same-id"), (a, "unknown")):
        with pytest.raises(ValueError):
            await store.ensure_session(session_id)
    assert len(await a.list_sessions()) == 1
    assert a.store_scope.cache_key != other_tenant.store_scope.cache_key
    with pytest.raises((FrozenInstanceError, AttributeError)):
        a.scope = b.scope
    assert await b.update_session_title("same-id", "stolen") is False
    assert await b.delete_session("same-id") is False


async def test_preferences_merge_version_pagination_parent_and_summary(stores):
    a, b, _ = stores
    parent = (await a.create_session("parent"))["id"]
    sid = (await a.create_session("child"))["id"]
    foreign = (await b.create_session())["id"]
    msg = await a.add_message(sid, "user", "question")
    assert isinstance(msg, int)
    assert await a.update_session_preferences(
        sid, {"pinned": True, "parent_session_id": parent, "language": "zh"}
    )
    assert await a.update_session_preferences(sid, {"archived": True})
    assert await a.update_summary(sid, "summary", msg)
    session = await a.get_session(sid)
    assert session["preferences"]["language"] == "zh"
    assert session["preferences"]["pinned"] is True
    assert session["preferences"]["archived"] is True
    assert session["preferences"]["parent_session_id"] == parent
    assert session["compressed_summary"] == "summary"
    assert session["summary_up_to_msg_id"] == msg
    assert session["version"] > 1
    assert len(await a.list_sessions(limit=1, offset=1)) == 1
    assert {s["id"] for s in await a.get_session_summaries([sid, foreign, sid])} == {sid}
    for bad_parent in (sid, foreign, "missing"):
        with pytest.raises(ValueError):
            await a.update_session_preferences(sid, {"parent_session_id": bad_parent})
    with pytest.raises(ValueError):
        await a.update_session_preferences(parent, {"parent_session_id": sid})
    with pytest.raises(ValueError):
        await a.update_summary(parent, "cross-session", msg)


async def test_message_branch_context_and_private_metadata(stores):
    a, b, _ = stores
    sid = (await a.create_session())["id"]
    root = await a.add_message(sid, "user", "root", parent_message_id=None)
    old = await a.add_message(
        sid,
        "assistant",
        "old",
        metadata={"provider_response_state": {"reasoning_content": "private"}},
    )
    branch = await a.add_message(sid, "assistant", "new", parent_message_id=root)
    await a.select_active_leaf(sid, old)
    assert [m["id"] for m in await a.get_messages_for_context(sid)] == [root, old]
    assert (await a.get_messages_for_context(sid))[-1]["metadata"]["provider_response_state"][
        "reasoning_content"
    ] == "private"
    assert [m["id"] for m in await a.get_message_path(sid, branch)] == [root, branch]
    assert [m["id"] for m in await a.get_messages(sid)] == [root, old, branch]
    detail = await a.get_session_with_messages(sid)
    assert "provider_response_state" not in detail["messages"][1]["metadata"]
    assert await b.get_messages(sid) == []
    assert await b.get_message_trace(sid, old) is None
    other = (await a.create_session())["id"]
    for operation in (
        a.add_message(other, "user", "bad", parent_message_id=root),
        a.select_active_leaf(other, old),
        a.get_messages_for_context(other, old),
    ):
        with pytest.raises(ValueError):
            await operation
    assert (await a.get_last_message(sid, role="assistant"))["id"] == branch


async def test_branch_selection_checks_real_parent_child_relationship(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    root = await a.add_message(sid, "user", "root", parent_message_id=None)
    child = await a.add_message(sid, "assistant", "child")
    assert await a.update_session_preferences(sid, {"selected_branches": {str(root): child}})
    with pytest.raises(ValueError):
        await a.update_session_preferences(sid, {"selected_branches": {str(child): root}})


async def test_one_active_turn_cas_fencing_and_terminal_immutability(stores):
    a, b, _ = stores
    sid = (await a.create_session())["id"]
    results = await asyncio.gather(
        *(a.begin_turn(sid, "chat", owner_id="executor", fencing_token=7) for _ in range(2)),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in results) == 1
    turn = next(r for r in results if isinstance(r, dict))
    tid = turn["id"]
    assert await b.get_turn(tid) is None
    assert await b.list_active_turns(sid) == []
    assert await b.transition_turn(tid, "cancelled") is False
    assert (
        await a.transition_turn(tid, "waiting_input", expected_status="running", fencing_token=6)
        is False
    )
    assert await a.transition_turn(tid, "waiting_input", expected_status="running", fencing_token=7)
    assert await a.transition_turn(tid, "running", expected_status="running") is False
    assert await a.transition_turn(tid, "running", expected_status="waiting_input")
    assert await a.transition_turn(tid, "cancelled", fencing_token=7)
    assert await a.transition_turn(tid, "completed") is False
    final = await a.get_turn(tid)
    assert final["state_version"] == 4
    assert final["finished_at"] is not None
    assert await a.list_nonterminal_turns() == []
    with pytest.raises(RuntimeError):
        await a.append_events(tid, [{"type": "content", "content": "late"}])


async def test_event_batches_are_atomic_monotonic_and_replayable(stores):
    a, b, _ = stores
    sid = (await a.create_session())["id"]
    tid = (await a.begin_turn(sid, fencing_token=9))["id"]
    batches = await asyncio.gather(
        *(
            a.append_events(
                tid,
                [
                    {"type": "content", "content": f"{i}:a"},
                    {"type": "content", "content": f"{i}:b"},
                ],
                fencing_token=9,
            )
            for i in range(8)
        )
    )
    events = await a.get_events(tid)
    assert [e["seq"] for e in events] == list(range(1, 17))
    assert all(batch[1]["seq"] == batch[0]["seq"] + 1 for batch in batches)
    assert len(await a.get_events(tid, after_seq=12)) == 4
    assert await a.append_events(tid, [events[0]], fencing_token=9) == [events[0]]
    for invalid in (
        [{"type": "content", "seq": 1, "content": "different"}],
        [{"type": "content"}, {"type": "content", "session_id": "foreign"}],
        [{"type": "content", "seq": 30}],
    ):
        with pytest.raises(ValueError):
            await a.append_events(tid, invalid)
    with pytest.raises(RuntimeError):
        await a.append_events(tid, [{"type": "content"}], fencing_token=8)
    assert len(await a.get_events(tid)) == 16
    assert (await a.get_turn(tid))["last_seq"] == 16
    assert await b.get_events(tid) == []


async def test_request_registration_deduplicates_and_sanitizes(stores, pg_dsn):
    a, b, _ = stores
    request = {
        "content": "question",
        "capability": "chat",
        "config": {"temperature": 0.3, "api_key": "never-store-this"},
    }
    results = await asyncio.gather(
        *(a.begin_request(request, operation_id="op-1") for _ in range(4))
    )
    assert sum(not r[2] for r in results) == 1
    assert len({r[1]["id"] for r in results}) == 1
    sid, tid = results[0][0]["id"], results[0][1]["id"]
    with pytest.raises(ValueError, match="conflict"):
        await a.begin_request({**request, "content": "different"}, operation_id="op-1")
    await a.transition_turn(tid, "failed", failure_code="interrupted", retryable=True)
    replay = await a.begin_request(request, operation_id="op-1")
    assert replay[2] and replay[1]["failure_code"] == "interrupted"
    assert len(await a.list_sessions()) == 1
    assert (await b.begin_request(request, operation_id="op-1"))[0]["id"] != sid
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        row = await (
            await c.execute(
                "SELECT request, expires_at>now()+interval '29 days' FROM enterprise.operations WHERE tenant_id=%s AND owner_id=%s",
                (a.scope.tenant_id, a.scope.user_id),
            )
        ).fetchone()
        assert "never-store-this" not in json.dumps(row[0])
        assert row[1]


async def test_unkeyed_requests_are_compatible_and_failed_registration_is_atomic(stores):
    a, b, _ = stores
    first = await a.begin_request({"content": "a"})
    second = await a.begin_request({"content": "a"})
    assert not first[2] and not second[2] and first[0]["id"] != second[0]["id"]
    with pytest.raises(ValueError):
        await b.begin_request({"session_id": first[0]["id"], "content": "take over"}, "foreign")
    assert await b.list_sessions() == []
    with pytest.raises(RuntimeError):
        await a.begin_request({"session_id": first[0]["id"], "content": "busy"}, "retry-after-busy")
    await a.transition_turn(first[1]["id"], "completed")
    result = await a.begin_request(
        {"session_id": first[0]["id"], "content": "busy"}, "retry-after-busy"
    )
    assert result[2] is False


async def test_finalize_commits_message_terminal_and_done_once(stores):
    a, _, _ = stores
    session, turn, _ = await a.begin_request({"content": "question"}, "complete-once")
    sid, tid = session["id"], turn["id"]
    user = await a.add_message(sid, "user", "question")
    await a.append_events(tid, [{"type": "content", "content": "answer"}])
    result = await a.finalize_turn(
        tid,
        status="completed",
        content="answer",
        parent_message_id=user,
        events=[{"type": "done", "metadata": {"cost_summary": {"total_cost": 0.03}}}],
    )
    assert result["turn"]["status"] == "completed"
    assert result["assistant_message_id"] == (await a.get_messages(sid))[-1]["id"]
    assert result["events"][0]["seq"] == 2
    assert result["events"][0]["metadata"]["cost_summary"]["total_cost"] == 0.03
    assert result["events"][0]["metadata"]["message_id"] == result["assistant_message_id"]
    replay = await a.finalize_turn(tid, status="completed", content="duplicate")
    assert replay["replayed"] is True
    assert len(await a.get_messages(sid)) == 2
    assert len(await a.get_events(tid)) == 2


async def test_cancel_and_complete_have_one_terminal_winner(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    tid = (await a.begin_turn(sid))["id"]
    await asyncio.gather(
        a.finalize_turn(tid, status="completed", content="answer"),
        a.finalize_turn(tid, status="cancelled"),
    )
    final = await a.get_turn(tid)
    messages = await a.get_messages(sid)
    assert len(await a.get_events(tid)) == 1
    assert len(messages) == (1 if final["status"] == "completed" else 0)
    assert final["assistant_message_id"] == (messages[0]["id"] if messages else None)


async def test_finalize_constraint_failure_rolls_back_all_results(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    tid = (await a.begin_turn(sid))["id"]
    other = (await a.create_session())["id"]
    foreign_parent = await a.add_message(other, "user", "other")
    with pytest.raises(ValueError):
        await a.finalize_turn(
            tid, status="completed", content="answer", parent_message_id=foreign_parent
        )
    assert await a.get_messages(sid) == []
    assert await a.get_events(tid) == []
    assert (await a.get_turn(tid))["status"] == "running"


async def test_trace_paging_preview_redaction_and_context_are_separate(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    tid = (await a.begin_turn(sid))["id"]
    long_text = "x" * 20000
    await a.append_events(
        tid,
        [
            {"type": "tool_result", "content": long_text},
            {"type": "content", "content": "answer"},
            {
                "type": "tool_result",
                "metadata": {
                    "provider_response_state": {"reasoning_content": "private"},
                    "ask_user": {"questions": []},
                },
            },
        ],
    )
    result = await a.finalize_turn(
        tid,
        status="completed",
        content="answer",
        metadata={"provider_response_state": {"reasoning_content": "model-only"}},
    )
    mid = result["assistant_message_id"]
    page = await a.get_message_trace(sid, mid, limit=2)
    assert page["total"] == 4 and page["next_seq"] == 2 and not page["complete"]
    assert page["events"][0]["content"] == long_text
    tail = await a.get_message_trace(sid, mid, after_seq=2, limit=2)
    assert tail["complete"] and tail["next_seq"] is None
    assert "provider_response_state" not in tail["events"][0]["metadata"]
    detail = await a.get_session_with_messages(sid)
    assert len(detail["messages"][0]["events"][0]["content"]) < len(long_text)
    assert detail["messages"][0]["trace"]["truncated"]
    assert (await a.get_messages_for_context(sid))[0]["metadata"]["provider_response_state"][
        "reasoning_content"
    ] == "model-only"
    assert await a.get_message_trace("wrong-session", mid) is None


async def test_delete_session_tombstones_requests_and_replay_does_not_resurrect(stores, pg_dsn):
    a, _, _ = stores
    request = {"content": "private body"}
    session, turn, _ = await a.begin_request(request, "deleted-op")
    sid, tid = session["id"], turn["id"]
    await a.finalize_turn(tid, status="completed", content="private answer")
    assert await a.delete_session(sid)
    assert await a.get_session(sid) is None and await a.get_events(tid) == []
    replay = await a.begin_request(request, "deleted-op")
    assert replay[2] and replay[0]["status"] == "deleted" and replay[1]["status"] == "deleted"
    assert await a.list_sessions() == []
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        row = await (
            await c.execute(
                "SELECT request,session_id,turn_id,status FROM enterprise.operations WHERE operation_id='deleted-op'"
            )
        ).fetchone()
        assert row == (None, None, None, "deleted")
        audit = await (
            await c.execute(
                "SELECT action,target_id FROM enterprise.audit WHERE action='session.delete'"
            )
        ).fetchall()
        assert len(audit) == 1 and audit[0][1] == sid


async def test_deleting_blocks_dispatch_and_active_delete_preserves_data(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    tid = (await a.begin_turn(sid))["id"]
    with pytest.raises(RuntimeError):
        await a.delete_session(sid)
    assert not (await a.get_session(sid))["deleting"]
    assert await a.mark_deleting(sid)
    with pytest.raises(RuntimeError):
        await a.begin_turn(sid)
    await a.finalize_turn(tid, status="cancelled")
    assert await a.delete_session(sid)


async def test_delete_refuses_external_dependencies_before_destructive_writes(stores, pg_dsn):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    msg = await a.add_message(sid, "user", "legacy")
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "UPDATE enterprise.messages SET attachments=%s WHERE tenant_id=%s AND id=%s",
            (Jsonb([{"id": "legacy-file"}]), a.scope.tenant_id, msg),
        )
    with pytest.raises(RuntimeError, match="depend"):
        await a.delete_session(sid)
    with pytest.raises(RuntimeError, match="depend"):
        await a.mark_deleting(sid)
    with pytest.raises(RuntimeError, match="depend"):
        await a.delete_message(msg)
    assert (await a.get_session(sid))["deleting"] is False
    assert len(await a.get_messages(sid)) == 1


async def test_delete_message_pair_splices_branches_and_tombstones_turn(stores):
    a, _, _ = stores
    session, turn, _ = await a.begin_request({"content": "one"}, "pair-delete")
    sid = session["id"]
    user = await a.add_message(sid, "user", "one")
    result = await a.finalize_turn(
        turn["id"], status="completed", content="two", parent_message_id=user
    )
    answer = result["assistant_message_id"]
    child = await a.add_message(sid, "user", "three", parent_message_id=answer)
    assert await a.update_summary(sid, "old summary", answer)
    result = await a.delete_turn_by_message(sid, answer)
    assert result == {
        "deleted": True,
        "attachment_ids": [],
        "turn_id": turn["id"],
        "was_running": False,
    }
    remaining = await a.get_messages(sid)
    assert [m["id"] for m in remaining] == [child]
    assert remaining[0]["parent_message_id"] is None
    assert (await a.get_session(sid))["summary_up_to_msg_id"] == 0
    assert (await a.begin_request({"content": "one"}, "pair-delete"))[1]["status"] == "deleted"


async def test_message_delete_conflicts_with_waiting_and_no_import_side_effects(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    user = await a.add_message(sid, "user", "question")
    tid = (await a.begin_turn(sid))["id"]
    await a.transition_turn(tid, "waiting_input")
    result = await a.delete_turn_by_message(sid, user)
    assert result["was_running"] and not result["deleted"]
    with pytest.raises(NotImplementedError):
        await a.import_legacy_session("legacy", "legacy", 0, 0, {}, [])
    assert await a.migrate_workspace_preferences() == 0


async def test_selected_branches_controls_model_context_not_latest_insertion(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    root = await a.add_message(sid, "user", "root", parent_message_id=None)
    old = await a.add_message(sid, "assistant", "old")
    old_followup = await a.add_message(sid, "user", "old-followup")
    new = await a.add_message(sid, "assistant", "new", parent_message_id=root)
    await a.update_session_preferences(sid, {"selected_branches": {str(root): old}})
    assert [m["id"] for m in await a.get_messages_for_context(sid)] == [root, old, old_followup]
    assert (await a.get_session(sid))["active_leaf_id"] == old_followup
    await a.update_session_preferences(sid, {"selected_branches": {str(root): new}})
    assert [m["id"] for m in await a.get_messages_for_context(sid)] == [root, new]


async def test_failed_turn_user_delete_tombstones_original_request(stores):
    a, _, _ = stores
    session, turn, _ = await a.begin_request({"content": "failed question"}, "failure-op")
    user = await a.add_message(session["id"], "user", "failed question")
    assert await a.link_turn_user_message(turn["id"], user)
    await a.transition_turn(turn["id"], "failed", failure_code="interrupted")
    assert await a.delete_message(user)
    assert await a.get_turn(turn["id"]) is None
    assert (await a.begin_request({"content": "failed question"}, "failure-op"))[1][
        "status"
    ] == "deleted"


async def test_assistant_cannot_be_linked_to_two_different_turns(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    first = await a.begin_turn(sid)
    answer = await a.add_message(sid, "assistant", "answer")
    assert await a.link_turn_message(first["id"], answer)
    await a.transition_turn(first["id"], "completed")
    second = await a.begin_turn(sid)
    assert await a.link_turn_message(second["id"], answer) is False


async def test_done_database_failure_rolls_back_message_and_terminal(stores, pg_dsn):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    tid = (await a.begin_turn(sid))["id"]
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("""
            CREATE FUNCTION enterprise.reject_done() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.event->>'type'='done' THEN RAISE EXCEPTION 'injected terminal persistence failure'; END IF;
            RETURN NEW; END $$;
            CREATE TRIGGER reject_done BEFORE INSERT ON enterprise.turn_events FOR EACH ROW EXECUTE FUNCTION enterprise.reject_done();
        """)
    with pytest.raises(psycopg.errors.RaiseException, match="terminal persistence failure"):
        await a.finalize_turn(tid, status="completed", content="must not commit")
    assert await a.get_messages(sid) == []
    assert await a.get_events(tid) == []
    assert (await a.get_turn(tid))["status"] == "running"
    assert (await a.get_session(sid))["active_leaf_id"] is None


async def test_expired_operation_does_not_promise_deduplication(stores, pg_dsn):
    a, _, _ = stores
    first = await a.begin_request({"content": "same"}, "expired-op")
    await a.finalize_turn(first[1]["id"], status="completed", content="first")
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "UPDATE enterprise.operations SET expires_at=now()-interval '1 second' WHERE operation_id='expired-op'"
        )
    second = await a.begin_request({"content": "same"}, "expired-op")
    assert not second[2] and first[1]["id"] != second[1]["id"]


async def test_parent_session_delete_preserves_child_without_dangling_parent(stores):
    a, _, _ = stores
    parent = (await a.create_session())["id"]
    child = (await a.create_session())["id"]
    await a.update_session_preferences(child, {"parent_session_id": parent})
    assert await a.delete_session(parent)
    row = await a.get_session(child)
    assert row["parent_session_id"] is None
    assert not row["preferences"].get("parent_session_id")


async def test_begin_and_delete_race_never_dispatches_into_deleted_session(stores):
    a, _, _ = stores
    for _ in range(6):
        sid = (await a.create_session())["id"]
        started, deleted = await asyncio.gather(
            a.begin_turn(sid), a.delete_session(sid), return_exceptions=True
        )
        if isinstance(started, dict):
            assert isinstance(deleted, RuntimeError)
            assert (await a.get_session(sid))["active_turn_id"] == started["id"]
            await a.finalize_turn(started["id"], status="cancelled")
            assert await a.delete_session(sid)
        else:
            assert isinstance(started, ValueError) and deleted is True
            assert await a.get_session(sid) is None


async def test_done_keeps_client_reconciliation_message_ids(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    tid = (await a.begin_turn(sid))["id"]
    user = await a.add_message(sid, "user", "question")
    assert await a.link_turn_user_message(tid, user)
    result = await a.finalize_turn(tid, status="completed", content="answer", user_message_id=user)
    metadata = result["events"][-1]["metadata"]
    assert metadata["assistant_message_id"] == result["assistant_message_id"]
    assert metadata["user_message_id"] == user


async def test_done_cannot_bypass_atomic_finalize(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    tid = (await a.begin_turn(sid))["id"]
    with pytest.raises(ValueError, match="finalize"):
        await a.append_events(tid, [{"type": "done"}])
    assert await a.get_events(tid) == []
    assert (await a.get_turn(tid))["status"] == "running"


async def test_private_session_mutations_leave_content_free_audit(stores, pg_dsn):
    a, _, _ = stores
    session = await a.create_session("private title")
    await a.update_session_title(session["id"], "another private title")
    turn = await a.begin_turn(session["id"])
    await a.finalize_turn(turn["id"], status="completed", content="private answer")
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        rows = await (
            await c.execute(
                "SELECT action,target_id,result FROM enterprise.audit WHERE tenant_id=%s AND actor_id=%s",
                (a.scope.tenant_id, a.scope.user_id),
            )
        ).fetchall()
    assert {"session.create", "session.update", "turn.begin", "turn.finalize"} <= {
        row[0] for row in rows
    }
    assert "private" not in json.dumps(rows)


async def test_deleting_regenerated_answer_preserves_shared_user_and_sibling_trace(stores):
    a, _, _ = stores
    first_session, first_turn, _ = await a.begin_request({"content": "question"}, "original-branch")
    sid = first_session["id"]
    user = await a.add_message(sid, "user", "question")
    await a.link_turn_user_message(first_turn["id"], user)
    first = await a.finalize_turn(
        first_turn["id"], status="completed", content="old answer", user_message_id=user
    )
    second_session, second_turn, _ = await a.begin_request(
        {
            "session_id": sid,
            "content": "question",
            "parent_message_id": user,
            "persist_user_message": False,
        },
        "regenerated-branch",
    )
    await a.link_turn_user_message(second_turn["id"], user)
    second = await a.finalize_turn(
        second_turn["id"], status="completed", content="new answer", user_message_id=user
    )
    await a.delete_turn_by_message(sid, second["assistant_message_id"])
    assert [m["id"] for m in await a.get_messages(sid)] == [user, first["assistant_message_id"]]
    assert [m["id"] for m in await a.get_messages_for_context(sid)] == [
        user,
        first["assistant_message_id"],
    ]
    assert (await a.get_turn(first_turn["id"]))["status"] == "completed"
    assert (await a.get_message_trace(sid, first["assistant_message_id"]))["total"] == 1
    assert (await a.begin_request({"content": "question"}, "original-branch"))[1][
        "status"
    ] == "completed"


async def test_request_parent_and_regenerate_validate_before_any_registration(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    user = await a.add_message(sid, "user", "original question")
    answer = await a.add_message(sid, "assistant", "original answer")
    other = (await a.create_session())["id"]
    invalid_requests = [
        {"content": "new session with foreign parent", "parent_message_id": user},
        {"session_id": other, "content": "wrong session parent", "parent_message_id": user},
        {
            "session_id": sid,
            "content": "changed question",
            "parent_message_id": user,
            "persist_user_message": False,
        },
        {
            "session_id": sid,
            "content": "original answer",
            "parent_message_id": answer,
            "persist_user_message": False,
        },
        {"session_id": sid, "content": "no user parent", "persist_user_message": False},
    ]
    for index, request in enumerate(invalid_requests):
        with pytest.raises(ValueError):
            await a.begin_request(request, f"invalid-{index}")
        assert await a.list_nonterminal_turns() == []
        assert len(await a.list_sessions()) == 2
    result = await a.begin_request(
        {
            "session_id": sid,
            "content": "original question",
            "parent_message_id": user,
            "persist_user_message": False,
        },
        "invalid-0",
    )
    assert result[2] is False


@pytest.mark.parametrize("delete_api", ["turn", "message"])
async def test_deleting_shared_user_removes_all_answers_without_harming_other_turns(
    stores, delete_api
):
    a, _, _ = stores
    previous_request = {"content": "previous question"}
    session, previous_turn, _ = await a.begin_request(previous_request, "previous-op")
    sid = session["id"]
    previous_user = await a.add_message(sid, "user", "previous question")
    previous = await a.finalize_turn(
        previous_turn["id"],
        status="completed",
        content="previous answer",
        user_message_id=previous_user,
    )

    original_request = {"session_id": sid, "content": "shared question"}
    _, original_turn, _ = await a.begin_request(original_request, "shared-original-op")
    shared_user = await a.add_message(sid, "user", "shared question")
    original = await a.finalize_turn(
        original_turn["id"],
        status="completed",
        content="original answer",
        user_message_id=shared_user,
    )
    regenerated_request = {
        "session_id": sid,
        "content": "shared question",
        "parent_message_id": shared_user,
        "persist_user_message": False,
    }
    _, regenerated_turn, _ = await a.begin_request(regenerated_request, "shared-regenerated-op")
    regenerated = await a.finalize_turn(
        regenerated_turn["id"],
        status="completed",
        content="regenerated answer",
        user_message_id=shared_user,
    )
    later_request = {"session_id": sid, "content": "later question"}
    _, later_turn, _ = await a.begin_request(later_request, "later-op")
    later_user = await a.add_message(sid, "user", "later question")
    later = await a.finalize_turn(
        later_turn["id"],
        status="completed",
        content="later answer",
        user_message_id=later_user,
    )

    if delete_api == "turn":
        deleted = await a.delete_turn_by_message(sid, shared_user)
        assert deleted["deleted"] and deleted["attachment_ids"] == [] and not deleted["was_running"]
        assert deleted["turn_id"] in (original_turn["id"], regenerated_turn["id"])
    else:
        assert await a.delete_message(shared_user)
    remaining = await a.get_messages(sid)
    expected_ids = [
        previous_user,
        previous["assistant_message_id"],
        later_user,
        later["assistant_message_id"],
    ]
    assert [message["id"] for message in remaining] == expected_ids
    assert remaining[2]["parent_message_id"] == previous["assistant_message_id"]
    assert [message["id"] for message in await a.get_messages_for_context(sid)] == expected_ids
    for removed_turn, removed_message, request, operation_id in (
        (original_turn, original, original_request, "shared-original-op"),
        (regenerated_turn, regenerated, regenerated_request, "shared-regenerated-op"),
    ):
        assert await a.get_turn(removed_turn["id"]) is None
        assert await a.get_events(removed_turn["id"]) == []
        assert await a.get_message_trace(sid, removed_message["assistant_message_id"]) is None
        assert (await a.begin_request(request, operation_id))[1]["status"] == "deleted"
    for kept_turn, kept_message, request, operation_id in (
        (previous_turn, previous, previous_request, "previous-op"),
        (later_turn, later, later_request, "later-op"),
    ):
        assert (await a.get_turn(kept_turn["id"]))["status"] == "completed"
        assert (await a.get_message_trace(sid, kept_message["assistant_message_id"]))["total"] == 1
        assert (await a.begin_request(request, operation_id))[1]["status"] == "completed"


async def test_deleting_user_removes_unlinked_answer_siblings_but_keeps_descendants(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    user = await a.add_message(sid, "user", "question")
    await a.add_message(sid, "assistant", "old answer", parent_message_id=user)
    await a.add_message(sid, "assistant", "new answer", parent_message_id=user)
    followup = await a.add_message(sid, "user", "next question")
    result = await a.delete_turn_by_message(sid, user)
    assert result == {"deleted": True, "attachment_ids": [], "turn_id": None, "was_running": False}
    remaining = await a.get_messages(sid)
    assert [message["id"] for message in remaining] == [followup]
    assert remaining[0]["parent_message_id"] is None


async def test_reply_command_replay_keeps_original_ask_version_and_deduplicates(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    tid = (await a.begin_turn(sid))["id"]
    await a.transition_turn(tid, "waiting_input")
    answer = {"answers": [{"question_id": "q1", "text": "first reply"}]}
    reservations = await asyncio.gather(
        *(a.reserve_command(tid, "reply-1", "reply", answer) for _ in range(4))
    )
    assert sum(not result["replayed"] for result in reservations) == 1
    assert all(result["accepted"] and result["state_version"] == 2 for result in reservations)
    await a.transition_turn(tid, "running")
    await a.transition_turn(tid, "waiting_input")
    assert (await a.get_turn(tid))["state_version"] == 4
    assert await a.reserve_command(tid, "reply-1", "reply", answer) == {
        "replayed": True,
        "accepted": True,
        "state_version": 2,
    }
    for kind, payload in (("reply", {"answers": [{"text": "another answer"}]}), ("cancel", answer)):
        with pytest.raises(ValueError, match="conflict"):
            await a.reserve_command(tid, "reply-1", kind, payload)
    assert await a.reserve_command(tid, "reply-2", "reply", {"answers": []}) == {
        "replayed": False,
        "accepted": True,
        "state_version": 4,
    }


async def test_rejected_or_undelivered_command_never_becomes_dispatchable_on_replay(stores):
    a, _, _ = stores
    sid = (await a.create_session())["id"]
    tid = (await a.begin_turn(sid))["id"]
    assert await a.reserve_command(tid, "too-early", "reply", {}) == {
        "replayed": False,
        "accepted": False,
        "state_version": 1,
    }
    await a.transition_turn(tid, "waiting_input")
    assert await a.reserve_command(tid, "too-early", "reply", {}) == {
        "replayed": True,
        "accepted": False,
        "state_version": 1,
    }
    assert (await a.reserve_command(tid, "queue-stopped", "reply", {}))["accepted"]
    await a.finish_command(tid, "queue-stopped", False)
    await a.finish_command(tid, "queue-stopped", False)
    await a.finish_command(tid, "queue-stopped", True)
    assert await a.reserve_command(tid, "queue-stopped", "reply", {}) == {
        "replayed": True,
        "accepted": False,
        "state_version": 2,
    }
    with pytest.raises(ValueError):
        await a.finish_command(tid, "unknown-command", False)


async def test_commands_are_owner_scoped_gate_cancel_and_cascade_on_delete(stores, pg_dsn):
    a, b, other_tenant = stores
    sid = (await a.create_session())["id"]
    tid = (await a.begin_turn(sid))["id"]
    assert await a.reserve_command(tid, "cancel-1", "cancel", {}) == {
        "replayed": False,
        "accepted": True,
        "state_version": 1,
    }
    for store, target in ((b, tid), (other_tenant, tid), (a, "unknown-turn")):
        with pytest.raises(ValueError, match="Turn not found"):
            await store.reserve_command(target, "cancel-1", "cancel", {})
        with pytest.raises(ValueError, match="Turn not found"):
            await store.finish_command(target, "cancel-1", False)
    await a.transition_turn(tid, "cancelled")
    assert (await a.reserve_command(tid, "cancel-again", "cancel", {}))["accepted"]
    assert not (await a.reserve_command(tid, "late-reply", "reply", {}))["accepted"]
    another = (await a.begin_turn(sid))["id"]
    await a.transition_turn(another, "completed")
    assert not (await a.reserve_command(another, "cancel-1", "cancel", {}))["accepted"]
    for command_id, kind in (("", "reply"), ("unknown-kind", "reply-other")):
        with pytest.raises(ValueError):
            await a.reserve_command(another, command_id, kind, {})
    assert await a.delete_session(sid)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        assert (
            await (await c.execute("SELECT count(*) FROM enterprise.turn_commands")).fetchone()
        )[0] == 0
