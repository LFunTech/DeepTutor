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
