"""恢复 CLI 必须通过真实 PG 的停机、世代和凭证重置门禁。"""

import asyncio
import json
import uuid

from deeptutor_enterprise.cli import main, parser
from deeptutor_enterprise.executor import ExecutorLease
from deeptutor_enterprise.identity.service import IdentityService
from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.stores.postgres.connection import Database
import pytest


@pytest.fixture
async def recovery_cli(pg_dsn, monkeypatch, tmp_path):
    await MigrationRunner(pg_dsn).apply()
    dsn = pg_dsn.replace("user=postgres", "user=dt_enterprise_app")
    tenant = str(uuid.uuid4())
    raw = {
        "version": 1,
        "tenant_id": tenant,
        "resource": "cli-recovery",
        "maintenance": True,
        "database_secret": "env:RECOVERY_DB",
        "signing_secret": "env:RECOVERY_SIGN",
        "auth_epoch_secret": "env:RECOVERY_EPOCH",
        "origins": ["https://school.example"],
        "models": [
            {
                "profile_id": "chat",
                "model_id": "primary",
                "model": "model",
                "base_url": "https://model.example/v1",
                "secret": "env:UNNEEDED_MODEL",
                "allowed_roles": ["user"],
            }
        ],
    }
    path = tmp_path / "recovery.json"
    path.write_text(json.dumps(raw))
    for name, value in {
        "RECOVERY_DB": dsn,
        "RECOVERY_SIGN": "s" * 48,
        "RECOVERY_EPOCH": "epoch-2",
        "RESET_PASSWORD": "verified-password-2",
    }.items():
        monkeypatch.setenv(name, value)
    async with Database(dsn, resource="cli-recovery") as db:
        identity = IdentityService(
            db,
            tenant_id=tenant,
            signing_key="s" * 48,
            auth_epoch="epoch-1",
            bootstrap_secret="b" * 48,
        )
        admin = await identity.bootstrap("admin", "old-password-1", secret="b" * 48)
        token = await identity.login("admin", "old-password-1", client="test")
        user = await identity.create_user(token, "ordinary", "old-password-2")
        yield path, raw, db, identity, admin, user, token


async def call(path, *args):
    return await asyncio.to_thread(
        main, ["--config", str(path), "recovery", *args, "--old-process-confirmed-stopped"]
    )


async def test_recovery_cli_quarantine_reset_release_never_revives_old_identity(
    recovery_cli, capsys
):
    path, raw, db, identity, admin, user, old_token = recovery_cli
    assert (
        await call(
            path,
            "reset-account",
            "--user-id",
            admin["id"],
            "--password-env",
            "RESET_PASSWORD",
            "--enable",
        )
        == 1
    )
    assert await call(path, "quarantine") == 0
    assert await call(path, "quarantine") == 0
    restored = IdentityService(
        db,
        tenant_id=raw["tenant_id"],
        signing_key="s" * 48,
        auth_epoch="epoch-2",
        bootstrap_secret=None,
    )
    with pytest.raises(PermissionError):
        await restored.authenticate(old_token)
    assert await call(path, "release") == 1
    assert (
        await call(
            path, "reset-account", "--user-id", user["id"], "--password-env", "RESET_PASSWORD"
        )
        == 0
    )
    assert (
        await call(
            path,
            "reset-account",
            "--user-id",
            admin["id"],
            "--password-env",
            "RESET_PASSWORD",
            "--enable",
        )
        == 0
    )
    assert await call(path, "release") == 0
    assert await restored.login("admin", "verified-password-2", client="restore")
    for name, password in (
        ("admin", "old-password-1"),
        ("ordinary", "old-password-2"),
        ("ordinary", "verified-password-2"),
    ):
        with pytest.raises(PermissionError):
            await restored.login(name, password, client="restore")
    text = capsys.readouterr()
    for secret in (old_token, "verified-password-2", "old-password-1", "s" * 48):
        assert secret not in text.out + text.err


async def test_recovery_cli_refuses_active_executor_wrong_epoch_and_nonmaintenance(
    recovery_cli, monkeypatch
):
    path, raw, db, identity, _, _, token = recovery_cli
    lease = ExecutorLease(db.pool.conninfo, resource="cli-recovery")
    await lease.acquire()
    try:
        assert await call(path, "quarantine") == 1
        assert await identity.authenticate(token)
    finally:
        await lease.close()
    monkeypatch.setenv("RECOVERY_EPOCH", "epoch-1")
    assert await call(path, "quarantine") == 1
    assert await identity.authenticate(token)
    monkeypatch.setenv("RECOVERY_EPOCH", "epoch-2")
    path.write_text(json.dumps({**raw, "maintenance": False}))
    assert await call(path, "quarantine") == 1
    assert await identity.authenticate(token)


def test_recovery_cli_requires_explicit_stop_and_never_accepts_inline_password():
    prefix = ["--config", "unused", "recovery"]
    for suffix in (
        ("quarantine",),
        (
            "reset-account",
            "--old-process-confirmed-stopped",
            "--user-id",
            "admin",
            "--password",
            "inline",
        ),
    ):
        with pytest.raises(SystemExit):
            parser().parse_args(prefix + list(suffix))
