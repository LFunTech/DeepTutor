from pathlib import Path


def test_github_python_tests_install_isolated_postgres_binaries() -> None:
    workflow = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")

    assert "Install isolated PostgreSQL test binaries" in workflow
    assert "DT_TEST_PG_BIN" in workflow
    assert "tests.fixtures.postgres" in workflow
    assert "no shared or developer database is used" in workflow
    assert "postgresql postgresql-client" in workflow


def test_postgres_fixture_creates_tmp_socket_only_cluster() -> None:
    fixture = Path("tests/fixtures/postgres.py").read_text(encoding="utf-8")

    assert "tmp_path_factory.mktemp" in fixture
    assert "tempfile.mkdtemp" in fixture
    assert "initdb" in fixture
    assert "pg_ctl" in fixture
    assert "listen_addresses=''" in fixture
    assert "CREATE DATABASE" in fixture
    assert "DROP DATABASE" in fixture
