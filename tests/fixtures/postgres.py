"""仅启动临时集群，不连接或迁移开发者现有数据库。"""

import os
from pathlib import Path
import shutil
import subprocess
import uuid

import pytest


@pytest.fixture(scope="session")
def pg_cluster(tmp_path_factory):
    bindir = Path(os.environ.get("DT_TEST_PG_BIN", "/opt/pgsql/bin"))
    if not (bindir / "initdb").is_file():
        pytest.fail("真实 PG 测试需要 DT_TEST_PG_BIN 指向 initdb/pg_ctl，不能以 mock 替代")
    root = tmp_path_factory.mktemp("enterprise-pg")
    # Unix socket 路径不能使用 pytest 过长的目录。
    import tempfile

    socket = Path(tempfile.mkdtemp(prefix="dtep-", dir="/tmp"))
    data = root / "cluster"
    subprocess.run(
        [
            str(bindir / "initdb"),
            "-D",
            str(data),
            "-U",
            "postgres",
            "-A",
            "trust",
            "--no-locale",
            "-E",
            "UTF8",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            str(bindir / "pg_ctl"),
            "-D",
            str(data),
            "-l",
            str(root / "postgres.log"),
            "-o",
            f"-c listen_addresses='' -k {socket}",
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    try:
        yield f"host={socket} user=postgres dbname=postgres"
    finally:
        subprocess.run(
            [str(bindir / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"],
            check=True,
            capture_output=True,
        )
        shutil.rmtree(socket)


def single_database_user_dsn(admin_dsn: str) -> str:
    """Create and return a non-privileged database owner DSN for one-test single-user runtime."""

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    info = conninfo_to_dict(admin_dsn)
    role = "owner_" + uuid.uuid4().hex
    with psycopg.connect(admin_dsn) as c:
        c.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(sql.Identifier(role))
        )
        c.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(info["dbname"]), sql.Identifier(role)
            )
        )
        schemas = [
            row[0]
            for row in c.execute(
                """
                SELECT nspname
                FROM pg_namespace
                WHERE nspname !~ '^pg_' AND nspname <> 'information_schema'
                """
            ).fetchall()
        ]
        for schema in schemas:
            c.execute(
                sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(
                    sql.Identifier(schema), sql.Identifier(role)
                )
            )
        objects = c.execute(
            """
            SELECT n.nspname, c.relname, c.relkind
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
              AND c.relkind IN ('r','p','v','m','f','S')
            ORDER BY CASE c.relkind WHEN 'S' THEN 2 ELSE 1 END
            """
        ).fetchall()
        kind_sql = {"r": "TABLE", "p": "TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW", "f": "FOREIGN TABLE", "S": "SEQUENCE"}
        for schema, name, kind in objects:
            c.execute(
                sql.SQL("ALTER {} {}.{} OWNER TO {}").format(
                    sql.SQL(kind_sql[kind]),
                    sql.Identifier(schema),
                    sql.Identifier(name),
                    sql.Identifier(role),
                )
            )
    return make_conninfo(**{**info, "user": role})


@pytest.fixture
def pg_single_user_dsn(pg_dsn):
    return single_database_user_dsn(pg_dsn)


@pytest.fixture
def pg_dsn(pg_cluster):
    import psycopg
    from psycopg import sql

    name = "test_" + uuid.uuid4().hex
    with psycopg.connect(pg_cluster, autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    yield pg_cluster.replace("dbname=postgres", f"dbname={name}")
    with psycopg.connect(pg_cluster, autocommit=True) as c:
        c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
