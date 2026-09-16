"""独立解释器导入不能先加载 SQLite runtime 或创建 HOME。"""

import os
from pathlib import Path
import subprocess
import sys


def test_reading_pg_import_is_pure(tmp_path):
    home = tmp_path / "absent"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import deeptutor.persistence.postgres.reading
assert 'sqlite3' not in sys.modules
assert 'deeptutor.reading.catalog_store' not in sys.modules
assert 'deeptutor.reading.store' not in sys.modules
""",
        ],
        env={**os.environ, "DEEPTUTOR_HOME": str(home)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not Path(home).exists()


def test_pg_store_retains_all_28_original_parameter_contracts():
    import ast
    import inspect

    from deeptutor.persistence.postgres.reading import PostgresReadingCatalogStore

    source = ast.parse(Path("deeptutor/reading/catalog_store.py").read_text())
    original = next(
        n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "ReadingCatalogStore"
    )
    methods = [
        n for n in original.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
    ]
    assert len(methods) == 28
    for method in methods:
        params = inspect.signature(getattr(PostgresReadingCatalogStore, method.name)).parameters
        for arg in method.args.args:
            assert (
                arg.arg in params
                and params[arg.arg].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
            )
        for arg in method.args.kwonlyargs:
            assert arg.arg in params and params[arg.arg].kind == inspect.Parameter.KEYWORD_ONLY


def test_reading_migration_resources_are_in_published_package_patterns():
    import fnmatch
    from importlib.resources import files
    import tomllib

    config = tomllib.loads(Path("pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"]["deeptutor"]
    for name in ("0006_reading.sql", "reading_catalog.json"):
        path = "persistence/postgres/migrations/" + name
        assert any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
        assert files("deeptutor.persistence.postgres.migrations").joinpath(name).read_bytes()
