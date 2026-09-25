# ruff: noqa: F811
# pytest fixture 重导出与注入参数同名。
"""受控账号 CLI 用临时 PG 与 Secret 环境引用，不连接常驻服务。"""

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn, single_database_user_dsn  # noqa: F401


def invoke(args, environment):
    return subprocess.run(
        [sys.executable, "-m", "deeptutor_cli", *args],
        env=environment,
        text=True,
        capture_output=True,
    )


def test_account_help_is_lazy(tmp_path):
    environment = {**os.environ, "DEEPTUTOR_HOME": str(tmp_path / "home")}
    environment.pop("DT_RUN_REAL_MODEL", None)
    result = invoke(["account", "--help"], environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert not (tmp_path / "home" / "user" / "auth_users.json").exists()


async def test_controlled_cli_bootstrap_and_account_lifecycle(pg_dsn, tmp_path):
    from deeptutor.persistence.postgres.connection import Database
    from deeptutor.persistence.postgres.identity.service import IdentityService
    from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

    await MigrationRunner(pg_dsn).apply()
    tenant = str(uuid.uuid4())
    config = tmp_path / "deployment.json"
    config.write_text(
        json.dumps(
            {
                "version": 1,
                "tenant_id": tenant,
                "resource": "cli-accounts",
                "signing_secret": "env:TEST_SIGN",
                "auth_epoch_secret": "env:TEST_EPOCH",
                "bootstrap_secret": "env:TEST_BOOT",
            }
        )
    )
    environment = {
        **os.environ,
        "DEEPTUTOR_HOME": str(tmp_path / "home"),
        "TEST_SIGN": "s" * 48,
        "TEST_EPOCH": "epoch1",
        "TEST_BOOT": "b" * 48,
        "DEEPTUTOR_DATABASE_URL": single_database_user_dsn(pg_dsn),
        "TEST_PASS": "administrator-123",
    }
    environment.pop("DT_RUN_REAL_MODEL", None)
    args = [
        "account",
        "bootstrap",
        "--config",
        str(config),
        "--username",
        "admin",
        "--password-env",
        "TEST_PASS",
    ]
    result = invoke(args, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    environment["TEST_PASS"] = "changed-password-1"
    result = invoke(args, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    async with Database(environment["DEEPTUTOR_DATABASE_URL"], resource="cli-test") as db:
        service = IdentityService(
            db, tenant_id=tenant, signing_key="s" * 48, auth_epoch="epoch1", bootstrap_secret=None
        )
        token = await service.login("admin", "administrator-123", client="test")
        environment["TEST_TOKEN"] = token
        result = invoke(
            [
                "account",
                "create",
                "--config",
                str(config),
                "--token-env",
                "TEST_TOKEN",
                "--username",
                "student",
                "--password-env",
                "TEST_PASS",
                "--preset",
                "learner",
            ],
            environment,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        student = json.loads(result.stdout)
        result = invoke(
            [
                "account",
                "disable",
                "--config",
                str(config),
                "--token-env",
                "TEST_TOKEN",
                "--user-id",
                student["id"],
            ],
            environment,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        with pytest.raises(PermissionError):
            await service.login("student", "changed-password-1", client="test")
    assert token not in result.stdout + result.stderr
