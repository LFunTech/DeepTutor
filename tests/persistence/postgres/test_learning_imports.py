"""新进程纯导入：PG与显式Service注入不加载旧SQLite运行时，不触发默认HOME/数据库。"""

import os
from pathlib import Path
import subprocess
import sys


def test_pg_learning_import_does_not_load_legacy_or_touch_storage(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    script = """
import os,sys
from pathlib import Path
import psycopg

def denied(*args,**kwargs):
    raise AssertionError("pure import attempted PostgreSQL checkout")
psycopg.connect=denied
psycopg.Connection.connect=denied
psycopg.AsyncConnection.connect=denied
from deeptutor.persistence.postgres.learning import AsyncLearningStore,PostgresLearningStore
from deeptutor.learning.service import LearningService
assert "deeptutor.learning.storage" not in sys.modules
assert "deeptutor.services.session.sqlite_store" not in sys.modules
assert not list(Path(os.environ["DEEPTUTOR_HOME"]).rglob("*"))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "DEEPTUTOR_HOME": str(home)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_import_id_helper_remains_runtime_safe_and_sqlite_store_is_direct_only(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    script = """
import os,sys
from pathlib import Path
import deeptutor.services.session as package
assert "deeptutor.services.session.sqlite_store" not in sys.modules
from deeptutor.services.session.import_ids import make_imported_session_id
assert package.make_imported_session_id is make_imported_session_id
assert "deeptutor.services.session.sqlite_store" not in sys.modules
try:
    package.SQLiteSessionStore
except AttributeError:
    pass
else:
    raise AssertionError("SQLiteSessionStore must not be a package-level runtime export")
assert not list(Path(os.environ["DEEPTUTOR_HOME"]).rglob("*"))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "DEEPTUTOR_HOME": str(home)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
