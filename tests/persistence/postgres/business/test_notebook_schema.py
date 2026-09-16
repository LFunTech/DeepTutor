"""0004 题库 schema：真实 PG 引用、隔离、去重与事务契约（尚非 Store 接线）。"""

import asyncio

import psycopg
from psycopg.types.json import Jsonb
import pytest

pytestmark = pytest.mark.asyncio


async def _wait_for_blocker(connection, blocked_pid, blocker_pid):
    # 观察 PG 的真实等待关系，不以 sleep 假设两写入已交错。
    while True:
        row = await (
            await connection.execute(
                "SELECT pg_blocking_pids(%s) AS blockers",
                (blocked_pid,),
            )
        ).fetchone()
        if blocker_pid in row["blockers"]:
            return
        await asyncio.sleep(0.01)


async def _entry(c, actor, session_id, *, id=17, turn_id="", question_id="q1", **fields):
    values = dict(
        tenant_id=actor.tenant_id,
        owner_id=actor.user_id,
        id=id,
        session_id=session_id,
        turn_id=turn_id,
        question_id=question_id,
        question="求 100%_\\ 的值",
        created_at=10.0,
        updated_at=11.0,
        **fields,
    )
    query = psycopg.sql.SQL(
        "INSERT INTO enterprise.notebook_entries ({}) VALUES ({}) RETURNING *"
    ).format(
        psycopg.sql.SQL(",").join(map(psycopg.sql.Identifier, values)),
        psycopg.sql.SQL(",").join(psycopg.sql.Placeholder() for _ in values),
    )
    return await (await c.execute(query, tuple(values.values()))).fetchone()


async def _category(c, actor, *, id=7, name="Math"):
    return await (
        await c.execute(
            "INSERT INTO enterprise.notebook_categories(tenant_id,owner_id,id,name,created_at) VALUES(%s,%s,%s,%s,10) RETURNING *",
            (actor.tenant_id, actor.user_id, id, name),
        )
    ).fetchone()


async def _link(c, actor, entry_id=17, category_id=7):
    await c.execute(
        "INSERT INTO enterprise.notebook_entry_categories(tenant_id,owner_id,entry_id,category_id) VALUES(%s,%s,%s,%s)",
        (actor.tenant_id, actor.user_id, entry_id, category_id),
    )


async def _session(factory, actor, suffix=""):
    return (await factory(actor).create_session("notebook", session_id=actor.user_id + suffix))[
        "id"
    ]


async def test_all_fields_roundtrip_and_legacy_book_execution_namespaces(
    business_database,
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    sid = await _session(pg_session_store_factory, actor)
    followup = await _session(pg_session_store_factory, actor, "-followup")
    async with business_database.transaction(actor.scope) as c:
        await c.execute(
            "INSERT INTO enterprise.turns(tenant_id,user_id,session_id,id,status,owner_id) VALUES(%s,%s,%s,'runtime','completed','worker')",
            (actor.tenant_id, actor.user_id, sid),
        )
        await c.execute(
            "INSERT INTO enterprise.mastery_paths(tenant_id,owner_id,path_id,state,revision,created_at,updated_at) VALUES(%s,%s,'path',%s,1,1,1)",
            (actor.tenant_id, actor.user_id, Jsonb({"book_id": "path"})),
        )
        await c.execute(
            "INSERT INTO enterprise.mastery_knowledge_points(tenant_id,owner_id,path_id,kp_id,active) VALUES(%s,%s,'path','topic',true)",
            (actor.tenant_id, actor.user_id),
        )
        fields = dict(
            question_type="choice",
            options=Jsonb({"A": "甲"}),
            correct_answer="A",
            explanation="说明",
            difficulty="hard",
            user_answer="A",
            user_answer_images=Jsonb([{"attachment_id": "synthetic-image"}]),
            source="mastery_path",
            material_id="path",
            material_title="路径",
            section_id="topic",
            section_title="主题",
            score_trend="improved",
            is_correct=True,
            resolved=True,
            bookmarked=True,
            followup_session_id=followup,
            ai_judgment="评语",
        )
        row = await _entry(c, actor, sid, turn_id="runtime", **fields)
        assert row["id"] == 17 and row["version"] == 1
        assert row["execution_turn_id"] == "runtime"
        assert row["followup_session_ref"] == followup
        for key, value in fields.items():
            assert row[key] == (value.obj if isinstance(value, Jsonb) else value)
        legacy = await _entry(c, actor, sid, id=18)
        book = await _entry(
            c, actor, sid, id=19, source="book", turn_id="page-block", material_id="book-id"
        )
        assert legacy["turn_id"] == "" and legacy["execution_turn_id"] is None
        assert legacy["followup_session_id"] == "" and legacy["followup_session_ref"] is None
        assert book["turn_id"] == "page-block" and book["execution_turn_id"] is None
        assert (
            await (
                await c.execute(
                    "SELECT id FROM enterprise.notebook_entries WHERE turn_id='' AND question_id='q1'"
                )
            ).fetchall()
        ) == [{"id": 18}]


async def test_same_integer_ids_are_scoped_and_admin_has_no_personal_bypass(
    business_database,
    business_actors,
    pg_session_store_factory,
):
    for tenant in business_actors.tenants:
        for actor in tenant.owners:
            sid = await _session(pg_session_store_factory, actor)
            async with business_database.transaction(actor.scope) as c:
                await _entry(c, actor, sid)
                await _category(c, actor)
                await _link(c, actor)
    for tenant in business_actors.tenants:
        for actor in (*tenant.owners, tenant.admin):
            async with business_database.transaction(actor.scope) as c:
                for table in (
                    "notebook_entries",
                    "notebook_categories",
                    "notebook_entry_categories",
                ):
                    rows = await (
                        await c.execute(f"SELECT owner_id FROM enterprise.{table}")
                    ).fetchall()
                    assert rows == ([] if actor is tenant.admin else [{"owner_id": actor.user_id}])
                    assert (
                        await c.execute(
                            f"UPDATE enterprise.{table} SET owner_id=owner_id WHERE owner_id<>%s",
                            (actor.user_id,),
                        )
                    ).rowcount == 0
                    assert (
                        await c.execute(
                            f"DELETE FROM enterprise.{table} WHERE owner_id<>%s", (actor.user_id,)
                        )
                    ).rowcount == 0


@pytest.mark.parametrize("foreign", ["owner", "tenant"])
@pytest.mark.parametrize("reference", ["session", "turn", "followup", "entry", "category"])
async def test_foreign_scope_composite_references_rejected_even_for_admin_connection(
    migrated_pg,
    business_database,
    business_actors,
    pg_session_store_factory,
    foreign,
    reference,
):
    actor = business_actors.tenants[0].owners[0]
    other = business_actors.tenants[foreign == "tenant"].owners[1]
    sid = await _session(pg_session_store_factory, actor)
    foreign_sid = await _session(pg_session_store_factory, other)
    async with business_database.transaction(other.scope) as c:
        await _entry(c, other, foreign_sid)
        await _category(c, other)
        await c.execute(
            "INSERT INTO enterprise.turns(tenant_id,user_id,session_id,id,status) VALUES(%s,%s,%s,'foreign-turn','completed')",
            (other.tenant_id, other.user_id, foreign_sid),
        )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as c:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            async with c.transaction():
                if reference == "session":
                    await _entry(c, actor, foreign_sid)
                elif reference == "turn":
                    await _entry(c, actor, sid, turn_id="foreign-turn")
                elif reference == "followup":
                    await _entry(c, actor, sid, followup_session_id=foreign_sid)
                elif reference == "entry":
                    await _category(c, actor)
                    await _link(c, actor)
                else:
                    await _entry(c, actor, sid)
                    await _link(c, actor)


@pytest.mark.parametrize(
    "change",
    [
        "execution_turn_id=NULL",
        "turn_id='missing'",
        "source='deep_question'",
        "followup_session_id='missing'",
    ],
)
async def test_derived_references_cannot_be_omitted_or_changed_to_dangling_values(
    business_database,
    business_actors,
    pg_session_store_factory,
    change,
):
    actor = business_actors.tenants[0].owners[0]
    sid = await _session(pg_session_store_factory, actor)
    async with business_database.transaction(actor.scope) as c:
        await _entry(c, actor, sid, source="book", turn_id="block")
    expected = (
        psycopg.errors.GeneratedAlways
        if change.startswith("execution")
        else psycopg.errors.ForeignKeyViolation
    )
    # 改 book 的 block 文本合法；为 turn_id 负例先切入 legacy execution 命名空间。
    if change.startswith("turn_id"):
        async with business_database.transaction(actor.scope) as c:
            await c.execute(
                "UPDATE enterprise.notebook_entries SET source='deep_question',turn_id=''"
            )
    with pytest.raises(expected):
        async with business_database.transaction(actor.scope) as c:
            await c.execute(f"UPDATE enterprise.notebook_entries SET {change}")


async def test_category_ascii_nocase_is_locale_independent_and_unicode_not_casefolded(
    business_database,
    business_actors,
):
    actor = business_actors.tenants[0].owners[0]
    async with business_database.transaction(actor.scope) as c:
        for i, name in enumerate(["Math", "Ä", "ä", "Straße", "STRASSE", "İ", "i"]):
            await _category(c, actor, id=i + 1, name=name)
    with pytest.raises(psycopg.errors.UniqueViolation):
        async with business_database.transaction(actor.scope) as c:
            await _category(c, actor, id=99, name="mATH")
    with pytest.raises(psycopg.errors.CheckViolation):
        async with business_database.transaction(actor.scope) as c:
            await _category(c, actor, id=99, name="")
    with pytest.raises(psycopg.errors.UniqueViolation):
        async with business_database.transaction(actor.scope) as c:
            await c.execute("UPDATE enterprise.notebook_categories SET name='MATH' WHERE id=2")


async def test_category_and_entry_deletes_cascade_only_links_and_followup_delete_refuses(
    business_database,
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    sid = await _session(pg_session_store_factory, actor)
    followup = await _session(pg_session_store_factory, actor, "-followup")
    async with business_database.transaction(actor.scope) as c:
        await _entry(c, actor, sid, followup_session_id=followup)
        await _category(c, actor)
        await _link(c, actor)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        async with business_database.transaction(actor.scope) as c:
            await c.execute("DELETE FROM enterprise.sessions WHERE id=%s", (followup,))
    async with business_database.transaction(actor.scope) as c:
        await c.execute("DELETE FROM enterprise.notebook_categories")
        assert (
            await (
                await c.execute("SELECT count(*) AS n FROM enterprise.notebook_entries")
            ).fetchone()
        )["n"] == 1
        assert (
            await (
                await c.execute("SELECT count(*) AS n FROM enterprise.notebook_entry_categories")
            ).fetchone()
        )["n"] == 0
        await _category(c, actor)
        await _link(c, actor)
        await c.execute("DELETE FROM enterprise.sessions WHERE id=%s", (sid,))
        assert await (await c.execute("SELECT * FROM enterprise.notebook_entries")).fetchall() == []
        assert (
            await (await c.execute("SELECT * FROM enterprise.notebook_entry_categories")).fetchall()
            == []
        )
        assert (
            await (
                await c.execute("SELECT count(*) AS n FROM enterprise.notebook_categories")
            ).fetchone()
        )["n"] == 1


async def test_two_connections_unique_conflict_and_entire_failed_batch_rolls_back(
    business_database,
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    sid = await _session(pg_session_store_factory, actor)
    started = asyncio.get_running_loop().create_future()

    async def competitor():
        with pytest.raises(psycopg.errors.UniqueViolation):
            async with business_database.transaction(actor.scope) as c:
                pid = (await (await c.execute("SELECT pg_backend_pid() AS pid")).fetchone())["pid"]
                started.set_result(pid)
                await _entry(c, actor, sid, id=18)
        return pid

    async with business_database.transaction(actor.scope) as c:
        pid = (await (await c.execute("SELECT pg_backend_pid() AS pid")).fetchone())["pid"]
        await _entry(c, actor, sid)
        task = asyncio.create_task(competitor())
        blocked_pid = await asyncio.wait_for(started, 5)
        await asyncio.wait_for(_wait_for_blocker(c, blocked_pid, pid), 5)
    assert await asyncio.wait_for(task, 5) != pid
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        async with business_database.transaction(actor.scope) as c:
            await c.execute(
                "UPDATE enterprise.notebook_entries SET user_answer='must rollback',version=version+1"
            )
            await _category(c, actor)
            await _link(c, actor)
            await _link(c, actor, entry_id=999)
    async with business_database.transaction(actor.scope) as c:
        row = await (
            await c.execute("SELECT id,user_answer,version FROM enterprise.notebook_entries")
        ).fetchone()
        assert row == {"id": 17, "user_answer": "", "version": 1}
        assert (
            await (await c.execute("SELECT * FROM enterprise.notebook_categories")).fetchall() == []
        )
        assert (
            await (await c.execute("SELECT * FROM enterprise.notebook_entry_categories")).fetchall()
            == []
        )


async def test_literal_search_and_bidirectional_stable_keyset_order(
    business_database,
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    sid = await _session(pg_session_store_factory, actor)
    async with business_database.transaction(actor.scope) as c:
        for id in (19, 17, 18):
            await _entry(c, actor, sid, id=id, question_id=str(id))
        rows = await (
            await c.execute(
                "SELECT id FROM enterprise.notebook_entries WHERE question LIKE %s ESCAPE '\\' ORDER BY created_at DESC,id DESC",
                ("%100\\%\\_\\\\%",),
            )
        ).fetchall()
        assert [r["id"] for r in rows] == [19, 18, 17]
        rows = await (
            await c.execute(
                "SELECT id FROM enterprise.notebook_entries WHERE (created_at,id)<(10,19) ORDER BY created_at DESC,id DESC LIMIT 1"
            )
        ).fetchall()
        assert rows == [{"id": 18}]
        rows = await (
            await c.execute(
                "SELECT id FROM enterprise.notebook_entries WHERE (created_at,id)>(10,17) ORDER BY created_at,id LIMIT 1"
            )
        ).fetchall()
        assert rows == [{"id": 18}]


@pytest.mark.parametrize(
    "table", ["notebook_entries", "notebook_categories", "notebook_entry_categories"]
)
async def test_rls_rejects_forged_owner_inserts_and_scope_updates(
    business_database,
    business_actors,
    pg_session_store_factory,
    table,
):
    actor = business_actors.tenants[0].owners[0]
    other = business_actors.tenants[0].owners[1]
    sid = await _session(pg_session_store_factory, other)
    async with business_database.transaction(other.scope) as c:
        await _entry(c, other, sid)
        await _category(c, other)
        await _link(c, other)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with business_database.transaction(actor.scope) as c:
            if table == "notebook_entries":
                await _entry(c, other, sid, id=18, question_id="q2")
            elif table == "notebook_categories":
                await _category(c, other, id=8, name="forged")
            else:
                await _link(c, other)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with business_database.transaction(other.scope) as c:
            await c.execute(f"UPDATE enterprise.{table} SET owner_id=%s", (actor.user_id,))


async def test_followup_self_reference_and_real_turn_delete_lifecycle(
    business_database,
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    sid = await _session(pg_session_store_factory, actor)
    other_sid = await _session(pg_session_store_factory, actor, "-other")
    async with business_database.transaction(actor.scope) as c:
        await c.execute(
            "INSERT INTO enterprise.turns(tenant_id,user_id,session_id,id,status) VALUES(%s,%s,%s,'runtime','completed')",
            (actor.tenant_id, actor.user_id, sid),
        )
        await _entry(c, actor, sid, turn_id="runtime", followup_session_id=sid)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        async with business_database.transaction(actor.scope) as c:
            await _entry(c, actor, other_sid, id=18, turn_id="runtime")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        async with business_database.transaction(actor.scope) as c:
            await c.execute("DELETE FROM enterprise.turns WHERE id='runtime'")
    async with business_database.transaction(actor.scope) as c:
        await c.execute("DELETE FROM enterprise.sessions WHERE id=%s", (sid,))
        assert await (await c.execute("SELECT * FROM enterprise.notebook_entries")).fetchall() == []
        assert await (await c.execute("SELECT * FROM enterprise.turns")).fetchall() == []


async def test_two_connections_ascii_category_conflict_and_rename_rollback(
    business_database,
    business_actors,
):
    actor = business_actors.tenants[0].owners[0]
    started = asyncio.get_running_loop().create_future()

    async def competitor():
        with pytest.raises(psycopg.errors.UniqueViolation):
            async with business_database.transaction(actor.scope) as c:
                pid = (await (await c.execute("SELECT pg_backend_pid() AS pid")).fetchone())["pid"]
                started.set_result(pid)
                await _category(c, actor, id=8, name="mATH")
        return pid

    async with business_database.transaction(actor.scope) as c:
        pid = (await (await c.execute("SELECT pg_backend_pid() AS pid")).fetchone())["pid"]
        await _category(c, actor)
        task = asyncio.create_task(competitor())
        blocked_pid = await asyncio.wait_for(started, 5)
        await asyncio.wait_for(_wait_for_blocker(c, blocked_pid, pid), 5)
    assert await asyncio.wait_for(task, 5) != pid
    async with business_database.transaction(actor.scope) as c:
        assert await (
            await c.execute("SELECT id,name,version FROM enterprise.notebook_categories")
        ).fetchall() == [{"id": 7, "name": "Math", "version": 1}]


async def test_generated_ids_and_json_enum_version_checks_with_low_privilege(
    business_database,
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    sid = await _session(pg_session_store_factory, actor)
    async with business_database.transaction(actor.scope) as c:
        row = await (
            await c.execute(
                "INSERT INTO enterprise.notebook_entries(tenant_id,owner_id,session_id,question_id,question,created_at,updated_at) VALUES(%s,%s,%s,'auto','auto',1,1) RETURNING id",
                (actor.tenant_id, actor.user_id, sid),
            )
        ).fetchone()
        assert isinstance(row["id"], int)
        category = await (
            await c.execute(
                "INSERT INTO enterprise.notebook_categories(tenant_id,owner_id,name,created_at) VALUES(%s,%s,'auto',1) RETURNING id",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        assert isinstance(category["id"], int)
    for fields in (
        {"source": "bad"},
        {"score_trend": "bad"},
        {"version": 0},
        {"user_answer_images": Jsonb({})},
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            async with business_database.transaction(actor.scope) as c:
                await _entry(c, actor, sid, **fields)


async def test_reader_never_observes_failed_writer_body_links_or_version(
    business_database,
    business_actors,
    pg_session_store_factory,
):
    actor = business_actors.tenants[0].owners[0]
    sid = await _session(pg_session_store_factory, actor)
    async with business_database.transaction(actor.scope) as c:
        await _entry(c, actor, sid)
    async with business_database.transaction(actor.scope) as reader:
        reader_pid = (await (await reader.execute("SELECT pg_backend_pid() AS pid")).fetchone())[
            "pid"
        ]
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            async with business_database.transaction(actor.scope) as writer:
                writer_pid = (
                    await (await writer.execute("SELECT pg_backend_pid() AS pid")).fetchone()
                )["pid"]
                assert reader_pid != writer_pid
                await writer.execute(
                    "UPDATE enterprise.notebook_entries SET user_answer='uncommitted',version=version+1"
                )
                await _category(writer, actor)
                await _link(writer, actor)
                assert await (
                    await reader.execute(
                        "SELECT user_answer,version FROM enterprise.notebook_entries"
                    )
                ).fetchall() == [{"user_answer": "", "version": 1}]
                assert (
                    await (
                        await reader.execute("SELECT * FROM enterprise.notebook_entry_categories")
                    ).fetchall()
                    == []
                )
                await _link(writer, actor, entry_id=999)
        assert await (
            await reader.execute("SELECT user_answer,version FROM enterprise.notebook_entries")
        ).fetchall() == [{"user_answer": "", "version": 1}]
        assert (
            await (
                await reader.execute("SELECT * FROM enterprise.notebook_entry_categories")
            ).fetchall()
            == []
        )
        assert (
            await (await reader.execute("SELECT * FROM enterprise.notebook_categories")).fetchall()
            == []
        )
