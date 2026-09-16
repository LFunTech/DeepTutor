"""PG-only 默认运行禁止旧 SQLite/PocketBase backend 工厂。"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


def test_sqlite_session_factory_is_deprecated_runtime_error() -> None:
    """默认运行若还能通过工厂创建 chat_history.db，应失败。"""

    import deeptutor.services.session as session_package
    from deeptutor.services.session.sqlite_store import get_sqlite_session_store

    with pytest.raises(RuntimeError, match="PostgreSQL-only.*offline import"):
        get_sqlite_session_store()
    with pytest.raises(RuntimeError, match="PostgreSQL-only.*offline import"):
        session_package.get_sqlite_session_store()


def test_pocketbase_session_store_constructor_is_deprecated_runtime_error() -> None:
    """PocketBase session backend 只能离线导出，不能作为运行 Store 构造。"""

    from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore

    with pytest.raises(RuntimeError, match="PostgreSQL-only.*PocketBase.*offline export"):
        PocketBaseSessionStore()


def test_pocketbase_client_runtime_factory_is_disabled(monkeypatch) -> None:
    """旧 PocketBase 配置存在时也不能重新启用运行期 backend。"""

    from deeptutor.services import pocketbase_client

    monkeypatch.setattr(
        pocketbase_client,
        "_pocketbase_settings",
        lambda: {
            "url": "http://127.0.0.1:8090",
            "admin_email": "admin@example.test",
            "admin_password": "secret",
        },
    )

    assert pocketbase_client.is_pocketbase_enabled() is False
    with pytest.raises(RuntimeError, match="PostgreSQL-only.*PocketBase.*offline export"):
        pocketbase_client.get_pb_client()


@pytest.mark.asyncio
async def test_runtime_doctor_reports_legacy_import_as_disabled(monkeypatch) -> None:
    """运行诊断不得再触发旧 chat/workspace 自动迁移路径。"""

    from deeptutor.services.doctor import run_runtime_diagnostics

    async def legacy_migration_must_not_run(**_: object):  # pragma: no cover - RED 标记
        raise AssertionError("runtime diagnostics must not invoke legacy migration paths")

    monkeypatch.setattr(
        "deeptutor.services.session.legacy_migration.migrate_all_legacy_chat_scopes",
        legacy_migration_must_not_run,
    )

    report = await run_runtime_diagnostics()

    legacy = next(check for check in report.checks if check.key == "legacy_chat_migration")
    assert legacy.status == "skip"
    assert legacy.required is False
    assert "offline import" in legacy.detail


def test_chat_history_import_router_does_not_load_sqlite_runtime(tmp_path) -> None:
    """普通业务路由可使用导入 ID helper，但不得因此加载 SQLite Store。"""

    home = tmp_path / "home"
    home.mkdir()
    script = """
import sys
import deeptutor.api.routers.imports  # noqa: F401
import deeptutor.services.session as session_package
assert "deeptutor.services.session.sqlite_store" not in sys.modules
assert session_package.make_imported_session_id("codex","abc").startswith("imported_codex_")
assert "deeptutor.services.session.sqlite_store" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "DEEPTUTOR_HOME": str(home)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
