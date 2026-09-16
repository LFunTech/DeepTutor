import importlib.util
from pathlib import Path
import subprocess
import uuid

from deeptutor_enterprise.identity.service import IdentityService
from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.scope import TenantScope
from deeptutor_enterprise.stores.postgres.connection import Database
import pytest


async def test_backup_restore_never_restores_old_password_or_token(pg_dsn, tmp_path):
    assert importlib.util.find_spec("deeptutor_enterprise.recovery"), "身份恢复门禁尚未实现"
    from deeptutor_enterprise.recovery import RecoveryOperations

    await MigrationRunner(pg_dsn).apply()
    dsn = pg_dsn.replace("user=postgres", "user=dt_enterprise_app")
    tenant = str(uuid.uuid4())
    backup = tmp_path / "backup.dump"
    async with Database(dsn, resource="restore") as db:
        identity = IdentityService(
            db,
            tenant_id=tenant,
            signing_key="s" * 48,
            auth_epoch="epoch-1",
            bootstrap_secret="b" * 48,
        )
        user = await identity.bootstrap("admin", "old-password-1", secret="b" * 48)
        token = await identity.login("admin", "old-password-1", client="test")
        from deeptutor_enterprise.stores.postgres.session import PostgresSessionStore

        store = PostgresSessionStore(db, TenantScope(tenant, user["id"]))
        session, turn, _ = await store.begin_request({"content": "original"})
        await store.finalize_turn(turn["id"], status="completed", content="history remains")
        subprocess.run(
            [
                "/opt/pgsql/bin/pg_dump",
                "--format=custom",
                "--dbname",
                pg_dsn,
                "--file",
                str(backup),
            ],
            check=True,
            capture_output=True,
        )
        await identity.change_password(token, user["id"], "new-password-2")
        fresh = await identity.login("admin", "new-password-2", client="test")
        await identity.set_enabled(fresh, user["id"], False)
    subprocess.run(
        [
            "/opt/pgsql/bin/pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--dbname",
            pg_dsn,
            str(backup),
        ],
        check=True,
        capture_output=True,
    )
    async with Database(dsn, resource="restore") as db:
        restored = IdentityService(
            db, tenant_id=tenant, signing_key="s" * 48, auth_epoch="epoch-2", bootstrap_secret=None
        )
        recovery = RecoveryOperations(
            db, tenant_id=tenant, resource="restore", auth_epoch="epoch-2", maintenance=True
        )
        await recovery.quarantine(old_process_confirmed_stopped=True)
        with pytest.raises(PermissionError):
            await restored.authenticate(token)
        with pytest.raises(PermissionError):
            await restored.login("admin", "old-password-1", client="restored")
        await recovery.reset_account(user["id"], "verified-new-password-3", enabled=True)
        await recovery.release()
        for password in ["old-password-1", "new-password-2"]:
            with pytest.raises(PermissionError):
                await restored.login("admin", password, client="restored")
        assert await restored.authenticate(
            await restored.login("admin", "verified-new-password-3", client="restored")
        )
        store = PostgresSessionStore(db, TenantScope(tenant, user["id"]))
        assert (await store.get_messages(session["id"]))[-1]["content"] == "history remains"
        assert (await store.get_events(turn["id"]))[-1]["type"] == "done"
