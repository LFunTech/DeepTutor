from __future__ import annotations

import json

from typer.testing import CliRunner

from deeptutor_cli.main import app


def test_data_migration_inventory_reports_hashes_and_redacts_secrets(tmp_path):
    """若 data inventory 修改源文件、泄漏 Secret 明文或不记录 owner/provider 决策，本测试应失败。"""

    root = tmp_path / "data"
    (root / "user" / "workspace").mkdir(parents=True)
    (root / "user" / "workspace" / "plot.svg").write_text("<svg />", encoding="utf-8")
    (root / "user" / "settings").mkdir(parents=True)
    (root / "user" / "settings" / "model_catalog.json").write_text(
        '{"api_key":"sk-secret-must-not-leak","default":"gpt"}', encoding="utf-8"
    )

    result = CliRunner().invoke(app, ["migration", "data", "inventory", "--source-root", str(root)])

    assert result.exit_code == 0, result.output
    assert "sk-secret-must-not-leak" not in result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "inventory"
    by_path = {row["source_path"]: row for row in payload["rows"]}
    assert by_path["user/workspace/plot.svg"]["target_provider"] == "objectstore"
    assert by_path["user/workspace/plot.svg"]["sha256"]
    assert by_path["user/settings/model_catalog.json"]["decision"] == "manual-secret-map"
    assert by_path["user/settings/model_catalog.json"]["sensitive_fields"] == ["api_key"]


def test_data_migration_inventory_blocks_symlink_escape(tmp_path):
    """若离线 data inventory 跟随 symlink 逃逸 source root，本测试应失败。"""

    root = tmp_path / "data"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("top-secret-body", encoding="utf-8")
    (root / "escape").symlink_to(outside)

    result = CliRunner().invoke(app, ["migration", "data", "inventory", "--source-root", str(root)])

    assert result.exit_code == 1
    assert "top-secret-body" not in result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["errors"][0]["reason_code"] == "symlink_escape"


def test_data_migration_inventory_records_tenant_owner_fingerprint_and_blocks_replay(tmp_path):
    """若多租户 report 缺 tenant/owner/prefix 指纹或不能阻断旧源重放，本测试应失败。"""

    root = tmp_path / "data"
    (root / "user" / "workspace").mkdir(parents=True)
    (root / "user" / "workspace" / "plot.svg").write_text("<svg />", encoding="utf-8")

    first = CliRunner().invoke(
        app,
        [
            "migration",
            "data",
            "inventory",
            "--source-root",
            str(root),
            "--source-id",
            "legacy-snapshot",
            "--target-tenant",
            "tenant-a",
            "--owner-map",
            "legacy-owner=target-owner",
        ],
    )

    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    row = payload["rows"][0]
    assert payload["source_id"] == "legacy-snapshot"
    assert payload["source_fingerprint"]
    assert row["tenant_target"] == "tenant-a"
    assert row["owner_source"] == "legacy-owner"
    assert row["owner_target"] == "target-owner"
    assert row["object_prefix"].startswith("tenants/tenant-a/owners/")

    replay = CliRunner().invoke(
        app,
        [
            "migration",
            "data",
            "inventory",
            "--source-root",
            str(root),
            "--expect-source-fingerprint",
            "bad-fingerprint",
        ],
    )
    assert replay.exit_code == 1
    assert json.loads(replay.output)["errors"][0]["reason_code"] == "source_fingerprint_mismatch"
