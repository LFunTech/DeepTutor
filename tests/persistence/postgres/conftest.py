"""此测试子树可用 --confcutdir=tests/persistence 单独运行。"""

import uuid

import psycopg
from psycopg import sql
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401


@pytest.fixture
def restricted_dsn(pg_dsn):  # noqa: F811 - pytest fixture 注入
    role = "app_" + uuid.uuid4().hex
    with psycopg.connect(pg_dsn) as c:
        c.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
        c.execute("CREATE SCHEMA core_test")
        c.execute(
            "CREATE TABLE core_test.items (tenant uuid NOT NULL, owner text NOT NULL, value text NOT NULL)"
        )
        c.execute("ALTER TABLE core_test.items ENABLE ROW LEVEL SECURITY")
        c.execute("ALTER TABLE core_test.items FORCE ROW LEVEL SECURITY")
        c.execute(
            "CREATE POLICY scoped ON core_test.items USING (tenant=nullif(current_setting('app.tenant_id',true),'')::uuid AND owner=current_setting('app.user_id',true))"
        )
        c.execute(sql.SQL("GRANT USAGE ON SCHEMA core_test TO {}").format(sql.Identifier(role)))
        c.execute(
            sql.SQL("GRANT SELECT, INSERT ON core_test.items TO {}").format(sql.Identifier(role))
        )
    return pg_dsn.replace("user=postgres", "user=" + role)
