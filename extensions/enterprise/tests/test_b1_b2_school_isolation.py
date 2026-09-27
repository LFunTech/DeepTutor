"""B2 双学校数据面：隔离合成数据，不代表真实 G2 放量证据。"""

import asyncio
import hashlib
import json
from uuid import uuid4

from deeptutor_enterprise.knowledge_bases import list_externalized_knowledge_bases
from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.scope import TenantScope
from deeptutor_enterprise.stores.postgres.connection import Database
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from deeptutor.persistence.postgres.session import PostgresSessionStore
from tests.fixtures.postgres import single_database_user_dsn


@pytest.mark.asyncio
async def test_two_schools_with_same_user_and_kb_ids_remain_isolated(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    schools = [str(uuid4()), str(uuid4())]
    user_id = "same-external-user"
    kb_id = "same-kb-name"

    async with Database(single_database_user_dsn(pg_dsn), resource="b2-synthetic") as db:
        for index, school_id in enumerate(schools):
            async with db.transaction(TenantScope(school_id, "@seed")) as c:
                await c.execute(
                    "INSERT INTO enterprise.tenants"
                    "(id,external_eligibility,local_enabled,provisioning_status,"
                    "auth_epoch,bootstrap_completed)"
                    " VALUES(%s,'not_required',true,'ready',%s,true)",
                    (school_id, f"epoch-{index}"),
                )
                await c.execute(
                    "INSERT INTO enterprise.users(tenant_id,id,username,role)"
                    " VALUES(%s,%s,%s,'user')",
                    (school_id, user_id, f"user-{index}"),
                )
                if index == 0:
                    await c.execute(
                        "INSERT INTO enterprise.users(tenant_id,id,username,role)"
                        " VALUES(%s,'another-user','user-a2','user')",
                        (school_id,),
                    )
                await c.execute(
                    "INSERT INTO enterprise.resource_objects"
                    "(tenant_id,owner_id,id,resource_kind,resource_id,bucket,object_key,"
                    "content_hash,size_bytes,mime_type,state,retention,metadata,created_by)"
                    " VALUES(%s,%s,%s,'knowledge_base_document',%s,'b2-test',%s,%s,1,"
                    "'text/plain','ready','retained',%s::jsonb,%s)",
                    (
                        school_id,
                        user_id,
                        uuid4(),
                        kb_id,
                        f"schools/{school_id}/{kb_id}",
                        hashlib.sha256(f"{school_id}:{kb_id}".encode()).hexdigest(),
                        json.dumps({"kb_label": f"学校 {index} 的同名知识库", "status": "ready"}),
                        user_id,
                    ),
                )

        a_store = PostgresSessionStore(db, TenantScope(schools[0], user_id))
        other_store = PostgresSessionStore(db, TenantScope(schools[0], "another-user"))
        b_store = PostgresSessionStore(db, TenantScope(schools[1], user_id))
        a_session = await a_store.create_session(title="学校 A 私有会话")
        other_session = await other_store.create_session(title="学校 A 另一用户私有会话")

        async def view(store):
            return await store.get_session(a_session["id"]), await list_externalized_knowledge_bases(
                store
            )

        (a_seen, a_kbs), (b_seen, b_kbs) = await asyncio.gather(view(a_store), view(b_store))
        assert a_seen is not None
        assert b_seen is None
        assert await other_store.get_session(a_session["id"]) is None
        assert await a_store.get_session(other_session["id"]) is None
        assert [(kb.id, kb.label) for kb in a_kbs] == [(kb_id, "学校 0 的同名知识库")]
        assert [(kb.id, kb.label) for kb in b_kbs] == [(kb_id, "学校 1 的同名知识库")]

        # 当前单库 owner 运行模式仅靠 Store 显式条件隔离；表 owner 会绕过非 FORCE RLS。
        async with db.transaction(TenantScope(schools[1], user_id)) as c:
            rows = await (await c.execute("SELECT tenant_id FROM enterprise.sessions")).fetchall()
            assert [str(row["tenant_id"]) for row in rows] == [schools[0], schools[0]]
        async with db.transaction(TenantScope(schools[0], user_id)) as c:
            rows = await (await c.execute("SELECT tenant_id FROM enterprise.sessions")).fetchall()
            assert [str(row["tenant_id"]) for row in rows] == [schools[0], schools[0]]

        role = "b2_restricted_" + uuid4().hex
        with psycopg.connect(pg_dsn) as admin:
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN NOBYPASSRLS").format(sql.Identifier(role)))
            admin.execute(sql.SQL("GRANT USAGE ON SCHEMA enterprise TO {}").format(sql.Identifier(role)))
            admin.execute(
                sql.SQL("GRANT SELECT,INSERT ON enterprise.sessions,enterprise.resource_objects TO {}")
                .format(sql.Identifier(role))
            )
        restricted_dsn = make_conninfo(**{**conninfo_to_dict(pg_dsn), "user": role})
        async with Database(restricted_dsn, resource="b2-restricted") as restricted:
            async with restricted.transaction(TenantScope(schools[1], user_id)) as c:
                rows = await (await c.execute("SELECT tenant_id FROM enterprise.sessions")).fetchall()
                assert rows == []
                rows = await (
                    await c.execute("SELECT tenant_id FROM enterprise.resource_objects")
                ).fetchall()
                assert [str(row["tenant_id"]) for row in rows] == [schools[1]]
            async with restricted.transaction(TenantScope(schools[0], user_id)) as c:
                rows = await (await c.execute("SELECT id FROM enterprise.sessions")).fetchall()
                assert [row["id"] for row in rows] == [a_session["id"]]
                rows = await (
                    await c.execute("SELECT tenant_id FROM enterprise.resource_objects")
                ).fetchall()
                assert [str(row["tenant_id"]) for row in rows] == [schools[0]]
            async with restricted.transaction(TenantScope(schools[0], "another-user")) as c:
                rows = await (await c.execute("SELECT id FROM enterprise.sessions")).fetchall()
                assert [row["id"] for row in rows] == [other_session["id"]]
            # 自定义 GUC 并非数据库验签身份：持有同一连接权限者可主动改 scope。
            # 此处只记录单账号威胁模型的边界，不把 FORCE/非 owner RLS 误称为抗恶意直连。
            async with restricted.transaction(TenantScope(schools[1], user_id)) as c:
                await c.execute("SELECT set_config('app.tenant_id',%s,true)", (schools[0],))
                rows = await (await c.execute("SELECT id FROM enterprise.sessions")).fetchall()
                assert [row["id"] for row in rows] == [a_session["id"]]
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                async with restricted.transaction(TenantScope(schools[1], user_id)) as c:
                    await c.execute(
                        "INSERT INTO enterprise.sessions(tenant_id,owner_id,id,title)"
                        " VALUES(%s,%s,'wrong-school','invalid')",
                        (schools[0], user_id),
                    )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                async with restricted.transaction(TenantScope(schools[0], user_id)) as c:
                    await c.execute(
                        "INSERT INTO enterprise.sessions(tenant_id,owner_id,id,title)"
                        " VALUES(%s,'another-user','wrong-owner','invalid')",
                        (schools[0],),
                    )
