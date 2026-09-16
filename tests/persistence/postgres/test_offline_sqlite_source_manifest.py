"""离线 SQLite→PG 导入源快照与 manifest 协议测试。"""

from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_legacy_chat_history(path: Path) -> None:
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    token = set_current_user(
        CurrentUser(
            id="legacy-user",
            username="legacy-user",
            role="user",
            scope=UserScope(kind="user", user_id="legacy-user", root=path.parent / "owner"),
        )
    )
    try:
        store = SQLiteSessionStore(db_path=path)
        session = asyncio.run(store.create_session(session_id="legacy-session"))
        assert session["id"] == "legacy-session"
        with sqlite3.connect(path) as connection:
            connection.execute(
                """
                INSERT INTO messages(id, session_id, role, content, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (10, "legacy-session", "user", "question", 1000.0),
            )
            connection.commit()
            # 测试 fixture 模拟已停写、已交付的稳定源；快照工具本身不得
            # checkpoint/VACUUM/修复源库。
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.commit()
    finally:
        reset_current_user(token)


def _snapshot(tmp_path: Path, source: Path):
    from deeptutor.persistence.postgres.offline_import import create_sqlite_source_snapshot

    return create_sqlite_source_snapshot(
        source_db=source,
        output_dir=tmp_path / "artifact",
        source_id="legacy-chat",
        source_version="chat_history_sqlite/v1",
        source_owner_id="legacy-user",
        target_tenant_id="tenant-1",
        owner_mappings={"legacy-user": "pg-owner-1"},
        freeze_id="freeze-001",
        stopped_writers=["web", "cron", "matrix"],
        operator="unit-test",
    )


def test_backup_manifest_is_independent_readonly_artifact_and_plan_uses_snapshot_only(
    tmp_path: Path,
) -> None:
    """生产代码若直接读取活动 source_db、改写源主库/WAL 或遗漏引用注册表应失败。"""

    from deeptutor.persistence.postgres.offline_import import (
        plan_sqlite_import,
        source_check_manifest,
    )

    source = tmp_path / "chat_history.db"
    _make_legacy_chat_history(source)
    source_main_before = _sha256(source)
    source_wal_before = _sha256(Path(str(source) + "-wal"))

    result = _snapshot(tmp_path, source)

    manifest = _read_json(result.manifest_path)
    source_entry = manifest["sources"][0]
    snapshot = Path(source_entry["snapshot"]["path"])
    assert snapshot.exists()
    assert snapshot != source
    assert not snapshot.is_symlink()
    assert not Path(str(snapshot) + "-wal").exists()
    assert source_entry["source_authority"]["main_sha256_before"] == source_main_before
    assert source_entry["source_authority"]["main_sha256_after"] == source_main_before
    assert source_entry["source_authority"]["wal_sha256_before"] == source_wal_before
    assert source_entry["source_authority"]["wal_sha256_after"] == source_wal_before
    assert _sha256(source) == source_main_before
    assert _sha256(Path(str(source) + "-wal")) == source_wal_before

    # 离线检查不得依赖活动源路径；源库被移走后仍应只用 manifest 对应制品。
    moved = tmp_path / "source-moved.db"
    source.rename(moved)
    check = source_check_manifest(result.manifest_path)
    assert check.ok, check.issues

    plan = plan_sqlite_import(result.manifest_path)
    assert plan.ok, plan.issues
    assert plan.sources[0]["table_counts"]["sessions"] == 1
    assert plan.sources[0]["table_counts"]["messages"] == 1
    assert "messages.parent_message_id" in plan.sources[0]["reference_fields"]
    assert "sessions.summary_up_to_msg_id" in plan.sources[0]["reference_fields"]


def test_source_check_rejects_active_source_paths_wal_dependencies_and_required_sidecars(
    tmp_path: Path,
) -> None:
    """生产代码若接受直接活动库、缺 WAL sidecar 或 WAL-dependent 快照应失败。"""

    from deeptutor.persistence.postgres.offline_import import source_check_manifest

    source = tmp_path / "chat_history.db"
    _make_legacy_chat_history(source)
    result = _snapshot(tmp_path, source)
    manifest = _read_json(result.manifest_path)

    active = copy.deepcopy(manifest)
    active["sources"][0]["snapshot"]["path"] = active["sources"][0]["source_path"]
    active_path = _write_json(tmp_path / "active-source-manifest.json", active)
    active_report = source_check_manifest(active_path)
    assert not active_report.ok
    assert "snapshot_is_source_database" in {issue["code"] for issue in active_report.issues}

    missing_wal = copy.deepcopy(manifest)
    missing_wal["sources"][0]["sidecars"]["wal"]["required"] = True
    missing_wal["sources"][0]["sidecars"]["wal"].pop("path", None)
    missing_wal_path = _write_json(tmp_path / "missing-wal-manifest.json", missing_wal)
    missing_wal_report = source_check_manifest(missing_wal_path)
    assert not missing_wal_report.ok
    assert "required_wal_sidecar_missing" in {issue["code"] for issue in missing_wal_report.issues}

    dependent = copy.deepcopy(manifest)
    dependent_snapshot = Path(dependent["sources"][0]["snapshot"]["path"])
    Path(str(dependent_snapshot) + "-wal").write_bytes(b"not self contained")
    dependent_path = _write_json(tmp_path / "wal-dependent-manifest.json", dependent)
    dependent_report = source_check_manifest(dependent_path)
    assert not dependent_report.ok
    assert "snapshot_has_wal_dependency" in {issue["code"] for issue in dependent_report.issues}


def test_source_check_rejects_unknown_source_version_and_unmapped_owner(
    tmp_path: Path,
) -> None:
    """生产代码若把未知版本或缺失 owner 映射默认归 admin 应失败。"""

    from deeptutor.persistence.postgres.offline_import import source_check_manifest

    source = tmp_path / "chat_history.db"
    _make_legacy_chat_history(source)
    result = _snapshot(tmp_path, source)
    manifest = _read_json(result.manifest_path)
    manifest["sources"][0]["source_version"] = "chat_history_sqlite/v999"
    manifest["owner_mappings"] = []
    bad_path = _write_json(tmp_path / "unknown-version-manifest.json", manifest)

    report = source_check_manifest(bad_path)

    codes = {issue["code"] for issue in report.issues}
    assert not report.ok
    assert "unknown_source_version" in codes
    assert "owner_mapping_missing" in codes


def test_reference_registry_and_schema_validation_are_versioned(tmp_path: Path) -> None:
    """生产代码若缺少固定字段注册表或接受坏 SQLite schema 应失败。"""

    from deeptutor.persistence.postgres.offline_import import (
        get_reference_registry,
        source_check_manifest,
    )

    registry = get_reference_registry("chat_history_sqlite/v1")
    paths = {field.path for field in registry.reference_fields}
    assert {
        "messages.parent_message_id",
        "messages.attachments_json[*].id",
        "turn_events.turn_id",
        "notebook_entries.session_id",
        "notebook_entry_categories.entry_id",
    }.issubset(paths)

    source = tmp_path / "bad-chat.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY)")
        connection.commit()
    result = _snapshot(tmp_path, source)

    report = source_check_manifest(result.manifest_path)

    assert not report.ok
    assert "schema_missing_table" in {issue["code"] for issue in report.issues}


def test_cli_source_check_and_plan_are_offline_and_json(tmp_path: Path) -> None:
    """生产 CLI 若尝试连接 PG/创建本地用户库，或未提供 plan/source-check，应失败。"""

    source = tmp_path / "chat_history.db"
    _make_legacy_chat_history(source)
    result = _snapshot(tmp_path, source)
    env = {**os.environ, "DEEPTUTOR_HOME": str(tmp_path / "home")}
    env.pop("DEEPTUTOR_DATABASE_URL", None)
    env.pop("DEEPTUTOR_MIGRATION_DATABASE_URL", None)

    check = subprocess.run(
        [
            sys.executable,
            "-m",
            "deeptutor_cli",
            "migration",
            "sqlite",
            "source-check",
            "--manifest",
            str(result.manifest_path),
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert json.loads(check.stdout)["ok"] is True

    plan = subprocess.run(
        [
            sys.executable,
            "-m",
            "deeptutor_cli",
            "migration",
            "sqlite",
            "plan",
            "--manifest",
            str(result.manifest_path),
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert plan.returncode == 0, plan.stdout + plan.stderr
    payload = json.loads(plan.stdout)
    assert payload["sources"][0]["table_counts"]["messages"] == 1
    assert not (tmp_path / "home" / "user" / "auth_users.json").exists()
