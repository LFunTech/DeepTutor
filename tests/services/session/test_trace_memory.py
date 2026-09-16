from __future__ import annotations

from deeptutor.services.session.event_preview import (
    MAX_LEGACY_EVENT_PAYLOAD_CHARS,
    MAX_TRACE_PREVIEW_EVENTS,
    compact_trace_preview,
)
from tests.services.session.pg_helpers import pg_session_runtime


def test_preview_keeps_semantic_events_and_bounds_legacy_payloads() -> None:
    events = [
        {"type": "content", "content": "delta"},
        {
            "type": "tool_result",
            "content": "x" * (MAX_LEGACY_EVENT_PAYLOAD_CHARS + 10),
            "metadata": {},
        },
        {"type": "result", "metadata": {"summary": "ok"}},
        {"type": "done", "metadata": {"status": "completed"}},
    ]

    preview, truncated = compact_trace_preview(events)

    assert truncated is True
    assert events[1]["content"] == "x" * (MAX_LEGACY_EVENT_PAYLOAD_CHARS + 10)
    assert [event["type"] for event in preview] == ["tool_result", "result", "done"]
    assert len(preview[0]["content"]) == MAX_LEGACY_EVENT_PAYLOAD_CHARS + len("...[truncated]")


def test_preview_prioritizes_the_terminal_tail() -> None:
    events = [{"type": "tool_call", "content": str(i)} for i in range(250)]
    events.append({"type": "done", "metadata": {"status": "completed"}})

    preview, truncated = compact_trace_preview(events)

    assert truncated is True
    assert len(preview) == 200
    assert preview[-1]["type"] == "done"


async def test_pg_context_rehydrates_ask_user_from_canonical_turn_events(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="trace-context") as runtime:
        store = runtime.store()
        session = await store.ensure_session(None)
        turn = await store.begin_turn(session["id"], capability="chat")
        message_id = await store.add_message(session["id"], "assistant", "answer")
        await store.append_turn_events(
            turn["id"],
            [
                {"type": "content", "content": "delta", "metadata": {}},
                {
                    "type": "tool_result",
                    "metadata": {"tool_metadata": {"ask_user": {"questions": []}}},
                },
                {"type": "progress", "metadata": {"ask_user_resolved": True}},
            ],
        )
        await store.link_turn_message(turn["id"], message_id)

        context = await store.get_messages_for_context(session["id"])

    assert [event["type"] for event in context[-1]["events"]] == [
        "tool_result",
        "progress",
    ]


async def test_pg_session_preview_returns_a_bounded_canonical_trace(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="trace-preview") as runtime:
        store = runtime.store()
        session = await store.ensure_session(None)
        turn = await store.begin_turn(session["id"], capability="chat")
        message_id = await store.add_message(session["id"], "assistant", "answer")
        await store.append_turn_events(
            turn["id"],
            [
                {"type": "tool_call", "content": f"call-{index}", "metadata": {}}
                for index in range(1_000)
            ],
        )
        await store.link_turn_message(turn["id"], message_id)

        detail = await store.get_session_with_messages(session["id"])

    assert detail is not None
    message = detail["messages"][0]
    assert message["trace"]["total"] == 1_000
    assert message["trace"]["truncated"] is True
    assert len(message["events"]) == MAX_TRACE_PREVIEW_EVENTS
    assert message["events"][0]["content"] == "call-800"
    assert message["events"][-1]["content"] == "call-999"


async def test_pg_early_mastery_card_survives_a_long_turn_preview(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="trace-mastery-card") as runtime:
        store = runtime.store()
        session = await store.ensure_session(None)
        turn = await store.begin_turn(session["id"], capability="chat")
        message_id = await store.add_message(session["id"], "assistant", "answer")
        card = {
            "type": "tool_result",
            "content": "",
            "metadata": {
                "tool_call_id": "call-quiz",
                "tool_metadata": {
                    "mastery_question": {"question_id": "q-1", "prompt": "Which reducer?"}
                },
            },
        }
        await store.append_turn_events(
            turn["id"],
            [
                card,
                *[
                    {"type": "tool_call", "content": f"call-{index}", "metadata": {}}
                    for index in range(1_000)
                ],
            ],
        )
        await store.link_turn_message(turn["id"], message_id)

        detail = await store.get_session_with_messages(session["id"])

    assert detail is not None
    events = detail["messages"][0]["events"]
    assert len(events) == MAX_TRACE_PREVIEW_EVENTS
    posed = [
        (event.get("metadata") or {}).get("tool_metadata", {}).get("mastery_question")
        for event in events
    ]
    assert [card["question_id"] for card in posed if card] == ["q-1"]


async def test_pg_message_trace_uses_cursor_and_limit(pg_dsn: str) -> None:
    async with pg_session_runtime(pg_dsn, resource="trace-cursor") as runtime:
        store = runtime.store()
        session = await store.ensure_session(None)
        turn = await store.begin_turn(session["id"], capability="chat")
        message_id = await store.add_message(session["id"], "assistant", "answer")
        await store.append_turn_events(
            turn["id"],
            [
                {"type": "tool_call", "content": f"call-{seq}", "metadata": {}}
                for seq in range(1, 1_201)
            ],
        )
        await store.link_turn_message(turn["id"], message_id)

        page = await store.get_message_trace(session["id"], message_id, after_seq=100, limit=50)

    assert page is not None
    assert [event["seq"] for event in page["events"]] == list(range(101, 151))
    assert page["total"] == 1_200
    assert page["last_seq"] == 1_200
    assert page["next_seq"] == 150
    assert page["complete"] is False
