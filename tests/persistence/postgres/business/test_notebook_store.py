"""PG question-bank Store 的真实行为、并发和稳定导出游标契约。"""

from __future__ import annotations

import asyncio
import base64
import json

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import PoolClosed
import pytest

from deeptutor.persistence.postgres.connection import Database
from deeptutor.persistence.postgres.notebook_query import decode_cursor, encode_cursor
from deeptutor.persistence.postgres.session import PostgresSessionStore
from deeptutor.services.session import protocol as session_protocol
from deeptutor.services.session.question_bank import (
    QuestionBankCursorError,
    QuestionBankQuery,
    QuestionBankReferenceConflict,
    QuestionBankVersionConflict,
)

pytestmark = pytest.mark.asyncio


async def test_protocol_keeps_the_complete_question_bank_surface():
    expected = {
        "upsert_notebook_entries",
        "list_notebook_entries",
        "has_question_bank_entries",
        "question_bank_stats",
        "list_question_bank_materials",
        "get_notebook_entry",
        "find_notebook_entry",
        "update_notebook_entry",
        "delete_notebook_entry",
        "create_category",
        "list_categories",
        "rename_category",
        "delete_category",
        "add_entry_to_category",
        "remove_entry_from_category",
        "get_entry_categories",
        "link_entries_to_category",
        "find_category_by_name",
    }
    repository = session_protocol.QuestionBankRepository
    assert {name for name in expected if hasattr(repository, name)} == expected


async def test_query_value_object_normalizes_without_importing_a_store_backend():
    query = QuestionBankQuery(
        category_id=7,
        uncategorized=True,
        source="invalid",
        score_trend="invalid",
        search="  " + "x" * 250 + "  ",
        session_ids=["b", "a"],
        sort="invalid",
        limit=999,
        offset=-4,
    ).normalized()
    assert query.category_id == 7 and query.uncategorized is False
    assert query.source == "" and query.score_trend == ""
    assert query.search == "x" * 200
    assert query.session_ids == ("b", "a")
    assert query.sort == "recent" and query.limit == 500 and query.offset == 0


async def _session_and_store(pg_session_store_factory, actor, suffix: str = ""):
    store = pg_session_store_factory(actor)
    session = await store.create_session(
        f"题库{suffix}", session_id=f"notebook-{actor.user_id}{suffix}"
    )
    return store, session["id"]


async def _wait_for_upsert_blockers(connection, role: str, count: int) -> None:
    while True:
        row = await (
            await connection.execute(
                """
                SELECT count(*) AS blocked
                FROM pg_stat_activity
                WHERE cardinality(pg_blocking_pids(pid))>0
                  AND usename=%s
                """,
                (role,),
            )
        ).fetchone()
        if row["blocked"] >= count:
            return
        await asyncio.sleep(0.01)


async def _wait_for_blocker(connection, blocker_pid: int, role: str) -> None:
    while True:
        row = await (
            await connection.execute(
                "SELECT count(*) AS blocked FROM pg_stat_activity"
                " WHERE usename=%s AND %s=ANY(pg_blocking_pids(pid))",
                (role, blocker_pid),
            )
        ).fetchone()
        if row["blocked"]:
            return
        await asyncio.sleep(0.01)


async def _wait_for_application_block_or_completion(
    connection, application_name: str, task: asyncio.Task
) -> bool:
    while True:
        row = await (
            await connection.execute(
                """
                SELECT EXISTS(
                  SELECT 1 FROM pg_stat_activity blocked
                  JOIN pg_stat_activity writer
                    ON writer.pid=ANY(pg_blocking_pids(blocked.pid))
                  WHERE writer.application_name=%s
                ) AS blocked
                """,
                (application_name,),
            )
        ).fetchone()
        if row["blocked"]:
            return True
        if task.done():
            return False
        await asyncio.sleep(0.01)


def _item(question_id: str, question: str, correct: bool = False, **extra):
    return {
        "question_id": question_id,
        "question": question,
        "is_correct": correct,
        "source": "book",
        **extra,
    }


async def test_full_entry_dto_answer_transitions_images_and_preserved_review_fields(
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    store, session_id = await _session_and_store(pg_session_store_factory, actor)
    _, followup_id = await _session_and_store(pg_session_store_factory, actor, "-followup")
    images = [
        {
            "id": "image-1",
            "url": "/synthetic/image-1.png",
            "filename": "image-1.png",
            "mime_type": "image/png",
        }
    ]
    initial = _item(
        "q1",
        "二次方程的根？",
        turn_id="book-block-1",
        question_type="choice",
        options={"A": "1", "B": "2"},
        correct_answer="B",
        explanation="代入",
        difficulty="medium",
        user_answer="A",
        user_answer_images=images,
        material_id="book-1",
        material_title="代数",
        section_id="chapter-1",
        section_title="方程",
    )
    assert await store.upsert_notebook_entries(session_id, [initial]) == 1
    entry = await store.find_notebook_entry(session_id, "q1", turn_id="book-block-1")
    assert entry is not None
    original_id = entry["id"]
    original_created_at = entry["created_at"]
    assert entry == {
        "id": original_id,
        "session_id": session_id,
        "session_title": "题库",
        "turn_id": "book-block-1",
        "question_id": "q1",
        "question": "二次方程的根？",
        "question_type": "choice",
        "options": {"A": "1", "B": "2"},
        "correct_answer": "B",
        "explanation": "代入",
        "difficulty": "medium",
        "user_answer": "A",
        "user_answer_images": images,
        "is_correct": False,
        "source": "book",
        "material_id": "book-1",
        "material_title": "代数",
        "section_id": "chapter-1",
        "section_title": "方程",
        "score_trend": "new",
        "resolved": False,
        "bookmarked": False,
        "followup_session_id": "",
        "ai_judgment": "",
        "created_at": original_created_at,
        "updated_at": entry["updated_at"],
        "version": 1,
    }

    assert await store.update_notebook_entry(
        original_id,
        {
            "bookmarked": True,
            "followup_session_id": followup_id,
            "ai_judgment": "需要复习",
        },
        expected_version=1,
    )
    assert (
        await store.upsert_notebook_entries(
            session_id,
            [
                _item(
                    "q1",
                    "二次方程的根（修订）？",
                    True,
                    turn_id="book-block-1",
                    user_answer="B",
                )
            ],
        )
        == 1
    )
    improved = await store.get_notebook_entry(original_id)
    assert improved is not None
    assert improved["id"] == original_id
    assert improved["created_at"] == original_created_at
    assert improved["version"] == 3
    assert improved["score_trend"] == "improved"
    assert improved["resolved"] is True
    assert improved["user_answer_images"] == images
    assert improved["bookmarked"] is True
    assert improved["followup_session_id"] == followup_id
    assert improved["ai_judgment"] == "需要复习"
    filtered = await store.list_notebook_entries(
        bookmarked=True,
        is_correct=True,
        source="book",
        material_id="",
        resolved=True,
        score_trend="improved",
    )
    assert [row["id"] for row in filtered["items"]] == [original_id]

    assert (
        await store.upsert_notebook_entries(
            session_id,
            [
                _item(
                    "q1",
                    "二次方程的根（修订）？",
                    False,
                    turn_id="book-block-1",
                    user_answer_images=[],
                )
            ],
        )
        == 1
    )
    declined = await store.get_notebook_entry(original_id)
    assert declined is not None
    assert declined["version"] == 4
    assert declined["score_trend"] == "declined"
    assert declined["resolved"] is False
    assert declined["user_answer_images"] == []
    assert (await store.list_notebook_entries(is_correct=False, score_trend="declined"))[
        "total"
    ] == 1


async def test_upsert_skips_bad_items_and_rolls_back_whole_batch_on_reference_failure(
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    store, session_id = await _session_and_store(pg_session_store_factory, actor)
    assert (
        await store.upsert_notebook_entries(
            session_id,
            [
                _item("", "有题干"),
                _item("blank", "   "),
                _item("valid", "有效题目"),
            ],
        )
        == 1
    )
    assert (await store.list_notebook_entries())["total"] == 1
    with pytest.raises(ValueError, match="Session not found"):
        await store.upsert_notebook_entries("missing", [_item("q", "题目")])

    with pytest.raises(ValueError, match="question-bank reference"):
        await store.upsert_notebook_entries(
            session_id,
            [
                _item("would-rollback", "先写入"),
                {
                    "question_id": "missing-turn",
                    "question": "后失败",
                    "turn_id": "not-a-real-turn",
                    "source": "invalid-source-falls-back",
                },
            ],
        )
    result = await store.list_notebook_entries(search="先写入")
    assert result == {"items": [], "total": 0}


async def test_filters_stats_materials_literal_search_and_category_batch_loading(
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    store, first = await _session_and_store(pg_session_store_factory, actor, "-first")
    _, second = await _session_and_store(pg_session_store_factory, actor, "-second")
    assert (
        await store.upsert_notebook_entries(
            first,
            [
                _item(
                    "percent",
                    "命中 100% 与中文",
                    material_id="m2",
                    material_title="zeta",
                    section_id="s1",
                ),
                _item("percent-decoy", "命中 1000 与中文"),
                _item("underscore", "变量 a_b"),
                _item("underscore-decoy", "变量 axb"),
                _item("slash", r"路径 C:\\tmp"),
                _item("slash-decoy", "路径 C:tmp"),
            ],
        )
        == 6
    )
    assert (
        await store.upsert_notebook_entries(
            second,
            [
                _item(
                    "correct",
                    "另一题",
                    True,
                    material_id="m1",
                    material_title="Alpha",
                )
            ],
        )
        == 1
    )
    rows = (await store.list_notebook_entries(session_id=first))["items"]
    by_id = {row["question_id"]: row for row in rows}
    category = await store.create_category("  易错  ")
    assert (
        await store.link_entries_to_category(
            [by_id["percent"]["id"], by_id["underscore"]["id"]], category["id"]
        )
        == 2
    )

    for needle, expected in (
        ("100%", {"percent"}),
        ("a_b", {"underscore"}),
        (r"C:\\tmp", {"slash"}),
        ("中文", {"percent", "percent-decoy"}),
    ):
        found = await store.list_notebook_entries(search=needle)
        assert {row["question_id"] for row in found["items"]} == expected
        assert found["total"] == len(expected)

    categorized = await store.list_notebook_entries(
        category_id=category["id"], uncategorized=True, session_ids=[first, second]
    )
    assert {row["question_id"] for row in categorized["items"]} == {
        "percent",
        "underscore",
    }
    assert all(
        row["categories"] == [{"id": category["id"], "name": "易错"}]
        for row in categorized["items"]
    )
    assert (await store.list_notebook_entries(session_id=first, session_ids=[second])) == {
        "items": [],
        "total": 0,
    }
    assert await store.list_notebook_entries(session_ids=[]) == {"items": [], "total": 0}
    assert (await store.list_notebook_entries(uncategorized=True))["total"] == 5
    exact_provenance = await store.list_notebook_entries(
        source="book", material_id="m2", section_id="s1"
    )
    assert [row["question_id"] for row in exact_provenance["items"]] == ["percent"]
    assert (await store.list_notebook_entries(source="not-valid"))["total"] == 7
    assert (await store.list_notebook_entries(score_trend="not-valid"))["total"] == 7
    assert await store.question_bank_stats([first]) == {
        "total": 6,
        "wrong": 6,
        "unresolved": 6,
        "bookmarked": 0,
        "uncategorized": 4,
    }
    assert await store.question_bank_stats([]) == {
        "total": 0,
        "wrong": 0,
        "unresolved": 0,
        "bookmarked": 0,
        "uncategorized": 0,
    }
    assert await store.list_question_bank_materials() == [
        {
            "source": "book",
            "material_id": "m1",
            "material_title": "Alpha",
            "entry_count": 1,
            "unresolved_count": 0,
        },
        {
            "source": "book",
            "material_id": "m2",
            "material_title": "zeta",
            "entry_count": 1,
            "unresolved_count": 1,
        },
    ]
    categories = await store.list_categories([])
    assert categories == [
        {
            "id": category["id"],
            "name": "易错",
            "created_at": category["created_at"],
            "entry_count": 0,
            "version": 1,
        }
    ]


async def test_cursor_export_is_bounded_filter_bound_and_stable_across_insert(
    business_database,
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    store, session_id = await _session_and_store(pg_session_store_factory, actor)
    await store.upsert_notebook_entries(
        session_id,
        [_item(f"q{i}", f"导出题 {i}") for i in range(5)],
    )
    async with business_database.transaction(actor.scope) as connection:
        await connection.execute(
            "UPDATE enterprise.notebook_entries SET created_at=100,updated_at=100"
        )

    offset_result = await store.list_notebook_entries(limit=2, offset=1)
    assert set(offset_result) == {"items", "total"}
    first = await store.list_notebook_entries(limit=2, cursor="")
    assert first["total"] == 5
    assert len(first["items"]) == 2
    assert isinstance(first["next_cursor"], str)
    oldest = await store.list_notebook_entries(limit=2, cursor="", sort="oldest")
    assert [row["id"] for row in oldest["items"]] == sorted(row["id"] for row in oldest["items"])

    other = business_actors.tenants[0].owners[1]
    other_store = pg_session_store_factory(other)
    assert await other_store.list_notebook_entries(limit=2, cursor=first["next_cursor"]) == {
        "items": [],
        "total": 0,
        "next_cursor": None,
    }

    await store.upsert_notebook_entries(session_id, [_item("late", "并发插入")])
    exported = list(first["items"])
    page = first
    while page["next_cursor"] is not None:
        page = await store.list_notebook_entries(limit=2, cursor=page["next_cursor"])
        assert page["total"] == 5
        exported.extend(page["items"])
    assert len(exported) == 5
    assert len({row["id"] for row in exported}) == 5
    assert "late" not in {row["question_id"] for row in exported}
    assert [row["id"] for row in exported] == sorted((row["id"] for row in exported), reverse=True)

    with pytest.raises(QuestionBankCursorError, match="filter"):
        await store.list_notebook_entries(search="different", limit=2, cursor=first["next_cursor"])
    with pytest.raises(QuestionBankCursorError):
        await store.list_notebook_entries(cursor="not-base64")
    with pytest.raises(QuestionBankCursorError, match="too large"):
        await store.list_notebook_entries(cursor="x" * 2049)
    with pytest.raises(QuestionBankCursorError, match="offset"):
        await store.list_notebook_entries(cursor="", offset=1)


async def test_entry_patch_cas_and_legacy_atomic_patch_concurrency(
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    store, session_id = await _session_and_store(pg_session_store_factory, actor)
    await store.upsert_notebook_entries(session_id, [_item("q1", "并发修改")])
    entry = (await store.list_notebook_entries())["items"][0]

    outcomes = await asyncio.gather(
        store.update_notebook_entry(
            entry["id"], {"bookmarked": True}, expected_version=entry["version"]
        ),
        store.update_notebook_entry(
            entry["id"], {"resolved": True}, expected_version=entry["version"]
        ),
        return_exceptions=True,
    )
    assert sum(result is True for result in outcomes) == 1
    assert sum(isinstance(result, QuestionBankVersionConflict) for result in outcomes) == 1
    after_cas = await store.get_notebook_entry(entry["id"])
    assert after_cas is not None and after_cas["version"] == 2

    assert await asyncio.gather(
        store.update_notebook_entry(entry["id"], {"bookmarked": True}),
        store.update_notebook_entry(entry["id"], {"resolved": True}),
    ) == [True, True]
    after_legacy = await store.get_notebook_entry(entry["id"])
    assert after_legacy is not None
    assert after_legacy["bookmarked"] is True
    assert after_legacy["resolved"] is True
    assert after_legacy["version"] == 4
    assert await store.update_notebook_entry(entry["id"], {}) is False
    assert await store.update_notebook_entry(entry["id"], {"unknown": True}) is False
    assert await store.update_notebook_entry(999999, {"bookmarked": True}) is False


async def test_serialized_concurrent_upsert_uses_current_row_for_score_trend(
    migrated_pg,
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    store, session_id = await _session_and_store(pg_session_store_factory, actor)
    await store.upsert_notebook_entries(session_id, [_item("q1", "趋势", False)])
    entry = (await store.list_notebook_entries())["items"][0]

    async with await psycopg.AsyncConnection.connect(
        migrated_pg.admin_dsn, row_factory=dict_row
    ) as blocker:
        async with Database(
            migrated_pg.runtime_dsn, resource="task-1.12-upsert-a", max_size=1
        ) as db_a:
            async with Database(
                migrated_pg.runtime_dsn, resource="task-1.12-upsert-b", max_size=1
            ) as db_b:
                stores = (
                    PostgresSessionStore(db_a, actor.scope),
                    PostgresSessionStore(db_b, actor.scope),
                )

                async def write(index: int, value: bool):
                    return await stores[index].upsert_notebook_entries(
                        session_id, [_item("q1", "趋势", value)]
                    )

                async with blocker.transaction():
                    await blocker.execute(
                        "SELECT id FROM enterprise.notebook_entries"
                        " WHERE tenant_id=%s AND owner_id=%s AND id=%s FOR UPDATE",
                        (actor.tenant_id, actor.user_id, entry["id"]),
                    )
                    tasks = [
                        asyncio.create_task(write(0, True)),
                        asyncio.create_task(write(1, False)),
                    ]
                    # 两个真实 Store 连接都已在同一行锁后等待，再释放并观察串行化结果。
                    await asyncio.wait_for(
                        _wait_for_upsert_blockers(blocker, migrated_pg.runtime_role, 2), 5
                    )
                results = await asyncio.gather(*tasks)
    assert results == [1, 1]
    final = await store.get_notebook_entry(entry["id"])
    assert final is not None
    assert final["version"] == 3
    assert final["score_trend"] == ("improved" if final["is_correct"] else "declined")


async def test_category_conflicts_versions_and_bulk_link_semantics(
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    store, session_id = await _session_and_store(pg_session_store_factory, actor)
    await store.upsert_notebook_entries(session_id, [_item("q1", "一"), _item("q2", "二")])
    entry_ids = [row["id"] for row in (await store.list_notebook_entries())["items"]]

    created = await asyncio.gather(
        store.create_category("  Math "),
        store.create_category("mATH"),
        return_exceptions=True,
    )
    categories = [row for row in created if isinstance(row, dict)]
    assert len(categories) == 1
    assert sum(isinstance(row, ValueError) for row in created) == 1
    category = categories[0]
    winning_name = category["name"]
    assert winning_name in {"Math", "mATH"}
    assert category["version"] == 1
    with pytest.raises(ValueError, match="must not be blank"):
        await store.create_category("   ")
    unicode_categories = [await store.create_category(name) for name in ("Ä", "ä")]
    assert [row["name"] for row in unicode_categories] == ["Ä", "ä"]
    other_category = await store.create_category("Other")
    with pytest.raises(ValueError, match="already exists"):
        await store.rename_category(other_category["id"], " math ")

    assert (
        await store.link_entries_to_category(
            [entry_ids[0], entry_ids[0], 999999, entry_ids[1]], category["id"]
        )
        == 2
    )
    assert await store.link_entries_to_category(entry_ids, category["id"]) == 0
    assert await store.add_entry_to_category(entry_ids[0], category["id"]) is True
    assert await store.add_entry_to_category(999999, category["id"]) is False
    assert await store.add_entry_to_category(entry_ids[0], 999999) is False
    assert await store.get_entry_categories(entry_ids[0]) == [
        {"id": category["id"], "name": winning_name}
    ]
    assert (
        await store.link_entries_to_category(
            [entry_ids[0], entry_ids[0], entry_ids[1]], category["id"], link=False
        )
        == 2
    )
    assert await store.remove_entry_from_category(entry_ids[0], category["id"]) is False
    assert await store.link_entries_to_category(entry_ids, 999999) == 0

    assert await store.rename_category(
        category["id"], "Algebra", expected_version=category["version"]
    )
    with pytest.raises(QuestionBankVersionConflict):
        await store.rename_category(category["id"], "Geometry", expected_version=1)
    found = await store.find_category_by_name("  aLgEbRa ")
    assert found is not None and found["version"] == 2
    assert await store.delete_category(category["id"]) is True
    assert await store.delete_category(category["id"]) is False


async def test_category_links_filter_concurrent_deletes_without_losing_valid_entries(
    migrated_pg,
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    store, session_id = await _session_and_store(pg_session_store_factory, actor, "-link-race")
    await store.upsert_notebook_entries(
        session_id,
        [_item("single-victim", "单条"), _item("bulk-victim", "批量坏"), _item("good", "批量好")],
    )
    entries = {
        row["question_id"]: row["id"] for row in (await store.list_notebook_entries())["items"]
    }
    category = await store.create_category("并发删除")

    async with await psycopg.AsyncConnection.connect(
        migrated_pg.admin_dsn, row_factory=dict_row
    ) as blocker:
        async with blocker.transaction():
            blocker_pid = (
                await (await blocker.execute("SELECT pg_backend_pid() AS pid")).fetchone()
            )["pid"]
            await blocker.execute(
                "DELETE FROM enterprise.notebook_entries"
                " WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (actor.tenant_id, actor.user_id, entries["single-victim"]),
            )
            single_task = asyncio.create_task(
                store.add_entry_to_category(entries["single-victim"], category["id"])
            )
            await asyncio.wait_for(
                _wait_for_blocker(blocker, blocker_pid, migrated_pg.runtime_role), 5
            )
        assert await single_task is False

        async with blocker.transaction():
            blocker_pid = (
                await (await blocker.execute("SELECT pg_backend_pid() AS pid")).fetchone()
            )["pid"]
            await blocker.execute(
                "DELETE FROM enterprise.notebook_entries"
                " WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (actor.tenant_id, actor.user_id, entries["bulk-victim"]),
            )
            bulk_task = asyncio.create_task(
                store.link_entries_to_category(
                    [entries["bulk-victim"], entries["good"]], category["id"]
                )
            )
            await asyncio.wait_for(
                _wait_for_blocker(blocker, blocker_pid, migrated_pg.runtime_role), 5
            )
        assert await bulk_task == 1
    assert await store.get_entry_categories(entries["good"]) == [
        {"id": category["id"], "name": "并发删除"}
    ]


@pytest.mark.parametrize("sort", ["recent", "oldest"])
async def test_cursor_export_waits_for_late_store_commit_and_fences_later_insert(
    migrated_pg,
    business_actors,
    pg_session_store_factory,
    business_database,
    sort,
):
    actor = business_actors.tenants[0].owners[0]
    store, session_id = await _session_and_store(pg_session_store_factory, actor, f"-{sort}")
    await store.upsert_notebook_entries(
        session_id, [_item("visible-1", "可见一"), _item("visible-2", "可见二")]
    )
    async with business_database.transaction(actor.scope) as connection:
        await connection.execute(
            "UPDATE enterprise.notebook_entries SET created_at=1e15,updated_at=1e15"
        )

    application_name = f"task112-late-{sort}"
    writer_dsn = make_conninfo(
        **{
            **conninfo_to_dict(migrated_pg.runtime_dsn),
            "application_name": application_name,
        }
    )
    inserted = asyncio.Event()
    release = asyncio.Event()
    guard_calls = 0

    async def pause_before_commit():
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 2:
            inserted.set()
            await release.wait()

    async with Database(writer_dsn, resource=application_name, max_size=1) as writer_database:
        writer_database.execution_guard = pause_before_commit
        writer = PostgresSessionStore(writer_database, actor.scope)
        writer_task = asyncio.create_task(
            writer.upsert_notebook_entries(session_id, [_item("late-commit", "迟提交")])
        )
        await asyncio.wait_for(inserted.wait(), 5)
        first_task = asyncio.create_task(store.list_notebook_entries(limit=1, cursor="", sort=sort))
        async with await psycopg.AsyncConnection.connect(
            migrated_pg.admin_dsn, row_factory=dict_row
        ) as observer:
            blocked = await asyncio.wait_for(
                _wait_for_application_block_or_completion(observer, application_name, first_task),
                5,
            )
        release.set()
        assert await writer_task == 1
        first = await first_task
    assert blocked is True
    assert first["total"] == 3

    await store.upsert_notebook_entries(session_id, [_item("after-fence", "游标后插入")])
    exported = list(first["items"])
    page = first
    while page["next_cursor"] is not None:
        page = await store.list_notebook_entries(limit=1, cursor=page["next_cursor"], sort=sort)
        assert page["total"] == 3
        exported.extend(page["items"])
    assert {row["question_id"] for row in exported} == {
        "visible-1",
        "visible-2",
        "late-commit",
    }


async def test_search_keeps_ascii_nocase_nonascii_exact_and_literal_escaping(
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    store, session_id = await _session_and_store(pg_session_store_factory, actor, "-search-case")
    await store.upsert_notebook_entries(
        session_id,
        [
            _item("question", "Fourier Transform 100%"),
            _item("user", "用户字段", user_answer="AnswerABC a_b"),
            _item("correct", "正确字段", correct_answer=r"CORRECTXYZ C:\\tmp"),
            _item("explanation", "解释字段", explanation="ExplainDEF"),
            _item("nonascii", "Ärger"),
            _item("percent-decoy", "Fourier Transform 1000"),
            _item("underscore-decoy", "AnswerABC axb"),
            _item("slash-decoy", "CORRECTXYZ C:tmp"),
        ],
    )
    for needle, expected in (
        ("fourier transform", {"question", "percent-decoy"}),
        ("answerabc", {"user", "underscore-decoy"}),
        ("correctxyz", {"correct", "slash-decoy"}),
        ("explaindef", {"explanation"}),
        ("100%", {"question"}),
        ("a_b", {"user"}),
        (r"C:\\tmp", {"correct"}),
        ("Ärger", {"nonascii"}),
        ("ärger", set()),
    ):
        result = await store.list_notebook_entries(search=needle)
        assert {row["question_id"] for row in result["items"]} == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("b", 10**400),
        ("a", -(10**400)),
        ("b_id", 10**40),
        ("a_id", 10**40),
        ("x", 10**40),
        ("v", True),
        ("v", 1.0),
    ],
)
async def test_cursor_rejects_overflowing_numbers_and_non_integer_version(field, value):
    query = QuestionBankQuery(cursor="").normalized()
    cursor = encode_cursor(
        query,
        boundary_created_at=100,
        boundary_id=4,
        after_created_at=100,
        after_id=3,
    )
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    if field == "v":
        payload["v"] = value
    elif field == "x":
        payload["x"] = value
    elif field.endswith("_id"):
        payload[field[0]][1] = value
    else:
        payload[field][0] = value
    malformed = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    assert len(malformed) < 2048
    with pytest.raises(QuestionBankCursorError):
        decode_cursor(QuestionBankQuery(cursor=malformed).normalized())


async def test_category_display_order_uses_name_not_casefold_key(
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    store, session_id = await _session_and_store(pg_session_store_factory, actor, "-cat-order")
    await store.upsert_notebook_entries(session_id, [_item("q", "分类排序")])
    entry = (await store.list_notebook_entries())["items"][0]
    zebra = await store.create_category("Zebra")
    apple = await store.create_category("apple")
    assert await store.add_entry_to_category(entry["id"], zebra["id"])
    assert await store.add_entry_to_category(entry["id"], apple["id"])
    assert [row["name"] for row in await store.list_categories()] == ["Zebra", "apple"]
    assert [row["name"] for row in await store.get_entry_categories(entry["id"])] == [
        "Zebra",
        "apple",
    ]


async def test_scope_async_probe_and_followup_delete_has_controlled_conflict(
    migrated_pg,
    business_actors,
    pg_session_store_factory,
):
    owner = business_actors.tenants[0].owners[0]
    other = business_actors.tenants[0].owners[1]
    store, source_id = await _session_and_store(pg_session_store_factory, owner, "-source")
    _, followup_id = await _session_and_store(pg_session_store_factory, owner, "-target")
    other_store = pg_session_store_factory(other)
    assert await store.has_question_bank_entries() is False
    await store.upsert_notebook_entries(source_id, [_item("q1", "引用")])
    entry = (await store.list_notebook_entries())["items"][0]
    assert await store.has_question_bank_entries() is True
    assert await other_store.has_question_bank_entries() is False
    assert await other_store.get_notebook_entry(entry["id"]) is None
    assert await other_store.delete_notebook_entry(entry["id"]) is False
    assert await other_store.add_entry_to_category(entry["id"], 1) is False

    assert await store.update_notebook_entry(entry["id"], {"followup_session_id": followup_id})
    with pytest.raises(QuestionBankReferenceConflict, match="follow-up"):
        await store.delete_session(followup_id)
    assert await store.get_session(followup_id) is not None
    assert await store.update_notebook_entry(entry["id"], {"followup_session_id": ""})
    assert await store.delete_session(followup_id) is True

    async with Database(
        migrated_pg.runtime_dsn, resource="task-1.12-probe-failure", max_size=1
    ) as disposable_database:
        disposable_store = PostgresSessionStore(disposable_database, owner.scope)
        assert await disposable_store.has_question_bank_entries() is True
    with pytest.raises(PoolClosed):
        await disposable_store.has_question_bank_entries()


async def test_legacy_turn_lookup_versioned_deletes_and_turn_reference_conflict(
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    store, session_id = await _session_and_store(pg_session_store_factory, actor, "-turns")
    await store.upsert_notebook_entries(
        session_id,
        [
            _item("same", "旧命名空间"),
            _item("same", "图书 block", turn_id="block-1"),
        ],
    )
    legacy = await store.find_notebook_entry(session_id, "same")
    block = await store.find_notebook_entry(session_id, "same", turn_id="block-1")
    assert legacy is not None and legacy["question"] == "旧命名空间"
    assert block is not None and block["question"] == "图书 block"
    with pytest.raises(QuestionBankVersionConflict):
        await store.delete_notebook_entry(legacy["id"], expected_version=99)
    assert await store.delete_notebook_entry(legacy["id"], expected_version=legacy["version"])
    assert await store.delete_notebook_entry(legacy["id"]) is False

    user_message = await store.add_message(session_id, "user", "问题")
    assistant_message = await store.add_message(
        session_id, "assistant", "答案", parent_message_id=user_message
    )
    turn = await store.begin_turn(session_id, "chat", turn_id="real-turn")
    assert await store.link_turn_user_message(turn["id"], user_message)
    assert await store.link_turn_message(turn["id"], assistant_message)
    assert await store.update_turn_status(turn["id"], "completed")
    await store.upsert_notebook_entries(
        session_id,
        [
            {
                "question_id": "runtime",
                "question": "真实 turn",
                "turn_id": turn["id"],
                "source": "deep_question",
            }
        ],
    )
    runtime = await store.find_notebook_entry(session_id, "runtime", turn_id=turn["id"])
    assert runtime is not None
    with pytest.raises(QuestionBankReferenceConflict, match="Turn"):
        await store.delete_turn_by_message(session_id, user_message)
    assert await store.get_turn(turn["id"]) is not None
    assert await store.delete_notebook_entry(runtime["id"])
    assert (await store.delete_turn_by_message(session_id, user_message))["deleted"] is True


async def test_category_delete_cas_and_entry_delete_cascade_links(
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    store, session_id = await _session_and_store(pg_session_store_factory, actor, "-deletes")
    await store.upsert_notebook_entries(session_id, [_item("q1", "待删除")])
    entry = (await store.list_notebook_entries())["items"][0]
    category = await store.create_category("删除测试")
    assert await store.add_entry_to_category(entry["id"], category["id"])
    with pytest.raises(QuestionBankVersionConflict):
        await store.delete_category(category["id"], expected_version=2)
    assert await store.delete_notebook_entry(entry["id"], expected_version=entry["version"])
    assert await store.get_entry_categories(entry["id"]) == []
    listed = await store.list_categories()
    assert listed[0]["entry_count"] == 0
    assert await store.delete_category(category["id"], expected_version=category["version"])
